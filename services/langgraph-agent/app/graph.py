"""
Graphe d'orchestration LangGraph.

Flux :
  1. retrieve_context   -> interroge Context Manager (RAG / mémoire)
  2. select_skill        -> interroge Skill Manager pour injecter un prompt de skill pertinent
  3. call_llm             -> appelle vLLM (API OpenAI-compatible) avec function calling
  4. require_approval (option) -> si le LLM demande un outil, met le graphe en pause
     (NodeInterrupt) tant qu'un humain n'a pas approuvé/refusé via l'état "approved"
  5. call_tools | reject_tools -> exécute l'outil via MCP Client, ou synthétise un
     refus si l'humain a refusé, puis reboucle sur call_llm
  6. END                  -> réponse finale

Supervision humaine : tout appel d'outil est soumis à approbation (voir
require_approval/reject_tools ci-dessous). Le graphe est donc compilé avec un
checkpointer (MemorySaver, en mémoire) pour pouvoir suspendre puis reprendre
l'exécution — au prix de perdre les approbations en attente si le service
redémarre (acceptable pour un usage local, voir README).
"""

import contextvars
import os
import json
from typing import Annotated, Optional, TypedDict

import httpx
import langchain_openai.chat_models.base as _openai_base
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import NodeInterrupt
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

# Ollama (modèles Qwen3+) renvoie le raisonnement dans un champ "reasoning" des
# deltas SSE, en plus de "content" — un champ hors du format OpenAI standard,
# que langchain-openai ignore silencieusement (_convert_delta_to_message_chunk
# ne lit que "content"/"tool_calls"/"function_call"). On l'y réinjecte en le
# repliant dans "content", entouré de <think>...</think> (convention reconnue
# par Open WebUI pour afficher une bulle de pensée repliable), ce qui le fait
# apparaître dans le flux de streaming existant sans toucher à app/main.py.
_think_state: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "_think_state", default=None
)
_original_convert_delta = _openai_base._convert_delta_to_message_chunk


def _convert_delta_with_reasoning(_dict, default_class):
    chunk = _original_convert_delta(_dict, default_class)
    state = _think_state.get()
    if state is None:
        return chunk
    reasoning = _dict.get("reasoning")
    if reasoning:
        prefix = "<think>" if not state["opened"] else ""
        state["opened"] = True
        chunk.content = prefix + reasoning
    elif chunk.content and state["opened"] and not state["closed"]:
        state["closed"] = True
        chunk.content = "</think>\n\n" + chunk.content
    return chunk


_openai_base._convert_delta_to_message_chunk = _convert_delta_with_reasoning

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://vllm:8000/v1")
CONTEXT_MANAGER_URL = os.environ.get("CONTEXT_MANAGER_URL", "http://context-manager:8002")
SKILL_MANAGER_URL = os.environ.get("SKILL_MANAGER_URL", "http://skill-manager:8001")
MCP_CLIENT_URL = os.environ.get("MCP_CLIENT_URL", "http://mcp-client:8003")

MAX_TOOL_ITERATIONS = 5


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_iterations: int
    approved: Optional[bool]
    # Nombre de messages Open WebUI (rôles user/assistant) déjà intégrés à ce
    # thread — permet à app/main.py de ne soumettre que les nouveaux messages
    # à chaque tour plutôt que tout l'historique renvoyé par Open WebUI (qui
    # est déjà persisté ici via le checkpointer), et donc d'éviter de le
    # dupliquer dans "messages" à chaque tour.
    owui_message_count: int


llm = ChatOpenAI(
    base_url=LLM_BASE_URL,
    api_key="not-needed",       # vLLM ne vérifie pas la clé par défaut
    model="agent-llm",
    temperature=0.2,
)


