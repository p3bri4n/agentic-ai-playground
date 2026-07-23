"""
Non-régression : une erreur pendant `agent_graph.ainvoke` (ex. dépassement de
contexte LLM) doit produire la même notice propre sur les TROIS chemins qui
invoquent le graphe (streaming, non-streaming, /approve), jamais un 500 brut.

Découvert en conditions réelles (tests_integration/test_web_tasks.py, tâches
T8/T11 sur des pages web réelles volumineuses) : le chemin streaming
(_stream_response) attrapait déjà ce cas via un `except Exception` englobant,
mais ni `/v1/chat/completions` non-streaming ni `/approve` ne l'avaient —
`openai.BadRequestError: Prompt length ... exceeds the available context
size` y remontait en 500 brut au lieu d'une réponse HTTP 200 avec une notice.
"""

import httpx
import pytest
import respx


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
        # Reproduit exactement l'erreur constatée en conditions réelles :
        # TabbyAPI (API compatible OpenAI) répond 400 quand le prompt dépasse
        # la fenêtre de contexte du modèle.
        mock.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Prompt length 69510 exceeds the available context size of 32768 tokens",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "context_length_exceeded",
                    }
                },
            )
        )
        yield mock


@pytest.mark.asyncio
async def test_non_streaming_endpoint_reports_internal_error_notice(mock_side_services):
    import app.graph as g
    import app.main as main_mod

    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Salut"}], "stream": False},
        )

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == main_mod._INTERNAL_ERROR_NOTICE


@pytest.mark.asyncio
async def test_approve_reports_internal_error_notice(mock_side_services):
    """
    /approve reprend un thread déjà en pause d'approbation : il faut d'abord
    l'y amener (1er appel non-streaming qui pause sur un tool_call sensible),
    PUIS faire échouer le tour suivant (celui déclenché par /approve) pour
    tester ce chemin précis plutôt que le premier.
    """
    import app.graph as g
    import app.main as main_mod
    from tests.fixtures.llm_sse import tool_call_response

    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph
    messages = [{"role": "user", "content": "Soumets ce formulaire"}]

    mock_side_services.get("http://fake-mcp-client/tools/schema").mock(
        return_value=httpx.Response(
            200,
            json={
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "submit_form",
                            "description": "",
                            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}},
                        },
                    }
                ]
            },
        )
    )
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "lancé"}]})
    )
    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=tool_call_response("submit_form", "call_1", '{"field": "value"}'),
            headers={"content-type": "text/event-stream"},
        )
    )
    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": messages, "stream": False},
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"].startswith("⚠️ Approbation requise")

        mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Prompt length 69510 exceeds the available context size of 32768 tokens",
                        "type": "invalid_request_error",
                        "code": "context_length_exceeded",
                    }
                },
            )
        )
        resp = await client.post(
            "/approve",
            json={"messages": messages, "approved": True, "grant_session": False},
        )

    assert resp.status_code == 200
    assert resp.json()["content"] == main_mod._INTERNAL_ERROR_NOTICE
