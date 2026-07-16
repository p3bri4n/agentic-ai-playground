"""
Graphe d'orchestration LangGraph.

Flux :
  1. retrieve_context   -> interroge Context Manager (RAG / mémoire)
  2. select_skill        -> interroge Skill Manager pour injecter un prompt de skill pertinent
  3. call_llm             -> appelle vLLM (API OpenAI-compatible) avec function calling
  4. has_tool_calls       -> route vers require_approval, ou directement vers
     auto_call_tools si TOUS les tool_calls du tour sont auto-approuvés selon
     la politique par tiers (app/approval_policy.py, voir plus bas)
  5. require_approval (option) -> si le LLM demande un outil non auto-approuvé,
     met le graphe en pause (NodeInterrupt) tant qu'un humain n'a pas
     approuvé/refusé via l'état "approved"
  6. call_tools | auto_call_tools | reject_tools -> exécute l'outil via MCP
     Client (même logique partagée, voir _execute_tool_calls), ou synthétise
     un refus si l'humain a refusé, puis reboucle sur call_llm. Seul
     auto_call_tools journalise dans le journal d'audit (Phase 2, voir
     app/audit_log.py) : call_tools est TOUJOURS atteint après un passage
     humain par require_approval CE tour-ci, déjà tracé dans la conversation.
  7. END                  -> réponse finale

Supervision humaine : par défaut, tout appel d'outil est soumis à
approbation (voir require_approval/reject_tools ci-dessous), à l'exception
des outils classés tier "read" ou "reversible" par app/approval_policy.py
(souris/capture d'écran GhostDesk, lecture filesystem/git, par défaut — voir
ce module pour le détail des tiers). Le graphe est donc compilé avec un
checkpointer (MemorySaver, en mémoire) pour pouvoir suspendre puis reprendre
l'exécution — au prix de perdre les approbations en attente si le service
redémarre (acceptable pour un usage local, voir README).
"""

import base64
import contextvars
import io
import os
import json
from typing import Annotated, Optional, TypedDict

import httpx
import langchain_openai.chat_models.base as _openai_base
from langchain_openai import ChatOpenAI
from PIL import Image
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import NodeInterrupt
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from app import approval_policy, audit_log

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

# Budget cumulé d'appels d'outils pour une même tâche : partagé sur toute la
# chaîne d'approbations d'un thread, PAS remis à zéro entre deux tours
# "approuver" (tool_iterations ne repart de 0 que sur un tout nouveau message
# utilisateur, voir _resolve_run dans app/main.py) — un ancien défaut de 5
# s'épuisait après 2-3 aller-retours d'approbation à peine, avant même
# d'atteindre la boucle GhostDesk auto-approuvée (capture/clic) qui consomme
# elle seule 2 itérations par geste. Dépassement signalé explicitement à
# l'utilisateur plutôt que silencieux (voir _current_answer, app/main.py).
MAX_TOOL_ITERATIONS = int(os.environ.get("MAX_TOOL_ITERATIONS", "20"))

# Politique d'approbation par tiers de réversibilité (voir
# app/approval_policy.py) : un tour est auto-approuvé si TOUS ses tool_calls
# sont en tier "read" ou "reversible" ; un tour mixte (même un seul outil en
# tier "sensitive") reste entièrement soumis à approbation, par sécurité —
# pas d'approbation partielle par outil. AUTO_APPROVED_TOOLS (ancienne
# variable d'env) continue de fonctionner comme override rétrocompatible,
# géré dans approval_policy.tool_tier().

