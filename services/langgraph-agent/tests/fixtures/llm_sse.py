"""
Construit des corps de réponse SSE conformes au format OpenAI streaming,
pour simuler vLLM dans les tests sans dépendre d'une vraie inférence.
"""

import json
import time
import uuid


def sse_body(deltas_with_finish):
    """
    deltas_with_finish : liste de tuples (delta_dict, finish_reason|None).
    Retourne le corps SSE complet, terminé par [DONE].
    """
    lines = []
    for delta, finish_reason in deltas_with_finish:
        payload = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "agent-llm",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        lines.append(f"data: {json.dumps(payload)}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines)


def tool_call_response(tool_name, tool_call_id, arguments_json):
    """Simule une réponse LLM qui décide d'appeler un outil, streamée en morceaux."""
    return sse_body(
        [
            (
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"index": 0, "id": tool_call_id, "type": "function", "function": {"name": tool_name, "arguments": ""}}
                    ],
                },
                None,
            ),
            ({"tool_calls": [{"index": 0, "function": {"arguments": arguments_json}}]}, None),
            ({}, "tool_calls"),
        ]
    )


def content_and_tool_call_response(content_text, tool_name, tool_call_id, arguments_json):
    """
    Simule un tour qui produit à la fois du texte visible (ex. le marqueur
    [CONSTAT: ...] du correctif latence, Itération 4 — voir
    app/graph.py:_verification_directive) ET un tool_call, dans le MÊME
    appel : le constat sur l'action précédente et la décision de la suite
    vivent désormais dans un seul tour, plus deux (voir HISTORY.md).
    """
    return sse_body(
        [({"role": "assistant", "content": content_text}, None)]
        + [
            (
                {
                    "tool_calls": [
                        {"index": 0, "id": tool_call_id, "type": "function", "function": {"name": tool_name, "arguments": ""}}
                    ],
                },
                None,
            ),
            ({"tool_calls": [{"index": 0, "function": {"arguments": arguments_json}}]}, None),
            ({}, "tool_calls"),
        ]
    )


def content_and_multi_tool_call_response(content_text, tool_calls):
    """
    Généralisation de content_and_tool_call_response à PLUSIEURS tool_calls
    dans le même tour (correctif latence 1/2-bis, voir HISTORY.md) : le
    constat vit désormais dans un tool call dédié obligatoire
    (report_and_act) plutôt qu'un marqueur texte, ce qui oblige à simuler au
    moins deux tool_calls (report_and_act + l'action réelle) dans la même
    réponse streamée. tool_calls : liste de (tool_name, tool_call_id,
    arguments_json).
    """
    header = {
        "tool_calls": [
            {"index": i, "id": tc_id, "type": "function", "function": {"name": name, "arguments": ""}}
            for i, (name, tc_id, _args) in enumerate(tool_calls)
        ],
    }
    arg_deltas = [
        ({"tool_calls": [{"index": i, "function": {"arguments": args}}]}, None)
        for i, (_name, _tc_id, args) in enumerate(tool_calls)
    ]
    return sse_body(
        [({"role": "assistant", "content": content_text}, None), (header, None)]
        + arg_deltas
        + [({}, "tool_calls")]
    )


def multi_tool_call_response(tool_calls):
    """
    Simule un tour où le modèle demande PLUSIEURS outils d'un coup.
    tool_calls : liste de (tool_name, tool_call_id, arguments_json).
    """
    header = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"index": i, "id": tc_id, "type": "function", "function": {"name": name, "arguments": ""}}
            for i, (name, tc_id, _args) in enumerate(tool_calls)
        ],
    }
    arg_deltas = [
        ({"tool_calls": [{"index": i, "function": {"arguments": args}}]}, None)
        for i, (_name, _tc_id, args) in enumerate(tool_calls)
    ]
    return sse_body([(header, None)] + arg_deltas + [({}, "tool_calls")])


def text_response(tokens):
    """Simule une réponse LLM en texte, streamée token par token."""
    return sse_body(
        [({"role": "assistant", "content": ""}, None)]
        + [({"content": tok}, None) for tok in tokens]
        + [({}, "stop")]
    )


def non_streaming_response(content):
    """
    Réponse LLM NON streamée (ChatCompletion classique), pour les appels via
    .ainvoke() plutôt que .astream()/.stream() — seul appel non-streamé du
    graphe : le nœud planificateur (app/graph.py:plan_task, Itération 1,
    Phase 1 « cœur cognitif »). À passer via httpx.Response(200, json=...),
    pas _sse_response (content-type JSON classique, pas text/event-stream).
    """
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "agent-llm",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }


def reasoning_tool_call_response(reasoning_tokens, tool_name, tool_call_id, arguments_json):
    """
    Simule un tour où le modèle raisonne (champ "reasoning") puis décide
    d'appeler un outil, sans jamais produire de "content" réel — cas normal
    pour un tool_call (le contenu visible reste vide, cf. tool_call_response).
    Reproduit le cas qui laissait la balise <think> ouverte dans le flux SSE
    streamé au client (voir app/main.py:_stream_response).
    """
    return sse_body(
        [({"role": "assistant", "content": ""}, None)]
        + [({"reasoning": tok}, None) for tok in reasoning_tokens]
        + [
            (
                {
                    "tool_calls": [
                        {"index": 0, "id": tool_call_id, "type": "function", "function": {"name": tool_name, "arguments": ""}}
                    ],
                },
                None,
            ),
            ({"tool_calls": [{"index": 0, "function": {"arguments": arguments_json}}]}, None),
            ({}, "tool_calls"),
        ]
    )


def reasoning_response(reasoning_tokens, content_tokens, field="reasoning"):
    """
    Simule une réponse qui streame un raisonnement dans un champ dédié des
    deltas, en plus de "content" — format hors standard OpenAI que
    langchain-openai ignore nativement (voir app/graph.py, patch de
    _convert_delta_to_message_chunk). `field` distingue les deux conventions
    rencontrées en conditions réelles : "reasoning" (Ollama, Qwen3+) et
    "reasoning_content" (llama-server/fork turboquant-webp, convention
    DeepSeek-R1/OpenAI o1 — confirmé par un appel streamé réel).
    """
    return sse_body(
        [({"role": "assistant", "content": ""}, None)]
        + [({field: tok}, None) for tok in reasoning_tokens]
        + [({"content": tok}, None) for tok in content_tokens]
        + [({}, "stop")]
    )


def reasoning_response_combined_final_chunk(reasoning_tokens, final_content, field="reasoning_content"):
    """
    Variante de reasoning_response où le DERNIER chunk contient à la fois la
    fin du raisonnement ET le début/toute la réponse finale dans le même
    delta ({field: ..., "content": ...}) — observé en conditions réelles
    avec TabbyAPI/ExLlamaV3 (llama-server/Ollama séparaient toujours les
    deux en chunks distincts). Voir app/graph.py,
    _convert_delta_with_reasoning : sans gérer ce cas, la vraie réponse
    était silencieusement jetée.
    """
    return sse_body(
        [({"role": "assistant", "content": ""}, None)]
        + [({field: tok}, None) for tok in reasoning_tokens[:-1]]
        + [({field: reasoning_tokens[-1], "content": final_content}, None)]
        + [({}, "stop")]
    )
