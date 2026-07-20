"""
Harnais de référence (Phase 0 du plan de migration langgraph/langchain-openai/
openai, voir README) : capture le comportement actuel du tool-calling contre
le trio pinné aujourd'hui (`langgraph==0.2.34`/`langchain-openai==0.2.2`/
`openai==1.51.2`) AVANT toute montée de version, pour pouvoir détecter une
régression de comportement après coup — pas pour faire échouer la CI sur la
qualité du modèle lui-même.

5 prompts fixes (mix simple / raisonnement préalable / capture->clic GhostDesk
/ sans outil / deux outils), rejoués `BASELINE_REPETITIONS` fois chacun (5 par
défaut, non-déterminisme du modèle assumé — voir README, plusieurs bugs déjà
documentés comme non-déterministes). Pour chaque run, classification
best-effort de l'issue :

  - "structured"         : tool_calls natif reconnu par le serveur (pause
                            d'approbation observée, OU exécution auto-approuvée
                            tracée dans le journal d'audit)
  - "fallback_recovered"  : `_extract_fallback_tool_call` a dû rattraper un
                            appel écrit en prose (détecté via le WARNING loggé
                            par `call_llm`, voir app/graph.py)
  - "empty_notice"        : dernier filet, `_format_empty_answer_notice`
                            affiché (voir app/main.py)
  - "ok_no_tool"          : réponse texte normale, aucun signal de tool_calls

Limite connue de cette classification (best-effort, pas d'instrumentation
serveur au-delà du journal d'audit existant) : un outil TIER_READ exécuté
seul, sans qu'aucun outil TIER_REVERSIBLE/TIER_SENSITIVE ne suive dans le même
tour, n'est ni loggé (jamais audité, voir approval_policy.py) ni visible dans
le texte streamé -> il retomberait à tort dans "ok_no_tool". Les prompts
ci-dessous ciblent donc délibérément des outils TIER_REVERSIBLE (journalisés
même auto-approuvés) pour rester détectables en boîte noire.

Vérifie en plus, sur CHAQUE run, les invariants structurels du streaming SSE
(indépendants de la qualité du modèle, doivent tenir même si le modèle
"dérive") :
  - format OpenAI (`chat.completion.chunk`, flux terminé par `data: [DONE]`,
    dernier chunk réel à `finish_reason: "stop"`) ;
  - au plus une balise `<think>` sur tout le tour streamé, ouverte en tout
    début de tour (jamais après du texte déjà visible) et refermée une seule
    fois si ouverte (voir README, "fusion d'un seul bloc <think> continu sur
    plusieurs itérations de la boucle d'outils auto-approuvés").

À la fin de la session, écrit/écrase automatiquement
`tests_integration/BASELINE.md` (tableau récapitulatif + détail par run) —
c'est ce fichier qu'il faut committer comme référence Phase 0, et rejouer tel
quel après la Phase 4 pour comparer les taux avant/après (voir le plan).

Comme `test_semantic_drift.py` : parle aux vrais conteneurs Docker via
`docker exec`, lent (génération LLM réelle) et non déterministe par nature.
Ignoré par défaut ; opt-in explicite :

    RUN_LIVE_LLM_TESTS=1 python -m pytest tests_integration/test_tool_calling_baseline.py -v

Prérequis identiques à `test_semantic_drift.py` : `docker compose up` avec
langgraph-agent/mcp-client/llama-server actifs, bureau virtuel GhostDesk sans
application ouverte (vérifié ci-dessous, mêmes raisons : une fenêtre parasite
fausserait le grounding visuel du prompt capture->clic).

Cadence délibérément ralentie entre runs (voir `_wait_for_llama_health` et
`BASELINE_PAUSE_SECONDS`) : une première version de ce harnais, tirant les 25
générations réelles à la chaîne sans pause, a fait planter `llama-server`
(observé en conditions réelles : `CUDA error: unspecified launch failure` sur
un rig double-GPU hétérogène, `ggml-cuda.cu`) — `llama-server` s'auto-relance
après ce crash (superviseur `cmd_child_to_router`), mais les requêtes tombant
pendant la fenêtre de rechargement du modèle échouaient en cascade
(`httpcore.RemoteProtocolError: Server disconnected without sending a
response`), polluant la classification (un crash GPU n'est pas un échec de
tool-calling). Attendre `GET http://llama-server:8000/health` en plus d'une
pause fixe avant chaque run rapproche la cadence d'un usage conversationnel
normal (jamais 25 générations dos-à-dos) plutôt que d'un test de charge — ce
harnais mesure le tool-calling, pas la résilience de `llama-server` sous
rafale, qui reste un problème d'infrastructure hors périmètre de cette
migration.
"""
import hashlib
import json
import os
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="test d'intégration live (LLM réel) : opt-in via RUN_LIVE_LLM_TESTS=1, nécessite docker compose up",
)

