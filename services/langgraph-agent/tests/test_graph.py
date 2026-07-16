"""
Tests du graphe LangGraph (app/graph.py) et de l'endpoint HTTP (app/main.py).
Tous les appels HTTP sortants (LLM inclus) sont interceptés par respx, qui
patche au niveau du transport httpx sans remplacer la classe httpx.AsyncClient
elle-même — contrairement à un monkeypatch naïf, cela n'interfère pas avec le
client interne du SDK openai (voir le README pour le détail de ce piège).
"""

import base64
import json

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import (
    multi_tool_call_response,
    reasoning_response,
    text_response,
    tool_call_response,
)


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
        mock.get("http://fake-mcp-client/tools/schema").mock(
            return_value=httpx.Response(200, json={"tools": []})
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
        return_value=_sse_response(tool_call_response("browser_navigate", "call_1", '{"url": "http://example.com"}'))
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
async def test_auto_approved_tool_skips_require_approval(mock_side_services):
    """
    Les outils souris/capture d'écran GhostDesk (AUTO_APPROVED_TOOLS) doivent
    s'exécuter sans passer par require_approval : sinon un modèle qui vise
    mal (limite de vision/grounding, voir README) oblige un humain à valider
    chaque clic un par un.
    """
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("mouse_click", "call_1", '{"x": 100, "y": 200}')),
        _sse_response(text_response(["Cliqué", "."])),
    ]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique là"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ()  # pas de pause : le tour est allé jusqu'au bout
    assert mcp_route.call_count == 1
    assert result["messages"][-1].content == "Cliqué."


@pytest.mark.asyncio
async def test_all_tier_read_tools_skip_approval_silently(mock_side_services):
    """
    Un tour dont TOUS les tool_calls sont en tier 1 (lecture pure, ex.
    run_command/git_status côté MCP) doit s'exécuter sans jamais passer par
    require_approval — pas seulement les outils historiques d'AUTO_APPROVED_TOOLS.
    """
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(
            multi_tool_call_response(
                [
                    ("run_command", "call_1", '{"command": "pwd"}'),
                    ("git_status", "call_2", "{}"),
                ]
            )
        ),
        _sse_response(text_response(["Terminé", "."])),
    ]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Regarde l'état"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ()
    assert mcp_route.call_count == 2
    assert result["messages"][-1].content == "Terminé."


@pytest.mark.asyncio
async def test_unknown_tool_requires_approval(mock_side_services):
    """Défaut = le tier le plus restrictif : un outil jamais classé nulle part reste sensible."""
    import app.graph as g

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(tool_call_response("some_never_seen_tool", "call_1", "{}"))
    )
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Fais un truc inédit"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ("require_approval",)
    assert mcp_route.call_count == 0


@pytest.mark.asyncio
async def test_mixed_auto_and_manual_tools_still_requires_approval(mock_side_services):
    """
    Un tour qui mélange un outil auto-approuvé (mouse_click) et un outil
    sensible (browser_navigate) doit rester intégralement soumis à
    approbation — pas d'approbation partielle par outil.
    """
    import app.graph as g

    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(
            multi_tool_call_response(
                [
                    ("mouse_click", "call_1", '{"x": 100, "y": 200}'),
                    ("browser_navigate", "call_2", '{"url": "http://example.com"}'),
                ]
            )
        )
    )
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique puis exécute pwd"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ("require_approval",)
    assert mcp_route.call_count == 0


@pytest.mark.asyncio
async def test_auto_approval_streak_limit_forces_human_checkin(mock_side_services, monkeypatch):
    """
    Garde-fou contre le clavier virtuel : une suite de clics auto-approuvés
    peut en théorie composer n'importe quelle saisie sans jamais qu'un humain
    ne valide quoi que ce soit. Passé AUTO_APPROVAL_STREAK_LIMIT tours
    auto-approuvés consécutifs, le tour suivant doit repasser par
    require_approval même s'il ne contient QUE des outils normalement
    auto-approuvés.
    """
    import app.graph as g

    monkeypatch.setattr(g, "AUTO_APPROVAL_STREAK_LIMIT", 2)

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("mouse_click", f"call_{i}", '{"x": 1, "y": 2}')) for i in range(3)
    ] + [_sse_response(text_response(["Terminé", "."]))]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique en boucle"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    # 2 tours auto-approuvés exécutés (mouse_click, iterations 1 et 2), le
    # 3e est bloqué en pause malgré mouse_click étant dans AUTO_APPROVED_TOOLS
    assert snapshot.next == ("require_approval",)
    assert snapshot.values["auto_approval_streak"] == 2
    assert mcp_route.call_count == 2

    # Une fois l'humain repassé par require_approval, le compteur est réarmé
    # à 0 : la pratique n'est pas bloquée définitivement, juste jalonnée d'un
    # point de contrôle humain périodique.
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True})
    await g.agent_graph.ainvoke(None, CONFIG)
    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ()
    assert snapshot.values["auto_approval_streak"] == 1  # 0 réarmé, puis +1 pour ce tour exécuté
    assert mcp_route.call_count == 3


