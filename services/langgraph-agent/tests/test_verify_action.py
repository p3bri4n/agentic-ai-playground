"""
Vérification post-action (Itération 2, révisée Itération 4 — correctif
latence 1/2 — puis correctifs latence 1/2-bis et 1/2-ter, Phase 1 « cœur
cognitif » — voir docs/briefs/phase-1-coeur-cognitif.md et
app/graph.py:verify_action/_verification_directive/_parse_constat/
_inject_constat_param). Plus d'appel LLM séparé : le verdict vit dans le
paramètre constat_precedent d'un tool_call — soit celui de l'ACTION
réelle du tour (schéma augmenté par _inject_constat_param, cas normal,
FUSIONNÉ en un seul appel), soit celui de report_and_act (outil de repli,
UNIQUEMENT quand le tour ne comporte aucune action réelle — réponse en
texte pur).

Historique des deux versions précédentes, pour situer le "pourquoi" :
- le marqueur texte [CONSTAT: ATTEINT|ECHEC] (trop fragile, le modèle
  l'omettait parfois) a été remplacé par un tool call SÉPARÉ obligatoire
  (report_and_act) — correctif 1/2-bis ;
- mesuré en campagne réelle, ce tool call séparé n'était en fait respecté
  que sur ~9% des tours (le modèle ne coordonnait pas deux tool_calls dans
  le même tour) — d'où la FUSION de ce module (1/2-ter) : constat_precedent
  voyage désormais comme paramètre de l'outil d'ACTION lui-même, plus rien
  à coordonner. report_and_act ne reste que pour le cas résiduel sans
  action réelle.

Dégradation INVERSÉE (depuis 1/2-bis) : constat absent/mal formé ->
"sans_objet" (NI succès NI échec, budget inchangé) + incrément du compteur
cumulatif constats_inexploitables, plutôt que facturé comme un échec de
sous-tâche.

Nouveau juge permanent (1/2-ter) : verify_action journalise désormais
TOUJOURS une entrée d'audit role="verification" (exploitable ou non) —
compagnon de constats_inexploitables pour mesurer le taux de COUVERTURE
(constats exploités / opportunités), pas seulement l'ambiguïté.

Le déclenchement du hint spécifique (critère à juger) repose sur
AgentState.pending_verification (posé par _execute_tool_calls, consommé par
verify_action) plutôt que sur une recherche dans l'historique des messages
— voir test_pending_verification_prevents_stale_constat_after_replan pour
la raison. VERIFICATION_ENABLED est désactivé par défaut : chaque test qui
exerce le mécanisme l'active explicitement via monkeypatch, même patron que
PLANNER_ENABLED (tests/test_plan_task.py).
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class _FakeConfig(dict):
    """config minimal attendu par verify_action (thread_id, voir audit_log)."""

    def __init__(self, thread_id="thread-1"):
        super().__init__(configurable={"thread_id": thread_id})


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


def _action_call_with_constat(verdict="atteint", tool_name="mouse_click", call_id="call_2", extra_args=None):
    """Cas normal (fusionné) : constat_precedent dans les arguments de
    l'outil d'ACTION lui-même — voir _inject_constat_param."""
    args = dict(extra_args or {})
    args["constat_precedent"] = verdict
    return {"id": call_id, "name": tool_name, "args": args}


def _report_and_act_call(verdict="atteint", call_id="report_1"):
    """Cas de repli : aucune action réelle ce tour-ci (réponse en texte pur)."""
    return {"id": call_id, "name": "report_and_act", "args": {"constat_precedent": verdict}}


def _with_constat(prior_messages, verdict="atteint", trailing=""):
    """Ajoute la réponse de call_llm (avec une action réelle portant le constat) en fin d'historique."""
    return prior_messages + [AIMessage(content=trailing, tool_calls=[_action_call_with_constat(verdict)])]


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _inject_constat_param (pure)
# ─────────────────────────────────────────────────────────────────────────


def test_inject_constat_param_adds_required_property():
    import app.graph as g

    tool = {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navigue vers une URL.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        },
    }
    wrapped = g._inject_constat_param(tool)
    params = wrapped["function"]["parameters"]
    assert "constat_precedent" in params["properties"]
    assert params["properties"]["constat_precedent"]["enum"] == ["atteint", "non_atteint", "sans_objet"]
    assert "constat_precedent" in params["required"]
    assert "url" in params["required"]  # les champs d'origine restent inchangés


def test_inject_constat_param_does_not_mutate_original():
    import app.graph as g

    tool = {
        "type": "function",
        "function": {"name": "t", "description": "d", "parameters": {"type": "object", "properties": {}}},
    }
    wrapped = g._inject_constat_param(tool)
    assert "constat_precedent" not in tool["function"]["parameters"]["properties"]
    assert "constat_precedent" in wrapped["function"]["parameters"]["properties"]


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _parse_constat (pure)
# ─────────────────────────────────────────────────────────────────────────


def test_parse_constat_from_real_action_call():
    import app.graph as g

    tool_calls = [_action_call_with_constat("atteint")]
    assert g._parse_constat(tool_calls) == ("atteint", True)


