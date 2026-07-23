"""
Heuristiques programmatiques de validation du plan (Itération 3, Phase 1
« cœur cognitif » — voir docs/briefs/phase-1-coeur-cognitif.md et
app/plan_validation.py). Pures, testées sans docker/LLM/état du graphe.
"""

from app.plan_validation import validate_plan_heuristics


def _subtask(description="A", success_criterion="critère A", tools=None):
    return {"description": description, "success_criterion": success_criterion, "tools": tools or []}


def _valid_plan():
    return [
        _subtask("Ouvrir le catalogue", "page affichée", tools=["browser_navigate"]),
        _subtask("Trouver le prix", "prix trouvé", tools=["browser_extract"]),
    ]


def test_valid_plan_has_no_rejection_reasons():
    reasons = validate_plan_heuristics(
        _valid_plan(), known_tools={"browser_navigate", "browser_extract"}, task_scope_urls=set()
    )
    assert reasons == []


def test_rejects_too_few_subtasks():
    reasons = validate_plan_heuristics([_subtask()], known_tools=set(), task_scope_urls=set())
    assert any("hors bornes" in r for r in reasons)


def test_rejects_too_many_subtasks():
    plan = [_subtask(f"étape {i}", f"critère {i}") for i in range(13)]
    reasons = validate_plan_heuristics(plan, known_tools=set(), task_scope_urls=set())
    assert any("hors bornes" in r for r in reasons)


def test_rejects_duplicate_subtasks():
    plan = [_subtask("A", "B"), _subtask("A", "B"), _subtask("C", "D")]
    reasons = validate_plan_heuristics(plan, known_tools=set(), task_scope_urls=set())
    assert any("dupliquée" in r for r in reasons)


def test_rejects_unknown_tool_reference():
    plan = [_subtask("A", "B", tools=["outil_inexistant"]), _subtask("C", "D")]
    reasons = validate_plan_heuristics(plan, known_tools={"browser_navigate"}, task_scope_urls=set())
    assert any("outil_inexistant" in r for r in reasons)


def test_rejects_out_of_scope_domain():
    plan = [
        _subtask("Va sur http://autre-site.example/page", "trouvé"),
        _subtask("C", "D"),
    ]
    reasons = validate_plan_heuristics(
        plan, known_tools=set(), task_scope_urls={"http://fixture-catalog/catalog/index.html"}
    )
    assert any("autre-site.example" in r for r in reasons)


def test_allows_url_on_same_domain_different_path():
    plan = [
        _subtask("Va sur http://fixture-catalog/catalog/product-1.html", "trouvé"),
        _subtask("C", "D"),
    ]
    reasons = validate_plan_heuristics(
        plan, known_tools=set(), task_scope_urls={"http://fixture-catalog/catalog/index.html"}
    )
    assert reasons == []


def test_no_domain_check_when_task_scope_is_empty():
    """Aucune URL dans le message humain d'origine (tâche non-web ou
    périmètre non déclaré) : pas de faux positif sur une URL de sous-tâche."""
    plan = [_subtask("Va sur http://exemple.com", "trouvé"), _subtask("C", "D")]
    reasons = validate_plan_heuristics(plan, known_tools=set(), task_scope_urls=set())
    assert reasons == []