@pytest.mark.asyncio
async def test_max_tool_iterations_ends_loop_with_pending_tool_calls(mock_side_services, monkeypatch):
    """
    Non-régression : rencontré en usage réel avec la boucle GhostDesk
    auto-approuvée (capture/clic en rafale) — has_tool_calls force la fin du
    graphe dès que tool_iterations atteint MAX_TOOL_ITERATIONS, MÊME SI le
    dernier message du modèle contient encore un tool_calls en attente. Sans
    vérification côté appelant (voir app/main.py), ce tool_calls est
    silencieusement perdu : l'agent semble juste "s'arrêter" en plein milieu
    d'une tâche, sans erreur ni pause d'approbation pour l'expliquer.
    """
    import app.graph as g

    monkeypatch.setattr(g, "MAX_TOOL_ITERATIONS", 2)

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    # mouse_click est auto-approuvé (AUTO_APPROVED_TOOLS) : la boucle
    # call_llm -> auto_call_tools ne repasse jamais par une pause tant que le
    # modèle continue à en redemander.
    route.side_effect = [
        _sse_response(tool_call_response("mouse_click", f"call_{i}", '{"x": 1, "y": 2}')) for i in range(3)
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique en boucle"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, {**CONFIG, "recursion_limit": 50})

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ()  # le graphe s'est bien terminé, pas mis en pause
    assert snapshot.values["tool_iterations"] == 2
    last_message = result["messages"][-1]
    # le 3e tool_call (mouse_click number 2) n'a jamais été exécuté ni approuvé
    assert last_message.tool_calls
    assert last_message.tool_calls[0]["name"] == "mouse_click"


@pytest.mark.asyncio
async def test_approval_resumes_and_calls_mcp_client(mock_side_services):
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("browser_navigate", "call_1", '{"url": "http://example.com"}')),
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
        _sse_response(tool_call_response("key_type", "call_1", '{"text": "rm -rf /"}')),
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
        _sse_response(tool_call_response("browser_navigate", "call_1", '{"url": "http://example.com"}')),
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
async def test_tool_schema_from_mcp_client_is_bound_to_llm(mock_side_services):
    """
    Non-régression : ChatOpenAI était instancié sans jamais appeler
    bind_tools(), donc le LLM ignorait purement et simplement l'existence des
    outils MCP (terminal/filesystem/git/browser/desktop-GhostDesk) — has_
    tool_calls()/require_approval() restaient du code mort en usage réel,
    quel que soit le modèle servi. Ce test échoue si le schéma récupéré
    depuis mcp-client (GET /tools/schema) n'est plus transmis au LLM dans la
    requête sortante.
    """
    import app.graph as g

    tool_schema = [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Exécute une commande shell.",
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
            },
        }
    ]
    mock_side_services.get("http://fake-mcp-client/tools/schema").mock(
        return_value=httpx.Response(200, json={"tools": tool_schema})
    )
    llm_route = mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(text_response(["OK"]))
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Salut"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    sent_body = json.loads(llm_route.calls.last.request.content)
    assert sent_body["tools"] == tool_schema


@pytest.mark.asyncio
async def test_tool_image_result_becomes_multimodal_user_message(mock_side_services):
    """
    Non-régression : le résultat brut d'un outil (ex. screen_shot de GhostDesk,
    format MCP {"type": "image", "data": <base64>, "mimeType": ...}) était
    json.dumps() intégralement dans un ToolMessage, un rôle qui ne supporte
    que du texte au format OpenAI-compatible — le modèle recevait donc un
    blob base64 illisible, pas une image, indépendamment de ses capacités
    vision. call_tools doit désormais extraire les blocs image et les
    réinjecter en message "user" multimodal (image_url), seul rôle qui les
    supporte. Le WebP (format par défaut de screen_shot) doit en plus être
    reconverti en PNG : le décodeur d'image d'Ollama (mtmd/llama.cpp) échoue
    explicitement dessus ("Failed to load image or audio file", vérifié en
    conditions réelles), PNG fonctionne.
    """
    import io

    from PIL import Image

    import app.graph as g

    webp_buf = io.BytesIO()
    Image.new("RGB", (2, 2), color="red").save(webp_buf, format="WEBP", lossless=True)
    webp_b64 = base64.b64encode(webp_buf.getvalue()).decode()

    # screen_shot puis une réponse texte finale : un seul aller-retour d'outil,
    # pour ne pas dépendre de MAX_TOOL_ITERATIONS pour terminer la boucle
    # (screen_shot est auto-approuvé, voir AUTO_APPROVED_TOOLS — un
    # return_value fixe bouclerait donc indéfiniment jusqu'à percuter le
    # recursion_limit interne de LangGraph, sans rapport avec ce qui est
    # testé ici).
    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("screen_shot", "call_1", "{}")),
        _sse_response(text_response(["Capture", " prise."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(
            200,
            json={"content": [{"type": "image", "data": webp_b64, "mimeType": "image/webp"}]},
        )
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Capture le bureau"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    tool_message = next(m for m in result["messages"] if getattr(m, "type", None) == "tool")
    assert webp_b64 not in tool_message.content  # le base64 ne doit plus polluer le ToolMessage

    image_message = next(m for m in result["messages"] if getattr(m, "type", None) == "human" and isinstance(m.content, list))
    url = image_message.content[0]["image_url"]["url"]
    assert image_message.content[0]["type"] == "image_url"
    assert url.startswith("data:image/png;base64,")

    # round-trip : le payload doit être un PNG 2x2 rouge valide, pas juste un
    # préfixe correct
    png_bytes = base64.b64decode(url.split(",", 1)[1])
    decoded = Image.open(io.BytesIO(png_bytes))
    assert decoded.format == "PNG"
    assert decoded.size == (2, 2)
    assert decoded.convert("RGB").getpixel((0, 0)) == (255, 0, 0)


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
