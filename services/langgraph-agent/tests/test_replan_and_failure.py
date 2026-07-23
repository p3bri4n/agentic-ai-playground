"""
Replanification, routage post-vérification et rapport d'échec honnête
(Itération 2, Phase 1 « cœur cognitif » — voir
docs/briefs/phase-1-coeur-cognitif.md et app/graph.py:replan_task/
route_after_verification/report_failure).
"""

import json

import httpx
import pytest
import respx
from langchain_core.messages import HumanMessage

from tests.fixtures.llm_sse import non_streaming_response


def _subtask(description="A", success_criterion="critère A", status="a_faire", attempts=0, result=None):
    return {
        "description": description,
        "success_criterion": success_criterion,
        "status": status,
        "attempts": attempts,
        "result": result,
    }


# ─────────────────────────────────────────────────────────────────────────
# route_after_verification (pure)
# ─────────────────────────────────────────────────────────────────────────


def test_route_after_verification_continue_when_no_failed_subtask():
    import app.graph as g

    state = {"plan": [_subtask(status="fait"), _subtask(status="en_cours")]}
    assert g.route_after_verification(state) == "continue"


def test_route_after_verification_replan_under_budget():
    import app.graph as g

    state = {"plan": [_subtask(status="echoue")], "replan_count": 0}
    assert g.route_after_verification(state) == "replan"


def test_route_after_verification_give_up_when_budget_exhausted(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "REPLAN_BUDGET", 2)
    state = {"plan": [_subtask(status="echoue")], "replan_count": 2}
    assert g.route_after_verification(state) == "give_up"


def test_route_after_verification_continue_with_empty_plan():
    import app.graph as g

    assert g.route_after_verification({"plan": []}) == "continue"


# ─────────────────────────────────────────────────────────────────────────
# replan_task
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replan_task_rebuilds_plan_preserving_done_subtasks(monkeypatch):
    import app.graph as g

    new_plan_json = json.dumps(
        {"sous_taches": [{"description": "Nouvelle approche", "critere_succes": "trouvé autrement"}]}
    )
    plan = [
        _subtask(description="Déjà fait", status="fait", result="ok"),
        _subtask(description="Échouée", status="echoue", attempts=3, result="rien trouvé"),
    ]
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-mcp-client/tools/schema").mock(return_value=httpx.Response(200, json={"tools": []}))
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=non_streaming_response(new_plan_json))
        )
        state = {
            "messages": [HumanMessage(content="Trouve le produit")],
            "plan": plan,
            "replan_count": 0,
        }
        result = await g.replan_task(state)

    new_plan = result["plan"]
    assert result["replan_count"] == 1
    assert new_plan[0]["description"] == "Déjà fait"
    assert new_plan[0]["status"] == "fait"
    assert new_plan[1]["description"] == "Nouvelle approche"
    assert new_plan[1]["status"] == "en_cours"
    assert new_plan[1]["attempts"] == 0


@pytest.mark.asyncio
async def test_replan_task_falls_back_to_retry_on_llm_error(monkeypatch):
    import app.graph as g

    plan = [_subtask(description="Échouée", status="echoue", attempts=3, result="rien trouvé")]
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(side_effect=httpx.ConnectError("down"))
        state = {
            "messages": [HumanMessage(content="Trouve le produit")],
            "plan": plan,
            "replan_count": 0,
        }
        result = await g.replan_task(state)

    new_plan = result["plan"]
    assert result["replan_count"] == 1
    assert new_plan[0]["status"] == "en_cours"
    assert new_plan[0]["attempts"] == 0


@pytest.mark.asyncio
async def test_replan_task_noop_without_failed_subtask():
    import app.graph as g

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://fake-vllm/v1/chat/completions")
        state = {
            "messages": [HumanMessage(content="Trouve le produit")],
            "plan": [_subtask(status="fait")],
            "replan_count": 0,
        }
        result = await g.replan_task(state)

    assert result == {"replan_count": 1}
    assert route.call_count == 0


# ─────────────────────────────────────────────────────────────────────────
# report_failure
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_failure_summarizes_plan_state():
    import app.graph as g

    plan = [
        _subtask(description="Ouvrir le catalogue", status="fait", result="ok"),
        _subtask(description="Trouver le produit", status="echoue", result="introuvable"),
    ]
    result = await g.report_failure({"plan": plan})

    text = result["messages"][0]["content"]
    assert "pas pu terminer" in text
    assert "[fait] Ouvrir le catalogue — ok" in text
    assert "[échoué] Trouver le produit — introuvable" in text
