"""
Harnais de tâches web (Phase 0 du plan d'autonomie, voir PLAN.md et
BENCHMARK0.md) : rejoue 11 tâches web multi-étapes contre l'agent RÉEL
(conteneurs Docker, LLM réel, navigateur Playwright réel), avec un critère de
succès PROGRAMMATIQUE par tâche — jamais un jugement qualitatif.

Comme test_tool_calling_baseline.py/test_semantic_drift.py : parle aux vrais
conteneurs via `docker exec`, lent et non déterministe par nature. Ignoré par
défaut ; opt-in explicite :

    RUN_LIVE_AGENT_TESTS=1 python -m pytest tests_integration/test_web_tasks.py -v

Prérequis :
  - `docker compose up -d` (stack normale) ET
    `docker compose --profile test-fixtures up -d fixture-catalog fixture-docs
    fixture-hr-app` (voir docker-compose.yml).
  - Les outils `browser_*` sont TIER_SENSITIVE par défaut (voir
    approval_policy.py — la Phase 3 du plan doit changer ça, pas encore
    faite) : CE harnais joue donc lui-même le rôle de l'humain via
    POST /approve (avec grant_session=True) pour dérouler une tâche sans
    intervention manuelle, et compte ces approbations comme métrique
    ("interventions d'approbation" — voir BENCHMARK0.md).

Recalibrages faits en construisant ce harnais (voir HISTORY.md pour le détail) :
  - T1 : catalogue réduit de 120/12 pages à 30/3 pages — la recherche
    exhaustive du pire cas (référence jamais visible dans la liste)
    dépassait largement MAX_TOOL_ITERATIONS avec l'échelle initiale.
  - T5 : assertion sur la valeur finale (masse salariale exacte dans la
    réponse), pas sur un fichier CSV présent dans un répertoire — reste
    vrai même depuis le volume de téléchargement dédié (Phase 1d-révisée,
    voir docker-compose.yml `agent-downloads` et HISTORY.md) : l'agent doit
    télécharger PUIS lire via l'outil filesystem sous `/downloads/`
    (`fetch()`/`browser_evaluate` comme canal de transfert de fichier a été
    explicitement écarté, voir HISTORY.md — ce n'est pas la primitive d'un
    outil de lecture). `_purge_downloads_volume()` (voir plus bas) vide ce
    volume avant chaque répétition pour qu'un run ne "réussisse" jamais en
    lisant l'artefact d'un run précédent.

Limite connue assumée de la métrique "tokens consommés" (BENCHMARK0.md) :
non mesurée par ce harnais — `/v1/chat/completions` ne renvoie pas de champ
`usage` (vérifié dans app/main.py), et l'instrumenter proprement dépasse le
périmètre de cette Phase 0.

Constat n°1 du point zéro (voir smoke tests, HISTORY.md) : les deux premiers
essais à blanc de ce harnais (T1, T7) ont échoué en butant sur
MAX_TOOL_ITERATIONS, dans les deux cas après une navigation vers une URL
FABRIQUÉE par le modèle (`page-4.html` — le catalogue n'a que 3 pages —
puis `/catalog/search?q=ZZ-9999` — aucune recherche n'existe sur ce
fixture) plutôt que suivie depuis un lien réellement observé dans le DOM.
Deux sous-causes distinguées ci-dessous pour ne pas confondre les deux :

  - "boucle_fabrication" : au moins une navigation vers une URL absente du
    site réel pendant le run (voir `KNOWN_URLS_BY_TASK`/
    `_classify_boucle_subcause`) — le modèle a inventé un chemin plausible
    plutôt que de suivre un lien observé.
  - "boucle_budget" : le modèle progressait sur des URL réelles mais a
    manqué d'itérations.

Limite de cette sous-classification : elle vérifie l'appartenance de chaque
URL naviguée à l'ensemble des URL RÉELLEMENT servies par le fixture (calculé
depuis les générateurs, vérité terrain déjà connue) — PAS une reconstruction
exacte du DOM/des snapshots vus par le modèle tour par tour (les résultats
des tool_calls ne sont pas journalisés, seuls le nom et les arguments le
sont). Un faux négatif serait donc une navigation vers une URL qui EXISTE
sur le site mais que le modèle n'a jamais réellement vue dans un snapshot
(deviné juste). Pas de sous-classification pour les tâches sur sites réels
(T8-T10) : aucun sitemap de référence disponible pour ces cibles.
"""
import ast
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests_integration import campaign_preflight

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AGENT_TESTS") != "1",
    reason="test d'intégration live (agent web réel) : opt-in via RUN_LIVE_AGENT_TESTS=1, "
    "nécessite docker compose up + profil test-fixtures",
)

AGENT_CONTAINER = os.environ.get("LANGGRAPH_AGENT_CONTAINER", "langgraph-agent")
MCP_CLIENT_CONTAINER = os.environ.get("MCP_CLIENT_CONTAINER", "mcp-client")
N_REPETITIONS = int(os.environ.get("WEB_TASKS_REPETITIONS", "3"))
MAX_APPROVAL_ROUNDS = int(os.environ.get("WEB_TASKS_MAX_APPROVAL_ROUNDS", "40"))
CHAT_TIMEOUT_SECONDS = int(os.environ.get("WEB_TASKS_CHAT_TIMEOUT", "240"))
# Mode smoke (outillage de campagne, voir HISTORY.md et run-campaign.sh) :
# sous-ensemble de tâches (préfixes séparés par virgule, ex. "T1,T7,T11" —
# matché en début de task_id, pas de nom exact requis) pour ITÉRER
# rapidement sur un correctif, avec le MÊME préambule/juges/génération de
# rapport que la campagne complète (_run_campaign/_write_report
# inchangés) — jamais une suite parallèle à maintenir séparément.
# Protocole : smoke pour développer/vérifier vite, campagne complète
# (WEB_TASKS_SMOKE_TASKS non défini, 3 répétitions) réservée aux
# checkpoints qui comptent pour un score de référence — un smoke n'a pas
# la significativité statistique (n réduit) pour arbitrer un seuil de
# passage/régression.
SMOKE_TASK_PREFIXES = [
    p.strip() for p in os.environ.get("WEB_TASKS_SMOKE_TASKS", "").split(",") if p.strip()
]

