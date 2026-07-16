"""
Tests des grants de session (Phase 3) : "approuver pour la session" ajoute
un outil à AgentState.session_grants (voir require_approval, app/graph.py),
qui le plafonne à TIER_REVERSIBLE (auto + audit) pour le reste du thread —
sans jamais l'exempter rétroactivement du tour qui l'a demandé. Les grants
vivent dans le checkpointer (MemorySaver, en mémoire) : un redémarrage du
service les perd, comme le reste de l'état du thread (comportement voulu,
voir README).
"""

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import text_response, tool_call_response


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


CONFIG = {"configurable": {"thread_id": "test-thread-grants"}}


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
async def test_first_call_of_sensitive_tool_still_requires_approval_even_with_grant_intent(mock_side_services):
    """
    Le grant ne s'applique jamais rétroactivement au tour qui le demande :
    même si l'humain va répondre "approuver pour la session", le tout premier
    appel de key_type doit passer par require_approval (il n'y a encore
    aucun grant au moment où has_tool_calls route ce tour).
    """
    import app.graph as g

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(tool_call_response("key_type", "call_1", '{"text": "Ceci est un texte assez long pour rester sensible par defaut"}'))
    )
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Tape hello"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ("require_approval",)
    assert mcp_route.call_count == 0


@pytest.mark.asyncio
async def test_grant_session_auto_approves_subsequent_calls_of_same_tool(mock_side_services):
    """
    Premier appel interrompu -> "approuver pour la session" -> deuxième appel
    du même outil (key_type, TIER_SENSITIVE par défaut) passe sans nouvelle
    pause d'approbation.
    """
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("key_type", "call_1", '{"text": "Ceci est un texte assez long pour rester sensible par defaut"}')),
        _sse_response(tool_call_response("key_type", "call_2", '{"text": "Un second texte tout aussi long pour verifier le comportement"}')),
        _sse_response(text_response(["Fini", "."])),
    ]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Tape hello puis world"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ("require_approval",)

    # "approuver pour la session" : approved=True + grant_session=True (voir
    # ApprovalDecisionRequest/_parse_approval_reply, app/main.py, pour le
    # parsing du texte réel côté endpoint HTTP).
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True, "grant_session": True})
    result = await g.agent_graph.ainvoke(None, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ()  # le deuxième key_type n'a pas remis le graphe en pause
    assert snapshot.values["session_grants"] == ["key_type"]
    assert mcp_route.call_count == 2  # les deux appels de key_type ont bien été exécutés
    assert result["messages"][-1].content == "Fini."


@pytest.mark.asyncio
async def test_grant_only_covers_the_granted_tool_name(mock_side_services):
    """Un grant sur key_type ne dispense pas un AUTRE outil sensible d'approbation."""
    import app.graph as g

    from tests.fixtures.llm_sse import multi_tool_call_response

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("key_type", "call_1", '{"text": "Ceci est un texte assez long pour rester sensible par defaut"}')),
        _sse_response(tool_call_response("browser_navigate", "call_2", '{"url": "http://example.com"}')),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Tape hello"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True, "grant_session": True})
    await g.agent_graph.ainvoke(None, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.values["session_grants"] == ["key_type"]
    # browser_navigate n'a jamais été granté : repasse par require_approval
    assert snapshot.next == ("require_approval",)


@pytest.mark.asyncio
async def test_session_grants_are_lost_after_simulated_checkpointer_restart(mock_side_services):
    """
    Les grants vivent dans AgentState, persisté par le checkpointer MemorySaver
    (en mémoire uniquement, voir build_graph). Un redémarrage du service en
    reconstruit un vide : reconstruire le graphe (nouveau MemorySaver) avec le
    MÊME thread_id simule ce redémarrage — le thread entier repart de zéro,
    grants inclus, et le prochain appel de key_type redemande une approbation.
    """
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("key_type", "call_1", '{"text": "Ceci est un texte assez long pour rester sensible par defaut"}')),
        _sse_response(text_response(["OK", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Tape hello"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True, "grant_session": True})
    await g.agent_graph.ainvoke(None, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.values["session_grants"] == ["key_type"]

    # Redémarrage simulé : nouveau MemorySaver, même thread_id.
    g.agent_graph = g.build_graph()

    route.side_effect = [
        _sse_response(tool_call_response("key_type", "call_2", '{"text": "Un second texte tout aussi long pour verifier le comportement"}')),
    ]
    fresh_state = {
        "messages": [{"role": "user", "content": "Tape world"}],
        "tool_iterations": 0,
        "approved": None,
    }
    await g.agent_graph.ainvoke(fresh_state, CONFIG)

    fresh_snapshot = await g.agent_graph.aget_state(CONFIG)
    assert fresh_snapshot.next == ("require_approval",)  # grant perdu, retour à l'approbation
    assert fresh_snapshot.values.get("session_grants") in (None, [])
