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
        )
    assert calls == [], "purge/reset ne doivent jamais tourner si le préambule échoue"


def test_run_preflight_purges_and_resets_when_schema_ok():
    calls = []

    preflight.run_preflight(
        purge_downloads=lambda: calls.append("purge"),
        reset_browser_session=lambda: calls.append("reset"),
        fetch_agent_tools=lambda: preflight.EXPECTED_TOOLS,
        fetch_mcp_tools=lambda: preflight.EXPECTED_TOOLS,
    )
    assert calls == ["purge", "reset"]