def test_parse_constat_detects_non_atteint():
    import app.graph as g

    assert g._parse_constat([_action_call_with_constat("non_atteint")]) == ("non_atteint", True)


def test_parse_constat_detects_sans_objet():
    import app.graph as g

    assert g._parse_constat([_action_call_with_constat("sans_objet")]) == ("sans_objet", True)


def test_parse_constat_prefers_report_and_act_when_present():
    """report_and_act (texte pur, pas d'action réelle) est reconnu en priorité."""
    import app.graph as g

    tool_calls = [_report_and_act_call("atteint")]
    assert g._parse_constat(tool_calls) == ("atteint", True)


def test_parse_constat_none_when_absent_from_all_tool_calls():
    import app.graph as g

    tool_calls = [{"id": "c1", "name": "browser_navigate", "args": {"url": "https://x"}}]
    assert g._parse_constat(tool_calls) == (None, False)


def test_parse_constat_none_on_empty_tool_calls():
    import app.graph as g

    assert g._parse_constat([]) == (None, False)
    assert g._parse_constat(None) == (None, False)


def test_parse_constat_malformed_verdict_is_inexploitable():
    import app.graph as g

    tool_calls = [{"id": "c1", "name": "mouse_click", "args": {"constat_precedent": "peut-etre"}}]
    assert g._parse_constat(tool_calls) == (None, False)


def test_parse_constat_report_and_act_missing_field_is_inexploitable():
    import app.graph as g

    tool_calls = [{"id": "c1", "name": "report_and_act", "args": {}}]
    assert g._parse_constat(tool_calls) == (None, False)


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : _verification_directive (injection dans call_llm)
# ─────────────────────────────────────────────────────────────────────────


