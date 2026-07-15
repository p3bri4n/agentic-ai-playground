"""
Tests de l'endpoint HTTP compatible OpenAI, en streaming et en mode classique,
via une vraie requête ASGI (httpx.ASGITransport) contre l'application FastAPI.
"""

import json

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import (
    reasoning_response,
    reasoning_tool_call_response,
    text_response,
    tool_call_response,
)


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
        mock.get("http://fake-mcp-client/tools/schema").mock(
            return_value=httpx.Response(200, json={"tools": []})
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
async def test_streaming_endpoint_closes_dangling_think_tag_before_approval_text(mock_side_services):
    """
    Non-régression : quand le modèle raisonne avant de décider d'appeler un
    outil, le tour se termine avec un content réel vide (le tool_call arrive
    par un canal séparé) — aucun chunk de contenu "réel" n'arrive jamais pour
    déclencher la fermeture de <think> (voir _convert_delta_with_reasoning
    dans app/graph.py). Sans le correctif, le texte "⚠️ Approbation requise"
    ajouté ensuite se retrouvait concaténé À L'INTÉRIEUR du <think> jamais
    fermé côté client — invisible en dehors de la bulle de pensée repliée
    d'Open WebUI, et donc introuvable par toute automatisation (bouton
    d'approbation) qui cherche ce texte dans le contenu du message.
    """
    import app.graph as g
    import app.main as main_mod

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(
            reasoning_tool_call_response(["Je vais ", "utiliser l'outil."], "run_command", "call_1", '{"command": "pwd"}')
        )
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    chunks = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Capture le bureau"}], "stream": True},
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and "[DONE]" not in line:
                    payload = json.loads(line[6:])
                    content = payload["choices"][0]["delta"].get("content")
                    if content:
                        chunks.append(content)

    full_text = "".join(chunks)
    assert "<think>" in full_text
    assert "</think>" in full_text
    # la balise doit être fermée AVANT le texte d'approbation, pas juste
    # présente quelque part dans le flux
    assert full_text.index("</think>") < full_text.index("Approbation requise")


@pytest.mark.asyncio
async def test_streaming_endpoint_merges_think_across_auto_approved_tool_loop(mock_side_services):
    """
    Non-régression : avec AUTO_APPROVED_TOOLS, call_llm peut s'exécuter
    plusieurs fois d'affilée sans pause d'approbation (boucle capture/clic
    GhostDesk). Chaque itération raisonne (champ "reasoning") avant de
    décider quoi faire ensuite. Sans le report de l'état <think> d'un appel
    de call_llm à l'autre (AgentState.think_opened/think_closed), chaque
    itération rouvrait sa propre balise <think> en plein milieu du flux —
    Open WebUI n'affiche en bulle repliable que celle en tout début de
    message, les suivantes apparaissant en texte brut visible au milieu de
    la réponse.
    """
    import app.graph as g
    import app.main as main_mod

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(
            reasoning_tool_call_response(["Je vais ", "cliquer."], "mouse_click", "call_1", '{"x": 1, "y": 2}')
        ),
        _sse_response(reasoning_response(["Et ", "voilà."], ["Cliqué", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    chunks = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Clique là"}], "stream": True},
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and "[DONE]" not in line:
                    payload = json.loads(line[6:])
                    content = payload["choices"][0]["delta"].get("content")
                    if content:
                        chunks.append(content)

    full_text = "".join(chunks)
    # Une seule balise ouvrante/fermante malgré deux itérations de call_llm :
    # tout le raisonnement des deux tours doit tenir dans le même bloc.
    assert full_text.count("<think>") == 1
    assert full_text.count("</think>") == 1
    assert full_text.index("<think>") < full_text.index("</think>") < full_text.index("Cliqué.")


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
async def test_non_streaming_endpoint_reports_iteration_limit_notice(mock_side_services, monkeypatch):
    """
    Non-régression : avant ce correctif, un run qui percutait
    MAX_TOOL_ITERATIONS avec un tool_call encore en attente (boucle
    GhostDesk auto-approuvée) rendait juste le dernier texte de raisonnement
    du modèle tel quel, sans aucune indication que la tâche avait été
    interrompue — observé en usage réel (l'agent semblait "s'arrêter" en
    plein milieu d'une phrase).
    """
    import app.graph as g
    import app.main as main_mod

    monkeypatch.setattr(g, "MAX_TOOL_ITERATIONS", 2)
    monkeypatch.setattr(main_mod, "MAX_TOOL_ITERATIONS", 2)

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("mouse_click", f"call_{i}", '{"x": 1, "y": 2}')) for i in range(3)
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Clique en boucle"}], "stream": False},
        )

    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "Limite d'itérations" in content
    assert "mouse_click" in content


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


@pytest.mark.asyncio
async def test_approve_endpoint_resumes_without_text_reply(mock_side_services):
    """
    /approve permet de reprendre une pause d'approbation depuis un clic de
    bouton (Open WebUI Action function) plutôt que le message texte
    "approuver" attendu par /v1/chat/completions. Le tour normal suivant ne
    doit pas dupliquer l'historique (même bookkeeping owui_message_count que
    le flux texte, voir _resolve_run).
    """
    import app.graph as g
    import app.main as main_mod

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}')),
        _sse_response(text_response(["Resultat", ": 42."])),
        _sse_response(text_response(["Autre", " reponse."])),
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
        approval_text = first.json()["choices"][0]["message"]["content"]
        assert "Approbation requise" in approval_text

        approved = await client.post(
            "/approve",
            json={
                "messages": [
                    {"role": "user", "content": "Question ?"},
                    {"role": "assistant", "content": approval_text},
                ],
                "approved": True,
            },
        )
        assert approved.status_code == 200
        assert approved.json()["content"] == "Resultat: 42."
        assert mcp_route.call_count == 1

        # Tour normal suivant : Open WebUI renvoie son historique tel quel
        # (sans "approuver", puisque la décision est passée par le bouton).
        # Ne doit ni dupliquer ni perdre de messages.
        second = await client.post(
            "/v1/chat/completions",
            json={
                "model": "agent-llm",
                "messages": [
                    {"role": "user", "content": "Question ?"},
                    {"role": "assistant", "content": "Resultat: 42."},
                    {"role": "user", "content": "Autre question ?"},
                ],
                "stream": False,
            },
        )

    assert second.json()["choices"][0]["message"]["content"] == "Autre reponse."

    thread_id = main_mod._derive_thread_id([type("M", (), {"role": "user", "content": "Question ?"})()])
    snapshot = await g.agent_graph.aget_state({"configurable": {"thread_id": thread_id}})
    # human1, AI(tool_call), tool, AI(final), human2, AI(autre) : exactement 6, aucun doublon
    assert len(snapshot.values["messages"]) == 6


@pytest.mark.asyncio
async def test_approve_endpoint_returns_409_without_pending_approval(mock_side_services):
    import app.graph as g
    import app.main as main_mod

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(text_response(["OK"]))
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Salut"}], "stream": False},
        )
        resp = await client.post(
            "/approve",
            json={"messages": [{"role": "user", "content": "Salut"}], "approved": True},
        )

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_pending_endpoint_reports_status_without_side_effects(mock_side_services):
    """
    /pending ne dépend que du premier message humain (thread_id) — jamais du
    contenu du dernier message assistant, qui peut être vide ou tronqué côté
    client selon comment celui-ci a interprété les balises <think> (observé
    en conditions réelles avec Open WebUI : le texte affiché à l'écran et le
    "content" du message tel que renvoyé à une intégration tierce peuvent
    diverger). C'est ce qui permet à un bouton d'UI de savoir s'il y a une
    approbation en attente sans se fier à ce contenu potentiellement vide.
    """
    import app.graph as g
    import app.main as main_mod

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(tool_call_response("run_command", "call_1", '{"command": "pwd"}'))
    )
    g.agent_graph = g.build_graph()
    main_mod.agent_graph = g.agent_graph

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        no_thread_yet = await client.post(
            "/pending", json={"messages": [{"role": "user", "content": "Question jamais posée"}]}
        )
        assert no_thread_yet.json() == {"pending": False}

        await client.post(
            "/v1/chat/completions",
            json={"model": "agent-llm", "messages": [{"role": "user", "content": "Question ?"}], "stream": False},
        )

        # Content vide sur le dernier message : reproduit le cas réel où le
        # client (Open WebUI) renvoie un content vide pour le message
        # d'approbation malgré son affichage correct à l'écran.
        during_pause = await client.post(
            "/pending",
            json={
                "messages": [
                    {"role": "user", "content": "Question ?"},
                    {"role": "assistant", "content": ""},
                ]
            },
        )
        assert during_pause.json()["pending"] is True
        assert "Approbation requise" in during_pause.json()["text"]

        approved = await client.post(
            "/approve",
            json={
                "messages": [
                    {"role": "user", "content": "Question ?"},
                    {"role": "assistant", "content": ""},
                ],
                "approved": True,
            },
        )
        assert approved.status_code == 200


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


@pytest.mark.asyncio
async def test_streaming_endpoint_reopens_think_tag_after_approval_resume(mock_side_services):
    """
    Non-régression : le premier tour raisonne puis demande un outil non
    auto-approuvé -> pause. Le </think> orphelin qui clôt alors le message
    d'approbation (closing_prefix, app/main.py) n'était jamais répercuté dans
    AgentState.think_opened/think_closed persisté par le checkpointer. Une
    fois l'utilisateur approuve et qu'un DEUXIÈME round de raisonnement
    démarre (avant la réponse finale), l'état persisté croyait le <think>
    encore ouvert : aucune balise ouvrante n'était réémise pour ce nouveau
    raisonnement, alors qu'une balise fermante l'était bien en fin de tour —
    un </think> visible côté client sans <think> correspondant dans ce tour.
    """
    import app.graph as g
    import app.main as main_mod

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(
            reasoning_tool_call_response(["Je cherche."], "run_command", "call_1", '{"command": "pwd"}')
        ),
        _sse_response(reasoning_response(["Je formule la réponse."], ["Resultat", ": 42."])),
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
    assert final_text.count("<think>") == final_text.count("</think>") == 1
    assert final_text.startswith("<think>")