AGENT_CONTAINER = os.environ.get("LANGGRAPH_AGENT_CONTAINER", "langgraph-agent")
MCP_CLIENT_CONTAINER = os.environ.get("MCP_CLIENT_CONTAINER", "mcp-client")
N_REPETITIONS = int(os.environ.get("BASELINE_REPETITIONS", "5"))
# Pause fixe avant chaque run, EN PLUS de l'attente de santé de llama-server
# (voir docstring du module) : rapproche la cadence d'un usage conversationnel
# normal plutôt que d'un test de charge qui a fait planter le GPU.
PAUSE_BETWEEN_RUNS_SECONDS = float(os.environ.get("BASELINE_PAUSE_SECONDS", "5"))
LLAMA_HEALTH_TIMEOUT_SECONDS = int(os.environ.get("BASELINE_HEALTH_TIMEOUT", "90"))

# Textes exacts émis côté serveur (voir app/main.py) : sert à classifier une
# issue depuis le texte streamé, sans dépendre du contenu variable qui suit.
_APPROVAL_PREFIX = "⚠️ Approbation requise pour"
_ITERATION_LIMIT_PREFIX = "⚠️ Limite d'itérations d'outils atteinte"
_EMPTY_NOTICE_PREFIX = "⚠️ Le modèle a terminé son tour sans réponse exploitable"
_FALLBACK_LOG_MARKER = "Tool call de secours extrait"
# Texte du repli `except Exception` de _stream_response (app/main.py) : un
# crash côté llama-server (ex. CUDA, voir docstring du module) coupe la
# génération en plein milieu et ce texte apparaît alors AU MILIEU du flux,
# pas forcément en préfixe — recherché en `in`, pas en `startswith`, et
# vérifié en priorité pour ne jamais retomber dans "ok_no_tool" par erreur.
_INTERNAL_ERROR_TEXT = "⚠️ Erreur interne pendant la génération, réessayez."

# (identifiant, prompt, tier ciblé) — les 4 premiers ciblent volontairement un
# outil TIER_REVERSIBLE (auto-approuvé mais journalisé, voir docstring) pour
# rester détectables en boîte noire ; le 5e est délibérément hors périmètre
# MCP.
PROMPTS = [
    (
        "appel_simple",
        "Lance une calculatrice sur le bureau.",
    ),
    (
        "appel_apres_raisonnement",
        "Le bureau semble ne pas répondre. Réfléchis d'abord à la meilleure "
        "façon de vérifier ça sans rien casser, puis appuie sur la touche "
        "Échap pour voir si ça débloque quelque chose.",
    ),
    (
        "capture_puis_clic",
        "Prends une capture d'écran du bureau, repère un bouton ou une icône "
        "visible, puis clique dessus.",
    ),
    (
        "deux_outils",
        "Lance une application de calculatrice, puis une fois lancée, "
        "clique une fois au centre de l'écran pour lui donner le focus.",
    ),
    (
        "sans_outil",
        "Explique en une phrase la différence entre TCP et UDP.",
    ),
]


def _docker_exec_python(container: str, script: str, timeout: int = 260) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", container, "python3", "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker exec dans {container} a échoué : {result.stderr}")
    return result.stdout


def _wait_for_llama_health(timeout: int = LLAMA_HEALTH_TIMEOUT_SECONDS) -> None:
    """
    Attend que llama-server réponde sain avant de lancer un nouveau run
    (voir docstring du module : un crash CUDA suivi d'un redémarrage
    automatique laisse une fenêtre de plusieurs secondes où le modèle
    recharge, pendant laquelle toute requête échoue en cascade). Requête
    faite depuis le conteneur langgraph-agent (réseau interne compose, nom
    de service `llama-server` résolu par Docker DNS) plutôt que depuis
    l'hôte, qui n'a pas forcément le port publié.
    """
    script = """
import urllib.request
try:
    with urllib.request.urlopen('http://llama-server:8000/health', timeout=5) as r:
        print(r.status)
except Exception as e:
    print(f"ERR:{e}")
"""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            last = _docker_exec_python(AGENT_CONTAINER, script, timeout=15).strip()
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            last = str(exc)
        if last == "200":
            return
        time.sleep(2)
    pytest.fail(
        f"llama-server ne répond pas sain après {timeout}s (dernier statut : {last!r}) "
        "— probable crash/redémarrage en cours, voir docker logs llama-server."
    )


