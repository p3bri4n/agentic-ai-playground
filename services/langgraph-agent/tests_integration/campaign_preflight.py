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
from typing import Callable, Iterable, Optional

import app.approval_policy as policy

AGENT_CONTAINER = "langgraph-agent"
MCP_CLIENT_CONTAINER = "mcp-client"

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


def run_preflight(
    *,
    purge_downloads: Callable[[], None],
    reset_browser_session: Callable[[], None],
    fetch_agent_tools: Callable[[], Iterable[str]] = _fetch_agent_tools,
    fetch_mcp_tools: Callable[[], Iterable[str]] = _fetch_mcp_tools,
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
    """
    error = check_tools_schema(fetch_agent_tools(), fetch_mcp_tools())
    if error:
        raise PreflightError(error)
    purge_downloads()
    reset_browser_session()
