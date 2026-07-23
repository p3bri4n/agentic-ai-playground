"""
Politique d'approbation par tiers de réversibilité.

Remplace la whitelist binaire historique (AUTO_APPROVED_TOOLS : auto ou pas)
par trois tiers, du moins au plus risqué :

  TIER_READ       : auto, silencieux. Introspection pure ou lecture seule —
                    rien à exfiltrer, rien à défaire.
  TIER_REVERSIBLE : auto + journalisation (voir Phase 2, journal d'audit).
                    Effet de bord, mais réversible et confiné (souris/clavier
                    GhostDesk, écritures filesystem sous /workspace, git
                    local...).
  TIER_SENSITIVE  : approbation humaine requise. Saisie de texte libre, tout
                    le reste, ET tout outil inconnu — le défaut est TOUJOURS
                    le tier le plus restrictif, jamais l'inverse : un outil
                    qui n'apparaît dans aucune liste ci-dessous n'est PAS
                    auto-approuvé.

Routage (voir has_tool_calls, app/graph.py) : un tour est auto-approuvé si
TOUS ses tool_calls sont en tier 1 ou 2 — un seul outil en tier sensible
(même mélangé à des outils auto-approuvés) soumet tout le tour à
approbation, pas d'approbation partielle par outil.

Rétrocompatibilité : AUTO_APPROVED_TOOLS (ancienne variable d'env) continue
de fonctionner comme override — tout outil qui y figure est traité comme
tier 2 (auto + audit) même s'il n'est dans aucune des listes par défaut
ci-dessous.
"""

import os
from typing import Optional

TIER_READ = "read"
TIER_REVERSIBLE = "reversible"
TIER_SENSITIVE = "sensitive"

# Ordre de restriction croissante, utilisé pour arbitrer les ambiguïtés
# (Phase 4 : plusieurs règles qui matchent le même outil) — le tier le plus
# restrictif gagne toujours.
_TIER_RANK = {TIER_READ: 0, TIER_REVERSIBLE: 1, TIER_SENSITIVE: 2}

# Introspection pure (aucun effet de bord) et lecture seule : rien à
# exfiltrer, rien à défaire. Reprend le sous-ensemble "lecture" de l'ancien
# AUTO_APPROVED_TOOLS (app_list, app_running, screen_shot, mouse_move) ainsi
# que les outils de lecture des serveurs MCP filesystem/git officiels et
# run_command de mcp-terminal (déjà une liste blanche stricte en lecture
# seule, voir services/mcp-terminal/server.py).
_DEFAULT_TIER_READ = {
    "app_list",
    "app_running",
    "app_status",
    "screen_shot",
    "mouse_move",
    "find_text",  # OCR d'appoint (ocr-service) : lecture pure, aucun effet de bord
    "read_screen",
    # Localisation/extraction ciblée dans la page (Phase 1d-révisée, voir
    # HISTORY.md "correctif extraction") : lecture pure malgré son
    # implémentation interne via browser_evaluate (mcp-client) — le modèle ne
    # fournit qu'un texte à chercher, jamais de code (voir
    # services/mcp-client/app/main.py, _build_extract_function : template JS
    # FIXE, requête interpolée via json.dumps).
    "browser_extract",
    "clipboard_get",  # lecture au sens outil, mais reste TIER_SENSITIVE : voir override ci-dessous
    "run_command",
    "read_file",
    "read_multiple_files",
    "list_directory",
    "directory_tree",
    "search_files",
    "get_file_info",
    "list_allowed_directories",
    # "git_branch" a été retiré d'ici (trouvé et corrigé pendant la sonde
    # live de l'Itération 4, Phase 1 « cœur cognitif ») : ce nom n'a jamais
    # correspondu à un outil réel du serveur MCP git officiel (12 outils
    # vérifiés via GET /tools/schema, mcp-client ET langgraph-agent
    # d'accord) — seul "git_create_branch" (déjà dans _DEFAULT_TIER_REVERSIBLE
    # ci-dessous) existe pour la gestion des branches. Resté inoffensif en
    # usage réel (un outil jamais proposé au modèle n'est jamais appelé),
    # mais faussait tests_integration/campaign_preflight.py:EXPECTED_TOOLS.
    "git_status",
    "git_diff_unstaged",
    "git_diff_staged",
    "git_diff",
    "git_log",
    "git_show",
}

