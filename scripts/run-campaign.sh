#!/usr/bin/env bash
# Outillage de campagne (voir HISTORY.md, "OUTILLAGE DE CAMPAGNE") : lance le
# harnais de tâches web (services/langgraph-agent/tests_integration/
# test_web_tasks.py) de bout en bout, zéro intervention entre le lancement et
# le rapport. Enchaîne : préambule (readiness LLM réelle + schéma d'outils,
# voir campaign_preflight.py) -> campagne (complète ou smoke) -> rapport
# écrit -> notification de fin.
#
# Usage :
#   scripts/run-campaign.sh                        # campagne complète (11 tâches x 3)
#   scripts/run-campaign.sh --tasks T1,T7,T11       # smoke ciblé (voir SMOKE_TASK_PREFIXES)
#   scripts/run-campaign.sh --tasks T7 --reps 1     # smoke minimal, une seule tâche
#   scripts/run-campaign.sh --label "post-correctif-X"
#
# Protocole (voir docstring de test_web_tasks.py, WEB_TASKS_SMOKE_TASKS) :
# le mode smoke (--tasks) sert à ITÉRER vite sur un correctif — n réduit,
# pas de signification statistique pour arbitrer un seuil de passage. Seule
# la campagne complète (par défaut, --reps 3 sur les 11 tâches) compte
# comme mesure de référence pour un checkpoint.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
AGENT_DIR="$PROJECT_DIR/services/langgraph-agent"

TASKS=""
REPS=3
LABEL=""
REPORT_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tasks) TASKS="$2"; shift 2 ;;
    --reps) REPS="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --report-path) REPORT_PATH="$2"; shift 2 ;;
    *) echo "Argument inconnu : $1" >&2; exit 1 ;;
  esac
done

VENV_PYTHON="${VENV_PYTHON:-$AGENT_DIR/.venv/bin/python}"
if [[ ! -x "$VENV_PYTHON" ]]; then
  VENV_PYTHON="python3"
fi

if [[ -z "$REPORT_PATH" ]]; then
  if [[ -n "$LABEL" ]]; then
    REPORT_PATH="$AGENT_DIR/tests_integration/TASKS-BASELINE-${LABEL}.md"
  elif [[ -n "$TASKS" ]]; then
    REPORT_PATH="$AGENT_DIR/tests_integration/TASKS-SMOKE-$(date +%Y%m%d-%H%M%S).md"
  else
    REPORT_PATH="$AGENT_DIR/tests_integration/TASKS-BASELINE.md"
  fi
fi

STATS_PATH="$AGENT_DIR/tests_integration/CAMPAIGN_DURATION_STATS.json"

# ─────────────────────────────────────────────────────────────────────────
# Estimation de durée AVANT lancement (médiane courante x tâches x reps) —
# voir DURATION_STATS_PATH dans test_web_tasks.py, mis à jour à la fin de
# CHAQUE campagne précédente (smoke ou complète). Défaut 150s/tâche pour
# une tâche jamais mesurée (ordre de grandeur observé sur les campagnes
# passées, voir HISTORY.md) — approximatif par construction, sert à choisir
# smoke vs complète en connaissance de cause, pas à garantir un temps exact.
# ─────────────────────────────────────────────────────────────────────────
ALL_TASK_IDS=(T1_extraction_paginee T2_formulaire_conge T3_tableau_dynamique
  T4_recherche_multi_sauts T5_telechargement_calcul T6_session_authentifiee
  T7_impossible_par_construction T8_wikipedia T9_google_insee
  T10_books_toscrape T11_sonde_peremption)

"$VENV_PYTHON" - "$STATS_PATH" "$REPS" "$TASKS" "${ALL_TASK_IDS[@]}" <<'PYEOF'
import json
import sys

stats_path, reps, tasks_filter, *all_tasks = sys.argv[1:]
reps = int(reps)
prefixes = [p for p in tasks_filter.split(",") if p]

try:
    with open(stats_path, encoding="utf-8") as f:
        stats = json.load(f)
except (OSError, ValueError):
    stats = {}

DEFAULT_ESTIMATE_SECONDS = 150

selected = [t for t in all_tasks if not prefixes or any(t == p or t.startswith(p + "_") for p in prefixes)]
total_seconds = sum(stats.get(t, DEFAULT_ESTIMATE_SECONDS) for t in selected) * reps
minutes = total_seconds / 60

print(f"--- Estimation ({len(selected)} tache(s) x {reps} repetition(s) = {len(selected) * reps} runs) ---")
for t in selected:
    known = t in stats
    print(f"  {t:32s} {stats.get(t, DEFAULT_ESTIMATE_SECONDS):6.1f}s{'' if known else ' (jamais mesuree, defaut)'}")
print(f"--- Duree totale estimee : ~{minutes:.0f} min ({total_seconds:.0f}s) ---")
PYEOF

# ─────────────────────────────────────────────────────────────────────────
# Campagne : préambule (readiness LLM réelle + schéma d'outils) -> runs ->
# rapport écrit -> stats de durée mises à jour — tout depuis
# test_web_tasks_baseline (campaign_preflight.run_preflight en tête, voir
# ce module). RUN_LIVE_AGENT_TESTS=1 lève le skip d'opt-in.
# ─────────────────────────────────────────────────────────────────────────
export RUN_LIVE_AGENT_TESTS=1
export WEB_TASKS_REPORT_PATH="$REPORT_PATH"
export WEB_TASKS_REPETITIONS="$REPS"
export WEB_TASKS_SMOKE_TASKS="$TASKS"
[[ -n "$LABEL" ]] && export WEB_TASKS_CAMPAIGN_LABEL="$LABEL"

cd "$AGENT_DIR"
STATUS=0
"$VENV_PYTHON" -m pytest tests_integration/test_web_tasks.py::test_web_tasks_baseline -q -s -p no:cacheprovider \
  || STATUS=$?

# ─────────────────────────────────────────────────────────────────────────
# Notification de fin — défaut : fichier DONE à côté du rapport (zéro
# dépendance externe, toujours disponible). ntfy en plus si NTFY_TOPIC est
# défini (curl vers ntfy.sh, best-effort — un échec réseau n'écrase jamais
# le fichier DONE). mail en plus si MAIL_TO est défini ET que la commande
# `mail` existe.
# ─────────────────────────────────────────────────────────────────────────
DONE_PATH="${REPORT_PATH%.md}.DONE"
SCORE_LINE="$(grep -m1 '^\*\*Score de campagne' "$REPORT_PATH" 2>/dev/null || echo "(rapport absent, voir STATUS=$STATUS)")"
{
  echo "Campagne terminée : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Statut pytest : $STATUS"
  echo "Rapport : $REPORT_PATH"
  echo "$SCORE_LINE"
} > "$DONE_PATH"
echo "--- $(cat "$DONE_PATH") ---"

if [[ -n "${NTFY_TOPIC:-}" ]]; then
  curl -fsS -m 10 -d "$(cat "$DONE_PATH")" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null 2>&1 \
    || echo "avertissement : notification ntfy échouée (réseau ?)" >&2
fi

if [[ -n "${MAIL_TO:-}" ]] && command -v mail &>/dev/null; then
  mail -s "Campagne terminée ($STATUS)" "$MAIL_TO" < "$DONE_PATH" \
    || echo "avertissement : notification mail échouée" >&2
fi

exit "$STATUS"
