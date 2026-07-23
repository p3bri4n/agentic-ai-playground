"""
Juge LLM du plan (Itération 3, Phase 1 « cœur cognitif » — voir
docs/briefs/phase-1-coeur-cognitif.md et app/graph.py:_judge_plan/
_validate_judge_json). PLAN_JUDGE_ENABLED désactivé par défaut — testé ici
indépendamment du flag (appel direct de _judge_plan) puisque le flag est
vérifié par le nœud appelant (validate_plan, voir test_validate_plan_node.py).
"""

import json

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import non_streaming_response


def _plan():
    return [{"description": "Ouvrir le catalogue", "success_criterion": "page affichée", "tools": ["browser_navigate"]}]


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _validate_judge_json (pure)
# ─────────────────────────────────────────────────────────────────────────


def test_validate_judge_json_accepts_feasible_verdict():
    import app.graph as g

    result = g._validate_judge_json(json.dumps({"faisable": True}))
    assert result == {"faisable": True, "risques": [], "etapes_manquantes": []}


def test_validate_judge_json_accepts_full_verdict():
    import app.graph as g

    result = g._validate_judge_json(
        json.dumps({"faisable": False, "risques": ["risque A"], "etapes_manquantes": ["étape manquante"]})
    )
    assert result == {"faisable": False, "risques": ["risque A"], "etapes_manquantes": ["étape manquante"]}


def test_validate_judge_json_rejects_invalid_json():
    import app.graph as g

    with pytest.raises(g.PlanJudgeValidationError, match="JSON invalide"):
        g._validate_judge_json("pas du json")


def test_validate_judge_json_rejects_non_bool_faisable():
    import app.graph as g

    with pytest.raises(g.PlanJudgeValidationError, match="faisable"):
        g._validate_judge_json(json.dumps({"faisable": "oui"}))


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _judge_plan (LLM mocké via respx)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_judge_plan_returns_empty_when_feasible():
    import app.graph as g

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=non_streaming_response(json.dumps({"faisable": True})))
        )
        reasons = await g._judge_plan(_plan(), "Trouve le prix du produit")

    assert reasons == []


@pytest.mark.asyncio
async def test_judge_plan_returns_reasons_when_not_feasible():
    import app.graph as g

    verdict = json.dumps(
        {"faisable": False, "risques": ["le site pourrait bloquer"], "etapes_manquantes": ["se connecter"]}
    )
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=non_streaming_response(verdict))
        )
        reasons = await g._judge_plan(_plan(), "Trouve le prix du produit")

    assert any("le site pourrait bloquer" in r for r in reasons)
    assert any("se connecter" in r for r in reasons)


@pytest.mark.asyncio
async def test_judge_plan_includes_page_snapshot_in_payload_when_provided():
    """Correctif d'ancrage (Itération 4, voir HISTORY.md) : le juge reçoit
    l'état réel de la page s'il est fourni, pour ne pas exiger une
    fonctionnalité absente (ex. barre de recherche inexistante)."""
    import app.graph as g

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=non_streaming_response(json.dumps({"faisable": True})))
        )
        await g._judge_plan(_plan(), "Trouve le prix du produit", page_snapshot="aucun champ de recherche visible")

    sent = json.loads(route.calls.last.request.content)
    verifier_message = json.loads(sent["messages"][-1]["content"])
    assert verifier_message["etat_actuel_de_la_page"] == "aucun champ de recherche visible"


@pytest.mark.asyncio
async def test_judge_plan_page_snapshot_absent_by_default():
    import app.graph as g

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=non_streaming_response(json.dumps({"faisable": True})))
        )
        await g._judge_plan(_plan(), "Trouve le prix du produit")

    sent = json.loads(route.calls.last.request.content)
    verifier_message = json.loads(sent["messages"][-1]["content"])
    assert verifier_message["etat_actuel_de_la_page"] is None


@pytest.mark.asyncio
async def test_judge_plan_fails_open_on_llm_error():
    """Juge indisponible : AUCUN motif renvoyé (pas de veto par défaut) —
    ne doit jamais bloquer une tâche par ailleurs valide selon les
    heuristiques (voir docstring de _judge_plan)."""
    import app.graph as g

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(side_effect=httpx.ConnectError("down"))
        reasons = await g._judge_plan(_plan(), "Trouve le prix du produit")

    assert reasons == []


@pytest.mark.asyncio
async def test_judge_plan_fails_open_on_invalid_json():
    import app.graph as g

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=non_streaming_response("pas du json"))
        )
        reasons = await g._judge_plan(_plan(), "Trouve le prix du produit")

    assert reasons == []
