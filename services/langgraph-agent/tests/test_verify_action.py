"""
Vérification post-action (Itération 2, révisée Itération 4 — correctif
latence 1/2, Phase 1 « cœur cognitif » — voir
docs/briefs/phase-1-coeur-cognitif.md et app/graph.py:verify_action/
_verification_directive/_parse_verification_marker). Plus d'appel LLM
séparé : le verdict vit dans le marqueur [CONSTAT: ATTEINT|ECHEC] que
call_llm injecte comme consigne et que verify_action se contente de parser.
Le déclenchement (consigne injectée / marqueur attendu) repose sur
AgentState.pending_verification (posé par _execute_tool_calls, consommé par
verify_action) plutôt que sur une recherche dans l'historique des messages
— voir test_pending_verification_prevents_stale_constat_after_replan pour
la raison (un tour de replanification n'exécute aucun outil, il ne doit
jamais déclencher un constat sur un résultat d'outil périmé).
VERIFICATION_ENABLED est désactivé par défaut : chaque test qui exerce le
mécanisme l'active explicitement via monkeypatch, même patron que
PLANNER_ENABLED (tests/test_plan_task.py).
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _subtask(description="Ouvrir le catalogue", success_criterion="page affichée", status="en_cours", attempts=0):
    return {
        "description": description,
        "success_criterion": success_criterion,
        "status": status,
        "attempts": attempts,
        "result": None,
    }


def _turn_messages(tool_call_id="call_1", tool_name="browser_navigate", args=None, result_text="page ouverte"):
    """Le tour PRÉCÉDENT (action + résultat), avant la réponse de call_llm à constater."""
    return [
        HumanMessage(content="Ouvre le catalogue"),
        AIMessage(content="", tool_calls=[{"id": tool_call_id, "name": tool_name, "args": args or {}}]),
        ToolMessage(content="page ouverte" if result_text is None else result_text, tool_call_id=tool_call_id),
    ]


def _with_constat(prior_messages, constat="ATTEINT", trailing=""):
    """Ajoute la réponse de call_llm (celle qui porte le marqueur) en fin d'historique."""
    return prior_messages + [AIMessage(content=f"[CONSTAT: {constat}] {trailing}".strip())]


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _parse_verification_marker (pure)
# ─────────────────────────────────────────────────────────────────────────


def test_parse_verification_marker_detects_atteint():
    import app.graph as g

    assert g._parse_verification_marker("[CONSTAT: ATTEINT] Je vois le produit.") is True


def test_parse_verification_marker_detects_echec():
    import app.graph as g

    assert g._parse_verification_marker("[CONSTAT: ECHEC] Rien trouvé.") is False


def test_parse_verification_marker_case_insensitive():
    import app.graph as g

    assert g._parse_verification_marker("[constat: atteint] ok") is True


def test_parse_verification_marker_ignores_marker_inside_think_block():
    import app.graph as g

    assert g._parse_verification_marker("<think>[CONSTAT: ATTEINT] brouillon</think>Réponse.") is None


def test_parse_verification_marker_none_when_absent():
    import app.graph as g

    assert g._parse_verification_marker("Je continue sans marqueur.") is None


def test_parse_verification_marker_none_on_empty_content():
    import app.graph as g

    assert g._parse_verification_marker("") is None


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _verification_directive (injection dans call_llm)
# ─────────────────────────────────────────────────────────────────────────


