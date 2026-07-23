"""
Nœud planificateur (Itération 1, Phase 1 « cœur cognitif » — voir
docs/briefs/phase-1-coeur-cognitif.md et app/graph.py:plan_task) : parsing/
validation JSON pure, comportement du nœud (LLM mocké via respx), et
intégration au niveau du graphe (une seule planification par tâche, jamais
recalculée au fil de la boucle d'outils). PLANNER_ENABLED est désactivé par
défaut (voir app/graph.py) : chaque test qui exerce le mécanisme active le
flag explicitement via monkeypatch, même patron que les tests
ADAPTIVE_THINKING existants (tests/test_image_retention_and_thinking.py).
"""

import json

import httpx
import pytest
import respx
from langchain_core.messages import AIMessage, HumanMessage

from tests.fixtures.llm_sse import non_streaming_response, text_response, tool_call_response

# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _validate_plan_json (pure, pas de docker/LLM)
# ─────────────────────────────────────────────────────────────────────────


def test_validate_plan_json_accepts_well_formed_plan():
    import app.graph as g

    raw = json.dumps(
        {
            "sous_taches": [
                {"description": "Ouvrir le catalogue", "critere_succes": "page catalogue affichée"},
                {"description": "Trouver le prix", "critere_succes": "prix visible"},
            ]
        }
    )
    result = g._validate_plan_json(raw)
    assert result == [
        {"description": "Ouvrir le catalogue", "success_criterion": "page catalogue affichée"},
        {"description": "Trouver le prix", "success_criterion": "prix visible"},
    ]


def test_validate_plan_json_strips_think_block_and_code_fence():
    import app.graph as g

    raw = (
        "<think>je réfléchis</think>```json\n"
        '{"sous_taches": [{"description": "A", "critere_succes": "B"}]}\n```'
    )
    result = g._validate_plan_json(raw)
    assert result == [{"description": "A", "success_criterion": "B"}]


def test_validate_plan_json_rejects_invalid_json():
    import app.graph as g

    with pytest.raises(g.PlanValidationError, match="JSON invalide"):
        g._validate_plan_json("pas du json")


def test_validate_plan_json_rejects_missing_key():
    import app.graph as g

    with pytest.raises(g.PlanValidationError, match="sous_taches"):
        g._validate_plan_json(json.dumps({"autre_chose": []}))


def test_validate_plan_json_rejects_too_many_subtasks():
    import app.graph as g

    subtasks = [{"description": f"étape {i}", "critere_succes": "ok"} for i in range(9)]
    with pytest.raises(g.PlanValidationError, match="hors bornes"):
        g._validate_plan_json(json.dumps({"sous_taches": subtasks}))


def test_validate_plan_json_rejects_empty_subtask_list():
    import app.graph as g

    with pytest.raises(g.PlanValidationError, match="hors bornes"):
        g._validate_plan_json(json.dumps({"sous_taches": []}))


def test_validate_plan_json_rejects_blank_description():
    import app.graph as g

    with pytest.raises(g.PlanValidationError, match="description"):
        g._validate_plan_json(json.dumps({"sous_taches": [{"description": "  ", "critere_succes": "B"}]}))


def test_validate_plan_json_rejects_missing_success_criterion():
    import app.graph as g

    with pytest.raises(g.PlanValidationError, match="critere_succes"):
        g._validate_plan_json(json.dumps({"sous_taches": [{"description": "A"}]}))


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : plan_task (LLM mocké via respx, appel direct de la fonction)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_task_is_noop_when_planner_disabled(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLANNER_ENABLED", False)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://fake-vllm/v1/chat/completions")
        state = {"messages": [HumanMessage(content="Fais X")]}
        result = await g.plan_task(state)

    assert result == {"messages": []}
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_plan_task_is_noop_when_plan_already_present(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLANNER_ENABLED", True)
    existing_plan = [{"description": "déjà là", "success_criterion": "x", "status": "en_cours"}]
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://fake-vllm/v1/chat/completions")
        state = {"messages": [HumanMessage(content="Fais X")], "plan": existing_plan}
        result = await g.plan_task(state)

    assert result == {"messages": []}
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_plan_task_builds_plan_from_valid_llm_response(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLANNER_ENABLED", True)
    plan_json = json.dumps(
        {
            "sous_taches": [
                {"description": "Ouvrir le catalogue", "critere_succes": "page affichée"},
                {"description": "Lire le prix", "critere_succes": "prix trouvé"},
            ]
        }
    )
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=non_streaming_response(plan_json))
        )
        state = {"messages": [HumanMessage(content="Trouve le prix du produit")]}
        result = await g.plan_task(state)

    plan = result["plan"]
    assert len(plan) == 2
    assert plan[0]["status"] == "en_cours"
    assert plan[1]["status"] == "a_faire"
    assert all(st["attempts"] == 0 and st["result"] is None for st in plan)
    assert plan[0]["description"] == "Ouvrir le catalogue"
    assert plan[0]["success_criterion"] == "page affichée"