@pytest.fixture(scope="session", autouse=True)
def _assert_desktop_is_clean_once():
    script = """
import json, urllib.request
req = urllib.request.Request(
    'http://localhost:8003/call',
    data=json.dumps({"tool": "app_running", "arguments": {}}).encode(),
    headers={'Content-Type': 'application/json'},
)
with urllib.request.urlopen(req, timeout=15) as r:
    print(r.read().decode())
"""
    raw = _docker_exec_python(MCP_CLIENT_CONTAINER, script)
    data = json.loads(raw)
    if data.get("content", []):
        pytest.fail(
            "Bureau virtuel GhostDesk non vide avant le harnais de baseline "
            f"(app_running a retourné {data['content']!r}) : ferme les "
            "applications ouvertes manuellement via noVNC avant de relancer."
        )
    yield


def _log_line_count(container: str) -> int:
    result = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
    return len((result.stdout + result.stderr).splitlines())


def _log_lines_since(container: str, since: int) -> str:
    result = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
    lines = (result.stdout + result.stderr).splitlines()
    return "\n".join(lines[since:])


def _stream_chat(content: str) -> str:
    payload = json.dumps(
        {"model": "agent-llm", "messages": [{"role": "user", "content": content}], "stream": True}
    )
    script = f"""
import json, urllib.request, urllib.error
req = urllib.request.Request(
    'http://localhost:8000/v1/chat/completions',
    data={payload!r}.encode(),
    headers={{'Content-Type': 'application/json'}},
)
try:
    with urllib.request.urlopen(req, timeout=240) as r:
        raw = r.read().decode()
    print(json.dumps({{"ok": True, "raw": raw}}))
except urllib.error.HTTPError as e:
    print(json.dumps({{"ok": False, "error": e.read().decode()}}))
"""
    raw_out = _docker_exec_python(AGENT_CONTAINER, script)
    result = json.loads(raw_out)
    if not result["ok"]:
        pytest.fail(f"Requête streaming à langgraph-agent en échec : {result['error']}")
    return result["raw"]


def _get_audit_entries(thread_id: str) -> list:
    script = f"""
import urllib.request
req = urllib.request.Request('http://localhost:8000/audit?thread_id={thread_id}')
with urllib.request.urlopen(req, timeout=15) as r:
    print(r.read().decode())
"""
    raw = _docker_exec_python(AGENT_CONTAINER, script)
    return json.loads(raw).get("entries", [])


def _parse_sse(raw: str) -> list:
    chunks = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        data = line[len("data: ") :]
        chunks.append({"done": True} if data == "[DONE]" else json.loads(data))
    return chunks


def _assert_sse_invariants(raw: str, chunks: list) -> list:
    assert raw.rstrip("\n").endswith("data: [DONE]"), "le flux SSE doit se terminer par 'data: [DONE]'"
    assert chunks and chunks[-1] == {"done": True}, "marqueur [DONE] absent des chunks parsés"
    real_chunks = chunks[:-1]
    assert real_chunks, "aucun chunk de contenu reçu avant [DONE]"
    for chunk in real_chunks:
        assert chunk.get("object") == "chat.completion.chunk", f"chunk hors-format OpenAI : {chunk}"
        assert chunk.get("choices"), f"chunk sans 'choices' : {chunk}"
    assert real_chunks[-1]["choices"][0]["finish_reason"] == "stop", (
        f"dernier chunk réel sans finish_reason=stop : {real_chunks[-1]}"
    )
    return real_chunks


def _extract_full_text(real_chunks: list) -> str:
    parts = []
    for chunk in real_chunks:
        delta = chunk["choices"][0]["delta"]
        if delta.get("content"):
            parts.append(delta["content"])
    return "".join(parts)


def _assert_think_invariants(full_text: str) -> None:
    open_count = full_text.count("<think>")
    close_count = full_text.count("</think>")
    assert open_count <= 1, f"<think> ouvert {open_count} fois (attendu au plus 1) : {full_text[:300]}..."
    if open_count == 1:
        assert close_count == 1, f"<think> ouvert mais refermé {close_count} fois : {full_text[:300]}..."
        assert full_text.index("<think>") == 0, (
            f"<think> doit ouvrir le tour, avant tout texte visible : {full_text[:300]}..."
        )
        assert full_text.index("</think>") > full_text.index("<think>")


