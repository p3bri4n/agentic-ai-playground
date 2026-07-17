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
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import audit_log
from app.graph import MAX_TOOL_ITERATIONS, agent_graph, describe_context, has_visible_answer

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


class ContextRequest(BaseModel):
    """
    POST /context (dashboard d'observabilité, services/dashboard) : accepte
    soit `messages` (même contrat que PendingCheckRequest, thread_id dérivé
    via _derive_thread_id), soit directement `thread_id` (Phase 3 — le
    dashboard le récupère via GET /threads/recent plutôt que de rejouer tout
    l'historique Open WebUI qu'il n'a de toute façon jamais eu). `thread_id`
    prend le pas s'il est fourni."""

    messages: Optional[List[ChatMessage]] = None
    thread_id: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    """Décision transmise hors bande, depuis un bouton d'UI (Open WebUI Action
    function) plutôt que par un message texte "approuver"/"refuser" — voir
    /approve. `messages` doit être l'historique complet tel que vu par Open
    WebUI au moment du clic (même contrat que ChatCompletionRequest.messages),
    nécessaire pour dériver le même thread_id et tenir owui_message_count à
    jour de la même façon que le flux texte existant."""

    messages: List[ChatMessage]
    approved: bool
    # "approuver pour la session" (Phase 3) : accorde l'outil pour tout le
    # thread plutôt que pour ce seul tour — voir AgentState.session_grants,
    # app/graph.py. Ignoré si approved=False.
    grant_session: bool = False


def _derive_thread_id(messages: List[ChatMessage]) -> str:
    first_human = next((m.content for m in messages if m.role == "user"), "")
    return hashlib.sha256(first_human.encode()).hexdigest()[:16]


# Registre en mémoire process (Phase 3, jamais persisté — cohérent avec le
# checkpointer MemorySaver lui-même en mémoire uniquement, voir README
# section Persistance des données) des threads vus récemment, pour que le
# dashboard d'observabilité (services/dashboard) puisse appeler POST /context
# sans avoir à rejouer l'historique Open WebUI complet, qu'il n'a de toute
# façon jamais reçu. Alimenté uniquement par les endpoints qui font
# réellement progresser une conversation (_resolve_run, /approve) — pas par
# /pending ni /context eux-mêmes, strictement lecture seule.
_recent_threads: dict = {}


def _touch_thread(thread_id: str) -> None:
    _recent_threads[thread_id] = datetime.now(timezone.utc).isoformat()


def _format_approval_request(tool_calls: list) -> str:
    demandes = ", ".join(f'`{tc["name"]}`({tc["args"]})' for tc in tool_calls)
    return (
        f'⚠️ Approbation requise pour : {demandes}. Réponds "approuver" (une fois), '
        f'"approuver pour la session" (pour ne plus être sollicité sur ce(s) outil(s) '
        f"tant que dure cette conversation) ou \"refuser\" pour continuer."
    )


def _parse_approval_reply(text: str) -> tuple:
    """
    Distingue les trois réponses possibles au message d'approbation (voir
    _format_approval_request) : "approuver pour la session" contenant lui-même
    "approuver", le grant est détecté en cherchant "session" EN PLUS
    d'"approuver" — un simple "approuver" ne grant jamais rien.
    """
    lowered = text.lower()
    approved = "approuver" in lowered
    grant_session = approved and "session" in lowered
    return approved, grant_session


def _format_iteration_limit_notice(tool_calls: list) -> str:
    demandes = ", ".join(f'`{tc["name"]}`({tc["args"]})' for tc in tool_calls)
    return (
        f"⚠️ Limite d'itérations d'outils atteinte pour cette tâche avant d'avoir pu exécuter : "
        f"{demandes}. Envoie un nouveau message pour relancer une tâche fraîche."
    )


