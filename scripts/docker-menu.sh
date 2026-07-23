#!/usr/bin/env bash
# Menu interactif (navigation clavier via whiptail) pour piloter les conteneurs
# du docker-compose.yml : tout démarrer/arrêter, rebuild ou logs d'un service
# en particulier. Nécessite `whiptail` (paquet `whiptail` ou `newt`, déjà
# présent sur la plupart des distros).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

DC=(docker compose)

if ! command -v whiptail &>/dev/null; then
  echo "whiptail est requis (ex : sudo apt install whiptail)." >&2
  exit 1
fi

# Pause "appuyez sur une touche" après une commande, pour lire la sortie
# avant de revenir au menu.
pause() {
  echo
  read -n 1 -s -r -p "Appuyez sur une touche pour revenir au menu..."
}

pick_service() {
  local title="$1"
  mapfile -t services < <("${DC[@]}" config --services | sort)
  local items=()
  for s in "${services[@]}"; do
    items+=("$s" "")
  done
  whiptail --title "$title" --menu "Choisissez un service :" 20 60 12 \
    "${items[@]}" 3>&1 1>&2 2>&3
}

action_start_all() {
  clear
  echo "==> Démarrage de tous les conteneurs..."
  "${DC[@]}" up -d
  pause
}

action_stop_all() {
  clear
  echo "==> Arrêt de tous les conteneurs..."
  "${DC[@]}" down
  pause
}

action_restart_all() {
  clear
  echo "==> Redémarrage de tous les conteneurs..."
  "${DC[@]}" restart
  pause
}

action_rebuild_one() {
  local svc
  svc=$(pick_service "Rebuild un service") || return
  [ -z "$svc" ] && return
  clear
  echo "==> Rebuild + relance de '$svc'..."
  "${DC[@]}" build "$svc"
  "${DC[@]}" up -d "$svc"
  pause
}

action_restart_one() {
  local svc
  svc=$(pick_service "Redémarrer un service") || return
  [ -z "$svc" ] && return
  clear
  echo "==> Redémarrage de '$svc'..."
  "${DC[@]}" restart "$svc"
  pause
}

action_logs_one() {
  local svc
  svc=$(pick_service "Logs d'un service") || return
  [ -z "$svc" ] && return
  clear
  echo "==> Logs de '$svc' (Ctrl+C pour revenir au menu)..."
  "${DC[@]}" logs -f --tail=200 "$svc" || true
  pause
}

action_status() {
  clear
  "${DC[@]}" ps
  pause
}

main_menu() {
  whiptail --title "Docker - agentic-ai-playground" --menu "Choisissez une action :" 20 70 10 \
    "1" "Démarrer tous les conteneurs" \
    "2" "Arrêter tous les conteneurs" \
    "3" "Redémarrer tous les conteneurs" \
    "4" "Rebuild un service en particulier" \
    "5" "Redémarrer un service en particulier" \
    "6" "Voir les logs d'un service" \
    "7" "Statut des conteneurs" \
    "8" "Quitter" \
    3>&1 1>&2 2>&3
}

while true; do
  choice=$(main_menu) || exit 0
  case "$choice" in
    1) action_start_all ;;
    2) action_stop_all ;;
    3) action_restart_all ;;
    4) action_rebuild_one ;;
    5) action_restart_one ;;
    6) action_logs_one ;;
    7) action_status ;;
    8) exit 0 ;;
  esac
done
