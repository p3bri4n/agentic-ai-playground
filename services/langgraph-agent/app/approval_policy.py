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
    "clipboard_get",  # lecture au sens outil, mais reste TIER_SENSITIVE : voir override ci-dessous
    "run_command",
    "read_file",
    "read_multiple_files",
    "list_directory",
    "directory_tree",
    "search_files",
    "get_file_info",
    "list_allowed_directories",
    "git_status",
    "git_diff_unstaged",
    "git_diff_staged",
    "git_diff",
    "git_log",
    "git_show",
    "git_branch",
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
    (Phase 3) ni des règles sur arguments (Phase 4) — voir approval_tier()
    une fois ces phases en place. Défaut = TIER_SENSITIVE."""
    if tool_name in TIER_READ_TOOLS:
        return TIER_READ
    if tool_name in TIER_REVERSIBLE_TOOLS or tool_name in AUTO_APPROVED_TOOLS:
        return TIER_REVERSIBLE
    return TIER_SENSITIVE


def is_auto_approved(tool_name: str) -> bool:
    return tool_tier(tool_name) in (TIER_READ, TIER_REVERSIBLE)