# Effet de bord réversible et confiné : souris/clavier GhostDesk (hors saisie
# de texte libre), écritures filesystem sous /workspace, opérations git
# locales non destructrices.
_DEFAULT_TIER_REVERSIBLE = {
    "mouse_click",
    "mouse_double_click",
    "mouse_drag",
    "mouse_scroll",
    "key_press",
    "app_launch",
    "clipboard_set",
    "write_file",
    "edit_file",
    "create_directory",
    "move_file",
    "git_add",
    "git_commit",
    "git_create_branch",
    "git_checkout",
    "git_reset",
    "git_init",
}

# clipboard_get exclu volontairement du tier lecture malgré son nom : il peut
# exfiltrer des données sensibles copiées par l'utilisateur (mot de passe,
# jeton...), pas moins sensible que clipboard_set (voir README). Retiré ici
# plutôt que de ne jamais l'ajouter ci-dessus, pour que la liste _DEFAULT_
# TIER_READ reste lisible comme "tout ce qui ressemble à de la lecture" et
# que cette exception saute aux yeux à la relecture.
_DEFAULT_TIER_READ.discard("clipboard_get")

# Jamais accordable pour la session (Phase 1d-révisée, voir HISTORY.md, T5) :
# exécution de code arbitraire dans la page (JS non contraint) — une
# élévation, pas une primitive de lecture, quel que soit le nombre de fois
# où un humain l'a déjà approuvée dans ce thread. Ces deux outils restent
# TIER_SENSITIVE par défaut (absents de toute liste ci-dessus) ; ce
# qu'ajoute NEVER_GRANTABLE_TOOLS est l'interdiction de l'assouplissement
# normalement permis par un grant de session (voir effective_tier) —
# "approuver pour la session" reste sans effet sur ces deux-là : chaque
# appel requiert une approbation explicite, individuelle.
NEVER_GRANTABLE_TOOLS = {"browser_run_code_unsafe", "browser_evaluate"}


def _load_tier_override(env_var: str, default: set) -> set:
    raw = os.environ.get(env_var)
    if raw is None:
        return set(default)
    return set(filter(None, raw.split(",")))


TIER_READ_TOOLS = _load_tier_override("TIER_READ_TOOLS", _DEFAULT_TIER_READ)
TIER_REVERSIBLE_TOOLS = _load_tier_override("TIER_REVERSIBLE_TOOLS", _DEFAULT_TIER_REVERSIBLE)

# Override rétrocompatible : un outil listé ici est traité comme tier 2 (auto
# + audit) même s'il n'apparaît dans aucune des deux listes ci-dessus. Vide
# par défaut — les anciens défauts d'AUTO_APPROVED_TOOLS sont désormais déjà
# couverts par _DEFAULT_TIER_READ/_DEFAULT_TIER_REVERSIBLE, donc ce nouveau
# défaut vide reproduit le même comportement pour un déploiement qui ne
# fixe pas cette variable.
AUTO_APPROVED_TOOLS = set(filter(None, os.environ.get("AUTO_APPROVED_TOOLS", "").split(",")))


def tool_tier(tool_name: str) -> str:
    """Tier statique d'un outil, sans tenir compte des grants de session
    (Phase 3) ni des règles sur arguments (Phase 4) — voir effective_tier()
    pour la résolution complète. Défaut = TIER_SENSITIVE."""
    if tool_name in TIER_READ_TOOLS:
        return TIER_READ
    if tool_name in TIER_REVERSIBLE_TOOLS or tool_name in AUTO_APPROVED_TOOLS:
        return TIER_REVERSIBLE
    return TIER_SENSITIVE


