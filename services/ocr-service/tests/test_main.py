"""
Tests de bout en bout de find_text/read_screen : @mcp.tool() (SDK mcp)
renvoie la fonction Python d'origine inchangée, donc appelable directement
ici (pas besoin de faire tourner ocr-service lui-même comme process HTTP
séparé). Seule la capture GhostDesk est un vrai aller-retour réseau, contre
un faux serveur MCP GhostDesk en Streamable HTTP (tests/fixtures/
fake_ghostdesk_server.py), sur le modèle des fixtures HTTP de mcp-client.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.ocr_engine import set_fake_detections

FAKE_GHOSTDESK_PATH = Path(__file__).parent / "fixtures" / "fake_ghostdesk_server.py"

IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 1024


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError(f"le faux serveur GhostDesk n'a pas démarré sur le port {port}")


@pytest.fixture
def fake_ghostdesk(monkeypatch):
    """Démarre le faux GhostDesk et pointe app.main vers lui."""
    port = _free_port()
    token = "ghostdesk-secret"
    proc = subprocess.Popen(
        [sys.executable, str(FAKE_GHOSTDESK_PATH), str(port), token, str(IMAGE_WIDTH), str(IMAGE_HEIGHT)]
    )
    try:
        _wait_for_port(port)

        import app.main as main_mod

        monkeypatch.setattr(main_mod, "GHOSTDESK_URL", f"http://127.0.0.1:{port}/mcp")
        monkeypatch.setattr(main_mod, "GHOSTDESK_AUTH_TOKEN", token)
        yield main_mod
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def _detection(text, x, y, width, height, confidence):
    return {"text": text, "x": x, "y": y, "width": width, "height": height, "confidence": confidence}


@pytest.mark.asyncio
async def test_find_text_returns_matches_sorted_by_confidence(fake_ghostdesk):
    set_fake_detections(
        [
            _detection("Fichier", x=10, y=10, width=80, height=20, confidence=0.7),
            _detection("Fichiers récents", x=10, y=40, width=150, height=20, confidence=0.95),
            _detection("Édition", x=200, y=10, width=80, height=20, confidence=0.9),
        ]
    )

    result = await fake_ghostdesk.find_text(query="fichier")

    assert [d["text"] for d in result] == ["Fichiers récents", "Fichier"]
    assert result[0]["confidence"] == 0.95


@pytest.mark.asyncio
async def test_find_text_converts_coordinates_to_normalized_space(fake_ghostdesk):
    set_fake_detections([_detection("Fichier", x=640, y=512, width=128, height=32, confidence=0.9)])

    result = await fake_ghostdesk.find_text(query="Fichier")

    assert result == [
        {"text": "Fichier", "x": 500, "y": 500, "width": 100, "height": 31, "confidence": 0.9}
    ]


@pytest.mark.asyncio
async def test_find_text_no_match_returns_empty_list(fake_ghostdesk):
    set_fake_detections([_detection("Fichier", x=10, y=10, width=80, height=20, confidence=0.9)])

    result = await fake_ghostdesk.find_text(query="motintrouvable", fuzzy=True)

    assert result == []


@pytest.mark.asyncio
async def test_find_text_fuzzy_recovers_ocr_misread(fake_ghostdesk):
    set_fake_detections([_detection("Parametres avances", x=10, y=10, width=200, height=20, confidence=0.9)])

    result = await fake_ghostdesk.find_text(query="Paramètres", fuzzy=True)

    assert len(result) == 1

    strict = await fake_ghostdesk.find_text(query="Paramètres", fuzzy=False)
    assert strict == []


@pytest.mark.asyncio
async def test_read_screen_caps_at_80_elements_sorted_by_confidence(fake_ghostdesk):
    detections = [
        _detection(f"mot{i}", x=i, y=i, width=10, height=10, confidence=round(i / 100, 3))
        for i in range(90)
    ]
    set_fake_detections(detections)

    result = await fake_ghostdesk.read_screen()

    assert len(result) == 80
    # Les 80 plus hautes confiances (0.10 à 0.89), triées décroissant.
    assert result[0]["confidence"] == 0.89
    assert result[-1]["confidence"] == round(10 / 100, 3)