# Nombre de tours auto-approuvés consécutifs tolérés avant de forcer malgré
# tout un passage par require_approval, même si tous les tool_calls du tour
# restent auto-approuvés (tier "read"/"reversible") — le garde-fou contre le
# clavier virtuel : un clic seul est anodin, mais une SUITE de clics peut
# composer une saisie complète via un clavier virtuel à l'écran, contournant
# de fait l'exclusion de key_type/key_press (tier "sensitive"). Sans plafond,
# une longue suite de clics pourrait au final saisir n'importe quel texte
# sans jamais qu'un humain ne valide quoi que ce soit. Remis à 0 à chaque
# passage réel par require_approval (voir cette fonction plus bas), pas
# seulement au début d'une nouvelle tâche — contrairement à tool_iterations,
# qui lui mesure un budget total et non un nombre de tours consécutifs SANS
# supervision humaine.
AUTO_APPROVAL_STREAK_LIMIT = int(os.environ.get("AUTO_APPROVAL_STREAK_LIMIT", "6"))


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_iterations: int
    approved: Optional[bool]
    # Tours auto-approuvés consécutifs depuis le dernier passage par
    # require_approval (voir AUTO_APPROVAL_STREAK_LIMIT plus haut).
    auto_approval_streak: int
    # Nombre de messages Open WebUI (rôles user/assistant) déjà intégrés à ce
    # thread — permet à app/main.py de ne soumettre que les nouveaux messages
    # à chaque tour plutôt que tout l'historique renvoyé par Open WebUI (qui
    # est déjà persisté ici via le checkpointer), et donc d'éviter de le
    # dupliquer dans "messages" à chaque tour.
    owui_message_count: int
    # État de la balise <think> (voir _think_state plus haut), reporté d'un
    # appel de call_llm à l'autre au sein d'un même tour utilisateur — requis
    # depuis AUTO_APPROVED_TOOLS, qui permet à call_llm de s'exécuter plusieurs
    # fois de suite sans pause d'approbation entre deux. Sans ce report, chaque
    # itération rouvrait sa propre balise <think>, et Open WebUI n'affiche en
    # bulle repliable que celle en tout début de message : les suivantes
    # apparaissaient en texte brut visible. Remis à False à chaque nouveau tour
    # (voir _resolve_run, app/main.py), comme tool_iterations.
    think_opened: bool
    think_closed: bool
    # Grants de session (Phase 3) : noms d'outils qu'un humain a approuvés
    # "pour la session" via require_approval (voir ce nœud plus bas) plutôt
    # qu'une fois seulement. Un outil dans cette liste est plafonné à
    # TIER_REVERSIBLE (auto + audit) pour le reste du thread, même s'il
    # serait normalement TIER_SENSITIVE (voir approval_policy.effective_tier).
    # Vit dans l'état du graphe, donc dans le checkpointer MemorySaver (en
    # mémoire uniquement) : un redémarrage du service perd les grants en même
    # temps que le reste du thread — comportement voulu, pas un bug (voir
    # README, section Supervision humaine).
    session_grants: list
    # Décision transitoire couplée à "approved" (voir require_approval) :
    # True si l'humain a répondu "approuver pour la session" plutôt que
    # "approuver" seul. Consommée puis remise à False dès que require_approval
    # a appliqué le grant, pour ne pas re-déclencher un grant à chaque reprise
    # ultérieure du thread.
    grant_session: bool


# Plafond de tokens par TOUR (un seul appel LLM), pas pour la conversation
# entière : sans lui, une dérive en boucle de répétition (observée en usage
# réel avec un modèle très quantisé — voir README) génère jusqu'à saturer
# tout le contexte avant de s'arrêter (des dizaines de secondes, des milliers
# de tokens), sans jamais produire de tool_calls ni déclencher nos propres
# garde-fous (MAX_TOOL_ITERATIONS/AUTO_APPROVAL_STREAK_LIMIT), qui ne comptent
# que des itérations d'outils, pas la longueur d'une génération.
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "2048"))

llm = ChatOpenAI(
    base_url=LLM_BASE_URL,
    api_key="not-needed",       # vLLM ne vérifie pas la clé par défaut
    model="agent-llm",
    temperature=0.2,
    max_tokens=LLM_MAX_TOKENS,
)

# Schéma des outils MCP (terminal/filesystem/git/browser/desktop-GhostDesk),
# récupéré depuis mcp-client et mis en cache pour la durée du process. Sans
# ce bind_tools, le LLM n'a aucune connaissance de l'existence de ces outils
# et ne peut donc jamais produire de tool_calls, quel que soit le modèle
# servi — has_tool_calls()/require_approval() restent alors du code mort.
_tools_schema_cache: Optional[list] = None


