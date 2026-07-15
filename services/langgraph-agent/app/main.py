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

from fastapi import FastAPI, HTTPException
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


class PendingCheckRequest(BaseModel):
    """Ne nécessite que de dériver le même thread_id que le reste (voir
    _derive_thread_id, basé uniquement sur le premier message humain) — donc
    insensible au fait que le contenu du dernier message assistant, tel que
    renvoyé par le client, puisse être vide ou tronqué (observé avec Open
    WebUI sur les messages contenant des balises <think>, indépendamment de
    ce service : sa valeur affichée et sa valeur stockée en interne peuvent
    diverger). Permet à un client (bouton d'UI) de savoir s'il y a une
    approbation en attente sans dépendre de ce contenu."""

    messages: List[ChatMessage]


class ApprovalDecisionRequest(BaseModel):
    """Décision transmise hors bande, depuis un bouton d'UI (Open WebUI Action
    function) plutôt que par un message texte "approuver"/"refuser" — voir
    /approve. `messages` doit être l'historique complet tel que vu par Open
    WebUI au moment du clic (même contrat que ChatCompletionRequest.messages),
    nécessaire pour dériver le même thread_id et tenir owui_message_count à
    jour de la même façon que le flux texte existant."""

    messages: List[ChatMessage]
    approved: bool


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
    streamed_text = []

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
        streamed_text.append(chunk.content)
        if not sent_role:
            yield _sse_chunk(completion_id, model, {"role": "assistant", "content": chunk.content})
            sent_role = True
        else:
            yield _sse_chunk(completion_id, model, {"content": chunk.content})

    snapshot = await agent_graph.aget_state(config)
    if snapshot.next:
        # Si le modèle a raisonné avant de décider d'appeler un outil, les
        # tokens <think>...</think> streamés ci-dessus (voir app/graph.py)
        # n'ont jamais reçu leur balise fermante : côté LLM, un tour qui
        # aboutit à un tool_call a un content final vide, donc aucun chunk de
        # contenu "réel" n'arrive jamais pour déclencher la fermeture (voir
        # _convert_delta_with_reasoning). call_llm referme bien la balise sur
        # le message PERSISTÉ après coup, mais ça ne corrige pas les chunks
        # déjà envoyés au client dans la boucle ci-dessus — c'est donc sur ce
        # qui a été réellement streamé (`streamed_text`) qu'il faut vérifier,
        # pas sur l'état déjà réparé. Sans ce correctif, le texte d'approbation
        # qui suit se retrouve avalé dans le <think> resté ouvert côté client,
        # invisible en dehors de la bulle de pensée repliée.
        full_streamed = "".join(streamed_text)
        needs_closing_tag = full_streamed.count("<think>") > full_streamed.count("</think>")
        pending = _format_approval_request(snapshot.values["messages"][-1].tool_calls)
        if needs_closing_tag:
            pending = "</think>\n\n" + pending
        yield _sse_chunk(completion_id, model, {"role": "assistant", "content": pending})

    yield _sse_chunk(completion_id, model, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"


async def _current_answer(config: dict) -> str:
    snapshot = await agent_graph.aget_state(config)
    if snapshot.next:
        return _format_approval_request(snapshot.values["messages"][-1].tool_calls)
    return snapshot.values["messages"][-1].content


@app.post("/pending")
async def pending(request: PendingCheckRequest):
    """Lecture seule : n'invoque jamais le graphe, ne modifie aucun état."""
    config = {"configurable": {"thread_id": _derive_thread_id(request.messages)}}
    snapshot = await agent_graph.aget_state(config)
    if not snapshot.next:
        return {"pending": False}
    return {"pending": True, "text": _format_approval_request(snapshot.values["messages"][-1].tool_calls)}


@app.post("/approve")
async def approve(request: ApprovalDecisionRequest):
    """
    Reprend un thread en pause d'approbation directement depuis une décision
    hors bande (bouton d'UI), sans passer par le message texte "approuver"/
    "refuser" qu'attend normalement _resolve_run.

    Bookkeeping owui_message_count (voir _resolve_run) : contrairement au
    flux texte, où le message "approuver" de l'utilisateur ET la réponse
    finale s'ajoutent tous deux à l'historique Open WebUI (d'où le +1 sur le
    compte déjà présent), ce bouton ne fait qu'éditer EN PLACE le message
    "⚠️ Approbation requise" existant avec la réponse finale (voir la
    fonction Action Open WebUI fournie) — aucun nouveau message n'est ajouté.
    Le compte reste donc celui déjà vu, sans +1, sous peine de désynchroniser
    le découpage `request.messages[already_seen:]` du tour normal suivant et
    de perdre le premier message que l'utilisateur enverra après.
    """
    config = {"configurable": {"thread_id": _derive_thread_id(request.messages)}}
    snapshot = await agent_graph.aget_state(config)
    if not snapshot.next:
        raise HTTPException(status_code=409, detail="Aucune approbation en attente pour ce thread.")

    owui_message_count = len(request.messages)
    await agent_graph.aupdate_state(
        config, {"approved": request.approved, "owui_message_count": owui_message_count}
    )
    await agent_graph.ainvoke(None, config)

    return {"content": await _current_answer(config)}


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    config, run_input = await _resolve_run(request)

    if request.stream:
        return StreamingResponse(
            _stream_response(config, run_input, request.model), media_type="text/event-stream"
        )

    await agent_graph.ainvoke(run_input, config)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": await _current_answer(config)},
                "finish_reason": "stop",
            }
        ],
    }
