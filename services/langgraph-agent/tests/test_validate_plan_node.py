"""
Nœud validate_plan et son routage (Itération 3, Phase 1 « cœur cognitif » —
voir docs/briefs/phase-1-coeur-cognitif.md et app/graph.py:validate_plan/
route_after_validation/_plan_tier/revise_plan). PLAN_VALIDATION_ENABLED
désactivé par défaut : chaque test qui exerce le mécanisme l'active
explicitement.
"""

import json

import httpx
import pytest
import respx
from langchain_core.messages import HumanMessage

from tests.fixtures.llm_sse import non_streaming_response


def _subtask(description="A", success_criterion="critère A", tools=None):
    return {
        "description": description,
        "success_criterion": success_criterion,
        "tools": tools or [],
        "status": "a_faire",
        "attempts": 0,
        "result": None,
    }


def _valid_plan():
    return [
        _subtask("Ouvrir le catalogue", "page affichée", tools=["browser_navigate"]),
        _subtask("Trouver le prix", "prix trouvé", tools=["browser_extract"]),
    ]


# ─────────────────────────────────────────────────────────────────────────
# _plan_tier (pure)
# ─────────────────────────────────────────────────────────────────────────


def test_plan_tier_read_when_no_tools_declared():
    import app.graph as g

    assert g._plan_tier([_subtask(tools=[])]) == g.approval_policy.TIER_READ


def test_plan_tier_read_for_read_tools():
    import app.graph as g

    assert g._plan_tier([_subtask(tools=["browser_extract"])]) == g.approval_policy.TIER_READ


def test_plan_tier_reversible_when_worst_tool_is_reversible():
    import app.graph as g

    plan = [_subtask(tools=["browser_extract"]), _subtask(tools=["mouse_click"])]
    assert g._plan_tier(plan) == g.approval_policy.TIER_REVERSIBLE


def test_plan_tier_sensitive_when_worst_tool_is_sensitive():
    import app.graph as g

    plan = [_subtask(tools=["mouse_click"]), _subtask(tools=["browser_navigate"])]
    assert g._plan_tier(plan) == g.approval_policy.TIER_SENSITIVE


def test_plan_tier_sensitive_for_unknown_tool():
    import app.graph as g

    assert g._plan_tier([_subtask(tools=["outil_jamais_vu"])]) == g.approval_policy.TIER_SENSITIVE


# ─────────────────────────────────────────────────────────────────────────
# route_after_validation (pure)
# ─────────────────────────────────────────────────────────────────────────