async def _get_bound_llm() -> ChatOpenAI:
    global _tools_schema_cache
    if _tools_schema_cache is None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{MCP_CLIENT_URL}/tools/schema")
                resp.raise_for_status()
                _tools_schema_cache = resp.json().get("tools", [])
        except (httpx.HTTPError, ValueError):
            # mcp-client injoignable ou réponse invalide : dégrade sans outils
            # plutôt que de faire échouer toute la conversation.
            _tools_schema_cache = []
    return llm.bind_tools(_tools_schema_cache) if _tools_schema_cache else llm


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
    bound_llm = await _get_bound_llm()
    # Repris tel quel depuis l'appel précédent au sein de ce tour (voir
    # AgentState.think_opened/think_closed) plutôt que remis à False, pour ne
    # produire qu'une seule balise <think> continue même si call_llm boucle
    # plusieurs fois via AUTO_APPROVED_TOOLS.
    token = _think_state.set(
        {"opened": state.get("think_opened", False), "closed": state.get("think_closed", False)}
    )
    try:
        merged = None
        async for chunk in bound_llm.astream(state["messages"]):
            merged = chunk if merged is None else merged + chunk
    finally:
        think = _think_state.get()
        _think_state.reset(token)

    # Ne force la fermeture ici que si ce tour n'ira pas relancer call_llm
    # (pas de tool_calls) : sinon on couperait prématurément un <think>
    # censé continuer sur la prochaine itération de la boucle d'outils
    # auto-approuvés. Le cas "tool_calls + pause d'approbation humaine" est
    # géré séparément côté flux streamé (voir needs_closing_tag, app/main.py).
    if think["opened"] and not think["closed"] and not getattr(merged, "tool_calls", None):
        merged.content += "</think>"
        think["closed"] = True

    return {"messages": [merged], "think_opened": think["opened"], "think_closed": think["closed"]}


def has_tool_calls(state: AgentState) -> str:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None)
    if not tool_calls or state["tool_iterations"] >= MAX_TOOL_ITERATIONS:
        return "end"
    grants = state.get("session_grants") or []
    all_auto_approved = all(
        approval_policy.is_auto_approved(tc["name"], tc.get("args"), grants) for tc in tool_calls
    )
    # Le garde-fou clavier virtuel (voir AUTO_APPROVAL_STREAK_LIMIT) : même un
    # tour entièrement auto-approuvé repasse par require_approval une fois le
    # plafond de tours consécutifs sans supervision humaine atteint.
    if all_auto_approved and state.get("auto_approval_streak", 0) < AUTO_APPROVAL_STREAK_LIMIT:
        return "auto_call_tools"
    return "call_tools"


async def require_approval(state: AgentState) -> dict:
    """Point de pause : bloque tant qu'un humain n'a pas approuvé/refusé (voir app/main.py)."""
    if state.get("approved") is None:
        raise NodeInterrupt("Approbation humaine requise avant exécution d'outil.")
    # Passage réel par un humain : réarme le budget de tours auto-approuvés
    # consécutifs (voir AUTO_APPROVAL_STREAK_LIMIT).
    updates = {"messages": [], "auto_approval_streak": 0, "grant_session": False}
    # "approuver pour la session" (Phase 3) : les outils du tour en attente
    # rejoignent session_grants, plafonnés à TIER_REVERSIBLE (auto + audit)
    # pour le reste du thread — voir approval_policy.effective_tier() et
    # AgentState.session_grants. Le tour lui-même reste soumis à CETTE
    # approbation (un grant ne s'applique qu'à partir du PROCHAIN appel du
    # même outil, pas rétroactivement à celui qui l'a demandé).
    if state.get("grant_session"):
        last = state["messages"][-1]
        granted_names = {tc["name"] for tc in last.tool_calls}
        updates["session_grants"] = list(set(state.get("session_grants") or []) | granted_names)
    return updates


def route_after_approval(state: AgentState) -> str:
    return "call_tools" if state["approved"] else "reject_tools"


def _to_png_data_uri(data_b64: str, mime_type: str) -> str:
    """
    Réencode systématiquement en PNG avant de transmettre au LLM. Le décodeur
    d'image d'Ollama (mtmd, côté llama.cpp) échoue explicitement sur le WebP
    ("Failed to load image or audio file") — or c'est le format par défaut de
    l'outil screen_shot de GhostDesk. Convertir ici plutôt que de compter sur
    le modèle pour systématiquement demander format="png" à chaque appel.
    """
    if mime_type == "image/png":
        return f"data:image/png;base64,{data_b64}"
    raw = base64.b64decode(data_b64)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def _split_image_blocks(result: dict) -> tuple[dict, list[dict]]:
    """
    Sépare les blocs image (format MCP : {"type": "image", "data": <base64>,
    "mimeType": ...}) du reste du résultat d'outil. Un ToolMessage (role
    "tool") ne peut contenir que du texte au format OpenAI-compatible — y
    mettre le base64 brut (via json.dumps sur tout le résultat, comme avant)
    produit un blob texte illisible pour le modèle, image ou pas, multimodal
    ou pas. Les images sont réinjectées séparément en message "user"
    multimodal (voir call_tools), le seul rôle qui supporte un bloc image_url.
    """
    content = result.get("content")
    if not isinstance(content, list):
        return result, []
    images = [b for b in content if isinstance(b, dict) and b.get("type") == "image"]
    if not images:
        return result, []
    rest = [b for b in content if b not in images]
    return {**result, "content": rest or "(voir image ci-dessous)"}, images


