"""
Tests unitaires de la politique par tiers (app/approval_policy.py), en
isolation du graphe LangGraph. Les tests d'intégration (routage réel dans
has_tool_calls) sont dans tests/test_graph.py.
"""

import pytest

import app.approval_policy as policy


def test_default_tier_read_tools_are_auto_approved():
    for name in ["screen_shot", "mouse_move", "app_list", "app_running", "run_command", "git_status", "read_file"]:
        assert policy.tool_tier(name) == policy.TIER_READ
        assert policy.is_auto_approved(name)


def test_ocr_tools_are_tier_read():
    """find_text/read_screen (services/ocr-service) : lecture pure, aucun
    effet de bord — auto-approuvés et silencieux comme screen_shot."""
    for name in ["find_text", "read_screen"]:
        assert policy.tool_tier(name) == policy.TIER_READ
        assert policy.is_auto_approved(name)


def test_browser_extract_is_tier_read():
    """Phase 1d-révisée (voir HISTORY.md "correctif extraction") :
    browser_extract est une lecture pure malgré son implémentation interne
    via browser_evaluate (mcp-client, template JS fixe) — le modèle ne
    fournit qu'un texte à chercher, jamais de code. browser_evaluate/
    browser_run_code_unsafe restent eux TIER_SENSITIVE (voir
    NEVER_GRANTABLE_TOOLS)."""
    assert policy.tool_tier("browser_extract") == policy.TIER_READ
    assert policy.is_auto_approved("browser_extract")
    assert policy.tool_tier("browser_evaluate") == policy.TIER_SENSITIVE


def test_default_tier_reversible_tools_are_auto_approved():
    for name in ["mouse_click", "mouse_double_click", "key_press", "clipboard_set", "write_file", "git_commit"]:
        assert policy.tool_tier(name) == policy.TIER_REVERSIBLE
        assert policy.is_auto_approved(name)


def test_unknown_tool_defaults_to_sensitive():
    """Défaut = le tier le plus restrictif, jamais l'inverse."""
    assert policy.tool_tier("some_never_seen_tool") == policy.TIER_SENSITIVE
    assert not policy.is_auto_approved("some_never_seen_tool")


def test_key_type_is_sensitive_by_default():
    """Saisie de texte libre : jamais auto-approuvée sans règle explicite (Phase 4)."""
    assert policy.tool_tier("key_type") == policy.TIER_SENSITIVE


def test_clipboard_get_stays_sensitive_despite_read_like_name():
    """
    Exclusion volontaire (voir README) : peut exfiltrer des données
    sensibles copiées par l'utilisateur, pas moins sensible que
    clipboard_set — donc jamais dans TIER_READ malgré son nom.
    """
    assert policy.tool_tier("clipboard_get") == policy.TIER_SENSITIVE


def test_legacy_auto_approved_tools_env_override_grants_tier_reversible(monkeypatch):
    """AUTO_APPROVED_TOOLS (ancienne variable d'env) reste un override rétrocompatible."""
    monkeypatch.setattr(policy, "AUTO_APPROVED_TOOLS", {"custom_legacy_tool"})
    assert policy.tool_tier("custom_legacy_tool") == policy.TIER_REVERSIBLE


def test_tier_read_override_via_env(monkeypatch):
    monkeypatch.setattr(policy, "TIER_READ_TOOLS", {"only_this_tool"})
    assert policy.tool_tier("only_this_tool") == policy.TIER_READ
    # un outil du défaut d'origine, absent de l'override, n'est plus tier 1
    assert policy.tool_tier("screen_shot") != policy.TIER_READ
