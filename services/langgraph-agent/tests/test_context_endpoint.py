"""
POST /context (services/dashboard, dashboard d'observabilité) : décomposition
approximative du contexte persisté pour un thread. Lecture seule comme
/pending — ces tests figent la décomposition en blocs (system/skills/
tools_schema/history_text/images) et la non-régression "thread inconnu ->
blocs vides, jamais 404" (le dashboard poll ce endpoint en continu).
"""

import base64

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import text_response, tool_call_response

TINY_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


@pytest.mark.asyncio
async def test_context_decomposition_with_mixed_text_and_image_history():
    import app.graph as g
    import app.main as main_mod

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-context-manager/retrieve").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        mock.post("http://fake-skill-manager/match").mock(
            return_value=httpx.Response(200, json={"skill": None})
        )
        mock.get("http://fake-mcp-client/tools/schema").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tools": [
                        {"name": "screen_shot", "description": "Capture l'écran", "inputSchema": {}},
                        {"name": "app_list", "description": "Liste les apps", "inputSchema": {}},
                    ]
                },
            )
        )
        mock.post("http://fake-mcp-client/call").mock(
            return_value=httpx.Response(
                200, json={"content": [{"type": "image", "data": TINY_PNG_B64, "mimeType": "image/png"}]}
            )
        )
        route = mock.post("http://fake-vllm/v1/chat/completions")
        route.side_effect = [
            # screen_shot est tier lecture (approval_policy) : auto-approuvé,
            # pas de pause d'approbation dans ce flux.
            _sse_response(tool_call_response("screen_shot", "call_1", "{}")),
            _sse_response(text_response(["Voici", " l'écran."])),
        ]

        g.agent_graph = g.build_graph()
        main_mod.agent_graph = g.agent_graph

        transport = httpx.ASGITransport(app=main_mod.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "agent-llm",
                    "messages": [{"role": "user", "content": "Capture l'écran"}],
                    "stream": False,
                },
            )
            assert resp.json()["choices"][0]["message"]["content"] == "Voici l'écran."

            thread_id = main_mod._derive_thread_id(
                [type("M", (), {"role": "user", "content": "Capture l'écran"})()]
            )
            ctx_resp = await client.post("/context", json={"thread_id": thread_id})

        assert ctx_resp.status_code == 200
        body = ctx_resp.json()
        blocks = {b["kind"]: b for b in body["blocks"]}

        assert set(blocks) == {"system", "skills", "tools_schema", "history_text", "images"}
        # system prompt transitoire (GROUNDING_DIRECTIVE + DOWNLOAD_DIRECTIVE +
        # BULK_CHECK_DIRECTIVE + PEREMPTION_DIRECTIVE, voir Phase 1d-révisée
        # puis conscience temporelle puis investigation T1) toujours présent,
        # aucun contexte RAG/skill injecté dans ce flux (résultats vides).
        assert blocks["system"]["count"] == 4
        assert blocks["skills"]["count"] == 0
        # Schéma d'outils mesuré depuis le cache _tools_schema_cache (2 outils
        # enregistrés côté mcp-client), jamais recalculé.
        assert blocks["tools_schema"]["count"] == 2
        assert blocks["tools_schema"]["est_tokens"] > 0
        # human(texte), AI(tool_call), tool, AI(texte final) : 4 messages
        # textuels, le message image étant compté à part.
        assert blocks["history_text"]["count"] == 4
        assert blocks["images"] == {
            "label": "Images",
            "kind": "images",
            "est_tokens": 1500,
            "count": 1,
        }

        assert body["message_count"] == 5
        assert body["total_est_tokens"] == sum(b["est_tokens"] for b in body["blocks"])
        assert body["total_est_tokens"] > 0

        # /v1/chat/completions a bien enregistré ce thread comme "récent"
        # (Phase 3, voir _touch_thread) — alimente GET /threads/recent.
        assert thread_id in main_mod._recent_threads


@pytest.mark.asyncio
async def test_context_unknown_thread_returns_empty_blocks_not_404():
    import app.graph as g
    import app.main as main_mod

    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/context", json={"thread_id": "jamais-vu-1234"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["message_count"] == 0
    assert body["total_est_tokens"] == 0
    assert all(b["count"] == 0 and b["est_tokens"] == 0 for b in body["blocks"])
    assert {b["kind"] for b in body["blocks"]} == {
        "system",
        "skills",
        "tools_schema",
        "history_text",
        "images",
    }


@pytest.mark.asyncio
async def test_context_accepts_messages_like_pending():
    """Même contrat que /pending : dérive aussi thread_id depuis `messages`."""
    import app.graph as g
    import app.main as main_mod

    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/context", json={"messages": [{"role": "user", "content": "Salut"}]})

    assert resp.status_code == 200
    assert resp.json()["message_count"] == 0


@pytest.mark.asyncio
async def test_threads_recent_ordered_by_recency_and_capped_at_five():
    import app.main as main_mod

    timestamps = [
        "2026-01-01T00:00:00+00:00",
        "2026-01-02T00:00:00+00:00",
        "2026-01-03T00:00:00+00:00",
        "2026-01-04T00:00:00+00:00",
        "2026-01-05T00:00:00+00:00",
        "2026-01-06T00:00:00+00:00",
    ]
    for i, ts in enumerate(timestamps):
        main_mod._recent_threads[f"thread-{i}"] = ts

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/threads/recent")

    assert resp.status_code == 200
    threads = resp.json()["threads"]
    assert [t["thread_id"] for t in threads] == [
        "thread-5",
        "thread-4",
        "thread-3",
        "thread-2",
        "thread-1",
    ]
    assert len(threads) == 5