async def _execute_tool_calls(state: AgentState, config: dict, *, audit: bool) -> dict:
    """
    Logique partagée entre call_tools (atteint après require_approval, donc
    un humain vient d'examiner ce tour) et auto_call_tools (atteint
    directement depuis has_tool_calls, jamais vu par un humain CE tour-ci).
    `audit` distingue les deux : seul auto_call_tools journalise (Phase 2,
    app/audit_log.py) — un tour passé par require_approval a déjà sa trace
    dans l'historique de conversation ("⚠️ Approbation requise" + la réponse
    de l'utilisateur), inutile de le dupliquer dans le journal d'audit, qui
    sert justement à tracer ce qui n'a PAS été vu par un humain.
    """
    last = state["messages"][-1]
    new_messages = []
    grants = state.get("session_grants") or []
    thread_id = config.get("configurable", {}).get("thread_id", "")

    async with httpx.AsyncClient(timeout=60) as client:
        for tool_call in last.tool_calls:
            if audit:
                tier = approval_policy.effective_tier(tool_call["name"], tool_call.get("args"), grants)
                if tier == approval_policy.TIER_REVERSIBLE:
                    audit_log.log_tool_call(thread_id, tool_call["name"], tool_call["args"], tier)
            try:
                resp = await client.post(
                    f"{MCP_CLIENT_URL}/call",
                    json={"tool": tool_call["name"], "arguments": tool_call["args"]},
                )
                resp.raise_for_status()
                result = resp.json()
            except httpx.HTTPError as exc:
                result = {"error": str(exc)}
                images = []
            else:
                result, images = _split_image_blocks(result)

            new_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            for image in images:
                new_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": _to_png_data_uri(image["data"], image.get("mimeType", "image/png"))
                                },
                            }
                        ],
                    }
                )

    return {
        "messages": new_messages,
        "tool_iterations": state["tool_iterations"] + 1,
        "approved": None,  # réarme la pause pour le prochain tour d'outils
        # Incrémenté systématiquement (tour auto-approuvé ou juste validé par
        # un humain) : require_approval l'a déjà remis à 0 dans ce second cas,
        # donc cette exécution repart correctement à 1 (voir
        # AUTO_APPROVAL_STREAK_LIMIT).
        "auto_approval_streak": state.get("auto_approval_streak", 0) + 1,
    }


async def call_tools(state: AgentState, config: dict) -> dict:
    """Atteint après require_approval (humain déjà passé) : jamais audité, voir _execute_tool_calls."""
    return await _execute_tool_calls(state, config, audit=False)


async def auto_call_tools(state: AgentState, config: dict) -> dict:
    """Atteint directement depuis has_tool_calls (aucun humain CE tour) : audité, voir _execute_tool_calls."""
    return await _execute_tool_calls(state, config, audit=True)


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
    graph.add_node("auto_call_tools", auto_call_tools)
    graph.add_node("reject_tools", reject_tools)

    graph.set_entry_point("retrieve_context")
    graph.add_edge("retrieve_context", "select_skill")
    graph.add_edge("select_skill", "call_llm")
    graph.add_conditional_edges(
        "call_llm",
        has_tool_calls,
        {"call_tools": "require_approval", "auto_call_tools": "auto_call_tools", "end": END},
    )
    graph.add_conditional_edges(
        "require_approval", route_after_approval, {"call_tools": "call_tools", "reject_tools": "reject_tools"}
    )
    graph.add_edge("call_tools", "call_llm")
    graph.add_edge("auto_call_tools", "call_llm")
    graph.add_edge("reject_tools", "call_llm")

    return graph.compile(checkpointer=checkpointer or MemorySaver())


agent_graph = build_graph()