def _format_empty_answer_notice() -> str:
    """
    Non-régression (bug réel observé en usage réel, cf. tableau des bugs du
    README) : un modèle peut terminer un tour sans aucun tool_calls
    structuré ET sans texte de réponse visible — ex. une tentative d'appel
    d'outil écrite en prose (imitant la syntaxe <tool_call> qu'il voit
    rendue par le template pour ses propres tours précédents) noyée dans le
    raisonnement, jamais reconnue comme un tool_calls OpenAI. Sans ce
    message, l'utilisateur ne voit que la bulle de raisonnement se refermer
    sur rien : le même symptôme de "l'agent semble s'arrêter en plein
    milieu d'une tâche" que MAX_TOOL_ITERATIONS (voir
    _format_iteration_limit_notice), mais via un chemin différent (aucun
    tool_calls en attente, juste une réponse vide).
    """
    return (
        "⚠️ Le modèle a terminé son tour sans réponse exploitable (probablement une "
        "tentative d'appel d'outil restée noyée dans son raisonnement plutôt que d'être "
        "émise comme un vrai appel d'outil structuré). Envoie un nouveau message pour réessayer."
    )


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
    # recursion_limit compte les NŒUDS visités (pas les appels d'outils) et
    # vaut 25 par défaut côté LangGraph — indépendant de MAX_TOOL_ITERATIONS
    # et bien plus vite atteint : la boucle GhostDesk auto-approuvée peut
    # enchaîner de nombreux tours call_llm/call_tools sans jamais repasser
    # par une pause d'approbation qui, elle, découperait le run en plusieurs
    # appels de ainvoke() avec un budget de récursion frais à chaque fois.
    # Sans cet ajustement, un run auto-approuvé assez long lève un
    # GraphRecursionError brut (500) avant même d'atteindre notre propre
    # notice de limite (voir _format_iteration_limit_notice plus haut).
    thread_id = _derive_thread_id(request.messages)
    _touch_thread(thread_id)
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": MAX_TOOL_ITERATIONS * 4 + 10,
    }
    snapshot = await agent_graph.aget_state(config)
    # Nombre de messages Open WebUI que ce tour aura entièrement couverts une
    # fois sa réponse (unique) produite : l'historique actuel + cette réponse.
    owui_message_count = len(request.messages) + 1

    if snapshot.next:
        last_human = next(
            (m.content for m in reversed(request.messages) if m.role == "user"), ""
        )
        approved, grant_session = _parse_approval_reply(last_human)
        await agent_graph.aupdate_state(
            config,
            {"approved": approved, "grant_session": grant_session, "owui_message_count": owui_message_count},
        )
        return config, None

    already_seen = snapshot.values.get("owui_message_count", 0) if snapshot.values else 0
    new_messages = request.messages[already_seen:]

    run_input = {
        "messages": [{"role": m.role, "content": m.content} for m in new_messages],
        "tool_iterations": 0,
        "approved": None,
        "owui_message_count": owui_message_count,
        "think_opened": False,
        "think_closed": False,
        "auto_approval_streak": 0,
        "session_grants": [],
        "grant_session": False,
        "empty_answer_retries": 0,
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

    # Si le modèle a raisonné avant de décider d'appeler un outil, les tokens
    # <think>...</think> streamés ci-dessus (voir app/graph.py) n'ont jamais
    # reçu leur balise fermante : côté LLM, un tour qui aboutit à un
    # tool_call a un content final vide, donc aucun chunk de contenu "réel"
    # n'arrive jamais pour déclencher la fermeture (voir
    # _convert_delta_with_reasoning). call_llm referme bien la balise sur le
    # message PERSISTÉ après coup, mais ça ne corrige pas les chunks déjà
    # envoyés au client dans la boucle ci-dessus — c'est donc sur ce qui a été
    # réellement streamé (`streamed_text`) qu'il faut vérifier, pas sur
    # l'état déjà réparé. Sans ce correctif, le texte ajouté ensuite (pause
    # d'approbation ou notice de limite) se retrouve avalé dans le <think>
    # resté ouvert côté client, invisible en dehors de la bulle repliée.
    full_streamed = "".join(streamed_text)
    closing_prefix = "</think>\n\n" if full_streamed.count("<think>") > full_streamed.count("</think>") else ""
    # closing_prefix ferme la balise côté client, mais AgentState.think_closed
    # (app/graph.py) reste False puisque call_llm n'a pas pu la fermer
    # lui-même (tool_calls présent). Sans cette mise à jour, une reprise après
    # approbation repartirait avec think_opened=True/think_closed=False :
    # un nouveau round de raisonnement ne recevrait alors aucune balise
    # ouvrante (déjà "opened" selon l'état persisté) mais recevrait quand
    # même une balise fermante en fin de tour — un </think> orphelin visible
    # côté client, sans <think> correspondant dans ce qu'il a reçu.
    if closing_prefix:
        await agent_graph.aupdate_state(config, {"think_opened": False, "think_closed": False})

    snapshot = await agent_graph.aget_state(config)
    if snapshot.next:
        pending = closing_prefix + _format_approval_request(snapshot.values["messages"][-1].tool_calls)
        yield _sse_chunk(completion_id, model, {"role": "assistant", "content": pending})
    else:
        last_message = snapshot.values["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            # Le graphe s'est arrêté sur MAX_TOOL_ITERATIONS avec un
            # tool_call encore en attente côté modèle : sans ce message,
            # l'agent semble juste "s'arrêter" en plein milieu d'une tâche,
            # sans qu'aucune erreur ni pause d'approbation ne l'explique
            # (voir MAX_TOOL_ITERATIONS, app/graph.py).
            notice = closing_prefix + _format_iteration_limit_notice(last_message.tool_calls)
            yield _sse_chunk(completion_id, model, {"role": "assistant", "content": notice})
        elif not has_visible_answer(full_streamed + closing_prefix):
            # Voir _format_empty_answer_notice : aucun tool_calls en attente
            # ET rien de visible hors <think> — même symptôme "agent
            # silencieux" que ci-dessus, cause différente.
            notice = closing_prefix + _format_empty_answer_notice()
            yield _sse_chunk(completion_id, model, {"role": "assistant", "content": notice})

    yield _sse_chunk(completion_id, model, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"


async def _current_answer(config: dict) -> str:
    snapshot = await agent_graph.aget_state(config)
    if snapshot.next:
        return _format_approval_request(snapshot.values["messages"][-1].tool_calls)
    last_message = snapshot.values["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return _format_iteration_limit_notice(last_message.tool_calls)
    if not has_visible_answer(last_message.content):
        return _format_empty_answer_notice()
    return last_message.content


@app.post("/pending")
async def pending(request: PendingCheckRequest):
    """Lecture seule : n'invoque jamais le graphe, ne modifie aucun état."""
    config = {"configurable": {"thread_id": _derive_thread_id(request.messages)}}
    snapshot = await agent_graph.aget_state(config)
    if not snapshot.next:
        return {"pending": False}
    return {"pending": True, "text": _format_approval_request(snapshot.values["messages"][-1].tool_calls)}


@app.post("/context")
async def context(request: ContextRequest):
    """
    Lecture seule (même convention que /pending, jamais d'effet de bord) :
    décomposition approximative du contexte persisté pour ce thread, à
    l'usage du dashboard d'observabilité (services/dashboard, POST
    /api/snapshot). Voir describe_context (app/graph.py) pour le détail des
    blocs. thread_id explicite (Phase 3, via GET /threads/recent) ou dérivé
    de `messages` comme /pending. Aucun état pour ce thread (thread_id
    inconnu du checkpointer, ou jamais renseigné) -> 200 avec des blocs
    vides plutôt qu'une 404 : le dashboard poll ce endpoint en continu, une
    404 transitoire (ex. juste avant le tout premier message d'une
    conversation) serait juste du bruit à gérer côté client.
    """
    thread_id = request.thread_id or _derive_thread_id(request.messages or [])
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await agent_graph.aget_state(config)
    messages = snapshot.values.get("messages", []) if snapshot.values else []

    pending_text = None
    if snapshot.next and messages and getattr(messages[-1], "tool_calls", None):
        pending_text = _format_approval_request(messages[-1].tool_calls)

    blocks = describe_context(messages, pending_text)
    return {
        "blocks": blocks,
        "total_est_tokens": sum(b["est_tokens"] for b in blocks),
        "message_count": len(messages),
    }


@app.get("/threads/recent")
async def threads_recent():
    """
    Threads vus récemment (Phase 3, voir _recent_threads plus haut) : les 5
    plus récents, triés du plus récent au plus ancien — alimente le menu
    déroulant du dashboard d'observabilité (services/dashboard), qui n'a
    sinon aucun moyen de savoir quel thread interroger via POST /context.
    """
    ordered = sorted(_recent_threads.items(), key=lambda item: item[1], reverse=True)[:5]
    return {"threads": [{"thread_id": tid, "last_seen": last_seen} for tid, last_seen in ordered]}


@app.get("/audit")
async def audit(thread_id: Optional[str] = None):
    """
    Consultation du journal d'audit (Phase 2, app/audit_log.py) : les
    tool_calls TIER_REVERSIBLE effectivement exécutés (auto-approuvés ou
    accordés pour la session). Sans thread_id, renvoie tout le journal
    disponible (tous fichiers journaliers confondus) ; avec thread_id, ne
    renvoie que les entrées de ce thread.
    """
    return {"entries": audit_log.read_entries(thread_id)}


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
    # Voir la note sur recursion_limit dans _resolve_run : ce endpoint reprend
    # aussi une exécution du graphe (ainvoke plus bas), donc soumis au même
    # risque de GraphRecursionError sur une boucle auto-approuvée longue.
    thread_id = _derive_thread_id(request.messages)
    _touch_thread(thread_id)
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": MAX_TOOL_ITERATIONS * 4 + 10,
    }
    snapshot = await agent_graph.aget_state(config)
    if not snapshot.next:
        raise HTTPException(status_code=409, detail="Aucune approbation en attente pour ce thread.")

    owui_message_count = len(request.messages)
    await agent_graph.aupdate_state(
        config,
        {
            "approved": request.approved,
            "grant_session": request.approved and request.grant_session,
            "owui_message_count": owui_message_count,
        },
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
