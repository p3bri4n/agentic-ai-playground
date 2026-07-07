"""
Tests du graphe LangGraph (app/graph.py) et de l'endpoint HTTP (app/main.py).
Tous les appels HTTP sortants (LLM inclus) sont interceptés par respx, qui
patche au niveau du transport httpx sans remplacer la classe httpx.AsyncClient
elle-même — contrairement à un monkeypatch naïf, cela n'interfère pas avec le
client interne du SDK openai (voir le README pour le détail de ce piège).
"""

import json

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import reasoning_response, text_response, tool_call_response


@pytest.fixture
def mock_side_services():
    """Mock les services annexes (contexte vide, aucune skill) pour isoler le LLM."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-context-manager/retrieve").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        mock.post("http://fake-skill-manager/match").mock(
            return_value=httpx.Response(200, json={"skill": None})
        )
        mock.post("http://fake-mcp-client/call").mock(
            return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "42"}]})
        )
        yield mock


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


CONFIG = {"configurable": {"thread_id": "test-thread"}}


@pytest.mark.asyncio
async def test_simple_response_without_tool_call(mock_side_services):
    import app.graph as g

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(text_response(["Bonjour", " !"]))
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Salut"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    assert result["messages"][-1].content == "Bonjour !"
    # human + réponse finale, rien de plus : pas de message system ajouté
    # puisque le contexte et le skill matching sont vides.
    assert len(result["messages"]) == 2


@pytest.mark.asyncio
async def test_tool_call_pauses_for_approval_without_calling_mcp_client(mock_side_services):
    """Le nœud require_approval doit bloquer avant tout appel réel à mcp-client."""
    import app.graph as g

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}'))
    )
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "42"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Question ?"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ("require_approval",)
    assert mcp_route.call_count == 0


@pytest.mark.asyncio
async def test_approval_resumes_and_calls_mcp_client(mock_side_services):
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}')),
        _sse_response(text_response(["Resultat", ": 42."])),
    ]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "42"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Question ?"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    await g.agent_graph.aupdate_state(CONFIG, {"approved": True})
    result = await g.agent_graph.ainvoke(None, CONFIG)

    assert mcp_route.call_count == 1
    assert result["messages"][-1].content == "Resultat: 42."

    tool_message = next(m for m in result["messages"] if getattr(m, "type", None) == "tool")
    payload = json.loads(tool_message.content)
    assert payload["content"][0]["text"] == "42"


@pytest.mark.asyncio
async def test_rejection_skips_mcp_client_and_synthesizes_refusal(mock_side_services):
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("run_command", "call_1", '{"command": "rm -rf /"}')),
        _sse_response(text_response(["Compris", ", annulé."])),
    ]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "42"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Question ?"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    await g.agent_graph.aupdate_state(CONFIG, {"approved": False})
    result = await g.agent_graph.ainvoke(None, CONFIG)

    assert mcp_route.call_count == 0
    tool_message = next(m for m in result["messages"] if getattr(m, "type", None) == "tool")
    payload = json.loads(tool_message.content)
    assert payload["error"] == "Rejeté par l'utilisateur"
    assert result["messages"][-1].content == "Compris, annulé."


@pytest.mark.asyncio
async def test_tool_call_loop_resolves_and_does_not_duplicate_messages(mock_side_services):
    """
    Non-régression du bug corrigé : les nœuds mutaient state['messages'] en
    place et retournaient l'état entier, ce qui faisait dupliquer les messages
    system/tool dans l'historique. Ce test échoue si la régression revient.
    Passe désormais par l'approbation (approved=True fourni dès le départ).
    """
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}')),
        _sse_response(text_response(["Resultat", ": 42."])),
    ]
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Question ?"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True})
    result = await g.agent_graph.ainvoke(None, CONFIG)

    # human, AI(tool_call), tool, AI(final) : exactement 4, aucun doublon
    assert len(result["messages"]) == 4
    assert result["messages"][-1].content == "Resultat: 42."

    # le contenu du ToolMessage doit correspondre au résultat mocké de mcp-client
    tool_message = result["messages"][2]
    payload = json.loads(tool_message.content)
    assert payload["content"][0]["text"] == "42"


@pytest.mark.asyncio
async def test_reasoning_field_is_folded_into_think_tags(mock_side_services):
    """
    Ollama (Qwen3+) streame le raisonnement dans un champ "reasoning" séparé
    de "content", hors format OpenAI standard : langchain-openai l'ignore
    silencieusement par défaut (_convert_delta_to_message_chunk ne lit que
    "content"/"tool_calls"/"function_call"). app/graph.py le replie dans
    "content", entouré de <think>...</think>, pour qu'Open WebUI l'affiche en
    bulle repliable. Ce test échoue si ce repli casse ou disparaît.
    """
    import app.graph as g

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(
            reasoning_response(["12*7", "=84"], ["Ça fait", " 84."])
        )
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Combien font 12*7 ?"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    assert result["messages"][-1].content == "<think>12*7=84</think>\n\nÇa fait 84."


@pytest.mark.asyncio
async def test_reasoning_without_trailing_content_still_closes_think_tag(mock_side_services):
    """Cas limite : le raisonnement va jusqu'au bout sans contenu final après (jamais
    observé en pratique avec Qwen3, mais call_llm doit rester robuste : la balise
    <think> ne doit jamais rester ouverte dans l'historique persisté)."""
    import app.graph as g

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(reasoning_response(["Hmm."], []))
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "..."}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    assert result["messages"][-1].content == "<think>Hmm.</think>"


@pytest.mark.asyncio
async def test_node_with_no_new_message_does_not_raise(mock_side_services):
    """
    Non-régression : un nœud qui ne produit aucun nouveau message doit
    retourner {"messages": []} explicitement, sinon LangGraph lève
    InvalidUpdateError ("Must write to at least one of [...]").
    """
    import app.graph as g

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(text_response(["OK"]))
    )
    g.agent_graph = g.build_graph()

    state = {
        "messages": [{"role": "user", "content": "Question sans contexte ni skill"}],
        "tool_iterations": 0,
        "approved": None,
    }
    # ne doit lever aucune exception (context vide + skill=None -> retrieve_context
    # et select_skill ne produisent aucun nouveau message)
    result = await g.agent_graph.ainvoke(state, CONFIG)
    assert result["messages"][-1].content == "OK"
