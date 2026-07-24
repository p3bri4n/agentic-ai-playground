"""
Préambule de campagne (Itération 0, docs/briefs/phase-1-coeur-cognitif.md) :
tests_integration/campaign_preflight.py. Ces tests couvrent uniquement la
logique PURE (check_tools_schema) et l'orchestration de run_preflight avec
des callables injectés — jamais de docker exec réel ici, contrairement à
test_web_tasks.py (opt-in RUN_LIVE_AGENT_TESTS=1). Vit dans tests/ (suite
rapide, toujours exécutée) précisément parce que cette logique n'a pas
besoin de la stack live pour être vérifiée.
"""

import pytest

from tests_integration import campaign_preflight as preflight


def test_check_tools_schema_ok_when_synced_and_complete():
    tools = preflight.EXPECTED_TOOLS | {"browser_extract", "browser_snapshot"}
    assert preflight.check_tools_schema(tools, tools) is None


def test_check_tools_schema_flags_desync_between_agent_and_mcp_client():
    agent_tools = preflight.EXPECTED_TOOLS
    mcp_tools = preflight.EXPECTED_TOOLS | {"browser_snapshot"}
    error = preflight.check_tools_schema(agent_tools, mcp_tools)
    assert error is not None
    assert "désynchronisé" in error
    assert "browser_snapshot" in error
    assert "docker compose restart langgraph-agent" in error


def test_check_tools_schema_flags_missing_expected_tool():
    incomplete = preflight.EXPECTED_TOOLS - {"browser_navigate"}
    error = preflight.check_tools_schema(incomplete, incomplete)
    assert error is not None
    assert "browser_navigate" in error


def test_run_preflight_raises_before_any_reset_on_desync():
    calls = []

    with pytest.raises(preflight.PreflightError):
        preflight.run_preflight(
            purge_downloads=lambda: calls.append("purge"),
            reset_browser_session=lambda: calls.append("reset"),
            fetch_agent_tools=lambda: preflight.EXPECTED_TOOLS,
            fetch_mcp_tools=lambda: preflight.EXPECTED_TOOLS | {"nouvel_outil"},
            fetch_llm_ready=lambda: True,
            fetch_tabbyapi_image_ids=lambda: ("sha256:same", "sha256:same"),
        )
    assert calls == [], "purge/reset ne doivent jamais tourner si le préambule échoue"


def test_run_preflight_purges_and_resets_when_schema_ok():
    calls = []

    preflight.run_preflight(
        purge_downloads=lambda: calls.append("purge"),
        reset_browser_session=lambda: calls.append("reset"),
        fetch_agent_tools=lambda: preflight.EXPECTED_TOOLS,
        fetch_mcp_tools=lambda: preflight.EXPECTED_TOOLS,
        fetch_llm_ready=lambda: True,
        fetch_tabbyapi_image_ids=lambda: ("sha256:same", "sha256:same"),
    )
    assert calls == ["purge", "reset"]


class _StopEarly(Exception):
    """Sentinelle : prouve juste que fetch_llm_ready est appelé AVANT le
    schéma, sans jamais attendre le vrai timeout (180s) de wait_for_llm_ready
    pour un fetch_llm_ready qui resterait False indéfiniment."""


def test_run_preflight_checks_llm_ready_before_schema():
    schema_calls = []

    def fetch_llm_ready():
        raise _StopEarly()

    with pytest.raises(_StopEarly):
        preflight.run_preflight(
            purge_downloads=lambda: None,
            reset_browser_session=lambda: None,
            fetch_agent_tools=lambda: schema_calls.append("agent") or preflight.EXPECTED_TOOLS,
            fetch_mcp_tools=lambda: schema_calls.append("mcp") or preflight.EXPECTED_TOOLS,
            fetch_llm_ready=fetch_llm_ready,
        )
    assert schema_calls == [], "le schéma ne doit pas être comparé si le LLM ne répond pas"


# ─────────────────────────────────────────────────────────────────────────
# check_tabbyapi_image_fresh (arbitrage post-1/2-ter, voir HISTORY.md)
# ─────────────────────────────────────────────────────────────────────────


def test_check_tabbyapi_image_fresh_ok_when_ids_match():
    assert preflight.check_tabbyapi_image_fresh(lambda: ("sha256:abc", "sha256:abc")) is None


def test_check_tabbyapi_image_fresh_flags_stale_container():
    error = preflight.check_tabbyapi_image_fresh(lambda: ("sha256:old", "sha256:new"))
    assert error is not None
    assert "sha256:old" in error
    assert "sha256:new" in error
    assert "docker compose up -d --build tabbyapi" in error


def test_run_preflight_checks_image_freshness_before_schema():
    schema_calls = []

    with pytest.raises(preflight.PreflightError, match="image différente"):
        preflight.run_preflight(
            purge_downloads=lambda: None,
            reset_browser_session=lambda: None,
            fetch_agent_tools=lambda: schema_calls.append("agent") or preflight.EXPECTED_TOOLS,
            fetch_mcp_tools=lambda: schema_calls.append("mcp") or preflight.EXPECTED_TOOLS,
            fetch_llm_ready=lambda: True,
            fetch_tabbyapi_image_ids=lambda: ("sha256:old", "sha256:new"),
        )
    assert schema_calls == [], "le schéma ne doit pas être comparé si l'image tabbyapi est périmée"


# ─────────────────────────────────────────────────────────────────────────
# wait_for_llm_ready (horloge/sleep injectés, jamais de vrai délai)
# ─────────────────────────────────────────────────────────────────────────


def test_wait_for_llm_ready_returns_immediately_when_already_ready():
    sleeps = []
    preflight.wait_for_llm_ready(lambda: True, sleep=lambda s: sleeps.append(s), now=lambda: 0.0)
    assert sleeps == []


def test_wait_for_llm_ready_retries_until_success():
    attempts = [False, False, True]
    sleeps = []

    def fetch():
        return attempts.pop(0)

    preflight.wait_for_llm_ready(
        fetch, timeout_seconds=100, interval_seconds=5, sleep=lambda s: sleeps.append(s), now=lambda: 0.0
    )
    assert sleeps == [5, 5]


def test_wait_for_llm_ready_raises_after_timeout():
    clock = iter([0.0, 1.0, 2.0, 200.0])

    with pytest.raises(preflight.PreflightError, match="ne répond pas"):
        preflight.wait_for_llm_ready(
            lambda: False, timeout_seconds=100, interval_seconds=5, sleep=lambda s: None, now=lambda: next(clock)
        )