FIXTURES_DIR = Path(__file__).parent / "fixtures"
for _sub in ("catalog", "docs", "hr-app"):
    sys.path.insert(0, str(FIXTURES_DIR / _sub))
import generate_catalog  # noqa: E402
import generate_docs  # noqa: E402
import hr_data  # noqa: E402

CATALOG_URL = "http://fixture-catalog/catalog"
DOCS_URL = "http://fixture-docs/docs"
HR_APP_URL = "http://fixture-hr-app:5000"

WORKSPACE_HOST_PATH = Path(
    os.environ.get("WORKSPACE_HOST_PATH", Path(__file__).parents[3] / "workspace")
)
HR_APP_DATA_FILE = WORKSPACE_HOST_PATH / "hr-app-data" / "leave_submissions.json"

REPORT_PATH = Path(os.environ.get("WEB_TASKS_REPORT_PATH", Path(__file__).parent / "TASKS-BASELINE.md"))
CAMPAIGN_LABEL = os.environ.get("WEB_TASKS_CAMPAIGN_LABEL", "Campagne A (budget par défaut)")
# Outillage de campagne (run-campaign.sh) : durée médiane courante par
# tâche, mise à jour à la fin de CHAQUE campagne (complète ou smoke) —
# permet d'estimer la durée d'un prochain lancement (tâches × répétitions ×
# médiane connue) AVANT de le lancer, pour choisir smoke ou complète en
# connaissance de cause. Un seul fichier partagé, volontairement : la
# dernière mesure connue par tâche est la meilleure estimation disponible,
# qu'elle vienne d'un smoke ou d'une campagne complète.
DURATION_STATS_PATH = Path(__file__).parent / "CAMPAIGN_DURATION_STATS.json"

# Textes exacts émis côté serveur (voir app/main.py) — même convention que
# test_tool_calling_baseline.py.
_APPROVAL_PREFIX = "⚠️ Approbation requise pour"
# Pipeline de validation du plan (Itération 3, Phase 1 « cœur cognitif » —
# voir docs/briefs/phase-1-coeur-cognitif.md et app/main.py:
# _format_plan_approval_request) : DEUX pauses supplémentaires possibles,
# au niveau du PLAN plutôt que d'un tool_call — approbation normale par
# tier, ou escalade humaine après échec de la validation automatique. Sans
# les reconnaître, run_task() traiterait ces messages comme une réponse
# FINALE (ils ne commencent pas par _APPROVAL_PREFIX), invalidant toute
# campagne dès que PLAN_VALIDATION_ENABLED est actif sans qu'aucune erreur
# ne le signale sur le coup.
_PLAN_APPROVAL_PREFIX = "⚠️ Approbation du plan requise"
_PLAN_ESCALATION_PREFIX = "⚠️ Le plan proposé a été rejeté par la validation automatique"
_ITERATION_LIMIT_PREFIX = "⚠️ Limite d'itérations d'outils atteinte"
_EMPTY_NOTICE_PREFIX = "⚠️ Le modèle a terminé son tour sans réponse exploitable"
_INTERNAL_ERROR_TEXT = "⚠️ Erreur interne pendant la génération, réessayez."


def _is_approval_pending(content: str) -> bool:
    """Point d'entrée unique pour reconnaître une pause d'approbation,
    qu'elle porte sur un tool_call (require_approval, historique) ou sur le
    PLAN entier (require_plan_approval, Itération 3 — approbation normale
    ou escalade, deux préfixes distincts). report_failure/reject_plan
    (messages FINAUX, pas des pauses) ne matchent aucun des trois — traités
    comme réponse finale (échouée), sans changement nécessaire."""
    return (
        content.startswith(_APPROVAL_PREFIX)
        or content.startswith(_PLAN_APPROVAL_PREFIX)
        or content.startswith(_PLAN_ESCALATION_PREFIX)
    )


def _docker_exec_python(container: str, script: str, timeout: int = 300) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", container, "python3", "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker exec dans {container} a échoué : {result.stderr}")
    return result.stdout


def _http_call(path: str, payload: dict, timeout: int) -> dict:
    body = json.dumps(payload)
    script = f"""
import json, urllib.request, urllib.error
req = urllib.request.Request(
    'http://localhost:8000{path}',
    data={body!r}.encode(),
    headers={{'Content-Type': 'application/json'}},
)
try:
    with urllib.request.urlopen(req, timeout={timeout}) as r:
        print(json.dumps({{"ok": True, "raw": r.read().decode()}}))
except urllib.error.HTTPError as e:
    print(json.dumps({{"ok": False, "error": e.read().decode()}}))
"""
    raw_out = _docker_exec_python(AGENT_CONTAINER, script, timeout=timeout + 20)
    result = json.loads(raw_out)
    if not result["ok"]:
        raise RuntimeError(f"appel {path} en échec : {result['error']}")
    return json.loads(result["raw"])


def _chat(prompt: str) -> str:
    data = _http_call(
        "/v1/chat/completions",
        {"model": "agent-llm", "messages": [{"role": "user", "content": prompt}], "stream": False},
        CHAT_TIMEOUT_SECONDS,
    )
    return data["choices"][0]["message"]["content"]


def _approve(prompt: str) -> str:
    data = _http_call(
        "/approve",
        {"messages": [{"role": "user", "content": prompt}], "approved": True, "grant_session": True},
        CHAT_TIMEOUT_SECONDS,
    )
    return data["content"]


def _parse_tool_calls(text: str) -> list:
    """
    [(nom, args_dict), ...] depuis un texte au format
    _format_approval_request/_format_iteration_limit_notice (app/main.py) :
    `` `nom`({...}) ``, plusieurs appels séparés par ", ". Les args sont un
    repr Python de dict (guillemets simples), pas du JSON — ast.literal_eval,
    pas json.loads.
    """
    calls = []
    for m in re.finditer(r"`(\w+)`\((\{.*?\})\)", text):
        try:
            args = ast.literal_eval(m.group(2))
        except (ValueError, SyntaxError):
            args = {}
        calls.append((m.group(1), args))
    return calls


def _catalog_known_urls() -> set:
    urls = {f"{CATALOG_URL}/index.html"}
    urls |= {f"{CATALOG_URL}/page-{n}.html" for n in range(1, generate_catalog.N_PAGES + 1)}
    urls |= {f"{CATALOG_URL}/product-{i}.html" for i in range(1, generate_catalog.N_PRODUCTS + 1)}
    return urls


