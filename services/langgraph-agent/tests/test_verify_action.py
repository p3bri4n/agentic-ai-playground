"""
Vérification post-action (Itération 2, Phase 1 « cœur cognitif » — voir
docs/briefs/phase-1-coeur-cognitif.md et app/graph.py:verify_action).
VERIFICATION_ENABLED est désactivé par défaut : chaque test qui exerce le
mécanisme l'active explicitement via monkeypatch, même patron que
PLANNER_ENABLED (tests/test_plan_task.py).
"""

import json

import httpx
import pytest
import respx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tests.fixtures.llm_sse import non_streaming_response


def _subtask(description="Ouvrir le catalogue", success_criterion="page affichée", status="en_cours", attempts=0):
    return {
        "description": description,
        "success_criterion": success_criterion,
        "status": status,
        "attempts": attempts,
        "result": None,
    }


def _turn_messages(tool_call_id="call_1", tool_name="browser_navigate", args=None, result_text="page ouverte"):
    return [
        HumanMessage(content="Ouvre le catalogue"),
        AIMessage(content="", tool_calls=[{"id": tool_call_id, "name": tool_name, "args": args or {}}]),
        ToolMessage(content=json.dumps({"content": [{"type": "text", "text": result_text}]}), tool_call_id=tool_call_id),
    ]


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _validate_verification_json (pure)
# ─────────────────────────────────────────────────────────────────────────


def test_validate_verification_json_accepts_positive_verdict():
    import app.graph as g

    result = g._validate_verification_json(json.dumps({"atteint": True, "raison": "page trouvée"}))
    assert result == {"atteint": True, "raison": "page trouvée"}


def test_validate_verification_json_accepts_negative_verdict_without_raison():
    import app.graph as g

    result = g._validate_verification_json(json.dumps({"atteint": False}))
    assert result == {"atteint": False, "raison": ""}


def test_validate_verification_json_rejects_invalid_json():
    import app.graph as g

    with pytest.raises(g.VerificationValidationError, match="JSON invalide"):
        g._validate_verification_json("pas du json")


def test_validate_verification_json_rejects_non_bool_atteint():
    import app.graph as g

    with pytest.raises(g.VerificationValidationError, match="atteint"):
        g._validate_verification_json(json.dumps({"atteint": "true"}))


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _previous_turn_tool_results
# ─────────────────────────────────────────────────────────────────────────


def test_previous_turn_tool_results_collects_trailing_tool_messages():
    import app.graph as g

    messages = _turn_messages(result_text="resultat A") + [ToolMessage(content="resultat B", tool_call_id="call_2")]
    results = g._previous_turn_tool_results(messages)
    assert len(results) == 2
    assert "resultat A" in results[0]
    assert results[1] == "resultat B"


def test_previous_turn_tool_results_ignores_trailing_image_message():
    import app.graph as g

    messages = _turn_messages(result_text="resultat A") + [
        HumanMessage(content=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}}])
    ]
    results = g._previous_turn_tool_results(messages)
    assert len(results) == 1
    assert "resultat A" in results[0]


def test_previous_turn_tool_results_empty_without_prior_tool_calls():
    import app.graph as g

    assert g._previous_turn_tool_results([HumanMessage(content="salut")]) == []


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : verify_action (LLM mocké via respx)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_action_noop_when_disabled(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", False)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://fake-vllm/v1/chat/completions")
        state = {"messages": _turn_messages(), "plan": [_subtask()]}
        result = await g.verify_action(state)

    assert result == {"messages": []}
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_verify_action_noop_without_active_subtask(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://fake-vllm/v1/chat/completions")
        state = {"messages": _turn_messages(), "plan": []}
        result = await g.verify_action(state)

    assert result == {"messages": []}
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_verify_action_noop_without_tool_results(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://fake-vllm/v1/chat/completions")
        state = {"messages": [HumanMessage(content="salut")], "plan": [_subtask()]}
        result = await g.verify_action(state)

    assert result == {"messages": []}
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_verify_action_positive_verdict_advances_plan(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    plan = [_subtask(status="en_cours"), _subtask(description="Lire le prix", status="a_faire")]
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, json=non_streaming_response(json.dumps({"atteint": True, "raison": "page bien ouverte"}))
            )
        )
        state = {"messages": _turn_messages(), "plan": plan}
        result = await g.verify_action(state)

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "fait"
    assert new_plan[0]["result"] == "page bien ouverte"
    assert new_plan[1]["status"] == "en_cours"


@pytest.mark.asyncio
async def test_verify_action_negative_verdict_under_budget_stays_en_cours(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    monkeypatch.setattr(g, "SUBTASK_ATTEMPT_BUDGET", 3)
    plan = [_subtask(status="en_cours", attempts=0)]
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, json=non_streaming_response(json.dumps({"atteint": False, "raison": "page vide"}))
            )
        )
        state = {"messages": _turn_messages(), "plan": plan}
        result = await g.verify_action(state)

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "en_cours"
    assert new_plan[0]["attempts"] == 1


@pytest.mark.asyncio
async def test_verify_action_negative_verdict_exhausts_budget(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    monkeypatch.setattr(g, "SUBTASK_ATTEMPT_BUDGET", 3)
    plan = [_subtask(status="en_cours", attempts=2)]
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, json=non_streaming_response(json.dumps({"atteint": False, "raison": "toujours rien"}))
            )
        )
        state = {"messages": _turn_messages(), "plan": plan}
        result = await g.verify_action(state)

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "echoue"
    assert new_plan[0]["attempts"] == 3
    assert new_plan[0]["result"] == "toujours rien"


@pytest.mark.asyncio
async def test_verify_action_falls_back_to_non_atteint_on_llm_error(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    plan = [_subtask(status="en_cours", attempts=0)]
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(side_effect=httpx.ConnectError("down"))
        state = {"messages": _turn_messages(), "plan": plan}
        result = await g.verify_action(state)

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "en_cours"
    assert new_plan[0]["attempts"] == 1
