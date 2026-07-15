#!/usr/bin/env bash
# Affiche la/les dernière(s) conversation(s) Open WebUI avec langgraph-agent,
# reconstruites depuis webui.db (raisonnement + message pour chaque tour,
# dans l'ordre réel de la branche active). Évite de refaire à la main les
# requêtes sqlite ad hoc à chaque session de debug.
#
# Usage :
#   scripts/last-chat.sh                  # dernière conversation
#   scripts/last-chat.sh -n 3             # 3 dernières conversations
#   scripts/last-chat.sh -q google         # conversations dont le titre matche "google"
#   scripts/last-chat.sh --raw             # + JSON brut du dernier message (done/error/tool_calls/childrenIds)
set -euo pipefail

CONTAINER="${OPEN_WEBUI_CONTAINER:-open-webui}"

docker exec -i "$CONTAINER" python3 - "$@" <<'PYEOF'
import argparse
import json
import sqlite3
from datetime import datetime

DB_PATH = "/app/backend/data/webui.db"


def text_of(item):
    content = item.get("content")
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content if isinstance(c, dict))
    return content or ""


def render_message(m):
    role = m.get("role", "?")
    content = m.get("content") or ""
    if not content and m.get("output"):
        # Open WebUI récent : content vide, tout est dans "output" (voir
        # PendingCheckRequest, services/langgraph-agent/app/main.py) —
        # reasoning et message séparés, à recombiner pour lecture humaine.
        parts = []
        for item in m["output"]:
            txt = text_of(item)
            if not txt:
                continue
            prefix = "[reasoning] " if item.get("type") == "reasoning" else ""
            parts.append(prefix + txt)
        content = "\n".join(parts)
    return f"--- {role} ({m.get('id', '')[:8]}) ---\n{content}\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=1, help="nombre de conversations à afficher")
    parser.add_argument("-q", default=None, help="filtre sur le titre (LIKE %%q%%)")
    parser.add_argument("--raw", action="store_true", help="dump JSON brut du dernier message de chaque conversation")
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    if args.q:
        cur.execute(
            "SELECT id, title, chat, updated_at FROM chat WHERE title LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (f"%{args.q}%", args.n),
        )
    else:
        cur.execute("SELECT id, title, chat, updated_at FROM chat ORDER BY updated_at DESC LIMIT ?", (args.n,))

    rows = cur.fetchall()
    if not rows:
        print("Aucune conversation trouvée.")
        return

    for chat_id, title, chat_json, updated_at in rows:
        data = json.loads(chat_json)
        hist = data.get("history", {})
        messages = hist.get("messages", {})
        print(f"===== {title} ({chat_id}) — {datetime.fromtimestamp(updated_at)} =====")

        # Suit la branche active (parentId en remontant depuis currentId),
        # pas l'ordre d'insertion du dict : nécessaire dès qu'il y a eu une
        # régénération de réponse (branches multiples dans messages).
        chain = []
        mid = hist.get("currentId")
        seen = set()
        while mid and mid in messages and mid not in seen:
            seen.add(mid)
            m = messages[mid]
            chain.append(m)
            mid = m.get("parentId")
        chain.reverse()
        if not chain:
            chain = list(messages.values())

        for m in chain:
            print(render_message(m))

        if args.raw and chain:
            print("--- raw (dernier message) ---")
            print(json.dumps(chain[-1], indent=2, ensure_ascii=False))
        print()


main()
PYEOF
