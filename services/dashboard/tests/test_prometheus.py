from app.prometheus import (
    extract_llama_metrics,
    normalize_slot,
    normalize_slots,
    parse_prometheus_text,
)

# Payload figé réaliste (format d'exposition Prometheus texte de
# llama-server --metrics) : commentaires # HELP/# TYPE mêlés aux métriques,
# comme un vrai /metrics.
LLAMA_METRICS_PAYLOAD = """\
# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 12345
# HELP llamacpp:prompt_tokens_seconds Average prompt throughput in tokens/s.
# TYPE llamacpp:prompt_tokens_seconds gauge
llamacpp:prompt_tokens_seconds 812.5
# HELP llamacpp:predicted_tokens_seconds Average generation throughput in tokens/s.
# TYPE llamacpp:predicted_tokens_seconds gauge
llamacpp:predicted_tokens_seconds 34.2
# HELP llamacpp:kv_cache_usage_ratio KV-cache usage ratio.
# TYPE llamacpp:kv_cache_usage_ratio gauge
llamacpp:kv_cache_usage_ratio 0.42
# HELP llamacpp:kv_cache_tokens KV-cache tokens.
# TYPE llamacpp:kv_cache_tokens gauge
llamacpp:kv_cache_tokens 13762
# HELP llamacpp:requests_processing Number of requests processing.
# TYPE llamacpp:requests_processing gauge
llamacpp:requests_processing 1
# HELP llamacpp:requests_deferred Number of requests deferred.
# TYPE llamacpp:requests_deferred gauge
llamacpp:requests_deferred 0
"""


def test_parse_prometheus_text_ignores_comments_and_reads_values():
    metrics = parse_prometheus_text(LLAMA_METRICS_PAYLOAD)
    assert metrics["llamacpp:predicted_tokens_seconds"] == 34.2
    assert metrics["llamacpp:requests_processing"] == 1.0
    assert "# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed." not in metrics


def test_parse_prometheus_text_ignores_unparsable_lines():
    text = "not a metric line\nllamacpp:requests_processing 2\ngarbage{label=x} notanumber\n"
    metrics = parse_prometheus_text(text)
    assert metrics == {"llamacpp:requests_processing": 2.0}


def test_extract_llama_metrics_returns_stable_keys():
    metrics = extract_llama_metrics(LLAMA_METRICS_PAYLOAD)
    assert metrics == {
        "decode_tokens_per_sec": 34.2,
        "prefill_tokens_per_sec": 812.5,
        "kv_cache_usage_ratio": 0.42,
        "kv_cache_tokens": 13762.0,
        "requests_processing": 1.0,
        "requests_deferred": 0.0,
    }


def test_extract_llama_metrics_missing_metric_is_none():
    metrics = extract_llama_metrics("llamacpp:requests_processing 3\n")
    assert metrics["decode_tokens_per_sec"] is None
    assert metrics["requests_processing"] == 3.0


def test_normalize_slot_picks_first_known_used_token_key():
    assert normalize_slot({"id": 0, "n_ctx": 32768, "is_processing": True, "n_past": 512}) == {
        "id": 0,
        "n_ctx": 32768,
        "is_processing": True,
        "used_tokens": 512,
    }
    # tokens_predicted utilisé si n_past absent
    assert normalize_slot({"id": 1, "n_ctx": 4096, "tokens_predicted": 10})["used_tokens"] == 10
    # aucune clé connue -> None plutôt qu'une erreur
    assert normalize_slot({"id": 2, "n_ctx": 4096})["used_tokens"] is None


def test_normalize_slots_filters_non_dict_entries():
    slots = normalize_slots([{"id": 0, "n_ctx": 1024, "n_past": 5}, "garbage", None])
    assert slots == [{"id": 0, "n_ctx": 1024, "is_processing": False, "used_tokens": 5}]
