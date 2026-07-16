"""
Journal d'audit (Phase 2) : trace machine-lisible de chaque tool_call
TIER_REVERSIBLE effectivement exécuté (auto-approuvé silencieusement, ou
après approbation humaine explicite d'un tour mixte/streak-limit — voir
call_tools, app/graph.py). Les tool_calls TIER_READ ne sont volontairement
PAS tracés (silencieux par design, rien de nouveau à auditer), pas plus que
les TIER_SENSITIVE (déjà tracés dans l'historique de conversation via le
message "⚠️ Approbation requise" et la réponse "approuver"/"refuser").

Un fichier JSONL par jour (rotation simple par nom de fichier, pas de
compaction/rétention automatique — à ajouter côté opérationnel si le volume
le justifie), sous AUDIT_LOG_DIR (défaut /workspace/.audit, partagé avec les
serveurs MCP filesystem/git/terminal via le même bind mount, voir
docker-compose.yml).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

AUDIT_LOG_DIR = os.environ.get("AUDIT_LOG_DIR", "/workspace/.audit")


def _log_path_for(when: datetime) -> Path:
    return Path(AUDIT_LOG_DIR) / f"{when.strftime('%Y-%m-%d')}.jsonl"


def log_tool_call(thread_id: str, tool_name: str, arguments: dict, tier: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "thread_id": thread_id,
        "tool": tool_name,
        "arguments": arguments,
        "tier": tier,
    }
    path = _log_path_for(datetime.now(timezone.utc))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_entries(thread_id: Optional[str] = None) -> list:
    """
    Relit tous les fichiers journaliers (potentiellement plusieurs si la
    conversation a traversé un changement de jour), triés par timestamp,
    optionnellement filtrés par thread_id. Usage : GET /audit (app/main.py).
    Une ligne corrompue individuelle est ignorée plutôt que de faire
    échouer toute la lecture — le journal reste consultable même si un
    écrivain a été interrompu en plein milieu d'une ligne.
    """
    root = Path(AUDIT_LOG_DIR)
    if not root.exists():
        return []

    entries = []
    for path in sorted(root.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if thread_id is None or entry.get("thread_id") == thread_id:
                    entries.append(entry)

    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries
