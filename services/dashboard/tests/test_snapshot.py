"""
GET /api/snapshot : agrégation best-effort de llama-server (/metrics,
/slots), langgraph-agent (/threads/recent, /context) et nvidia-smi (VRAM).
Chaque source en panne renvoie sa section à null/[] plutôt que de faire
échouer toute la requête (statut 200 dans tous les cas) — c'est justement ce
que ces tests figent.
"""

import httpx
import pytest
import respx

from app.prometheus import extract_llama_metrics

LLAMA_METRICS_PAYLOAD = (
    "llamacpp:predicted_tokens_seconds 34.2\n"
    "llamacpp:prompt_tokens_seconds 812.5\n"
    "llamacpp:kv_cache_usage_ratio 0.42\n"
    "llamacpp:kv_cache_tokens 13762\n"
    "llamacpp:requests_processing 1\n"
    "llamacpp:requests_deferred 0\n"
)

LLAMA_SLOTS_PAYLOAD = [{"id": 0, "n_ctx": 32768, "is_processing": True, "n_past": 4096}]


def _client():
    import app.main as main_mod

    transport = httpx.ASGITransport(app=main_mod.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_snapshot_aggregates_all_sources_when_healthy():
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-llama-server/metrics").mock(
            return_value=httpx.Response(200, text=LLAMA_METRICS_PAYLOAD)
        )
        mock.get("http://fake-llama-server/slots").mock(
            return_value=httpx.Response(200, json=LLAMA_SLOTS_PAYLOAD)
        )
        mock.get("http://fake-langgraph-agent/threads/recent").mock(
            return_value=httpx.Response(
                200, json={"threads": [{"thread_id": "abc123", "last_seen": "2026-07-17T10:00:00+00:00"}]}
            )
        )
        mock.post("http://fake-langgraph-agent/context").mock(
            return_value=httpx.Response(
                200,
                json={
                    "blocks": [{"label": "System prompt", "kind": "system", "est_tokens": 10, "count": 1}],
                    "total_est_tokens": 10,
                    "message_count": 1,
                },
            )
        )

        async with _client() as client:
            resp = await client.get("/api/snapshot")

    assert resp.status_code == 200
    body = resp.json()
    assert body["llama"]["metrics"] == extract_llama_metrics(LLAMA_METRICS_PAYLOAD)
    assert body["llama"]["slots"] == [{"id": 0, "n_ctx": 32768, "is_processing": True, "used_tokens": 4096}]
    assert body["threads"] == [{"thread_id": "abc123", "last_seen": "2026-07-17T10:00:00+00:00"}]
    # aucun thread_id explicite en query -> le plus récent (threads[0]) choisi par défaut
    assert body["selected_thread_id"] == "abc123"
    assert body["context"]["total_est_tokens"] == 10
    assert body["gpu"] is None  # ENABLE_GPU_STATS=false dans conftest.py


@pytest.mark.asyncio
async def test_snapshot_llama_server_down_returns_null_section_status_200():
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-llama-server/metrics").mock(side_effect=httpx.ConnectError("refused"))
        mock.get("http://fake-llama-server/slots").mock(side_effect=httpx.ConnectError("refused"))
        mock.get("http://fake-langgraph-agent/threads/recent").mock(
            return_value=httpx.Response(200, json={"threads": []})
        )

        async with _client() as client:
            resp = await client.get("/api/snapshot")

    assert resp.status_code == 200
    body = resp.json()
    assert body["llama"] == {"metrics": None, "slots": None}
    assert body["threads"] == []
    assert body["selected_thread_id"] is None
    assert body["context"] is None


@pytest.mark.asyncio
async def test_snapshot_langgraph_agent_down_returns_null_context():
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-llama-server/metrics").mock(return_value=httpx.Response(200, text=""))
        mock.get("http://fake-llama-server/slots").mock(return_value=httpx.Response(200, json=[]))
        mock.get("http://fake-langgraph-agent/threads/recent").mock(side_effect=httpx.ConnectError("refused"))

        async with _client() as client:
            resp = await client.get("/api/snapshot")

    assert resp.status_code == 200
    body = resp.json()
    assert body["threads"] == []
    assert body["context"] is None


@pytest.mark.asyncio
async def test_snapshot_explicit_thread_id_overrides_most_recent():
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-llama-server/metrics").mock(return_value=httpx.Response(200, text=""))
        mock.get("http://fake-llama-server/slots").mock(return_value=httpx.Response(200, json=[]))
        mock.get("http://fake-langgraph-agent/threads/recent").mock(
            return_value=httpx.Response(
                200,
                json={
                    "threads": [
                        {"thread_id": "recent", "last_seen": "2026-07-17T10:00:00+00:00"},
                        {"thread_id": "older", "last_seen": "2026-07-17T09:00:00+00:00"},
                    ]
                },
            )
        )
        context_route = mock.post("http://fake-langgraph-agent/context").mock(
            return_value=httpx.Response(
                200, json={"blocks": [], "total_est_tokens": 0, "message_count": 0}
            )
        )

        async with _client() as client:
            resp = await client.get("/api/snapshot?thread_id=older")

    assert resp.status_code == 200
    assert resp.json()["selected_thread_id"] == "older"
    assert context_route.calls.last.request.content
    import json as _json

    assert _json.loads(context_route.calls.last.request.content)["thread_id"] == "older"


@pytest.mark.asyncio
async def test_snapshot_gpu_stats_enabled_uses_nvidia_smi(monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "ENABLE_GPU_STATS", True)
    monkeypatch.setattr(
        main_mod,
        "run_nvidia_smi",
        lambda: "0, GPU-Fake, 1000, 2000, 50\n",
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-llama-server/metrics").mock(return_value=httpx.Response(200, text=""))
        mock.get("http://fake-llama-server/slots").mock(return_value=httpx.Response(200, json=[]))
        mock.get("http://fake-langgraph-agent/threads/recent").mock(
            return_value=httpx.Response(200, json={"threads": []})
        )

        async with _client() as client:
            resp = await client.get("/api/snapshot")

    assert resp.status_code == 200
    assert resp.json()["gpu"] == [
        {"index": 0, "name": "GPU-Fake", "memory_used_mib": 1000, "memory_total_mib": 2000, "utilization_pct": 50}
    ]


@pytest.mark.asyncio
async def test_snapshot_gpu_stats_disabled_by_default_no_error(monkeypatch):
    """ENABLE_GPU_STATS absent (conftest.py le met à 'false') : section gpu à
    None, jamais d'appel à nvidia-smi ni d'erreur."""
    import app.main as main_mod

    def _boom():
        raise AssertionError("run_nvidia_smi ne doit jamais être appelé si ENABLE_GPU_STATS est désactivé")

    monkeypatch.setattr(main_mod, "run_nvidia_smi", _boom)

    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-llama-server/metrics").mock(return_value=httpx.Response(200, text=""))
        mock.get("http://fake-llama-server/slots").mock(return_value=httpx.Response(200, json=[]))
        mock.get("http://fake-langgraph-agent/threads/recent").mock(
            return_value=httpx.Response(200, json={"threads": []})
        )

        async with _client() as client:
            resp = await client.get("/api/snapshot")

    assert resp.status_code == 200
    assert resp.json()["gpu"] is None
