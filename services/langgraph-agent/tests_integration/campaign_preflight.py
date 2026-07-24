"""
Préambule de campagne (Itération 0, docs/briefs/phase-1-coeur-cognitif.md) :
avant de lancer une campagne du harnais (test_web_tasks.py), vérifie que le
schéma d'outils effectivement vu par langgraph-agent correspond à l'attendu
ET à ce que sert mcp-client au même instant, puis force un état de départ
propre (reset de session navigateur, purge du volume downloads). Un
manquement lève PreflightError AVANT le premier run de la campagne — jamais
un run qui démarre puis échoue pour une raison d'infra déjà détectable.

Raison d'être (leçon du "bug de cache de schéma d'outils", voir HISTORY.md,
Phase 1d-révisée) : `_tools_schema_cache` (app/graph.py) est rempli une
seule fois pour la durée du process langgraph-agent et n'est JAMAIS
invalidé. Un redémarrage de mcp-client seul (nouvel outil ajouté/schéma mis
à jour côté serveur) peut donc laisser langgraph-agent tourner avec une vue
périmée, silencieusement — une première tentative de campagne complète
Phase 1d-révisée a tourné entièrement sur un schéma figé avant même
l'activation réelle de `browser_extract`, invalidant tout le run sans
qu'aucune erreur ne le signale sur le coup. Ce module rend cette classe de
bug détectable AVANT de dépenser une campagne entière dessus.

EXPECTED_TOOLS n'est PAS une tentative d'énumération exhaustive du schéma
(la plupart des outils browser_* proviennent de l'image officielle
mcp/playwright, dont le nom exact de chaque tool n'est pas maintenu dans ce
dépôt — les deviner violerait la règle "toute affirmation sur le
comportement d'une lib se vérifie contre le code installé", CLAUDE.md #8).
Se limite donc à l'union des outils déjà nommés ailleurs dans CE dépôt :
les tiers de app/approval_policy.py (déjà la config de référence
maintenue) + browser_navigate (seul nom de tool browser_* littéralement
référencé dans app/graph.py, via le garde-fou de fabrication d'URL).
"""

import json
import subprocess
import time
from typing import Callable, Iterable, Optional

import app.approval_policy as policy

AGENT_CONTAINER = "langgraph-agent"
MCP_CLIENT_CONTAINER = "mcp-client"
TABBYAPI_CONTAINER = "tabbyapi"
TABBYAPI_IMAGE_TAG = "agentic-ai-playground-tabbyapi"

# Readiness LLM (outillage de campagne, voir HISTORY.md) : trouvé en
# conditions réelles — un `docker compose up --build langgraph-agent` a
# aussi recréé tabbyapi (dérive de config détectée) ; la campagne a démarré
# ~20s après "Model successfully loaded" mais AVANT que le serveur HTTP
# n'écoute réellement, produisant 30 échecs quasi instantanés
# (openai.APIConnectionError, capturé comme notice d'erreur interne) avant
# qu'aucune assertion n'ait pu révéler le problème. Le préambule
# précédent (check_tools_schema) ne vérifiait QUE le schéma d'outils via
# mcp-client, jamais que le backend LLM répond réellement à une
# complétion — angle mort désormais couvert par wait_for_llm_ready.
LLM_READY_TIMEOUT_SECONDS = 180
LLM_READY_POLL_INTERVAL_SECONDS = 5

EXPECTED_TOOLS = policy.TIER_READ_TOOLS | policy.TIER_REVERSIBLE_TOOLS | policy.NEVER_GRANTABLE_TOOLS | {
    "browser_navigate"
}


class PreflightError(RuntimeError):
    """Levée par run_preflight() : la campagne ne doit PAS démarrer."""


