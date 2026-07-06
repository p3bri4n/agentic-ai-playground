"""
Non-régression : l'ajout du checkpointer + thread_id stable (supervision
humaine des outils) a introduit un risque de duplication des messages —
Open WebUI renvoie l'historique COMPLET à chaque requête, alors que ce
thread a déjà persisté les tours précédents. Sans le filtrage par
owui_message_count (app/main.py:_resolve_run), chaque nouveau tour
réinjectait tout l'historique déjà stocké, dupliquant les messages à chaque
tour (vérifié : 2 tours simples produisaient 6 messages internes au lieu de
4). Ces tests figent le comportement correct.
"""

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import text_response, tool_call_response


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


@pytest.mark.asyncio
async def test_two_turn_conversation_message_count():
    import app.graph as g
    import app.main as main_mod

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-context-manager/retrieve").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        mock.post("http://fake-skill-manager/match").mock(
            return_value=httpx.Response(200, json={"skill": None})
        )
        route = mock.post("http://fake-vllm/v1/chat/completions")
        route.side_effect = [
            _sse_response(text_response(["Bonjour", " !"])),
            _sse_response(text_response(["Comment", " puis-je", " aider ?"])),
        ]

        g.agent_graph = g.build_graph()
        main_mod.agent_graph = g.agent_graph

        transport = httpx.ASGITransport(app=main_mod.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/v1/chat/completions",
                json={"model": "agent-llm", "messages": [{"role": "user", "content": "Salut"}], "stream": False},
            )
            second = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "agent-llm",
                    "messages": [
                        {"role": "user", "content": "Salut"},
                        {"role": "assistant", "content": first.json()["choices"][0]["message"]["content"]},
                        {"role": "user", "content": "Comment vas-tu ?"},
                    ],
                    "stream": False,
                },
            )

        thread_id = main_mod._derive_thread_id(
            [type("M", (), {"role": "user", "content": "Salut"})()]
        )
        snapshot = await g.agent_graph.aget_state({"configurable": {"thread_id": thread_id}})
        # human1, AI1, human2, AI2 : exactement 4, aucun doublon de tour 1
        assert len(snapshot.values["messages"]) == 4


@pytest.mark.asyncio
async def test_tool_approval_then_new_turn_message_count():
    import app.graph as g
    import app.main as main_mod

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
        route = mock.post("http://fake-vllm/v1/chat/completions")
        route.side_effect = [
            _sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}')),
            _sse_response(text_response(["Resultat", ": 42."])),
            _sse_response(text_response(["Autre", " reponse."])),
        ]

        g.agent_graph = g.build_graph()
        main_mod.agent_graph = g.agent_graph

        transport = httpx.ASGITransport(app=main_mod.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/v1/chat/completions",
                json={"model": "agent-llm", "messages": [{"role": "user", "content": "Question ?"}], "stream": False},
            )
            approval_text = first.json()["choices"][0]["message"]["content"]

            second = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "agent-llm",
                    "messages": [
                        {"role": "user", "content": "Question ?"},
                        {"role": "assistant", "content": approval_text},
                        {"role": "user", "content": "approuver"},
                    ],
                    "stream": False,
                },
            )
            final_text = second.json()["choices"][0]["message"]["content"]

            third = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "agent-llm",
                    "messages": [
                        {"role": "user", "content": "Question ?"},
                        {"role": "assistant", "content": approval_text},
                        {"role": "user", "content": "approuver"},
                        {"role": "assistant", "content": final_text},
                        {"role": "user", "content": "Autre question ?"},
                    ],
                    "stream": False,
                },
            )

        thread_id = main_mod._derive_thread_id(
            [type("M", (), {"role": "user", "content": "Question ?"})()]
        )
        snapshot = await g.agent_graph.aget_state({"configurable": {"thread_id": thread_id}})
        # human1, AI(tool_call), tool, AI(final), human2, AI(autre) : exactement 6, aucun doublon
        assert len(snapshot.values["messages"]) == 6
        assert third.json()["choices"][0]["message"]["content"] == "Autre reponse."
