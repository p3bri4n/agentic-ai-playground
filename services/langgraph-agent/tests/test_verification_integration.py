"""
Intégration graphe complet (Itération 2, Phase 1 « cœur cognitif » —
PLANNER_ENABLED + VERIFICATION_ENABLED activés ensemble ; révisé Itération 4
— correctif latence 1/2, voir HISTORY.md : verify_action ne fait plus
d'appel LLM séparé, le constat [CONSTAT: ATTEINT|ECHEC] vit dans la même
réponse que la décision de la suite) : un scénario retry-puis-succès et un
scénario budget+replan épuisés aboutissant à report_failure/END. Bornés à
ces deux cas plutôt qu'une matrice complète, pour garder la suite lisible
(voir docs/briefs/phase-1-coeur-cognitif.md).
"""

import json

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import content_and_tool_call_response, non_streaming_response, text_response, tool_call_response

CONFIG_A = {"configurable": {"thread_id": "test-thread-verif-retry-success"}}
CONFIG_B = {"configurable": {"thread_id": "test-thread-verif-give-up"}}


def _sse(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


@pytest.fixture
def mock_side_services():
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-context-manager/retrieve").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        mock.post("http://fake-skill-manager/match").mock(return_value=httpx.Response(200, json={"skill": None}))
        mock.get("http://fake-mcp-client/tools/schema").mock(return_value=httpx.Response(200, json={"tools": []}))
        mock.post("http://fake-mcp-client/call").mock(
            return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
        )
        yield mock


@pytest.mark.asyncio
async def test_retry_then_success_reaches_fait_and_final_answer(mock_side_services, monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLANNER_ENABLED", True)
    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)

    plan_json = json.dumps({"sous_taches": [{"description": "Cliquer sur le bouton", "critere_succes": "bouton cliqué"}]})
    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        httpx.Response(200, json=non_streaming_response(plan_json)),  # plan_task
        _sse(tool_call_response("mouse_click", "call_1", '{"x": 1, "y": 1}')),  # call_llm #1 : rien à constater encore
        _sse(content_and_tool_call_response("[CONSTAT: ECHEC] pas encore.", "mouse_click", "call_2", '{"x": 2, "y": 2}')),  # call_llm #2 : constate + retry (stratégie différente)
        _sse(text_response(["[CONSTAT: ATTEINT] ", "Fait", "."])),  # call_llm #3 : constate + réponse finale
    ]
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique sur le bouton"}], "tool_iterations": 0, "approved": None}
    final_state = await g.agent_graph.ainvoke(state, CONFIG_A)

    assert route.call_count == 4
    plan = final_state["plan"]
    assert len(plan) == 1
    assert plan[0]["status"] == "fait"
    assert plan[0]["attempts"] == 1
    last_message = final_state["messages"][-1]
    assert "Fait." in last_message.content


@pytest.mark.asyncio
async def test_budget_and_replan_exhausted_reaches_report_failure(mock_side_services, monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLANNER_ENABLED", True)
    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    monkeypatch.setattr(g, "SUBTASK_ATTEMPT_BUDGET", 1)
    monkeypatch.setattr(g, "REPLAN_BUDGET", 1)

    plan_json = json.dumps({"sous_taches": [{"description": "Trouver le prix caché", "critere_succes": "prix trouvé"}]})
    replan_json = json.dumps({"sous_taches": [{"description": "Autre approche", "critere_succes": "prix trouvé autrement"}]})
    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        httpx.Response(200, json=non_streaming_response(plan_json)),  # plan_task
        _sse(tool_call_response("mouse_click", "call_1", '{"x": 1, "y": 1}')),  # call_llm #1 : rien à constater encore
        _sse(text_response(["[CONSTAT: ECHEC] ", "echec1"])),  # call_llm #2 : constate action1 -> echoue (budget=1)
        httpx.Response(200, json=non_streaming_response(replan_json)),  # replan_task
        _sse(tool_call_response("mouse_click", "call_2", '{"x": 9, "y": 9}')),  # call_llm #3 : rien à constater (juste replanifié)
        _sse(text_response(["[CONSTAT: ECHEC] ", "echec2"])),  # call_llm #4 : constate action2 -> echoue, replan_budget épuisé
    ]
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Trouve le prix caché"}], "tool_iterations": 0, "approved": None}
    final_state = await g.agent_graph.ainvoke(state, CONFIG_B)

    assert route.call_count == 6
    plan = final_state["plan"]
    assert plan[0]["description"] == "Autre approche"
    assert plan[0]["status"] == "echoue"
    assert final_state["replan_count"] == 1
    last_message = final_state["messages"][-1]
    assert "pas pu terminer" in last_message["content"] if isinstance(last_message, dict) else last_message.content