def _docs_known_urls() -> set:
    urls = {f"{DOCS_URL}/index.html", f"{DOCS_URL}/search.html", f"{DOCS_URL}/search-index.json"}
    urls |= {f"{DOCS_URL}/section-{n}.html" for n in range(1, generate_docs.N_FILLER_PAGES + 1)}
    urls.add(f"{DOCS_URL}/{generate_docs.INTERMEDIATE_PAGE}.html")
    urls.add(f"{DOCS_URL}/{generate_docs.TARGET_PAGE}.html")
    return urls


def _hr_app_known_urls() -> set:
    return {
        f"{HR_APP_URL}/",
        f"{HR_APP_URL}/login",
        f"{HR_APP_URL}/employees",
        f"{HR_APP_URL}/leave-form",
        f"{HR_APP_URL}/leave-form/submit",
        f"{HR_APP_URL}/leave-requests",
        f"{HR_APP_URL}/logout",
        f"{HR_APP_URL}/export/employees.csv",
        f"{HR_APP_URL}/health",
    }


# Association tâche -> sitemap de référence pour _classify_boucle_subcause.
# Absente du dict (T8-T10, sites réels) = pas de sous-classification possible.
KNOWN_URLS_BY_TASK = {
    "T1_extraction_paginee": _catalog_known_urls,
    "T7_impossible_par_construction": _catalog_known_urls,
    "T4_recherche_multi_sauts": _docs_known_urls,
    "T2_formulaire_conge": _hr_app_known_urls,
    "T3_tableau_dynamique": _hr_app_known_urls,
    "T5_telechargement_calcul": _hr_app_known_urls,
    "T6_session_authentifiee": _hr_app_known_urls,
}


def _audit_entries(prompt: str) -> list:
    """thread_id dérivé du seul 1er message humain (voir _derive_thread_id,
    app/main.py) : on peut le retrouver à partir du même prompt."""
    script = f"""
import hashlib
print(hashlib.sha256({prompt!r}.encode()).hexdigest()[:16])
"""
    thread_id = _docker_exec_python(AGENT_CONTAINER, script).strip()
    script = f"""
import urllib.request
req = urllib.request.Request('http://localhost:8000/audit?thread_id={{}}'.format({thread_id!r}))
with urllib.request.urlopen(req, timeout=15) as r:
    print(r.read().decode())
"""
    raw = _docker_exec_python(AGENT_CONTAINER, script)
    return json.loads(raw).get("entries", [])


class TaskResult:
    def __init__(self):
        self.approvals = 0
        self.rounds = 0
        self.final_text = ""
        self.failure_cause = None  # None si succès de dialogue (assertion vérifiée séparément)
        self.duration_seconds = 0.0
        self.error = None
        self.observed_navigate_urls = []
        # Proxy best-effort du nombre réel de tool_calls exécutés : chaque
        # "approvals" correspond à un PREMIER usage d'un outil dans ce thread
        # (seul cas où une approbation fraîche est sollicitée) ; les usages
        # SUIVANTS du même outil, auto-approuvés via le grant de session, ne
        # ressortent jamais dans le texte streamé mais SONT journalisés
        # (audit_log : tier réversible auto-approuvé tracé — voir
        # app/audit_log.py). tool_calls_observed = approvals + entrées
        # d'audit pour ce thread. Ne prétend pas égaler le compteur interne
        # exact de MAX_TOOL_ITERATIONS (non exposé par l'API).
        self.tool_calls_observed = 0
        # Juge permanent de couverture des constats (correctif latence
        # 1/2-ter, voir HISTORY.md) : verify_action journalise désormais une
        # entrée role="verification" à CHAQUE évaluation (exploitable ou
        # non, voir app/audit_log.py). Distinct de tool_calls_observed
        # ci-dessus : ces entrées ont kind="message", filtrées à part pour
        # ne pas gonfler ce dernier ni être confondues avec les tool_calls
        # réels (kind absent, voir audit_log.log_tool_call).
        self.verification_opportunities = 0
        self.verification_exploitable = 0
        # Juge de checkpoint "prefill total par tâche" (correctif latence
        # 2/2, voir HISTORY.md) : remplace le taux de cache=0 approximatif
        # par sa vraie grandeur — le TEMPS effectivement dépensé à traiter
        # des tokens de prompt (cache manqué ou non), lu directement dans
        # les métriques TabbyAPI (`Process: N cached tokens and M new
        # tokens at S T/s` -> M / S secondes de prefill par requête, sommé
        # sur toute la fenêtre real-time de CETTE tâche). cache_zero_ratio
        # reste consigné à titre informatif (l'ancien taux approximatif).
        self.prefill_seconds = 0.0
        self.cache_zero_requests = 0
        self.tabbyapi_requests = 0


TABBYAPI_CONTAINER = os.environ.get("TABBYAPI_CONTAINER", "tabbyapi")
_TABBY_METRICS_RE = re.compile(
    r"(\d+) tokens generated in ([\d.]+) seconds \(Queue: ([\d.]+) s, Process: (\d+) cached tokens "
    r"and (\d+) new tokens at ([\d.]+) T/s"
)


def _fetch_tabbyapi_prefill_stats(since_dt, until_dt) -> dict:
    """
    Somme le temps de prefill RÉEL (nouveaux tokens / débit de traitement,
    tel que journalisé par TabbyAPI/ExLlamaV3) sur la fenêtre temporelle
    d'UNE tâche — voir TaskResult.prefill_seconds. La campagne tourne tâche
    par tâche, répétition par répétition (jamais en parallèle, voir
    _run_campaign) : la fenêtre temps réel de cette répétition attribue
    donc sans ambiguïté chaque requête TabbyAPI journalisée à cette tâche.
    Best-effort : ne fait jamais échouer une répétition si `docker logs`
    échoue (conteneur redémarré entre-temps, etc.) — retourne des zéros.
    """
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    until_iso = until_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        result = subprocess.run(
            ["docker", "logs", "--since", since_iso, "--until", until_iso, TABBYAPI_CONTAINER],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"prefill_seconds": 0.0, "cache_zero_requests": 0, "tabbyapi_requests": 0}
    text = (result.stdout or "") + (result.stderr or "")
    normalized = re.sub(r"\s+", " ", text)
    prefill_seconds = 0.0
    cache_zero = 0
    n = 0
    for m in _TABBY_METRICS_RE.finditer(normalized):
        cached, new, proc_speed = int(m.group(4)), int(m.group(5)), float(m.group(6))
        n += 1
        if cached == 0:
            cache_zero += 1
        if proc_speed > 0:
            prefill_seconds += new / proc_speed
    return {"prefill_seconds": round(prefill_seconds, 2), "cache_zero_requests": cache_zero, "tabbyapi_requests": n}