def test_route_after_validation_call_llm_when_disabled(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", False)
    state = {"plan": [_subtask(tools=["mouse_click"])], "plan_validation_reasons": ["motif"]}
    assert g.route_after_validation(state) == "call_llm"


def test_route_after_validation_revise_when_rejected_under_cycle_budget(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    monkeypatch.setattr(g, "PLAN_VALIDATION_CYCLES_MAX", 2)
    state = {"plan": _valid_plan(), "plan_validation_reasons": ["motif"], "plan_validation_cycles": 1}
    assert g.route_after_validation(state) == "revise_plan"


def test_route_after_validation_escalates_when_cycle_budget_exhausted(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    monkeypatch.setattr(g, "PLAN_VALIDATION_CYCLES_MAX", 2)
    state = {"plan": _valid_plan(), "plan_validation_reasons": ["motif"], "plan_validation_cycles": 3}
    assert g.route_after_validation(state) == "require_plan_approval"


def test_route_after_validation_call_llm_when_accepted_and_read_tier(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    state = {"plan": [_subtask(tools=["browser_extract"])], "plan_validation_reasons": []}
    assert g.route_after_validation(state) == "call_llm"


def test_route_after_validation_requires_approval_for_reversible_tier_without_grant(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    state = {"plan": [_subtask(tools=["mouse_click"])], "plan_validation_reasons": [], "plan_grant": False}
    assert g.route_after_validation(state) == "require_plan_approval"


def test_route_after_validation_call_llm_for_reversible_tier_with_grant(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    state = {"plan": [_subtask(tools=["mouse_click"])], "plan_validation_reasons": [], "plan_grant": True}
    assert g.route_after_validation(state) == "call_llm"


def test_route_after_validation_requires_approval_for_sensitive_tier_even_with_grant(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    state = {"plan": [_subtask(tools=["browser_navigate"])], "plan_validation_reasons": [], "plan_grant": True}
    assert g.route_after_validation(state) == "require_plan_approval"


# ─────────────────────────────────────────────────────────────────────────
# validate_plan (heuristiques + juge, LLM mocké via respx)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_plan_noop_when_disabled(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", False)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://fake-vllm/v1/chat/completions")
        result = await g.validate_plan({"plan": _valid_plan(), "messages": [HumanMessage(content="x")]})

    assert result == {"messages": []}
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_validate_plan_accepts_valid_plan_without_judge(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    monkeypatch.setattr(g, "PLAN_JUDGE_ENABLED", False)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-mcp-client/tools/schema").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tools": [
                        {"type": "function", "function": {"name": "browser_navigate"}},
                        {"type": "function", "function": {"name": "browser_extract"}},
                    ]
                },
            )
        )
        judge_route = mock.post("http://fake-vllm/v1/chat/completions")
        state = {
            "plan": _valid_plan(),
            "messages": [HumanMessage(content="Sur http://fixture-catalog/catalog/index.html, trouve le prix.")],
            "plan_validation_cycles": 0,
        }
        result = await g.validate_plan(state)

    assert result == {"plan_validation_reasons": [], "plan_approved": None}
    assert judge_route.call_count == 0


@pytest.mark.asyncio
async def test_validate_plan_rejects_on_heuristic_failure_without_calling_judge(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    monkeypatch.setattr(g, "PLAN_JUDGE_ENABLED", True)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-mcp-client/tools/schema").mock(return_value=httpx.Response(200, json={"tools": []}))
        judge_route = mock.post("http://fake-vllm/v1/chat/completions")
        state = {
            "plan": [_subtask(tools=["outil_inconnu"])],  # 1 seule sous-tâche : hors bornes (2-12) aussi
            "messages": [HumanMessage(content="x")],
            "plan_validation_cycles": 0,
        }
        result = await g.validate_plan(state)

    assert result["plan_validation_reasons"]
    assert result["plan_validation_cycles"] == 1
    assert judge_route.call_count == 0  # heuristiques déjà en échec : juge jamais appelé


@pytest.mark.asyncio
async def test_validate_plan_calls_judge_when_heuristics_pass(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    monkeypatch.setattr(g, "PLAN_JUDGE_ENABLED", True)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-mcp-client/tools/schema").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tools": [
                        {"type": "function", "function": {"name": "browser_navigate"}},
                        {"type": "function", "function": {"name": "browser_extract"}},
                    ]
                },
            )
        )
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, json=non_streaming_response(json.dumps({"faisable": False, "risques": ["manque une étape"]}))
            )
        )
        state = {
            "plan": _valid_plan(),
            "messages": [HumanMessage(content="Sur http://fixture-catalog/catalog/index.html, trouve le prix.")],
            "plan_validation_cycles": 0,
        }
        result = await g.validate_plan(state)

    assert any("manque une étape" in r for r in result["plan_validation_reasons"])
    assert result["plan_validation_cycles"] == 1


# ─────────────────────────────────────────────────────────────────────────
# revise_plan
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revise_plan_regenerates_from_rejection_reasons(monkeypatch):
    import app.graph as g

    new_plan_json = json.dumps(
        {"sous_taches": [{"description": "Nouvelle décomposition", "critere_succes": "ok", "outils": []}]}
    )
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-mcp-client/tools/schema").mock(return_value=httpx.Response(200, json={"tools": []}))
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=non_streaming_response(new_plan_json))
        )
        state = {
            "messages": [HumanMessage(content="Trouve le prix")],
            "plan_validation_reasons": ["nombre de sous-tâches hors bornes (1, attendu 2-12)"],
        }
        result = await g.revise_plan(state)

    plan = result["plan"]
    assert len(plan) == 1
    assert plan[0]["description"] == "Nouvelle décomposition"
    assert plan[0]["status"] == "en_cours"


@pytest.mark.asyncio
async def test_revise_plan_falls_back_on_llm_error():
    import app.graph as g

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(side_effect=httpx.ConnectError("down"))
        state = {
            "messages": [HumanMessage(content="Trouve le prix")],
            "plan_validation_reasons": ["motif"],
        }
        result = await g.revise_plan(state)

    plan = result["plan"]
    assert len(plan) == 1
    assert plan[0]["description"] == "Trouve le prix"
