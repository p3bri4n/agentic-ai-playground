"""
Parser Prometheus minimal maison pour GET /metrics de llama-server
(--metrics, voir README). Pas de dépendance à la lib officielle
prometheus_client (côté parsing, inutile ici) : seules ~6 métriques
"llamacpp:*" nous intéressent, un parser ligne à ligne suffit largement.
"""

from typing import Optional

# Noms exposés par llama-server (convention "llamacpp:<nom>", voir
# --metrics dans son README) mappés vers des clés stables côté dashboard,
# indépendantes du nom Prometheus exact.
_METRIC_KEYS = {
    "decode_tokens_per_sec": "llamacpp:predicted_tokens_seconds",
    "prefill_tokens_per_sec": "llamacpp:prompt_tokens_seconds",
    "kv_cache_usage_ratio": "llamacpp:kv_cache_usage_ratio",
    "kv_cache_tokens": "llamacpp:kv_cache_tokens",
    "requests_processing": "llamacpp:requests_processing",
    "requests_deferred": "llamacpp:requests_deferred",
}


def parse_prometheus_text(text: str) -> dict[str, float]:
    """
    Extrait `metric_name -> valeur` d'un corps au format d'exposition
    Prometheus texte. Ignore les lignes `# HELP`/`# TYPE` et les labels
    (`metric_name{label="x"} value` -> clé `metric_name`, labels jetés :
    llama-server n'en met pas sur les métriques qui nous intéressent ici).
    Une ligne illisible (valeur non numérique, format inattendu) est
    ignorée plutôt que de faire échouer tout le parsing.
    """
    metrics: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name_part, _, value_part = line.rpartition(" ")
        if not name_part:
            continue
        name = name_part.split("{", 1)[0]
        try:
            metrics[name] = float(value_part)
        except ValueError:
            continue
    return metrics


def extract_llama_metrics(text: str) -> dict[str, Optional[float]]:
    """Sous-ensemble utile au dashboard, valeur `None` si la métrique est absente du payload."""
    raw = parse_prometheus_text(text)
    return {key: raw.get(prom_name) for key, prom_name in _METRIC_KEYS.items()}


# Clés retenues d'un slot /slots (voir README llama-server, --slots) : le
# nom du champ contenant le nombre de tokens de contexte déjà occupés par ce
# slot diffère selon la version (n_past historiquement, tokens_predicted /
# n_tokens sur des builds plus récents) — on prend le premier présent plutôt
# que de dépendre d'un seul nom exact.
_SLOT_USED_TOKEN_KEYS = ("n_past", "tokens_predicted", "n_tokens")


def normalize_slot(slot: dict) -> dict:
    used_tokens = next((slot[key] for key in _SLOT_USED_TOKEN_KEYS if key in slot), None)
    return {
        "id": slot.get("id"),
        "n_ctx": slot.get("n_ctx"),
        "is_processing": bool(slot.get("is_processing", False)),
        "used_tokens": used_tokens,
    }


def normalize_slots(slots: list) -> list[dict]:
    return [normalize_slot(s) for s in slots if isinstance(s, dict)]
