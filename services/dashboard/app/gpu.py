"""
VRAM des GPU via `nvidia-smi` (subprocess, best-effort). Actif uniquement si
ENABLE_GPU_STATS=true (voir app/main.py) : sans GPU visible dans le
conteneur (pas de runtime nvidia dans docker-compose.yml), la commande est
absente ou échoue — dans les deux cas, section renvoyée à None plutôt qu'une
erreur qui ferait échouer tout /api/snapshot.
"""

import subprocess
from typing import Optional

_NVIDIA_SMI_ARGS = [
    "nvidia-smi",
    "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
    "--format=csv,noheader,nounits",
]


def run_nvidia_smi(timeout: float = 2.0) -> Optional[str]:
    """
    Isolé dans sa propre fonction pour rester facilement mockable en test
    (monkeypatch de cette seule fonction) sans dépendre d'un vrai binaire
    nvidia-smi ni d'un GPU réel.
    """
    try:
        result = subprocess.run(_NVIDIA_SMI_ARGS, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def parse_nvidia_smi_csv(text: str) -> list[dict]:
    gpus = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5:
            continue
        index, name, mem_used, mem_total, util = parts
        try:
            gpus.append(
                {
                    "index": int(index),
                    "name": name,
                    "memory_used_mib": int(mem_used),
                    "memory_total_mib": int(mem_total),
                    "utilization_pct": int(util),
                }
            )
        except ValueError:
            continue
    return gpus