def _classify(full_text: str, fallback_logged: bool, audit_entries: list) -> str:
    if _INTERNAL_ERROR_TEXT in full_text:
        return "internal_error"
    visible = full_text.split("</think>", 1)[-1].strip() if "</think>" in full_text else full_text.strip()
    if visible.startswith(_EMPTY_NOTICE_PREFIX):
        return "empty_notice"
    if fallback_logged:
        return "fallback_recovered"
    if visible.startswith(_APPROVAL_PREFIX) or visible.startswith(_ITERATION_LIMIT_PREFIX):
        return "structured"
    if audit_entries:
        return "structured"
    return "ok_no_tool"


_RESULTS: list = []


@pytest.fixture(scope="session", autouse=True)
def _write_baseline_report():
    yield
    if not _RESULTS:
        return
    _write_baseline_md(_RESULTS)


def _write_baseline_md(results: list) -> None:
    path = os.path.join(os.path.dirname(__file__), "BASELINE.md")
    by_prompt = defaultdict(lambda: defaultdict(int))
    for r in results:
        by_prompt[r["prompt_id"]][r["classification"]] += 1

    categories = ["structured", "fallback_recovered", "empty_notice", "ok_no_tool", "internal_error"]
    lines = [
        "# Baseline tool-calling — trio actuel",
        "",
        "Trio de référence : `langgraph==0.2.34` / `langchain-openai==0.2.2` / "
        "`openai==1.51.2` (voir requirements.txt et README, section Streaming SSE).",
        "",
        f"Généré automatiquement par `test_tool_calling_baseline.py` le "
        f"{datetime.now(timezone.utc).isoformat()} — {N_REPETITIONS} répétitions par prompt "
        f"(pause {PAUSE_BETWEEN_RUNS_SECONDS}s + attente santé llama-server entre chaque run).",
        "",
        "| Prompt | structured | fallback_recovered | empty_notice | ok_no_tool | internal_error |",
        "|---|---|---|---|---|---|",
    ]
    for prompt_id, _ in PROMPTS:
        counts = by_prompt[prompt_id]
        lines.append(
            f"| `{prompt_id}` | " + " | ".join(str(counts.get(c, 0)) for c in categories) + " |"
        )
    lines += ["", "## Runs détaillés", ""]
    for r in results:
        lines.append(
            f"- `{r['prompt_id']}` rep{r['repetition']} -> **{r['classification']}** "
            f"({r['word_count']} mots, thread `{r['thread_id']}`)"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


@pytest.mark.parametrize("repetition", range(N_REPETITIONS))
@pytest.mark.parametrize("prompt_id,prompt_text", PROMPTS, ids=[p[0] for p in PROMPTS])
def test_tool_calling_run(prompt_id, prompt_text, repetition):
    # Tag unique par run (identifiant + répétition + pid) pour dériver un
    # thread_id frais à chaque fois (_derive_thread_id, app/main.py, hash du
    # premier message humain) : sans ça, deux runs du même prompt
    # partageraient le même thread et le second reprendrait l'état persisté
    # du premier au lieu de démarrer une tâche neuve.
    tag = f"[baseline {prompt_id} rep{repetition} pid{os.getpid()}]"
    content = f"{tag} {prompt_text}"
    thread_id = hashlib.sha256(content.encode()).hexdigest()[:16]

    # Cadence délibérément ralentie (voir docstring du module) : attend que
    # llama-server soit sain (couvre le cas d'un crash CUDA pendant le run
    # précédent, encore en train de recharger le modèle) puis marque une
    # pause fixe, pour ne jamais tirer deux générations réelles dos-à-dos.
    _wait_for_llama_health()
    time.sleep(PAUSE_BETWEEN_RUNS_SECONDS)

    log_before = _log_line_count(AGENT_CONTAINER)
    raw = _stream_chat(content)
    new_logs = _log_lines_since(AGENT_CONTAINER, log_before)

    chunks = _parse_sse(raw)
    real_chunks = _assert_sse_invariants(raw, chunks)
    full_text = _extract_full_text(real_chunks)
    _assert_think_invariants(full_text)

    fallback_logged = _FALLBACK_LOG_MARKER in new_logs
    audit_entries = _get_audit_entries(thread_id)
    classification = _classify(full_text, fallback_logged, audit_entries)

    _RESULTS.append(
        {
            "prompt_id": prompt_id,
            "repetition": repetition,
            "classification": classification,
            "thread_id": thread_id,
            "word_count": len(full_text.split()),
        }
    )
