"""
Conscience temporelle (PLAN.md Phase 1, point 7 — amendement dédié,
implémenté ici après diagnostic T11, voir HISTORY.md) : injection de date
(granularité JOUR, jamais l'heure — préservation du cache de préfixe
ExLlamaV3) + directive de péremption (le modèle ne doit pas répondre de
mémoire sur des faits volatils sans vérifier via le web).
"""

import json
from datetime import datetime

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import text_response


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


CONFIG = {"configurable": {"thread_id": "test-thread-temporal"}}


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


def test_date_directive_format_and_day_granularity(monkeypatch):
    """Format exact "Date actuelle : {jour} {date} ({timezone})", granularité
    JOUR uniquement — jamais l'heure/minute (préservation du cache de
    préfixe, voir docstring du module)."""
    import app.graph as g

    directive = g._date_directive()
    assert directive.startswith("\nDate actuelle : ")
    assert directive.endswith(f"({g._AGENT_TIMEZONE}).")
    # Aucune heure/minute (ex. "14:32") entre le label et la timezone.
    body = directive.split("Date actuelle : ", 1)[1].split("(")[0]
    assert ":" not in body
    # Le jour de la semaine français et l'année courante apparaissent bien
    now = datetime.now()
    assert g._WEEKDAYS_FR[now.weekday()] in directive
    assert str(now.year) in directive


def test_date_directive_stable_within_the_same_day():
    """Deux appels le même jour produisent EXACTEMENT le même texte — la
    valeur ne doit varier qu'une fois par jour, pas à chaque appel/tour
    (voir chasse au cache=0, HISTORY.md)."""
    import app.graph as g

    assert g._date_directive() == g._date_directive()


def test_peremption_directive_mentions_verification_and_stable_facts():
    import app.graph as g

    assert "VÉRIFIE" in g.PEREMPTION_DIRECTIVE
    assert "faits stables" in g.PEREMPTION_DIRECTIVE


def test_peremption_directive_warns_against_biased_search_query():
    """Biais trouvé APRÈS la 1re version de cette directive (voir
    HISTORY.md, sonde T11) : le modèle décidait bien de vérifier, mais
    interrogeait ensuite browser_extract avec sa propre valeur supposée
    ("Python 3.13") au lieu d'un terme neutre — la vérification devient
    inutile si la requête est déjà biaisée par la réponse supposée."""
    import app.graph as g

    assert "requête" in g.PEREMPTION_DIRECTIVE
    assert "terme neutre" in g.PEREMPTION_DIRECTIVE


@pytest.mark.asyncio
async def test_call_llm_system_message_includes_temporal_directives(mock_side_services):
    """Vérifie le câblage bout en bout : le message système envoyé au LLM
    contient bien la directive de péremption ET la date du jour, en plus
    des directives statiques déjà en place."""
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [_sse_response(text_response(["OK"]))]
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Salut"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    sent_body = json.loads(route.calls.last.request.content.decode())
    system_content = sent_body["messages"][0]["content"]
    assert g.PEREMPTION_DIRECTIVE in system_content
    assert g._date_directive() in system_content
    assert g.GROUNDING_DIRECTIVE in system_content