@pytest.mark.asyncio
async def test_plan_task_falls_back_to_single_subtask_on_invalid_response(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLANNER_ENABLED", True)
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=non_streaming_response("réponse pas du tout en JSON"))
        )
        state = {"messages": [HumanMessage(content="Trouve le prix du produit")]}
        result = await g.plan_task(state)

    plan = result["plan"]
    assert len(plan) == 1
    assert plan[0]["status"] == "en_cours"
    assert plan[0]["description"] == "Trouve le prix du produit"


@pytest.mark.asyncio
async def test_plan_task_falls_back_when_llm_unreachable(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLANNER_ENABLED", True)
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-vllm/v1/chat/completions").mock(side_effect=httpx.ConnectError("down"))
        state = {"messages": [HumanMessage(content="Trouve le prix du produit")]}
        result = await g.plan_task(state)

    plan = result["plan"]
    assert len(plan) == 1
    assert plan[0]["description"] == "Trouve le prix du produit"


@pytest.mark.asyncio
async def test_plan_task_noop_without_human_message(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "PLANNER_ENABLED", True)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://fake-vllm/v1/chat/completions")
        state = {"messages": [AIMessage(content="rien d'humain ici")]}
        result = await g.plan_task(state)

    assert result == {"messages": []}
    assert route.call_count == 0


# ─────────────────────────────────────────────────────────────────────────
# Intégration graphe : une seule planification par tâche
# ─────────────────────────────────────────────────────────────────────────

CONFIG = {"configurable": {"thread_id": "test-thread-plan-task"}}


@pytest.mark.asyncio
async def test_plan_task_runs_once_per_task_not_per_tool_loop_iteration(monkeypatch):
    """
    Boucle d'outils auto-approuvée de 2 itérations (screen_shot x2 -> texte) :
    plan_task ne doit tourner qu'UNE fois, pas à chaque retour sur call_llm
    (voir AgentState.plan : calculé une fois, jamais reconstruit au sein
    d'une même tâche)."""
    import app.graph as g

    monkeypatch.setattr(g, "PLANNER_ENABLED", True)
    plan_json = json.dumps({"sous_taches": [{"description": "Capturer deux fois", "critere_succes": "fait"}]})

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-context-manager/retrieve").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        mock.post("http://fake-skill-manager/match").mock(return_value=httpx.Response(200, json={"skill": None}))
        mock.get("http://fake-mcp-client/tools/schema").mock(return_value=httpx.Response(200, json={"tools": []}))
        mock.post("http://fake-mcp-client/call").mock(
            return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
        )
        route = mock.post("http://fake-vllm/v1/chat/completions")
        route.side_effect = [
            httpx.Response(200, json=non_streaming_response(plan_json)),  # plan_task, 1 seule fois
            httpx.Response(
                200,
                content=tool_call_response("screen_shot", "call_1", "{}"),
                headers={"content-type": "text/event-stream"},
            ),
            httpx.Response(
                200,
                content=tool_call_response("screen_shot", "call_2", "{}"),
                headers={"content-type": "text/event-stream"},
            ),
            httpx.Response(
                200,
                content=text_response(["Fait", "."]),
                headers={"content-type": "text/event-stream"},
            ),
        ]
        g.agent_graph = g.build_graph()

        state = {
            "messages": [{"role": "user", "content": "Capture deux fois"}],
            "tool_iterations": 0,
            "approved": None,
            "plan": [],
        }
        final_state = await g.agent_graph.ainvoke(state, CONFIG)

    # 4 appels au total : 1 planification + 3 tours call_llm (2 tool_calls + 1 texte final).
    assert route.call_count == 4
    assert len(final_state["plan"]) == 1
    assert final_state["plan"][0]["description"] == "Capturer deux fois"
