"""
Expose une API compatible OpenAI (/v1/chat/completions) consommée par Open WebUI,
et qui délègue en interne au graphe LangGraph (app/graph.py). Supporte le
streaming SSE token-par-token via astream_events.

Supervision humaine : chaque appel d'outil suspend le graphe (voir
require_approval dans app/graph.py) jusqu'à ce que l'utilisateur réponde
"approuver"/"refuser" dans le tour de conversation suivant. Open WebUI
renvoyant l'historique complet à chaque requête sans identifiant de
conversation stable, le thread LangGraph est retrouvé en dérivant un
thread_id déterministe à partir du premier message humain (cf.
_derive_thread_id) — deux conversations démarrant par un message strictement
identique partageraient donc le même thread, limite assumée pour un usage
local mono-utilisateur.
"""

import hashlib
import json
import time
import uuid
from typing import List, Optional

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.graph import agent_graph

app = FastAPI(title="LangGraph Agent")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "agent-llm"
    messages: List[ChatMessage]
    stream: Optional[bool] = False


def _derive_thread_id(messages: List[ChatMessage]) -> str:
    first_human = next((m.content for m in messages if m.role == "user"), "")
    return hashlib.sha256(first_human.encode()).hexdigest()[:16]


def _format_approval_request(tool_calls: list) -> str:
    demandes = ", ".join(f'`{tc["name"]}`({tc["args"]})' for tc in tool_calls)
    return f'⚠️ Approbation requise pour : {demandes}. Réponds "approuver" ou "refuser" pour continuer.'


async def _resolve_run(request: ChatCompletionRequest):
    """
    Prépare le (config, run_input) à passer au graphe.

    Trois cas, distingués via l'état persisté par le checkpointer pour ce
    thread :
      - une pause d'approbation est en cours -> on injecte la décision et on
        reprend (run_input=None) ;
      - le thread existe déjà (conversation en cours, tours précédents déjà
        persistés) -> Open WebUI renvoie l'historique COMPLET à chaque
        requête, mais ce thread a déjà persisté les tours précédents via le
        checkpointer ; ne soumettre que les nouveaux messages (au-delà de
        owui_message_count) évite de dupliquer tout l'historique déjà stocké ;
      - tout premier tour de cette conversation -> aucun état persisté encore,
        on soumet l'historique initial tel quel.
    """
    config = {"configurable": {"thread_id": _derive_thread_id(request.messages)}}
    snapshot = await agent_graph.aget_state(config)
    # Nombre de messages Open WebUI que ce tour aura entièrement couverts une
    # fois sa réponse (unique) produite : l'historique actuel + cette réponse.
    owui_message_count = len(request.messages) + 1

    if snapshot.next:
        last_human = next(
            (m.content for m in reversed(request.messages) if m.role == "user"), ""
        )
        approved = "approuver" in last_human.lower()
        await agent_graph.aupdate_state(
            config, {"approved": approved, "owui_message_count": owui_message_count}
        )
        return config, None

    already_seen = snapshot.values.get("owui_message_count", 0) if snapshot.values else 0
    new_messages = request.messages[already_seen:]

    run_input = {
        "messages": [{"role": m.role, "content": m.content} for m in new_messages],
        "tool_iterations": 0,
        "approved": None,
        "owui_message_count": owui_message_count,
    }
    return config, run_input


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models():
    # nécessaire pour que Open WebUI découvre le "modèle" agent
    return {
        "object": "list",
        "data": [{"id": "agent-llm", "object": "model", "owned_by": "langgraph-agent"}],
    }


def _sse_chunk(completion_id: str, model: str, delta: dict, finish_reason: Optional[str] = None) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_response(config: dict, run_input: Optional[dict], model: str):
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    sent_role = False

    # Ne transmet au client QUE les tokens de contenu (on_chat_model_stream).
    # Les itérations qui décident d'un appel d'outil ont un contenu vide côté
    # LLM (le tool_call arrive dans un canal séparé), donc rien de visible
    # n'est envoyé pendant la résolution des outils : seule la réponse finale
    # apparaît, token par token. Si le graphe se met en pause pour
    # approbation, aucun token n'est émis par ce mécanisme (voir plus bas).
    async for event in agent_graph.astream_events(run_input, config, version="v2"):
        if event["event"] != "on_chat_model_stream":
            continue
        chunk = event["data"]["chunk"]
        if not chunk.content:
            continue
        if not sent_role:
            yield _sse_chunk(completion_id, model, {"role": "assistant", "content": chunk.content})
            sent_role = True
        else:
            yield _sse_chunk(completion_id, model, {"content": chunk.content})

    snapshot = await agent_graph.aget_state(config)
    if snapshot.next:
        pending = _format_approval_request(snapshot.values["messages"][-1].tool_calls)
        yield _sse_chunk(completion_id, model, {"role": "assistant", "content": pending})

    yield _sse_chunk(completion_id, model, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    config, run_input = await _resolve_run(request)

    if request.stream:
        return StreamingResponse(
            _stream_response(config, run_input, request.model), media_type="text/event-stream"
        )

    await agent_graph.ainvoke(run_input, config)

    snapshot = await agent_graph.aget_state(config)
    if snapshot.next:
        answer = _format_approval_request(snapshot.values["messages"][-1].tool_calls)
    else:
        answer = snapshot.values["messages"][-1].content

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
    }
