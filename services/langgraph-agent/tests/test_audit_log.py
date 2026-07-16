"""
Tests du journal d'audit (Phase 2, app/audit_log.py) : écriture au niveau du
graphe (call_tools) et lecture via l'endpoint GET /audit (app/main.py).
AUDIT_LOG_DIR pointe vers un répertoire temporaire dédié aux tests (voir
tests/conftest.py, _reset_audit_log_dir), jamais vers /workspace/.audit.
"""

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import text_response, tool_call_response


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


CONFIG = {"configurable": {"thread_id": "test-thread-audit"}}


@pytest.fixture
def mock_side_services():
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-context-manager/retrieve").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        mock.post("http://fake-skill-manager/match").mock(
            return_value=httpx.Response(200, json={"skill": None})
        )
        mock.get("http://fake-mcp-client/tools/schema").mock(
            return_value=httpx.Response(200, json={"tools": []})
        )
        yield mock


@pytest.mark.asyncio
async def test_tier_reversible_auto_approved_call_is_audited(mock_side_services):
    import app.audit_log as audit_log
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("mouse_click", "call_1", '{"x": 1, "y": 2}')),
        _sse_response(text_response(["Cliqué", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique là"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    entries = audit_log.read_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["thread_id"] == "test-thread-audit"
    assert entry["tool"] == "mouse_click"
    assert entry["arguments"] == {"x": 1, "y": 2}
    assert entry["tier"] == "reversible"
    assert "timestamp" in entry


@pytest.mark.asyncio
async def test_tier_read_call_is_not_audited(mock_side_services):
    """Silencieux par design (voir approval_policy.py) : rien de nouveau à tracer."""
    import app.audit_log as audit_log
    import app.graph as g

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}'))
    )
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "pwd"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    assert audit_log.read_entries() == []


@pytest.mark.asyncio
async def test_granted_sensitive_tool_is_audited_once_auto_approved(mock_side_services):
    """
    Un outil TIER_SENSITIVE accordé pour la session (Phase 3) devient
    TIER_REVERSIBLE pour les appels suivants : ceux-ci doivent apparaître
    dans le journal d'audit, contrairement au tout premier appel (qui, lui,
    est passé par une approbation humaine explicite, déjà tracée dans
    l'historique de conversation).
    """
    import app.audit_log as audit_log
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("key_type", "call_1", '{"text": "Ceci est un texte assez long pour rester sensible par defaut"}')),
        _sse_response(tool_call_response("key_type", "call_2", '{"text": "Un second texte tout aussi long pour verifier le comportement"}')),
        _sse_response(text_response(["Fini", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Tape hello puis world"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True, "grant_session": True})
    await g.agent_graph.ainvoke(None, CONFIG)

    entries = audit_log.read_entries()
    assert len(entries) == 1  # seul le deuxième appel (auto-approuvé via le grant) est audité
    assert entries[0]["tool"] == "key_type"
    assert entries[0]["arguments"] == {"text": "Un second texte tout aussi long pour verifier le comportement"}


@pytest.mark.asyncio
async def test_audit_endpoint_filters_by_thread_id(mock_side_services):
    import app.graph as g
    import app.main as main_mod

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("mouse_click", "call_1", '{"x": 1, "y": 2}')),
        _sse_response(text_response(["OK", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Clique"}], "stream": False},
        )

        thread_id = main_mod._derive_thread_id([type("M", (), {"role": "user", "content": "Clique"})()])
        matching = await client.get("/audit", params={"thread_id": thread_id})
        other = await client.get("/audit", params={"thread_id": "un-autre-thread"})
        everything = await client.get("/audit")

    assert len(matching.json()["entries"]) == 1
    assert other.json()["entries"] == []
    assert len(everything.json()["entries"]) == 1
