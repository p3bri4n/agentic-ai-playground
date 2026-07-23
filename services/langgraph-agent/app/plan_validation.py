"""
Heuristiques programmatiques de validation du plan (Itération 3, Phase 1
« cœur cognitif » — voir docs/briefs/phase-1-coeur-cognitif.md). Module
autonome, testable sans docker/LLM/état du graphe : seule entrée,
`validate_plan_heuristics`, prend le plan et son contexte en arguments
plutôt que d'aller les chercher elle-même.

`_URL_RE` est délibérément DUPLIQUÉ depuis app/graph.py (pas importé) :
app/graph.py importe ce module pour l'appeler depuis validate_plan — un
import réciproque créerait un cycle d'import. Le duplicata est un seul
regex de quelques caractères, la duplication documentée est préférable à
introduire un troisième module juste pour l'héberger.
"""

import re
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s'\")\]]+")

SUBTASKS_MIN = 2
SUBTASKS_MAX = 12


def _domain(url: str) -> str:
    return urlparse(url).netloc


def validate_plan_heuristics(plan: list, *, known_tools: set, task_scope_urls: set) -> list:
    """
    Retourne les motifs de rejet (liste vide = plan valide) :
      - bornes de taille (SUBTASKS_MIN..SUBTASKS_MAX) ;
      - pas de doublons (paire description+critère identique à une autre) ;
      - outils référencés existants (`known_tools`, schéma effectif de
        langgraph-agent — voir _get_tools_schema, app/graph.py) ;
      - domaines mentionnés dans le périmètre déclaré (URL trouvées dans le
        texte des sous-tâches, comparées par DOMAINE à `task_scope_urls` —
        même page ou autre chemin du même site autorisé, domaine différent
        rejeté).

    "Pas de cycles" : N/A, non vérifié — le plan est une liste séquentielle,
    aucune structure de dépendance n'existe pour qu'un cycle soit seulement
    définissable.
    "Cohérence de tier" : vérifiée par construction ailleurs (le tier du
    plan, calculé dans app/graph.py, dérive UNIQUEMENT des outils déclarés
    ici — pas de tier "tâche" séparé à comparer, ce concept appartient à la
    Phase 3 du PLAN.md, pas encore construite).
    """
    reasons = []
    if not (SUBTASKS_MIN <= len(plan) <= SUBTASKS_MAX):
        reasons.append(
            f"nombre de sous-tâches hors bornes ({len(plan)}, attendu {SUBTASKS_MIN}-{SUBTASKS_MAX})"
        )

    scope_domains = {_domain(u) for u in task_scope_urls if _domain(u)}
    seen = set()
    for i, subtask in enumerate(plan):
        key = (subtask.get("description"), subtask.get("success_criterion"))
        if key in seen:
            reasons.append(f"sous-tâche {i} dupliquée (description+critère identiques à une autre)")
        seen.add(key)

        for tool in subtask.get("tools", []):
            if tool not in known_tools:
                reasons.append(f"sous-tâche {i} référence un outil inconnu : {tool}")

        text = f"{subtask.get('description', '')} {subtask.get('success_criterion', '')}"
        for url in _URL_RE.findall(text):
            domain = _domain(url)
            if scope_domains and domain and domain not in scope_domains:
                reasons.append(f"sous-tâche {i} référence un domaine hors périmètre : {domain}")

    return reasons
