"""
Tests du filet de sécurité "réponse vide" (app/graph.py) — bug réel observé
en usage réel avec llama-server (fork turboquant-webp) : un modèle peut
terminer un tour sans tool_calls structuré ET sans texte visible, sa
tentative d'appel d'outil restant piégée en prose dans le raisonnement (voir
README, tableau des bugs, pour la cause racine confirmée côté serveur).

Deux mitigations testées séparément :
  1. _extract_fallback_tool_call : reconstruit un tool_calls structuré à
     partir du texte, quand c'est possible.
  2. retry_empty_answer (via has_tool_calls) : reboucle automatiquement sur
     call_llm quand la reconstruction échoue, jusqu'à MAX_EMPTY_ANSWER_RETRIES
     fois avant d'abandonner.
"""

import httpx
import pytest
import respx

import app.graph as g
from tests.fixtures.llm_sse import reasoning_response, text_response, tool_call_response


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


CONFIG = {"configurable": {"thread_id": "test-thread-empty-answer"}}


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


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _extract_fallback_tool_call
# ─────────────────────────────────────────────────────────────────────────


def test_extract_fallback_tool_call_parses_qwen_style_xml():
    content = (
        "Je vais cliquer.\n"
        "<tool_call>\n<function=mouse_click>\n"
        "<parameter=x>\n10\n</parameter>\n"
        "<parameter=y>\n20\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    result = g._extract_fallback_tool_call(content)
    assert result["name"] == "mouse_click"
    assert result["args"] == {"x": "10", "y": "20"}
    assert result["id"].startswith("fallback_")


def test_extract_fallback_tool_call_returns_none_without_match():
    assert g._extract_fallback_tool_call("Juste du texte, rien à voir.") is None
    assert g._extract_fallback_tool_call("") is None
    assert g._extract_fallback_tool_call(None) is None


def test_extract_fallback_tool_call_handles_multiline_parameter_value():
    """Cas réel observé : un paramètre de saisie (URL) entouré de sauts de ligne."""
    content = (
        "<tool_call>\n<function=key_type>\n"
        "<parameter=text>\nfr.wikipedia.org/wiki/Toulouse\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    result = g._extract_fallback_tool_call(content)
    assert result["name"] == "key_type"
    assert result["args"] == {"text": "fr.wikipedia.org/wiki/Toulouse"}


# ─────────────────────────────────────────────────────────────────────────
# Intégration : récupération de secours dans call_llm
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_llm_recovers_tool_call_trapped_in_reasoning(mock_side_services):
    """
    Le modèle a écrit son appel d'outil en prose, noyé dans reasoning_content
    (jamais un vrai tool_calls structuré) : call_llm doit le reconstruire
    avant que has_tool_calls ne le traite. mouse_click est auto-approuvé
    (tier réversible) : une fois récupéré, il s'exécute directement sans
    passer par require_approval ni consommer de retry.
    """
    trapped = (
        "Je vais cliquer sur le bouton.\n"
        "<tool_call>\n<function=mouse_click>\n"
        "<parameter=x>\n10\n</parameter>\n<parameter=y>\n20\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(reasoning_response([trapped], [])),
        _sse_response(text_response(["Cliqué", "."])),
    ]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique là"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    ai_messages = [m for m in result["messages"] if getattr(m, "type", None) == "ai"]
    recovered_call = ai_messages[0].tool_calls
    assert len(recovered_call) == 1
    assert recovered_call[0]["name"] == "mouse_click"
    assert recovered_call[0]["args"] == {"x": "10", "y": "20"}

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ()
    assert snapshot.values.get("empty_answer_retries", 0) == 0  # jamais consommé : récupéré au 1er essai
    assert mcp_route.call_count == 1
    assert result["messages"][-1].content == "Cliqué."


@pytest.mark.asyncio
async def test_fallback_recovered_tool_call_still_requires_approval_for_sensitive_tool(mock_side_services):
    """Le tool_call reconstruit reste soumis à la politique par tiers normale (ici : sensible -> approbation)."""
    trapped = (
        "<tool_call>\n<function=key_type>\n"
        "<parameter=text>\nun texte assez long pour rester sensible par defaut ici\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    mock_side_services.post("http://fake-vllm/v1/chat/completions").mock(
        return_value=_sse_response(reasoning_response([trapped], []))
    )
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Tape ce texte"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ("require_approval",)
    assert mcp_route.call_count == 0


# ─────────────────────────────────────────────────────────────────────────
# Intégration : retry automatique quand rien n'est récupérable
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retries_automatically_then_succeeds(mock_side_services):
    """1er tour : reasoning seul, rien de récupérable -> retry silencieux -> 2e tour réussit normalement."""
    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(reasoning_response(["Hmm, je réfléchis sans conclure."], [])),
        _sse_response(text_response(["Voici", " la réponse."])),
    ]
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Question ?"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ()  # le graphe est allé jusqu'au bout, pas de pause
    assert snapshot.values["empty_answer_retries"] == 1
    # deux messages AI accumulés (tentative ratée + retry réussi), le dernier est la vraie réponse
    assert result["messages"][-1].content == "Voici la réponse."


@pytest.mark.asyncio
async def test_retry_resets_think_state_for_fresh_reasoning_block(mock_side_services):
    """
    Non-régression : sans reset de think_opened/think_closed au retry, le
    raisonnement de la 2e tentative s'afficherait en texte brut (déjà
    "opened" selon l'état persisté par la tentative ratée).
    """
    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(reasoning_response(["Premier essai, rien ne sort."], [])),
        _sse_response(reasoning_response(["Second essai."], ["Réponse", " finale."])),
    ]
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Question ?"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    assert result["messages"][-1].content == "<think>Second essai.</think>\n\nRéponse finale."


@pytest.mark.asyncio
async def test_gives_up_after_exhausting_retry_budget(mock_side_services, monkeypatch):
    """Budget de retries épuisé (MAX_EMPTY_ANSWER_RETRIES=1) : le graphe abandonne, laisse app/main.py notifier."""
    monkeypatch.setattr(g, "MAX_EMPTY_ANSWER_RETRIES", 1)

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(reasoning_response(["Premier essai."], [])),
        _sse_response(reasoning_response(["Deuxieme essai, encore rien."], [])),
    ]
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Question ?"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.next == ()
    assert snapshot.values["empty_answer_retries"] == 1  # budget consommé, pas de 3e tentative
    assert route.call_count == 2  # exactement 2 appels LLM, pas plus
    assert result["messages"][-1].content == "<think>Deuxieme essai, encore rien.</think>"


@pytest.mark.asyncio
async def test_normal_tool_call_flow_unaffected_by_retry_logic(mock_side_services):
    """Non-régression : un tool_calls structuré normal ne déclenche jamais le chemin de retry."""
    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("mouse_click", "call_1", '{"x": 1, "y": 2}')),
        _sse_response(text_response(["Cliqué", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique"}], "tool_iterations": 0, "approved": None}
    result = await g.agent_graph.ainvoke(state, CONFIG)

    snapshot = await g.agent_graph.aget_state(CONFIG)
    assert snapshot.values.get("empty_answer_retries", 0) == 0
    assert result["messages"][-1].content == "Cliqué."