async def retrieve_context(state: AgentState) -> dict:
    last_user_msg = next(
        (m.content for m in reversed(state["messages"]) if m.type == "human"), ""
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{CONTEXT_MANAGER_URL}/retrieve", json={"query": last_user_msg, "top_k": 5}
            )
            resp.raise_for_status()
            snippets = resp.json().get("results", [])
    except httpx.HTTPError:
        snippets = []

    if not snippets:
        return {"messages": []}

    context_text = "\n".join(f"- {s}" for s in snippets)
    return {"messages": [{"role": "system", "content": f"Contexte pertinent récupéré :\n{context_text}"}]}


async def select_skill(state: AgentState) -> dict:
    last_user_msg = next(
        (m.content for m in reversed(state["messages"]) if m.type == "human"), ""
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SKILL_MANAGER_URL}/match", json={"query": last_user_msg}
            )
            resp.raise_for_status()
            skill = resp.json().get("skill")
    except httpx.HTTPError:
        skill = None

    if not skill:
        return {"messages": []}

    return {"messages": [{"role": "system", "content": f"Skill activée : {skill['name']}\n{skill['content']}"}]}


async def call_llm(state: AgentState) -> dict:
    token = _think_state.set({"opened": False, "closed": False})
    try:
        merged = None
        async for chunk in llm.astream(state["messages"]):
            merged = chunk if merged is None else merged + chunk
    finally:
        think = _think_state.get()
        _think_state.reset(token)

    if think["opened"] and not think["closed"]:
        merged.content += "</think>"
    return {"messages": [merged]}


def has_tool_calls(state: AgentState) -> str:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None)
    if tool_calls and state["tool_iterations"] < MAX_TOOL_ITERATIONS:
        return "call_tools"
    return "end"


async def require_approval(state: AgentState) -> dict:
    """Point de pause : bloque tant qu'un humain n'a pas approuvé/refusé (voir app/main.py)."""
    if state.get("approved") is None:
        raise NodeInterrupt("Approbation humaine requise avant exécution d'outil.")
    return {"messages": []}


def route_after_approval(state: AgentState) -> str:
    return "call_tools" if state["approved"] else "reject_tools"


async def call_tools(state: AgentState) -> dict:
    last = state["messages"][-1]
    new_messages = []

    async with httpx.AsyncClient(timeout=60) as client:
        for tool_call in last.tool_calls:
            try:
                resp = await client.post(
                    f"{MCP_CLIENT_URL}/call",
                    json={"tool": tool_call["name"], "arguments": tool_call["args"]},
                )
                resp.raise_for_status()
                result = resp.json()
            except httpx.HTTPError as exc:
                result = {"error": str(exc)}

            new_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return {
        "messages": new_messages,
        "tool_iterations": state["tool_iterations"] + 1,
        "approved": None,  # réarme la pause pour le prochain tour d'outils
    }


async def reject_tools(state: AgentState) -> dict:
    """Miroir de call_tools quand l'humain a refusé : synthétise un refus, n'appelle jamais mcp-client."""
    last = state["messages"][-1]
    new_messages = [
        {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": json.dumps({"error": "Rejeté par l'utilisateur"}, ensure_ascii=False),
        }
        for tool_call in last.tool_calls
    ]
    return {
        "messages": new_messages,
        "tool_iterations": state["tool_iterations"] + 1,
        "approved": None,
    }


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("select_skill", select_skill)
    graph.add_node("call_llm", call_llm)
    graph.add_node("require_approval", require_approval)
    graph.add_node("call_tools", call_tools)
    graph.add_node("reject_tools", reject_tools)

    graph.set_entry_point("retrieve_context")
    graph.add_edge("retrieve_context", "select_skill")
    graph.add_edge("select_skill", "call_llm")
    graph.add_conditional_edges("call_llm", has_tool_calls, {"call_tools": "require_approval", "end": END})
    graph.add_conditional_edges(
        "require_approval", route_after_approval, {"call_tools": "call_tools", "reject_tools": "reject_tools"}
    )
    graph.add_edge("call_tools", "call_llm")
    graph.add_edge("reject_tools", "call_llm")

    return graph.compile(checkpointer=checkpointer or MemorySaver())


agent_graph = build_graph()