def check_tools_schema(agent_tools: Iterable[str], mcp_tools: Iterable[str]) -> Optional[str]:
    """
    Pure, unit-testable sans docker : None si tout va bien, sinon un message
    motivant le refus (comparaison AVANT expected, car une désynchronisation
    entre les deux services rend toute conclusion sur "l'attendu" trompeuse
    tant qu'elle n'est pas résolue).
    """
    agent_tools = set(agent_tools)
    mcp_tools = set(mcp_tools)
    if agent_tools != mcp_tools:
        missing_in_agent = sorted(mcp_tools - agent_tools)
        extra_in_agent = sorted(agent_tools - mcp_tools)
        return (
            "schéma d'outils désynchronisé entre langgraph-agent et mcp-client "
            f"(absents côté langgraph-agent={missing_in_agent}, superflus côté "
            f"langgraph-agent={extra_in_agent}) — _tools_schema_cache est probablement "
            "périmé, commande à taper : docker compose restart langgraph-agent"
        )
    missing_expected = sorted(EXPECTED_TOOLS - agent_tools)
    if missing_expected:
        return f"outils attendus absents du schéma effectif de langgraph-agent : {missing_expected}"
    return None


def _docker_exec_python(container: str, script: str, timeout: int = 30) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", container, "python3", "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise PreflightError(f"docker exec dans {container} a échoué (préambule) : {result.stderr}")
    return result.stdout


def _fetch_agent_tools() -> list:
    script = """
import urllib.request
with urllib.request.urlopen('http://localhost:8000/tools/schema', timeout=10) as r:
    print(r.read().decode())
"""
    return json.loads(_docker_exec_python(AGENT_CONTAINER, script)).get("tools", [])


def _fetch_mcp_tools() -> list:
    script = """
import json, urllib.request
with urllib.request.urlopen('http://localhost:8003/tools/schema', timeout=10) as r:
    body = json.loads(r.read().decode())
print(json.dumps(sorted({t["function"]["name"] for t in body.get("tools", [])})))
"""
    return json.loads(_docker_exec_python(MCP_CLIENT_CONTAINER, script))


def _fetch_llm_ready() -> bool:
    """
    Appel de complétion RÉEL (pas un /health) contre LLM_BASE_URL tel que vu
    par langgraph-agent lui-même (portable au backend alternatif
    llama-server, voir README « Backend d'inférence » — pas seulement
    TabbyAPI) : c'est la seule vérification qui aurait détecté le cas
    trouvé en conditions réelles (serveur pas encore à l'écoute malgré un
    modèle déjà chargé). enable_thinking=False + max_tokens=1 : le plus
    rapide possible, on ne veut qu'un finish_reason, pas une vraie réponse.
    """
    script = """
import json, os, urllib.request, urllib.error
base = os.environ.get('LLM_BASE_URL', 'http://tabbyapi:5000/v1').rstrip('/')
req = urllib.request.Request(
    base + '/chat/completions',
    data=json.dumps({
        'model': 'agent-llm',
        'messages': [{'role': 'user', 'content': 'ping'}],
        'max_tokens': 1,
        'enable_thinking': False,
    }).encode(),
    headers={'Content-Type': 'application/json'},
)
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print(r.status)
except Exception as e:
    print('ERROR', repr(e))
"""
    out = _docker_exec_python(AGENT_CONTAINER, script, timeout=15)
    return out.strip() == "200"


def _run_docker(args: list, timeout: int = 15) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise PreflightError(f"`docker {' '.join(args)}` a échoué (préambule) : {result.stderr.strip()}")
    return result.stdout.strip()


def _fetch_tabbyapi_image_ids() -> tuple:
    """(id de l'image RÉELLEMENT utilisée par le conteneur tabbyapi qui
    tourne, id de la dernière image construite localement pour ce tag) —
    voir check_tabbyapi_image_fresh."""
    running = _run_docker(["inspect", "--format", "{{.Image}}", TABBYAPI_CONTAINER])
    built = _run_docker(["image", "inspect", "--format", "{{.Id}}", TABBYAPI_IMAGE_TAG])
    return running, built