def test_verification_directive_empty_when_disabled(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", False)
    state = {"messages": _turn_messages(), "plan": [_subtask()], "pending_verification": True}
    assert g._verification_directive(state) == ""


def test_verification_directive_empty_without_active_subtask(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    state = {"messages": _turn_messages(), "plan": [], "pending_verification": True}
    assert g._verification_directive(state) == ""


def test_verification_directive_empty_without_pending_verification(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    # Aucune action exécutée depuis le dernier constat (ex. tout premier
    # tour, ou tour de replanification) : rien à constater.
    state = {"messages": [HumanMessage(content="salut")], "plan": [_subtask()], "pending_verification": False}
    assert g._verification_directive(state) == ""


def test_verification_directive_includes_active_criterion(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    plan = [_subtask(success_criterion="le prix est visible")]
    state = {"messages": _turn_messages(), "plan": plan, "pending_verification": True}
    directive = g._verification_directive(state)
    assert "le prix est visible" in directive
    assert "[CONSTAT: ATTEINT]" in directive
    assert "[CONSTAT: ECHEC]" in directive


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : verify_action (analyse pure, AUCUN appel LLM)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_action_noop_when_disabled(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", False)
    state = {"messages": _with_constat(_turn_messages()), "plan": [_subtask()], "pending_verification": True}
    result = await g.verify_action(state)
    assert result == {"messages": []}


@pytest.mark.asyncio
async def test_verify_action_noop_without_active_subtask(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    state = {"messages": _with_constat(_turn_messages()), "plan": [], "pending_verification": True}
    result = await g.verify_action(state)
    assert result == {"messages": [], "pending_verification": False}


@pytest.mark.asyncio
async def test_verify_action_noop_without_pending_verification(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    state = {
        "messages": [HumanMessage(content="salut"), AIMessage(content="[CONSTAT: ATTEINT] bonjour")],
        "plan": [_subtask()],
        "pending_verification": False,
    }
    result = await g.verify_action(state)
    assert result == {"messages": []}


@pytest.mark.asyncio
async def test_pending_verification_prevents_stale_constat_after_replan(monkeypatch):
    """
    Cas limite trouvé en concevant le correctif (voir docstring du module) :
    un tour de replanification ne doit JAMAIS déclencher de constat sur le
    résultat d'outil de l'ANCIENNE sous-tâche (déjà traitée) contre le
    critère de la NOUVELLE sous-tâche. `_previous_turn_tool_calls`
    (recherche dans l'historique) confondrait les deux si le tour
    intermédiaire était resté sans tool_calls ; `pending_verification`
    (remis à False par verify_action, jamais remis à True par
    replan_task/validate_plan) évite ce contresens par construction.
    """
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    # Historique réaliste : ancienne action + constat ECHEC (déjà consommé,
    # pending_verification serait False à ce stade) + nouveau plan +
    # nouvelle réponse SANS action exécutée entre-temps.
    messages = _turn_messages() + [
        AIMessage(content="[CONSTAT: ECHEC] rien trouvé."),
        AIMessage(content="[CONSTAT: ATTEINT] (ne devrait jamais être lu ici)"),
    ]
    plan = [_subtask(description="Nouvelle approche", status="en_cours", attempts=0)]
    state = {"messages": messages, "plan": plan, "pending_verification": False}
    result = await g.verify_action(state)
    assert result == {"messages": []}
    assert g._verification_directive(state) == ""


@pytest.mark.asyncio
async def test_verify_action_positive_marker_advances_plan(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    plan = [_subtask(status="en_cours"), _subtask(description="Lire le prix", status="a_faire")]
    state = {"messages": _with_constat(_turn_messages(), "ATTEINT"), "plan": plan, "pending_verification": True}
    result = await g.verify_action(state)

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "fait"
    assert new_plan[1]["status"] == "en_cours"
    assert result["pending_verification"] is False


@pytest.mark.asyncio
async def test_verify_action_negative_marker_under_budget_stays_en_cours(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    monkeypatch.setattr(g, "SUBTASK_ATTEMPT_BUDGET", 3)
    plan = [_subtask(status="en_cours", attempts=0)]
    state = {"messages": _with_constat(_turn_messages(), "ECHEC"), "plan": plan, "pending_verification": True}
    result = await g.verify_action(state)

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "en_cours"
    assert new_plan[0]["attempts"] == 1
    assert result["pending_verification"] is False


@pytest.mark.asyncio
async def test_verify_action_negative_marker_exhausts_budget(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    monkeypatch.setattr(g, "SUBTASK_ATTEMPT_BUDGET", 3)
    plan = [_subtask(status="en_cours", attempts=2)]
    state = {"messages": _with_constat(_turn_messages(), "ECHEC"), "plan": plan, "pending_verification": True}
    result = await g.verify_action(state)

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "echoue"
    assert new_plan[0]["attempts"] == 3


@pytest.mark.asyncio
async def test_verify_action_missing_marker_treated_as_non_atteint(monkeypatch):
    """Dégradation conservative (même philosophie que l'ancien mécanisme
    LLM) : un marqueur absent/mal formé ne doit jamais accorder un succès
    implicite — le modèle a simplement oublié la consigne."""
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    monkeypatch.setattr(g, "SUBTASK_ATTEMPT_BUDGET", 3)
    plan = [_subtask(status="en_cours", attempts=0)]
    messages = _turn_messages() + [AIMessage(content="Je continue sans le marqueur demandé.")]
    state = {"messages": messages, "plan": plan, "pending_verification": True}
    result = await g.verify_action(state)

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "en_cours"
    assert new_plan[0]["attempts"] == 1


@pytest.mark.asyncio
async def test_verify_action_never_calls_llm(monkeypatch):
    """Le cœur du correctif latence : aucun appel HTTP vers le backend LLM,
    quel que soit le verdict — respx sans aucune route mockée doit rester
    silencieux (AllMockedAssertionError sinon)."""
    import respx

    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    plan = [_subtask(status="en_cours")]
    with respx.mock(assert_all_called=False, assert_all_mocked=True):
        state = {"messages": _with_constat(_turn_messages(), "ATTEINT"), "plan": plan, "pending_verification": True}
        result = await g.verify_action(state)

    assert result["plan"][0]["status"] == "fait"
