from app.gpu import parse_nvidia_smi_csv

NVIDIA_SMI_PAYLOAD = (
    "0, NVIDIA GeForce RTX 5060 Ti, 8192, 16384, 55\n"
    "1, NVIDIA GeForce RTX 5060 Ti, 4096, 16384, 12\n"
)


def test_parse_nvidia_smi_csv_two_gpus():
    gpus = parse_nvidia_smi_csv(NVIDIA_SMI_PAYLOAD)
    assert gpus == [
        {
            "index": 0,
            "name": "NVIDIA GeForce RTX 5060 Ti",
            "memory_used_mib": 8192,
            "memory_total_mib": 16384,
            "utilization_pct": 55,
        },
        {
            "index": 1,
            "name": "NVIDIA GeForce RTX 5060 Ti",
            "memory_used_mib": 4096,
            "memory_total_mib": 16384,
            "utilization_pct": 12,
        },
    ]


def test_parse_nvidia_smi_csv_ignores_malformed_lines():
    assert parse_nvidia_smi_csv("garbage line\n\n0, GPU, 1, 2, 3\n") == [
        {"index": 0, "name": "GPU", "memory_used_mib": 1, "memory_total_mib": 2, "utilization_pct": 3}
    ]


def test_parse_nvidia_smi_csv_empty_text():
    assert parse_nvidia_smi_csv("") == []
