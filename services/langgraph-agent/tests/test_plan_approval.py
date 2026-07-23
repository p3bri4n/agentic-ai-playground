"""
Approbation humaine du plan (Itération 3, Phase 1 « cœur cognitif » — voir
docs/briefs/phase-1-coeur-cognitif.md et app/graph.py:require_plan_approval/
route_after_plan_approval/reject_plan). Couvre aussi la NON-FUSION avec
l'approbation d'un outil TIER_SENSITIVE à l'exécution, via un scénario
d'intégration graphe complet.
"""

import json

import httpx
import pytest
import respx
from langgraph.errors import NodeInterrupt

from tests.fixtures.llm_sse import non_streaming_response, text_response, tool_call_response

CONFIG = {"configurable": {"thread_id": "test-thread-plan-approval"}}


def _sse(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


# ─────────────────────────────────────────────────────────────────────────
# require_plan_approval / route_after_plan_approval / reject_plan (unitaire)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_plan_approval_raises_when_no_decision_yet():
    import app.graph as g

    with pytest.raises(NodeInterrupt):
        await g.require_plan_approval({"plan_approved": None})


@pytest.mark.asyncio
async def test_require_plan_approval_leaves_decision_readable_without_grant():
    """plan_approved n'est PAS réarmé ici (voir commentaire du nœud) :
    route_after_plan_approval doit encore pouvoir le lire — c'est
    validate_plan qui réarme à None pour le PROCHAIN plan."""
    import app.graph as g

    result = await g.require_plan_approval({"plan_approved": True, "plan_grant_session": False})
    assert result == {"plan_grant_session": False}


@pytest.mark.asyncio
async def test_require_plan_approval_persists_grant_when_requested():
    import app.graph as g

    result = await g.require_plan_approval({"plan_approved": True, "plan_grant_session": True})
    assert result == {"plan_grant_session": False, "plan_grant": True}


def test_route_after_plan_approval_call_llm_when_approved():
    import app.graph as g

    assert g.route_after_plan_approval({"plan_approved": True}) == "call_llm"


def test_route_after_plan_approval_reject_plan_when_refused():
    import app.graph as g

    assert g.route_after_plan_approval({"plan_approved": False}) == "reject_plan"


@pytest.mark.asyncio
async def test_reject_plan_produces_final_message():
    import app.graph as g

    result = await g.reject_plan({})
    assert "refusé" in result["messages"][0]["content"]


# ─────────────────────────────────────────────────────────────────────────
# Intégration graphe : non-fusion plan/outil pour un plan TIER_SENSITIVE
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_side_services():
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-context-manager/retrieve").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        mock.post("http://fake-skill-manager/match").mock(return_value=httpx.Response(200, json={"skill": None}))
        mock.get("http://fake-mcp-client/tools/schema").mock(
            return_value=httpx.Response(
                200, json={"tools": [{"type": "function", "function": {"name": "browser_navigate"}}]}
            )
        )
        mock.post("http://fake-mcp-client/call").mock(
            return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
        )
        yield mock


@pytest.mark.asyncio
async def test_plan_approval_does_not_substitute_for_tool_approval(mock_side_services, monkeypatch):
    """
    Plan TIER_SENSITIVE (déclare browser_navigate) approuvé une fois au
    niveau du plan : le tool_call browser_navigate lui-même, à l'exécution,
    redemande STILL sa propre approbation (require_approval, inchangé) —
    les deux ne sont jamais fusionnables (voir brief, point 3).
    """
    import app.graph as g

    monkeypatch.setattr(g, "PLANNER_ENABLED", True)
    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    monkeypatch.setattr(g, "PLAN_JUDGE_ENABLED", False)

    plan_json = json.dumps(
        {
            "sous_taches": [
                {"description": "Ouvrir le catalogue", "critere_succes": "page affichée", "outils": ["browser_navigate"]},
                {"description": "Lire le prix", "critere_succes": "prix trouvé", "outils": []},
            ]
        }
    )
    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        httpx.Response(200, json=non_streaming_response(plan_json)),  # plan_task
        _sse(tool_call_response("browser_navigate", "call_1", '{"url": "http://fixture-catalog/catalog/index.html"}')),  # call_llm
        _sse(text_response(["Fait", "."])),  # call_llm après exécution
    ]
    g.agent_graph = g.build_graph()

    state = {
        "messages": [{"role": "user", "content": "Sur http://fixture-catalog/catalog/index.html, trouve le prix."}],
        "tool_iterations": 0,
        "approved": None,
    }
    await g.agent_graph.ainvoke(state, CONFIG)

    # 1ère pause : approbation du PLAN (tier sensible, browser_navigate déclaré).
    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert "require_plan_approval" in snapshot.next
    await g.agent_graph.aupdate_state(CONFIG, {"plan_approved": True})

    result = await g.agent_graph.ainvoke(None, CONFIG)
    # Le plan est approuvé, mais le tool_call browser_navigate lui-même
    # (TIER_SENSITIVE) redemande sa PROPRE approbation — pas de passage direct.
    assert result.get("approved") is None

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert "require_approval" in snapshot.next
    assert mock_side_services.calls.last  # au moins un appel a eu lieu (pas d'exécution mcp-client encore)

    await g.agent_graph.aupdate_state(CONFIG, {"approved": True})
    final_state = await g.agent_graph.ainvoke(None, CONFIG)

    assert route.call_count == 3
    assert final_state["messages"][-1].content == "Fait."


# ─────────────────────────────────────────────────────────────────────────
# POST /approve : bug réel trouvé en conditions réelles (campagne live,
# Itération 3) — ce endpoint mettait inconditionnellement à jour
# "approved"/"grant_session" sans distinguer une pause require_plan_approval,
# laissant plan_approved indéfiniment None (jamais renseigné) et la tâche
# bloquée en boucle sur require_plan_approval malgré un /approve "réussi".
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_endpoint_resumes_plan_approval_pause(mock_side_services, monkeypatch):
    import app.graph as g
    import app.main as main_mod

    monkeypatch.setattr(g, "PLANNER_ENABLED", True)
    monkeypatch.setattr(g, "PLAN_VALIDATION_ENABLED", True)
    monkeypatch.setattr(g, "PLAN_JUDGE_ENABLED", False)

    plan_json = json.dumps(
        {
            "sous_taches": [
                {"description": "Ouvrir le catalogue", "critere_succes": "page affichée", "outils": ["browser_navigate"]},
                {"description": "Lire le prix", "critere_succes": "prix trouvé", "outils": []},
            ]
        }
    )
    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        httpx.Response(200, json=non_streaming_response(plan_json)),
        _sse(tool_call_response("mouse_click", "call_1", "{}")),  # tier reversible : auto-approuvé après le plan
        _sse(text_response(["Fait", "."])),
    ]
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        prompt = "Sur http://fixture-catalog/catalog/index.html, trouve le prix."
        first = await client.post(
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": prompt}], "stream": False},
        )
        approval_text = first.json()["choices"][0]["message"]["content"]
        assert "Approbation du plan requise" in approval_text

        approved = await client.post(
            "/approve",
            json={
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": approval_text},
                ],
                "approved": True,
            },
        )

    assert approved.status_code == 200
    # Avant le correctif : la pause require_plan_approval n'était jamais
    # levée, /approve renvoyait le MÊME texte "Approbation du plan requise"
    # en boucle. Après : la tâche progresse jusqu'à sa réponse finale.
    assert approved.json()["content"] == "Fait."