def effective_tier(tool_name: str, args=None, session_grants=None) -> str:
    """
    Tier réel d'un tool_call précis (nom + arguments) pour CE thread :

      1. Règles sur arguments (Phase 4, voir plus bas) : si au moins une
         règle nommée pour cet outil matche ces arguments, son tier
         l'emporte sur le tier statique de l'outil — PAS un ET logique avec
         celui-ci. Si plusieurs règles matchent avec des tiers différents,
         le plus restrictif gagne (ambiguïté).
      2. Sinon, tier statique de l'outil (tool_tier(), sans regard aux
         arguments ni aux grants).
      3. Grants de session (Phase 3, voir AgentState.session_grants dans
         app/graph.py) : si le résultat des deux étapes précédentes est
         TIER_SENSITIVE et que l'outil est dans session_grants, plafonné à
         TIER_REVERSIBLE. Un grant ne peut qu'assouplir, jamais durcir — un
         outil déjà TIER_READ/TIER_REVERSIBLE n'est pas affecté par cette
         étape.
    """
    rule_tier = _match_rules(tool_name, args or {})
    resolved = rule_tier if rule_tier is not None else tool_tier(tool_name)
    if (
        resolved == TIER_SENSITIVE
        and session_grants
        and tool_name in session_grants
        and tool_name not in NEVER_GRANTABLE_TOOLS
    ):
        return TIER_REVERSIBLE
    return resolved


def is_auto_approved(tool_name: str, args=None, session_grants=None) -> bool:
    return effective_tier(tool_name, args, session_grants) in (TIER_READ, TIER_REVERSIBLE)


# ─────────────────────────────────────────────────────────────────────────
# Phase 4 : règles sur arguments ("outil(pattern)", à la Claude Code) —
# permettent d'affiner le tier d'un outil selon SES ARGUMENTS plutôt que son
# seul nom. Implémentation minimale volontaire : des matchers nommés en
# Python (pas de DSL de pattern générique à parser/valider), une table de
# règles ci-dessous, surchargeable/complétable via un fichier YAML optionnel
# (APPROVAL_RULES_PATH).
# ─────────────────────────────────────────────────────────────────────────


class Rule:
    __slots__ = ("tool", "matcher", "tier")

    def __init__(self, tool: str, matcher, tier: str):
        self.tool = tool
        self.matcher = matcher
        self.tier = tier


def _matcher_any(args: dict) -> bool:
    return True


def _matcher_key_type_short(args: dict) -> bool:
    """key_type(len<50,no_newline) : saisie courte et sans retour à la ligne
    — assez anodin pour ne pas justifier une approbation à chaque frappe,
    contrairement à un texte long ou multi-lignes (rédaction de code, script
    collé...), qui reste TIER_SENSITIVE par défaut (tool_tier)."""
    text = args.get("text", "")
    return len(text) < 50 and "\n" not in text


def _matcher_command_prefix(prefixes):
    """commandes terminal par préfixe, ex. run_command(prefix:git status)."""

    def _match(args: dict) -> bool:
        command = args.get("command", "")
        return any(command == p or command.startswith(p + " ") for p in prefixes)

    return _match


# Registre des matchers surchargeables par nom depuis un fichier YAML (voir
# _load_rules_from_yaml) — "command_prefix" attend un paramètre ("prefixes"),
# les autres sont utilisés tels quels.
_MATCHER_REGISTRY = {
    "any": _matcher_any,
    "key_type_short": _matcher_key_type_short,
    "command_prefix": _matcher_command_prefix,
}

# key_type(*) reste TIER_SENSITIVE par défaut : tool_tier("key_type") le
# classe déjà ainsi (absent de TIER_READ_TOOLS/TIER_REVERSIBLE_TOOLS), donc
# nul besoin d'une règle catch-all explicite ici — seule l'exception (saisie
# courte) a besoin d'une règle.
DEFAULT_RULES = [
    Rule("key_type", _matcher_key_type_short, TIER_REVERSIBLE),
]


def _load_rules_from_yaml(path: str) -> list:
    import yaml  # import paresseux : seuls les déploiements qui fixent APPROVAL_RULES_PATH en ont besoin

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    rules = []
    for item in data.get("rules", []):
        matcher_name = item["matcher"]
        factory = _MATCHER_REGISTRY[matcher_name]
        matcher = factory(item["prefixes"]) if matcher_name == "command_prefix" else factory
        rules.append(Rule(item["tool"], matcher, item["tier"]))
    return rules


def _load_rules() -> list:
    rules = list(DEFAULT_RULES)
    path = os.environ.get("APPROVAL_RULES_PATH")
    if path:
        rules += _load_rules_from_yaml(path)
    return rules


RULES = _load_rules()


def _match_rules(tool_name: str, args: dict) -> Optional[str]:
    matched = [r.tier for r in RULES if r.tool == tool_name and r.matcher(args)]
    if not matched:
        return None
    return max(matched, key=lambda t: _TIER_RANK[t])
