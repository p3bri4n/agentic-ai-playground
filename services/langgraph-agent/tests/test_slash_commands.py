"""
Tests des commandes slash (ex. "/app_list", "/mouse_click x=100 y=200") :
appellent un outil MCP directement, sans passer par le LLM ni par la
politique d'approbation — voir app/graph.py, run_slash_command/_route_entry.
"""

import json

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import text_response

CONFIG = {"configurable": {"thread_id": "test-thread-slash"}}


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


@pytest.fixture
def mock_side_services():
    """Même fixture que test_graph.py, dupliquée ici pour ne pas coupler les
    deux fichiers de test — voir ce fichier pour le rationnel de chaque mock."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-context-manager/retrieve").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        mock.post("http://fake-skill-manager/match").mock(
            return_value=httpx.Response(200, json={"skill": None})
        )
        mock.get("http://fake-mcp-client/tools/schema").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tools": [
                        {"type": "function", "function": {"name": "app_list", "description": "", "parameters": {}}},
                        {
                            "type": "function",
                            "function": {"name": "mouse_click", "description": "", "parameters": {}},
                        },
                        {
                            "type": "function",
                            "function": {"name": "key_type", "description": "", "parameters": {}},
                        },
                    ]
                },
            )
        )
        yield mock


def _parse():
    import app.graph as g

    return g._parse_slash_command


@pytest.mark.parametrize(
    "content,expected",
    [
        ("/app_list", ("app_list", {})),
        ("/mouse_click x=100 y=200", ("mouse_click", {"x": 100, "y": 200})),
        ("/key_type text=bonjour", ("key_type", {"text": "bonjour"})),
        ('/key_type text="bonjour le monde"', ("key_type", {"text": "bonjour le monde"})),
        ("/toggle actif=true", ("toggle", {"actif": True})),
        ("/set ratio=1.5", ("set", {"ratio": 1.5})),
        ("Salut, comment ça va ?", None),
        ("", None),
        ("/", None),
    ],
)
def test_parse_slash_command(content, expected):
    parse = _parse()
    assert parse(content) == expected


def test_parse_slash_command_ignores_malformed_argument():
    parse = _parse()
    tool_name, args = parse("/app_list bruit_sans_egal x=1")
    assert tool_name == "app_list"
    assert args == {"x": 1}


@pytest.mark.asyncio
async def test_slash_command_calls_tool_directly_without_llm(mock_side_services):
    import app.graph as g

    call_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "app1\napp2"}]})
    )
    llm_route = mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=httpx.Response(500)
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "/app_list"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    assert call_route.called
    assert not llm_route.called
    assert json.loads(call_route.calls.last.request.content) == {"tool": "app_list", "arguments": {}}
    assert result["messages"][-1].content == "app1\napp2"


@pytest.mark.asyncio
async def test_slash_command_with_arguments_sends_typed_values(mock_side_services):
    import app.graph as g

    call_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {
        "messages": [{"role": "user", "content": "/mouse_click x=100 y=200"}],
        "tool_iterations": 0,
        "approved": None,
    }
    await g.agent_graph.ainvoke(state, CONFIG)

    sent = json.loads(call_route.calls.last.request.content)
    assert sent == {"tool": "mouse_click", "arguments": {"x": 100, "y": 200}}


@pytest.mark.asyncio
async def test_unknown_slash_like_message_falls_back_to_normal_flow(mock_side_services):
    """Un message qui commence par "/" sans correspondre à un outil connu part
    dans le flux normal (LLM) plutôt que de déclencher une erreur 404."""
    import app.graph as g

    call_route = mock_side_services.post("http://fake-mcp-client/call")
    llm_route = mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=(
                b'data: {"choices":[{"delta":{"role":"assistant","content":"Chemin recu."},'
                b'"finish_reason":null}]}\n\n'
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
            headers={"content-type": "text/event-stream"},
        )
    )
    g.agent_graph = g.build_graph()

    state = {
        "messages": [{"role": "user", "content": "/home/user/fichier.txt existe ?"}],
        "tool_iterations": 0,
        "approved": None,
    }
    result = await g.agent_graph.ainvoke(state, CONFIG)

    assert not call_route.called
    assert llm_route.called
    assert result["messages"][-1].content == "Chemin recu."


@pytest.mark.asyncio
async def test_slash_command_on_sensitive_tool_pauses_for_approval(mock_side_services):
    """
    GARDE-FOU : un outil TIER_SENSITIVE (key_type avec texte long) invoqué
    via commande slash NE s'exécute PAS directement — il part par
    require_approval comme un tool_calls normal du LLM, exactement comme
    test_approval_rules.py::test_long_key_type_interrupts_in_graph.
    """
    import app.graph as g

    call_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    # Après approbation, call_tools -> call_llm (flux normal, inchangé) :
    # nécessaire pour la reprise, même si cette suite ne teste pas ce tour-là.
    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(text_response(["Fait", "."]))
    )
    g.agent_graph = g.build_graph()

    long_text = "Un texte de plus de cinquante caracteres pour rester sensible par defaut"
    state = {
        "messages": [{"role": "user", "content": f'/key_type text="{long_text}"'}],
        "tool_iterations": 0,
        "approved": None,
    }
    await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ("require_approval",)
    assert call_route.call_count == 0

    # Une fois approuvé, l'outil s'exécute réellement (via call_tools normal).
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True})
    await g.agent_graph.ainvoke(None, CONFIG)
    assert call_route.call_count == 1
    sent = json.loads(call_route.calls.last.request.content)
    assert sent == {"tool": "key_type", "arguments": {"text": long_text}}


@pytest.mark.asyncio
async def test_slash_command_audits_reversible_tool_but_not_read_tool(mock_side_services):
    import app.audit_log as audit_log
    import app.graph as g

    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    # mouse_click est TIER_REVERSIBLE par défaut (voir approval_policy.py) :
    # doit apparaître dans le journal d'audit même invoqué via slash-command.
    state = {
        "messages": [{"role": "user", "content": "/mouse_click x=1 y=2"}],
        "tool_iterations": 0,
        "approved": None,
    }
    await g.agent_graph.ainvoke(state, CONFIG)
    entries = audit_log.read_entries(CONFIG["configurable"]["thread_id"])
    assert any(e["tool"] == "mouse_click" for e in entries)

    # app_list est TIER_READ par défaut : jamais audité, tool-call ou slash-command.
    state2 = {"messages": [{"role": "user", "content": "/app_list"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state2, CONFIG)
    entries2 = audit_log.read_entries(CONFIG["configurable"]["thread_id"])
    assert not any(e["tool"] == "app_list" for e in entries2)
