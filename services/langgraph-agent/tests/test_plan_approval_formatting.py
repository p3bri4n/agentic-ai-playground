"""
Formatage de l'approbation du plan côté API (Itération 3, Phase 1 « cœur
cognitif » — voir app/main.py:_format_plan_approval_request/
_pending_approval_text). Tests unitaires purs (pas de docker/LLM) sauf pour
la distinction de pause qui nécessite un snapshot factice minimal.
"""

from types import SimpleNamespace


def test_format_plan_approval_request_normal_tier():
    import app.main as main_mod

    plan = [{"description": "Ouvrir la page", "success_criterion": "page chargée", "status": "en_cours"}]
    text = main_mod._format_plan_approval_request(plan, "reversible")

    assert text.startswith("⚠️ Approbation du plan requise (tier : reversible).")
    assert "Plan de la tâche :" in text
    assert "Réponds" in text


def test_format_plan_approval_request_escalation_with_reasons():
    import app.main as main_mod

    plan = [{"description": "X", "success_criterion": "Y", "status": "a_faire"}]
    text = main_mod._format_plan_approval_request(plan, "sensitive", reasons=["motif A", "motif B"])

    assert "rejeté par la validation automatique" in text
    assert "- motif A" in text
    assert "- motif B" in text


def _snapshot(next_nodes, values):
    return SimpleNamespace(next=next_nodes, values=values)


def test_pending_approval_text_none_when_no_pause():
    import app.main as main_mod

    assert main_mod._pending_approval_text(_snapshot((), {})) is None


def test_pending_approval_text_plan_pause():
    import app.main as main_mod

    plan = [{"description": "X", "success_criterion": "Y", "status": "en_cours"}]
    snapshot = _snapshot(("require_plan_approval",), {"plan": plan, "plan_validation_reasons": []})
    text = main_mod._pending_approval_text(snapshot)

    assert text.startswith("⚠️ Approbation du plan requise")


def test_pending_approval_text_tool_pause():
    import app.main as main_mod
    from langchain_core.messages import AIMessage

    ai = AIMessage(content="", tool_calls=[{"id": "1", "name": "browser_navigate", "args": {"url": "http://x"}}])
    snapshot = _snapshot(("require_approval",), {"messages": [ai], "plan": []})
    text = main_mod._pending_approval_text(snapshot)

    assert text.startswith("⚠️ Approbation requise pour")