def test_verification_directive_empty_when_disabled(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", False)
    state = {"messages": _turn_messages(), "plan": [_subtask()], "pending_verification": True}
    assert g._verification_directive(state) == ""


def test_verification_directive_base_reminder_always_present_when_enabled(monkeypatch):
    """Correctif 1/2-ter : le rappel de base (constat_precedent requis sur
    CHAQUE outil) est injecté dès que VERIFICATION_ENABLED est actif — plus
    seulement quand pending_verification est vrai, puisque le schéma le
    requiert dès le tout premier outil de la tâche."""
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    state = {"messages": [HumanMessage(content="salut")], "plan": [], "pending_verification": False}
    directive = g._verification_directive(state)
    assert "constat_precedent" in directive
    assert directive != ""


def test_verification_directive_includes_active_criterion(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    plan = [_subtask(success_criterion="le prix est visible")]
    state = {"messages": _turn_messages(), "plan": plan, "pending_verification": True}
    directive = g._verification_directive(state)
    assert "le prix est visible" in directive
    assert "constat_precedent" in directive


def test_verification_directive_omits_criterion_without_pending_verification(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    plan = [_subtask(success_criterion="le prix est visible")]
    state = {"messages": [HumanMessage(content="salut")], "plan": plan, "pending_verification": False}
    directive = g._verification_directive(state)
    assert "le prix est visible" not in directive


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : verify_action (analyse pure, AUCUN appel LLM)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_action_noop_when_disabled(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", False)
    state = {"messages": _with_constat(_turn_messages()), "plan": [_subtask()], "pending_verification": True}
    result = await g.verify_action(state, _FakeConfig())
    assert result == {"messages": []}


@pytest.mark.asyncio
async def test_verify_action_noop_without_active_subtask(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    state = {"messages": _with_constat(_turn_messages()), "plan": [], "pending_verification": True}
    result = await g.verify_action(state, _FakeConfig())
    assert result == {"messages": [], "pending_verification": False}


@pytest.mark.asyncio
async def test_verify_action_noop_without_pending_verification(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    state = {
        "messages": [HumanMessage(content="salut"), AIMessage(content="bonjour")],
        "plan": [_subtask()],
        "pending_verification": False,
    }
    result = await g.verify_action(state, _FakeConfig())
    assert result == {"messages": []}


@pytest.mark.asyncio
async def test_pending_verification_prevents_stale_constat_after_replan(monkeypatch):
    """
    Cas limite trouvé en concevant le correctif (voir docstring du module) :
    un tour de replanification ne doit JAMAIS déclencher de constat sur le
    résultat d'outil de l'ANCIENNE sous-tâche (déjà traitée) contre le
    critère de la NOUVELLE sous-tâche. `pending_verification` (remis à
    False par verify_action, jamais remis à True par
    replan_task/validate_plan) évite ce contresens par construction.
    """
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    messages = _turn_messages() + [
        AIMessage(content="", tool_calls=[_action_call_with_constat("non_atteint")]),
        AIMessage(content="(ne devrait jamais être lu ici)", tool_calls=[_action_call_with_constat("atteint")]),
    ]
    plan = [_subtask(description="Nouvelle approche", status="en_cours", attempts=0)]
    state = {"messages": messages, "plan": plan, "pending_verification": False}
    result = await g.verify_action(state, _FakeConfig())
    assert result == {"messages": []}


@pytest.mark.asyncio
async def test_verify_action_atteint_advances_plan(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    plan = [_subtask(status="en_cours"), _subtask(description="Lire le prix", status="a_faire")]
    state = {"messages": _with_constat(_turn_messages(), "atteint"), "plan": plan, "pending_verification": True}
    result = await g.verify_action(state, _FakeConfig())

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "fait"
    assert new_plan[1]["status"] == "en_cours"
    assert result["pending_verification"] is False


@pytest.mark.asyncio
async def test_verify_action_non_atteint_under_budget_stays_en_cours(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    monkeypatch.setattr(g, "SUBTASK_ATTEMPT_BUDGET", 3)
    plan = [_subtask(status="en_cours", attempts=0)]
    state = {"messages": _with_constat(_turn_messages(), "non_atteint"), "plan": plan, "pending_verification": True}
    result = await g.verify_action(state, _FakeConfig())

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "en_cours"
    assert new_plan[0]["attempts"] == 1
    assert result["pending_verification"] is False


@pytest.mark.asyncio
async def test_verify_action_non_atteint_exhausts_budget(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    monkeypatch.setattr(g, "SUBTASK_ATTEMPT_BUDGET", 3)
    plan = [_subtask(status="en_cours", attempts=2)]
    state = {"messages": _with_constat(_turn_messages(), "non_atteint"), "plan": plan, "pending_verification": True}
    result = await g.verify_action(state, _FakeConfig())

    new_plan = result["plan"]
    assert new_plan[0]["status"] == "echoue"
    assert new_plan[0]["attempts"] == 3


@pytest.mark.asyncio
async def test_verify_action_sans_objet_does_not_mutate_plan(monkeypatch):
    """Un "sans_objet" légitimement déclaré par le modèle est exploitable
    (pas de compteur incrémenté) mais ne mute pas le plan."""
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    plan = [_subtask(status="en_cours", attempts=1)]
    state = {
        "messages": _with_constat(_turn_messages(), "sans_objet"),
        "plan": plan,
        "pending_verification": True,
        "constats_inexploitables": 0,
    }
    result = await g.verify_action(state, _FakeConfig())

    assert "plan" not in result
    assert result["pending_verification"] is False
    assert "constats_inexploitables" not in result


@pytest.mark.asyncio
async def test_verify_action_missing_constat_is_inexploitable(monkeypatch):
    """Dégradation INVERSÉE (correctif 1/2-bis) : constat_precedent
    absent/mal formé ne facture RIEN à la sous-tâche (ni succès ni échec,
    budget inchangé) mais incrémente constats_inexploitables — l'ambiguïté
    se mesure, elle ne se facture plus comme un échec (voir HISTORY.md,
    régression 18/33 de la version marqueur-texte)."""
    import app.graph as g

    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    monkeypatch.setattr(g, "SUBTASK_ATTEMPT_BUDGET", 3)
    plan = [_subtask(status="en_cours", attempts=0)]
    messages = _turn_messages() + [
        AIMessage(content="", tool_calls=[{"id": "c2", "name": "mouse_click", "args": {"x": 1, "y": 1}}])
    ]
    state = {"messages": messages, "plan": plan, "pending_verification": True, "constats_inexploitables": 0}
    result = await g.verify_action(state, _FakeConfig())

    assert "plan" not in result
    assert result["pending_verification"] is False
    assert result["constats_inexploitables"] == 1


@pytest.mark.asyncio
async def test_verify_action_logs_verification_audit_entry_for_coverage(monkeypatch, tmp_path):
    """Nouveau juge permanent (correctif 1/2-ter) : verify_action journalise
    TOUJOURS une entrée role="verification" (exploitable ou non) — permet de
    calculer un taux de couverture (constats exploités / opportunités),
    distinct de constats_inexploitables qui ne mesure que l'ambiguïté."""
    import json

    import app.graph as g
    import app.audit_log as audit_log

    monkeypatch.setattr(audit_log, "AUDIT_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(g, "VERIFICATION_ENABLED", True)
    plan = [_subtask(status="en_cours")]

    state_ok = {"messages": _with_constat(_turn_messages(), "atteint"), "plan": plan, "pending_verification": True}
    await g.verify_action(state_ok, _FakeConfig("thread-cov"))

    messages_missing = _turn_messages() + [
        AIMessage(content="", tool_calls=[{"id": "c2", "name": "mouse_click", "args": {}}])
    ]
    state_missing = {"messages": messages_missing, "plan": plan, "pending_verification": True}
    await g.verify_action(state_missing, _FakeConfig("thread-cov"))

    entries = audit_log.read_entries("thread-cov")
    verifs = [e for e in entries if e.get("kind") == "message" and e.get("role") == "verification"]
    assert len(verifs) == 2
    assert verifs[0]["content"]["exploitable"] is True
    assert verifs[1]["content"]["exploitable"] is False


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
        state = {"messages": _with_constat(_turn_messages(), "atteint"), "plan": plan, "pending_verification": True}
        result = await g.verify_action(state, _FakeConfig())

    assert result["plan"][0]["status"] == "fait"