def check_tabbyapi_image_fresh(fetch_image_ids: Callable[[], tuple] = _fetch_tabbyapi_image_ids) -> Optional[str]:
    """
    Vérification du digest d'image (arbitrage post-1/2-ter, voir
    HISTORY.md, action 1) : détecte un conteneur tabbyapi qui tournerait
    sur une image DIFFÉRENTE de la dernière construite localement pour ce
    tag — ex. `docker compose build` exécuté sans le `up -d` qui applique
    le changement, ou un rollback d'image manuel oublié. Un tel écart
    laisserait tourner une campagne entière contre un modèle/une version
    différente de celle attendue, silencieusement (aucune erreur, juste un
    comportement différent) — même classe de risque que la désynchronisation
    de schéma d'outils que check_tools_schema détecte déjà côté
    langgraph-agent/mcp-client. Pure une fois fetch_image_ids injecté (voir
    tests/test_campaign_preflight.py) : aucun docker réel dans les tests.
    """
    running_id, built_id = fetch_image_ids()
    if running_id != built_id:
        return (
            f"le conteneur {TABBYAPI_CONTAINER} tourne sur une image différente de la dernière "
            f"construite pour {TABBYAPI_IMAGE_TAG} (running={running_id}, built={built_id}) — "
            "commande à taper : docker compose up -d --build tabbyapi"
        )
    return None


def wait_for_llm_ready(
    fetch_llm_ready: Callable[[], bool] = _fetch_llm_ready,
    *,
    timeout_seconds: int = LLM_READY_TIMEOUT_SECONDS,
    interval_seconds: int = LLM_READY_POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> None:
    """
    Interroge fetch_llm_ready jusqu'à succès ou expiration — voir
    LLM_READY_TIMEOUT_SECONDS plus haut pour la raison d'être. `sleep`/`now`
    injectables pour un test unitaire rapide (voir
    tests/test_campaign_preflight.py), sans vrai délai ni docker.
    """
    deadline = now() + timeout_seconds
    while not fetch_llm_ready():
        if now() >= deadline:
            raise PreflightError(
                f"LLM_BASE_URL ne répond pas à une complétion réelle après {timeout_seconds}s "
                "— vérifier `docker logs tabbyapi` (serveur pas encore démarré, ou crash au chargement)"
            )
        sleep(interval_seconds)


def run_preflight(
    *,
    purge_downloads: Callable[[], None],
    reset_browser_session: Callable[[], None],
    fetch_agent_tools: Callable[[], Iterable[str]] = _fetch_agent_tools,
    fetch_mcp_tools: Callable[[], Iterable[str]] = _fetch_mcp_tools,
    fetch_llm_ready: Callable[[], bool] = _fetch_llm_ready,
    fetch_tabbyapi_image_ids: Callable[[], tuple] = _fetch_tabbyapi_image_ids,
) -> None:
    """
    Appelé UNE fois par campagne (pas par répétition, contrairement à
    purge_downloads/reset_browser_session qui restent aussi appelés avant
    chaque répétition individuelle — voir test_web_tasks.py). Callables de
    fetch injectables pour permettre un test unitaire complet de
    l'orchestration sans docker (voir tests/test_campaign_preflight.py) ;
    purge_downloads/reset_browser_session restent des paramètres obligatoires
    plutôt que des défauts internes pour ne jamais dupliquer leur
    implémentation (déjà dans test_web_tasks.py, avec leurs propres raisons
    d'être documentées).

    Ordre : readiness LLM D'ABORD (le moins cher à constater EN ERREUR —
    inutile de comparer des schémas d'outils si le backend ne répond même
    pas), puis fraîcheur d'image tabbyapi (arbitrage post-1/2-ter, voir
    HISTORY.md), puis schéma d'outils, puis purge/reset.
    """
    wait_for_llm_ready(fetch_llm_ready)
    error = check_tabbyapi_image_fresh(fetch_tabbyapi_image_ids)
    if error:
        raise PreflightError(error)
    error = check_tools_schema(fetch_agent_tools(), fetch_mcp_tools())
    if error:
        raise PreflightError(error)
    purge_downloads()
    reset_browser_session()