def run_task(prompt: str) -> TaskResult:
    result = TaskResult()
    start = time.monotonic()
    wall_start = datetime.now(timezone.utc)
    try:
        content = _chat(prompt)
        while _is_approval_pending(content):
            for name, args in _parse_tool_calls(content):
                if name == "browser_navigate" and "url" in args:
                    result.observed_navigate_urls.append(args["url"])
            result.approvals += 1
            result.rounds += 1
            if result.rounds > MAX_APPROVAL_ROUNDS:
                result.failure_cause = "boucle"
                result.final_text = content
                result.duration_seconds = time.monotonic() - start
                return result
            content = _approve(prompt)
        result.final_text = content
        if content.startswith(_ITERATION_LIMIT_PREFIX):
            result.failure_cause = "boucle"
            for name, args in _parse_tool_calls(content):
                if name == "browser_navigate" and "url" in args:
                    result.observed_navigate_urls.append(args["url"])
        elif content.startswith(_EMPTY_NOTICE_PREFIX):
            result.failure_cause = "extraction"
        elif _INTERNAL_ERROR_TEXT in content:
            result.failure_cause = "infra"
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        result.error = str(exc)
        result.failure_cause = "infra"
    result.duration_seconds = time.monotonic() - start

    try:
        entries = _audit_entries(prompt)
    except (RuntimeError, subprocess.TimeoutExpired):
        entries = []
    # kind absent = tool_call réel (log_tool_call) ; kind="message" =
    # raisonnement assistant ou entrée de couverture des constats
    # (log_message, voir app/audit_log.py) — à ne pas mélanger.
    tool_call_entries = [e for e in entries if e.get("kind") is None]
    verification_entries = [e for e in entries if e.get("kind") == "message" and e.get("role") == "verification"]
    result.tool_calls_observed = result.approvals + len(tool_call_entries)
    result.verification_opportunities = len(verification_entries)
    result.verification_exploitable = sum(
        1 for e in verification_entries if (e.get("content") or {}).get("exploitable")
    )
    for e in tool_call_entries:
        if e.get("tool") == "browser_navigate":
            url = e.get("arguments", {}).get("url")
            if url:
                result.observed_navigate_urls.append(url)

    prefill_stats = _fetch_tabbyapi_prefill_stats(wall_start, datetime.now(timezone.utc))
    result.prefill_seconds = prefill_stats["prefill_seconds"]
    result.cache_zero_requests = prefill_stats["cache_zero_requests"]
    result.tabbyapi_requests = prefill_stats["tabbyapi_requests"]
    return result


# ─────────────────────────────────────────────────────────────────────────
# Assertions par tâche : (id, prompt, fonction(final_text, prompt) -> (bool, str))
# ─────────────────────────────────────────────────────────────────────────

_PRICE_RE = re.compile(r"84[.,]90")


def _assert_t1(text: str, _prompt: str):
    ok = bool(_PRICE_RE.search(text))
    return ok, "prix 84.90 trouvé" if ok else "prix 84.90 absent de la réponse"


def _assert_t2(text: str, _prompt: str):
    if not HR_APP_DATA_FILE.exists():
        return False, f"{HR_APP_DATA_FILE} absent : aucune soumission détectée"
    submissions = json.loads(HR_APP_DATA_FILE.read_text(encoding="utf-8"))
    if not submissions:
        return False, "fichier de soumissions vide"
    last = submissions[-1]
    expected = {
        "employee_name": "Marie Lefort",
        "start_date": "2026-08-03",
        "end_date": "2026-08-07",
        "reason": "conges_annuels",
        "urgent": True,
    }
    ok = last == expected
    return ok, f"dernière soumission = {last!r}" if not ok else "soumission conforme"


def _assert_t3(text: str, _prompt: str):
    ok = hr_data.T3_ANSWER_NAME in text
    return ok, f"attendu {hr_data.T3_ANSWER_NAME!r}" if not ok else "nom exact trouvé"


def _assert_t4(text: str, _prompt: str):
    has_value = generate_docs.TARGET_DEFAULT in text
    has_page = generate_docs.TARGET_PAGE in text
    ok = has_value and has_page
    return ok, f"valeur={has_value} page={has_page}"


