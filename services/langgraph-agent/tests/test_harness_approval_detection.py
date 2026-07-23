"""
Détection de pause d'approbation dans le harnais de tâches web
(tests_integration/test_web_tasks.py:_is_approval_pending) — étendue à
l'Itération 3 (pauses de PLAN, pas seulement d'outil, voir
docs/briefs/phase-1-coeur-cognitif.md). Test unitaire pur (pas de
docker/LLM) : sans lui, une régression sur cette détection ne serait
découverte qu'au prix d'une vraie campagne live invalidée.
"""

from tests_integration import test_web_tasks as tw


def test_recognizes_tool_approval_pause():
    assert tw._is_approval_pending("⚠️ Approbation requise pour : `browser_navigate`({'url': 'http://x'}). Réponds...")


def test_recognizes_plan_approval_pause():
    assert tw._is_approval_pending("⚠️ Approbation du plan requise (tier : sensitive).\n\nPlan de la tâche :\n1. ...")


def test_recognizes_plan_escalation_pause():
    assert tw._is_approval_pending(
        "⚠️ Le plan proposé a été rejeté par la validation automatique après plusieurs tentatives — décision humaine requise."
    )


def test_does_not_flag_normal_final_answer():
    assert not tw._is_approval_pending("Le prix est 84.90 €.")


def test_does_not_flag_report_failure_message():
    assert not tw._is_approval_pending(
        "Je n'ai pas pu terminer la tâche avec le budget de tentatives/replanifications disponible.\nÉtat atteint :\n..."
    )


def test_does_not_flag_reject_plan_message():
    assert not tw._is_approval_pending("Plan refusé par l'utilisateur — tâche non exécutée.")
