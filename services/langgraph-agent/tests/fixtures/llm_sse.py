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


def text_response(tokens):
    """Simule une réponse LLM en texte, streamée token par token."""
    return sse_body(
        [({"role": "assistant", "content": ""}, None)]
        + [({"content": tok}, None) for tok in tokens]
        + [({}, "stop")]
    )