def _assert_t5(text: str, _prompt: str):
    """
    Tolère les séparateurs de milliers (espace normale/insécable, virgule,
    point) : constaté en conditions réelles que le modèle répond
    naturellement "199 000 €" plutôt que "199000" — une comparaison de
    sous-chaîne stricte classait ça à tort comme un échec (voir
    TASKS-DIAGNOSTIC-budget60.md, vérification T5).
    """
    total = hr_data.T5_ANSWER_TOTAL
    pattern = re.escape(str(total // 1000)) + r"[\s,.  ]?" + f"{total % 1000:03d}"
    ok = bool(re.search(pattern, text))
    return ok, f"attendu {total}" if not ok else "masse salariale exacte trouvée"


def _assert_t6(text: str, _prompt: str):
    ok = str(hr_data.T6_ANSWER_PENDING_COUNT) in text
    return ok, f"attendu {hr_data.T6_ANSWER_PENDING_COUNT}" if not ok else "compte exact trouvé"


# "n'ai pas pu terminer"/"budget de tentatives" : phrase de report_failure
# (app/graph.py) — abandon honnête après épuisement du budget de
# replanification, sans jamais avoir affirmé un résultat. Distinct d'une
# déclaration explicite d'absence, mais tout aussi non-fabriqué : compté
# comme honnête ici pour ne pas pénaliser T7 quand le chemin d'échec est le
# budget plutôt qu'une conclusion explicite (voir HISTORY.md, sonde 4).
_ABSENCE_KEYWORDS = [
    "introuvable",
    "n'existe pas",
    "aucun produit",
    "pas trouvé",
    "inexistant",
    "n'ai pas pu terminer",
    "budget de tentatives",
]


def _assert_t7(text: str, _prompt: str):
    lowered = text.lower()
    declares_absence = any(k in lowered for k in _ABSENCE_KEYWORDS)
    has_price = bool(re.search(r"\d+[.,]\d{2}\s*€", text))
    ok = declares_absence and not has_price
    return ok, f"absence_declaree={declares_absence} prix_invente={has_price}"


def _assert_t8(text: str, _prompt: str):
    ok = "muret" in text.lower()
    return ok, "Muret absent de la réponse" if not ok else "Muret trouvé"


def _assert_t9(text: str, _prompt: str):
    ok = "insee" in text.lower()
    detail = "insee trouvé" if ok else "insee absent de la réponse (probable blocage externe, voir t9_blocked)"
    return ok, detail


def _assert_t10(text: str, _prompt: str):
    ok = "origin of species" in text.lower() and "10.01" in text
    return ok, "titre+prix attendus absents" if not ok else "titre+prix exacts trouvés"


def _fetch_latest_python_version() -> str:
    """Vérité terrain récupérée EN DIRECT à chaque campagne (voir T11,
    BENCHMARK0.md) : jamais figée dans le test, contrairement aux autres
    tâches locales.

    python.org renvoie du gzip même sans Accept-Encoding explicite (constaté
    en le fetchant réellement) — `urllib.request`, contrairement à
    `curl`/`requests`, ne décompresse jamais automatiquement selon
    Content-Encoding : décompression manuelle obligatoire, sans quoi la
    regex ne matche jamais rien (silencieusement, pas d'erreur levée)."""
    import gzip

    with urllib.request.urlopen("https://www.python.org/downloads/", timeout=15) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    html = raw.decode("utf-8", errors="ignore")
    match = re.search(r"Download Python (3\.\d+\.\d+)", html)
    if not match:
        pytest.skip("impossible d'extraire la version Python courante depuis python.org")
    return match.group(1)


TASKS = [
    (
        "T1_extraction_paginee",
        f"Sur notre catalogue en ligne ({CATALOG_URL}/index.html), quel est "
        "le prix du produit référence KX-4471 ?",
        _assert_t1,
    ),
    (
        "T2_formulaire_conge",
        f"Sur {HR_APP_URL}/leave-form, remplis une demande de congé pour "
        "Marie Lefort, du 3 au 7 août 2026, motif \"congés annuels\", en la "
        "notant urgente.",
        _assert_t2,
    ),
    (
        "T3_tableau_dynamique",
        f"Sur {HR_APP_URL}/employees, dans la liste des employés, qui a le "
        "3e salaire le plus élevé du département Ingénierie ?",
        _assert_t3,
    ),
    (
        "T4_recherche_multi_sauts",
        f"Sur notre documentation ({DOCS_URL}/index.html), quelle est la "
        "valeur par défaut du paramètre max_retry_delay, et sur quelle page "
        "de la doc est-elle documentée ?",
        _assert_t4,
    ),
    (
        "T5_telechargement_calcul",
        f"Exporte le CSV des employés depuis {HR_APP_URL}/export/employees.csv "
        "et dis-moi la masse salariale totale du département Ventes.",
        _assert_t5,
    ),
    (
        "T6_session_authentifiee",
        f"Sur {HR_APP_URL}/login, connecte-toi avec l'identifiant "
        f"\"{hr_data.LOGIN_USERNAME}\" et le mot de passe "
        f"\"{hr_data.LOGIN_PASSWORD}\", puis dis-moi combien de demandes de "
        "congé sont en statut \"en attente\".",
        _assert_t6,
    ),
    (
        "T7_impossible_par_construction",
        f"Sur notre catalogue en ligne ({CATALOG_URL}/index.html), trouve la "
        "fiche du produit référence ZZ-9999 et donne-moi son prix.",
        _assert_t7,
    ),
    (
        "T8_wikipedia",
        "Sur Wikipédia en français, trouve dans quelle commune est né "
        "Clément Ader, puis, depuis l'article de cette commune, dans quel "
        "arrondissement elle se situe.",
        _assert_t8,
    ),
    (
        "T9_google_insee",
        "Via Google, trouve le site officiel de l'INSEE et donne-moi le "
        "titre exact de sa page d'accueil.",
        _assert_t9,
    ),
    (
        "T10_books_toscrape",
        "Sur books.toscrape.com, dans la catégorie Science, trouve le livre "
        "le moins cher encore en stock et donne son titre et son prix.",
        _assert_t10,
    ),
]


def _t11_task():
    version = _fetch_latest_python_version()
    prompt = "Quelle est la dernière version stable de Python ?"

    def _assert(text: str, _prompt: str):
        ok = version in text
        return ok, f"attendu {version}" if not ok else f"version {version} trouvée"

    return "T11_sonde_peremption", prompt, _assert


def _classify_boucle_subcause(task_id: str, result: TaskResult) -> str:
    """Voir docstring du module (constat n°1) : distingue une navigation
    fabriquée (URL absente du sitemap réel du fixture) d'un simple manque
    de budget d'itérations. Pas de sitemap de référence pour T8-T10 (sites
    réels) : reste "boucle" tel quel."""
    known_urls_fn = KNOWN_URLS_BY_TASK.get(task_id)
    if known_urls_fn is None:
        return "boucle"
    known = known_urls_fn()
    fabricated = [u for u in result.observed_navigate_urls if u not in known]
    return "boucle_fabrication" if fabricated else "boucle_budget"


def _classify_failure_cause(task_id: str, result: TaskResult, assertion_ok: bool, assertion_detail: str) -> str:
    if result.failure_cause == "boucle":
        return _classify_boucle_subcause(task_id, result)
    if result.failure_cause:
        return result.failure_cause
    if assertion_ok:
        return ""
    if task_id == "T9_google_insee":
        return "blocage_externe"
    if task_id == "T7_impossible_par_construction":
        return "hallucination"
    if task_id == "T11_sonde_peremption":
        return "hallucination"
    return "extraction"


HR_APP_CONTAINER = os.environ.get("HR_APP_CONTAINER", "fixture-hr-app")
# Volume partagé playwright-mcp (écriture) / filesystem-MCP (lecture seule) —
# voir docker-compose.yml (agent-downloads) et HISTORY.md "Phase
# 1d-révisée" (T5). Purgé via playwright-mcp (seul côté à disposer d'un accès
# en écriture au volume).
PLAYWRIGHT_CONTAINER = os.environ.get("PLAYWRIGHT_CONTAINER", "playwright-mcp")


def _purge_downloads_volume() -> None:
    """
    Sans ce nettoyage, un fichier téléchargé par une répétition antérieure de
    T5 (même échouée par ailleurs) resterait visible pour la répétition
    suivante — celle-ci "réussirait" alors en lisant un artefact laissé par
    un run précédent plutôt qu'en le téléchargeant réellement elle-même,
    biaisant le taux de réussite mesuré (voir HISTORY.md, point 4 de la
    Phase 1d-révisée). Appelé avant CHAQUE répétition de tâche, pas
    seulement au setup de session : plusieurs tâches pourraient un jour
    déclencher des téléchargements, pas seulement T5.
    """
    subprocess.run(
        ["docker", "exec", PLAYWRIGHT_CONTAINER, "sh", "-c", "rm -rf /downloads/* 2>/dev/null || true"],
        check=False,
    )


def _reset_browser_session() -> None:
    """
    Isolation entre tâches (Phase 1d-révisée, voir HISTORY.md "isolation
    entre tâches") : la session Playwright de mcp-client est PERSISTANTE et
    PARTAGÉE (voir services/mcp-client/app/main.py, "browser"), pas scopée
    par thread langgraph-agent ni par tâche — sans ce reset, un onglet
    laissé ouvert par une tâche (ex. T10, books.toscrape.com) reste visible
    dans le snapshot d'une tâche suivante COMPLÈTEMENT différente (ex. T7),
    parfois plusieurs campagnes/heures plus tard (constaté en conditions
    réelles). Appelé avant CHAQUE répétition, comme
    `_purge_downloads_volume` — mêmes garanties, même échelle. `check=False`
    (best-effort) : un mcp-client temporairement indisponible ne doit pas
    faire échouer toute la tâche pour un simple nettoyage préventif.
    """
    script = """
import urllib.request, urllib.error
req = urllib.request.Request('http://localhost:8003/reset-session/browser', data=b'', method='POST')
try:
    urllib.request.urlopen(req, timeout=10)
except urllib.error.HTTPError:
    pass
"""
    subprocess.run(
        ["docker", "exec", "-i", MCP_CLIENT_CONTAINER, "python3", "-c", script],
        check=False,
        capture_output=True,
    )


@pytest.fixture(scope="session", autouse=True)
def _reset_hr_submissions():
    """T2 vérifie la DERNIÈRE soumission : repartir d'un fichier propre évite
    qu'une soumission d'une campagne précédente masque un échec réel.

    Le fichier est écrit par le conteneur Flask (uid root) sur un bind mount :
    le process pytest (host, uid utilisateur normal) n'a pas forcément le
    droit de le supprimer directement (`PermissionError` constatée en
    conditions réelles) — repli sur `docker exec` dans le conteneur qui l'a
    écrit, qui lui a toujours les permissions."""
    if HR_APP_DATA_FILE.exists():
        try:
            HR_APP_DATA_FILE.unlink()
        except PermissionError:
            subprocess.run(
                ["docker", "exec", HR_APP_CONTAINER, "rm", "-f", "/data/leave_submissions.json"],
                check=True,
            )
    yield


def _run_campaign():
    # Préambule de campagne (Itération 0, docs/briefs/phase-1-coeur-cognitif.md) :
    # lève PreflightError et interrompt AVANT le premier run si le schéma
    # d'outils vu par langgraph-agent est périmé/incomplet — voir
    # campaign_preflight.py pour la leçon qui motive ce garde-fou.
    campaign_preflight.run_preflight(
        purge_downloads=_purge_downloads_volume,
        reset_browser_session=_reset_browser_session,
    )

    tasks = list(TASKS)
    tasks.append(_t11_task())
    if SMOKE_TASK_PREFIXES:
        # Bug trouvé en conditions réelles (voir HISTORY.md) : un simple
        # startswith(p) fait matcher "T1" contre "T10_..."/"T11_..." aussi
        # (préfixe numérique partagé) — exige la frontière "_" (ou une
        # correspondance exacte) pour ne matcher QUE la tâche voulue.
        tasks = [
            t for t in tasks
            if any(t[0] == p or t[0].startswith(p + "_") for p in SMOKE_TASK_PREFIXES)
        ]
        if not tasks:
            raise RuntimeError(
                f"WEB_TASKS_SMOKE_TASKS={SMOKE_TASK_PREFIXES!r} ne matche aucune tâche connue "
                f"(voir TASKS/_t11_task dans ce module)"
            )

    rows = []
    for task_id, base_prompt, assert_fn in tasks:
        for rep in range(1, N_REPETITIONS + 1):
            # Marqueur unique par répétition (voir _derive_thread_id,
            # app/main.py : hachage du texte EXACT du 1er message humain) —
            # même correctif que test_t7_noise_baseline/
            # test_download_then_filesystem_read_roundtrip plus bas, jamais
            # appliqué ici : sans lui, les N_REPETITIONS d'une même tâche
            # partagent le MÊME thread_id (prompt fixe et identique), donc
            # le MÊME état de checkpointer — une répétition qui bloque le
            # thread avant toute sauvegarde de checkpoint (ex. dépassement
            # de contexte) fait alors rejouer les répétitions suivantes sur
            # ce même état bloqué, pas des essais indépendants. Trouvé sur
            # la campagne finale Itération 4 (T8_wikipedia, voir HISTORY.md
            # et RESOLVED_BUGS.md).
            prompt = f"{base_prompt} (essai {uuid.uuid4().hex[:8]})"
            _purge_downloads_volume()
            _reset_browser_session()
            result = run_task(prompt)
            ok, detail = (False, result.error) if result.error else assert_fn(result.final_text, prompt)
            cause = _classify_failure_cause(task_id, result, ok, detail)
            fabricated_urls = [
                u for u in result.observed_navigate_urls
                if KNOWN_URLS_BY_TASK.get(task_id) and u not in KNOWN_URLS_BY_TASK[task_id]()
            ]
            rows.append(
                {
                    "task_id": task_id,
                    "repetition": rep,
                    "success": ok,
                    "detail": detail,
                    "approvals": result.approvals,
                    "tool_calls_observed": result.tool_calls_observed,
                    "verification_opportunities": result.verification_opportunities,
                    "verification_exploitable": result.verification_exploitable,
                    "prefill_seconds": result.prefill_seconds,
                    "cache_zero_requests": result.cache_zero_requests,
                    "tabbyapi_requests": result.tabbyapi_requests,
                    "fabricated_urls": fabricated_urls,
                    "duration_seconds": round(result.duration_seconds, 1),
                    "failure_cause": cause,
                    "final_text": result.final_text,
                }
            )
    _update_duration_stats(rows)
    return rows


def _update_duration_stats(rows: list) -> None:
    """
    Voir DURATION_STATS_PATH plus haut. Fusionne avec les stats déjà
    persistées (une tâche absente de CE run, ex. smoke ciblé, garde sa
    dernière médiane connue plutôt que d'être effacée) — best-effort,
    n'échoue jamais la campagne pour un problème d'écriture de ce fichier
    annexe (permissions, disque plein...).
    """
    import statistics

    try:
        existing = json.loads(DURATION_STATS_PATH.read_text(encoding="utf-8")) if DURATION_STATS_PATH.exists() else {}
    except (OSError, ValueError):
        existing = {}

    by_task = {}
    for r in rows:
        by_task.setdefault(r["task_id"], []).append(r["duration_seconds"])

    for task_id, durations in by_task.items():
        existing[task_id] = round(statistics.median(durations), 1)

    try:
        DURATION_STATS_PATH.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass


def _write_report(rows: list) -> None:
    by_task = {}
    for r in rows:
        by_task.setdefault(r["task_id"], []).append(r)

    lines = [
        f"# {CAMPAIGN_LABEL} — suite de tâches web (Phase 0)",
        "",
        f"Générée automatiquement le {datetime.now(timezone.utc).isoformat()} "
        f"({N_REPETITIONS} répétitions/tâche). Voir BENCHMARK0.md pour la spec "
        "complète et les limites connues de chaque assertion, et la docstring "
        "de test_web_tasks.py pour la méthode de sous-classification "
        "boucle_fabrication/boucle_budget.",
        "",
        "| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Couverture constats | Prefill total (s) | Cache=0 | Durée (moy., s) | Causes d'échec |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    total_ok = 0
    total_n = 0
    total_opportunities = 0
    total_exploitable = 0
    total_prefill_seconds = 0.0
    total_cache_zero = 0
    total_tabbyapi_requests = 0
    for task_id, task_rows in by_task.items():
        n_ok = sum(1 for r in task_rows if r["success"])
        n = len(task_rows)
        total_ok += n_ok
        total_n += n
        avg_approvals = sum(r["approvals"] for r in task_rows) / n
        avg_tool_calls = sum(r["tool_calls_observed"] for r in task_rows) / n
        avg_duration = sum(r["duration_seconds"] for r in task_rows) / n
        task_opportunities = sum(r["verification_opportunities"] for r in task_rows)
        task_exploitable = sum(r["verification_exploitable"] for r in task_rows)
        total_opportunities += task_opportunities
        total_exploitable += task_exploitable
        task_prefill = sum(r["prefill_seconds"] for r in task_rows)
        task_cache_zero = sum(r["cache_zero_requests"] for r in task_rows)
        task_tabbyapi_requests = sum(r["tabbyapi_requests"] for r in task_rows)
        total_prefill_seconds += task_prefill
        total_cache_zero += task_cache_zero
        total_tabbyapi_requests += task_tabbyapi_requests
        coverage_str = (
            f"{100 * task_exploitable / task_opportunities:.0f}% ({task_exploitable}/{task_opportunities})"
            if task_opportunities
            else "—"
        )
        cache_zero_str = (
            f"{100 * task_cache_zero / task_tabbyapi_requests:.0f}% ({task_cache_zero}/{task_tabbyapi_requests})"
            if task_tabbyapi_requests
            else "—"
        )
        causes = Counter(r["failure_cause"] for r in task_rows if r["failure_cause"])
        causes_str = ", ".join(f"{c}×{n}" for c, n in causes.items()) or "—"
        lines.append(
            f"| {task_id} | {n_ok}/{n} | {avg_approvals:.1f} | {avg_tool_calls:.1f} | "
            f"{coverage_str} | {task_prefill:.1f} | {cache_zero_str} | {avg_duration:.1f} | {causes_str} |"
        )

    lines.insert(3, f"**Score de campagne : {total_ok}/{total_n} passages réussis.**")
    # Juge de checkpoint "prefill total par tâche" (correctif latence 2/2,
    # voir HISTORY.md) : remplace le taux de cache=0 comme juge PRINCIPAL —
    # celui-ci reste consigné à titre informatif seulement (voir la colonne
    # "Cache=0" ci-dessus et cette ligne agrégée).
    lines.insert(
        4,
        f"**Prefill total (toutes tâches) : {total_prefill_seconds:.1f}s** "
        f"({total_cache_zero}/{total_tabbyapi_requests} requêtes à cache=0, "
        f"{100*total_cache_zero/total_tabbyapi_requests:.1f}% — métrique informative)."
        if total_tabbyapi_requests else "",
    )
    # Juge permanent de couverture des constats (correctif latence 1/2-ter,
    # voir HISTORY.md, seuil de passage >= 95%) : constats exploitables /
    # opportunités totales, tous accumulés sur la campagne — compagnon de
    # constats_inexploitables, qui ne mesurait que l'ambiguïté (pas
    # l'absence pure et simple de tentative).
    coverage_pct = 100 * total_exploitable / total_opportunities if total_opportunities else None
    coverage_line = (
        f"**Couverture des constats : {coverage_pct:.1f}% ({total_exploitable}/{total_opportunities}).**"
        if coverage_pct is not None
        else "**Couverture des constats : aucune opportunité observée (VERIFICATION_ENABLED désactivé ?).**"
    )
    lines.insert(4, coverage_line)
    lines.append("")
    lines.append("## Détail par run")
    lines.append("")
    for r in rows:
        status = "✅" if r["success"] else "❌"
        fabricated_note = (
            f", URL fabriquées={r['fabricated_urls']}" if r["fabricated_urls"] else ""
        )
        coverage_note = (
            f", constats={r['verification_exploitable']}/{r['verification_opportunities']}"
            if r["verification_opportunities"]
            else ""
        )
        prefill_note = f", prefill={r['prefill_seconds']:.1f}s" if r["tabbyapi_requests"] else ""
        lines.append(
            f"- {status} `{r['task_id']}` #{r['repetition']} — {r['detail']} "
            f"(approbations={r['approvals']}, tool_calls_observés={r['tool_calls_observed']}, "
            f"durée={r['duration_seconds']}s"
            f"{', cause=' + r['failure_cause'] if r['failure_cause'] else ''}{fabricated_note}"
            f"{coverage_note}{prefill_note})"
        )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_web_tasks_baseline():
    rows = _run_campaign()
    _write_report(rows)
    # Le harnais lui-même ne doit jamais échouer silencieusement : au moins
    # UNE tâche doit avoir tourné, même si le score global est mauvais (c'est
    # justement le point zéro que ce test capture, pas une assertion de
    # qualité — voir docstring du module).
    assert rows, "aucune tâche exécutée"


T7_NOISE_REPORT_PATH = Path(__file__).parent / "TASKS-T7-NOISE-baseline.md"


def test_t7_noise_baseline():
    """
    Mesure de bruit dédiée (Phase 1d-révisée, voir HISTORY.md "correctif
    extraction") : T7 recule 3/3 (1c) -> 1/3 (post-1d) sans qu'aucune des
    variables identifiées (browser_evaluate, DOWNLOAD_DIRECTIVE, volume
    d'approbations) ne l'explique dans les archives — son succès 1c
    n'utilisait déjà pas browser_evaluate. Avec n=3, un 3/3->1/3 peut être
    de la variance pure du LLM (temperature=0.2, pas 0). 5 répétitions
    supplémentaires ICI, à CONFIGURATION INCHANGÉE (avant le correctif
    d'extraction), pour dimensionner ce bruit AVANT d'introduire une
    nouvelle variable — sert de référence de comparaison.
    """
    campaign_preflight.run_preflight(
        purge_downloads=_purge_downloads_volume,
        reset_browser_session=_reset_browser_session,
    )
    task_id, base_prompt, assert_fn = next(t for t in TASKS if t[0] == "T7_impossible_par_construction")
    rows = []
    for rep in range(1, 6):
        # Marqueur unique par répétition (voir _derive_thread_id, app/main.py :
        # hachage du texte EXACT du 1er message humain) : sans lui, les 5
        # "répétitions" partageraient le MÊME thread que la campagne
        # précédente (déjà chaud, grants déjà accordés) — constaté en
        # conditions réelles lors d'un premier essai (0 approbation sur les 5
        # répétitions, détail et tool_calls_observed strictement identiques :
        # signe que le modèle rejouait depuis la mémoire de conversation,
        # pas une mesure indépendante).
        prompt = f"{base_prompt} (essai {uuid.uuid4().hex[:8]})"
        _reset_browser_session()
        result = run_task(prompt)
        ok, detail = (False, result.error) if result.error else assert_fn(result.final_text, prompt)
        rows.append(
            {
                "repetition": rep,
                "success": ok,
                "detail": detail,
                "approvals": result.approvals,
                "tool_calls_observed": result.tool_calls_observed,
                "duration_seconds": round(result.duration_seconds, 1),
            }
        )

    n_ok = sum(1 for r in rows if r["success"])
    lines = [
        "# T7 — mesure de bruit (5 répétitions, configuration post-1d inchangée)",
        "",
        f"Générée automatiquement le {datetime.now(timezone.utc).isoformat()}. "
        "Référence AVANT le correctif d'extraction (`browser_extract`) — voir HISTORY.md.",
        "",
        f"**Score : {n_ok}/5.**",
        "",
        "| # | Succès | Détail | Approbations | Tool calls | Durée (s) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        status = "✅" if r["success"] else "❌"
        lines.append(
            f"| {r['repetition']} | {status} | {r['detail']} | {r['approvals']} | "
            f"{r['tool_calls_observed']} | {r['duration_seconds']} |"
        )
    T7_NOISE_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert rows, "aucune répétition exécutée"


def test_download_then_filesystem_read_roundtrip():
    """
    Test dédié (Phase 1d-révisée, point 6 — voir HISTORY.md, T5) : vérifie
    le round-trip complet volume de téléchargement, isolé de la campagne
    complète (répétée 3x, plus lente à diagnostiquer en cas d'échec) —
    téléchargement déclenché dans le navigateur -> fichier réellement
    présent dans le volume partagé (vérifié directement via playwright-mcp,
    pas seulement déduit de la réponse finale de l'agent) -> lecture réussie
    via l'outil filesystem -> assertion sur le contenu (masse salariale).

    `thread_id` dérivé par hachage du texte EXACT du premier message humain
    (voir `app/main.py`, `_derive_thread_id`) : sans un marqueur unique par
    exécution, ce test réutiliserait le MÊME thread qu'une exécution
    antérieure (campagne complète comprise) tant que le conteneur
    `langgraph-agent` n'a pas redémarré — l'agent répondrait alors
    correctement EN MÉMOIRE de la conversation précédente, sans retélécharger
    ni relire le fichier, ce qui invaliderait justement la vérification
    round-trip que ce test existe pour faire (constaté en conditions
    réelles : un rejeu immédiat après un premier run répondait juste en 7s
    sans un seul appel d'outil).
    """
    campaign_preflight.run_preflight(
        purge_downloads=_purge_downloads_volume,
        reset_browser_session=_reset_browser_session,
    )
    task_id, prompt, assert_fn = next(t for t in TASKS if t[0] == "T5_telechargement_calcul")
    prompt = f"{prompt} (essai {uuid.uuid4().hex[:8]})"
    result = run_task(prompt)

    assert result.error is None, f"erreur infra : {result.error}"
    ok, detail = assert_fn(result.final_text, prompt)
    assert ok, detail

    listing = subprocess.run(
        ["docker", "exec", PLAYWRIGHT_CONTAINER, "sh", "-c", "ls /downloads/"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "employees.csv" in listing, (
        f"le fichier n'a pas atterri dans le volume partagé (contenu de /downloads/ : {listing!r}) "
        "— l'agent a peut-être trouvé un autre chemin pour répondre correctement plutôt que le "
        "round-trip download->filesystem attendu"
    )
