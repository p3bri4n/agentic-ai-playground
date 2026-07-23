"""
Résumé du plan dans le message d'approbation (Itération 1, Phase 1 « cœur
cognitif » — voir docs/briefs/phase-1-coeur-cognitif.md,
app/main.py:_format_plan_summary/_format_approval_request). Tests unitaires
purs, pas de docker/LLM : ce module ne fait que du formatage de texte.
"""


def test_format_plan_summary_empty_for_no_plan():
    import app.main as main_mod

    assert main_mod._format_plan_summary(None) == ""
    assert main_mod._format_plan_summary([]) == ""


def test_format_plan_summary_lists_subtasks_with_translated_status():
    import app.main as main_mod

    plan = [
        {"description": "Ouvrir le catalogue", "success_criterion": "page affichée", "status": "fait"},
        {"description": "Lire le prix", "success_criterion": "prix trouvé", "status": "en_cours"},
        {"description": "Répondre", "success_criterion": "réponse envoyée", "status": "a_faire"},
    ]
    summary = main_mod._format_plan_summary(plan)

    assert summary.startswith("Plan de la tâche :")
    assert "1. [fait] Ouvrir le catalogue (critère : page affichée)" in summary
    assert "2. [en cours] Lire le prix (critère : prix trouvé)" in summary
    assert "3. [à faire] Répondre (critère : réponse envoyée)" in summary


def test_format_plan_summary_falls_back_to_raw_status_label():
    import app.main as main_mod

    plan = [{"description": "X", "success_criterion": "Y", "status": "statut_inconnu"}]
    summary = main_mod._format_plan_summary(plan)

    assert "[statut_inconnu] X" in summary


def test_format_approval_request_unchanged_without_plan():
    """Non-régression : plan=None (comportement par défaut, PLANNER_ENABLED
    désactivé) -> texte STRICTEMENT identique à avant l'Itération 1."""
    import app.main as main_mod

    tool_calls = [{"name": "browser_navigate", "args": {"url": "http://example"}}]
    with_none = main_mod._format_approval_request(tool_calls, None)
    without_arg = main_mod._format_approval_request(tool_calls)

    assert with_none == without_arg
    assert "Plan de la tâche" not in with_none
    assert with_none.startswith("⚠️ Approbation requise pour")


def test_format_approval_request_appends_plan_summary_when_present():
    import app.main as main_mod

    tool_calls = [{"name": "browser_navigate", "args": {"url": "http://example"}}]
    plan = [{"description": "Ouvrir la page", "success_criterion": "page chargée", "status": "en_cours"}]
    text = main_mod._format_approval_request(tool_calls, plan)

    assert text.startswith("⚠️ Approbation requise pour")
    assert "Plan de la tâche :" in text
    assert "[en cours] Ouvrir la page (critère : page chargée)" in text
