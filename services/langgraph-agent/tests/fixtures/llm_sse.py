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


def reasoning_response(reasoning_tokens, content_tokens):
    """
    Simule une réponse Ollama (Qwen3+) qui streame un raisonnement dans le
    champ "reasoning" des deltas, en plus de "content" — format hors standard
    OpenAI que langchain-openai ignore nativement (voir app/graph.py, patch de
    _convert_delta_to_message_chunk).
    """
    return sse_body(
        [({"role": "assistant", "content": ""}, None)]
        + [({"reasoning": tok}, None) for tok in reasoning_tokens]
        + [({"content": tok}, None) for tok in content_tokens]
        + [({}, "stop")]
    )
