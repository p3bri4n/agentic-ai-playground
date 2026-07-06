"""
Tests de l'endpoint HTTP compatible OpenAI, en streaming et en mode classique,
via une vraie requête ASGI (httpx.ASGITransport) contre l'application FastAPI.
"""

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import text_response, tool_call_response


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


@pytest.fixture
def mock_side_services():
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


@pytest.mark.asyncio
async def test_non_streaming_endpoint_returns_full_answer(mock_side_services):
    import app.graph as g
    import app.main as main_mod

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(text_response(["Bon", "jour"]))
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Salut"}], "stream": False},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "Bonjour"
    assert body["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_streaming_endpoint_yields_sse_chunks_and_done(mock_side_services):
    import app.graph as g
    import app.main as main_mod

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(text_response(["Bon", "jour", " !"]))
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    lines = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Salut"}], "stream": True},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line:
                    lines.append(line)

    assert lines[-1] == "data: [DONE]"
    assert any('"content": "Bon"' in l for l in lines)
    assert any('"finish_reason": "stop"' in l for l in lines)


@pytest.mark.asyncio
async def test_non_streaming_endpoint_pauses_for_approval(mock_side_services):
    import app.graph as g
    import app.main as main_mod

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}'))
    )
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "42"}]})
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Question ?"}], "stream": False},
        )

    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "Approbation requise" in content
    assert mcp_route.call_count == 0


@pytest.mark.asyncio
async def test_non_streaming_endpoint_resumes_after_approval_reply(mock_side_services):
    import app.graph as g
    import app.main as main_mod

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}')),
        _sse_response(text_response(["Resultat", ": 42."])),
    ]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "42"}]})
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Question ?"}], "stream": False},
        )
        assert "Approbation requise" in first.json()["choices"][0]["message"]["content"]

        # Open WebUI renvoie l'historique complet, y compris la question d'approbation
        # et la réponse de l'utilisateur au tour suivant.
        second = await client.post(
            "/v1/chat/completions",
            json={
                "model": "agent-llm",
                "messages": [
                    {"role": "user", "content": "Question ?"},
                    {"role": "assistant", "content": first.json()["choices"][0]["message"]["content"]},
                    {"role": "user", "content": "approuver"},
                ],
                "stream": False,
            },
        )

    assert mcp_route.call_count == 1
    assert second.json()["choices"][0]["message"]["content"] == "Resultat: 42."


async def _stream_contents(client, messages):
    contents = []
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "agent-llm", "messages": messages, "stream": True},
    ) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data: ") and "[DONE]" not in line:
                import json as _json

                payload = _json.loads(line[len("data: "):])
                delta = payload["choices"][0]["delta"]
                if delta.get("content"):
                    contents.append(delta["content"])
    return "".join(contents)


@pytest.mark.asyncio
async def test_streaming_endpoint_hides_tool_call_iteration_then_asks_approval(mock_side_services):
    """
    L'itération où le LLM décide d'appeler un outil ne doit produire aucun
    token de contenu normal ; seul le message d'approbation apparaît, en une
    fois, à la place de la réponse finale.
    """
    import app.graph as g
    import app.main as main_mod

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}'))
    )
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "42"}]})
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        content = await _stream_contents(client, [{"role": "user", "content": "Question ?"}])

    assert "Approbation requise" in content
    assert mcp_route.call_count == 0


@pytest.mark.asyncio
async def test_streaming_endpoint_resumes_after_approval_reply(mock_side_services):
    import app.graph as g
    import app.main as main_mod

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}')),
        _sse_response(text_response(["Resultat", ": 42."])),
    ]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "42"}]})
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        approval_text = await _stream_contents(client, [{"role": "user", "content": "Question ?"}])
        final_text = await _stream_contents(
            client,
            [
                {"role": "user", "content": "Question ?"},
                {"role": "assistant", "content": approval_text},
                {"role": "user", "content": "approuver"},
            ],
        )

    assert mcp_route.call_count == 1
    assert final_text == "Resultat: 42."
