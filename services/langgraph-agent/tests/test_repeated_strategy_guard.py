"""
Garde-fou "stratégie différente" (Itération 2, Phase 1 « cœur cognitif » —
voir docs/briefs/phase-1-coeur-cognitif.md et app/graph.py:_execute_tool_calls).
Une fois qu'une sous-tâche a subi un échec de vérification (attempts > 0),
répéter EXACTEMENT le même tool_call (nom+args) que le tour précédent est
refusé sans appeler mcp-client. VERIFICATION_ENABLED désactivé par défaut :
chaque test l'active explicitement.
"""

import httpx
import pytest
import respx
from langchain_core.messages import AIMessage, HumanMessage

CONFIG = {"configurable": {"thread_id": "test-thread-repeated-strategy"}}


def _subtask(attempts=1, status="en_cours"):
    return {"description": "X", "success_criterion": "Y", "status": status, "attempts": attempts, "result": None}


def _state(previous_args, current_args, attempts=1):
    return {
        "messages": [
            HumanMessage(content="Fais X"),
            AIMessage(content="", tool_calls=[{"id": "prev", "name": "browser_click", "args": previous_args}]),
            {"role": "tool", "tool_call_id": "prev", "content": '{"content": [{"type": "text", "text": "rien"}]}'},
            AIMessage(content="", tool_calls=[{"id": "current", "name": "browser_click", "args": current_args}]),
        ],
        "plan": [_subtask(attempts=attempts)],
        "tool_iterations": 0,
        "session_grants": [],
    }


@pytest.mark.asyncio
async def test_identical_tool_call_after_failure_is_blocked(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    with respx.mock(assert_all_called=False) as mock:
        mcp_route = mock.post("http://fake-mcp-client/call").mock(
            return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ne doit jamais être appelé"}]})
        )
        state = _state({"selector": "#a"}, {"selector": "#a"}, attempts=1)
        result = await g._execute_tool_calls(state, CONFIG, audit=True)

    assert mcp_route.call_count == 0
    tool_message = next(m for m in result["messages"] if m.get("role") == "tool")
    assert "Nouvelle tentative refusée" in tool_message["content"]


@pytest.mark.asyncio
async def test_different_args_after_failure_is_allowed(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    with respx.mock(assert_all_called=False) as mock:
        mcp_route = mock.post("http://fake-mcp-client/call").mock(
            return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
        )
        state = _state({"selector": "#a"}, {"selector": "#b"}, attempts=1)
        result = await g._execute_tool_calls(state, CONFIG, audit=True)

    assert mcp_route.call_count == 1
    tool_message = next(m for m in result["messages"] if m.get("role") == "tool")
    assert "Nouvelle tentative refusée" not in tool_message["content"]


@pytest.mark.asyncio
async def test_identical_tool_call_without_prior_failure_is_allowed(monkeypatch):
    """attempts == 0 (pas encore d'échec constaté) : le garde-fou ne s'applique pas."""
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    with respx.mock(assert_all_called=False) as mock:
        mcp_route = mock.post("http://fake-mcp-client/call").mock(
            return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
        )
        state = _state({"selector": "#a"}, {"selector": "#a"}, attempts=0)
        result = await g._execute_tool_calls(state, CONFIG, audit=True)

    assert mcp_route.call_count == 1
    tool_message = next(m for m in result["messages"] if m.get("role") == "tool")
    assert "Nouvelle tentative refusée" not in tool_message["content"]


@pytest.mark.asyncio
async def test_identical_tool_call_after_failure_allowed_when_verification_disabled(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", False)
    with respx.mock(assert_all_called=False) as mock:
        mcp_route = mock.post("http://fake-mcp-client/call").mock(
            return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
        )
        state = _state({"selector": "#a"}, {"selector": "#a"}, attempts=1)
        result = await g._execute_tool_calls(state, CONFIG, audit=True)

    assert mcp_route.call_count == 1
    tool_message = next(m for m in result["messages"] if m.get("role") == "tool")
    assert "Nouvelle tentative refusée" not in tool_message["content"]
