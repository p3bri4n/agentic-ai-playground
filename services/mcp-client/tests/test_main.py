"""
Tests de mcp-client : le registre de SERVERS est remplacé par un vrai petit
serveur MCP de test (process Python, transport stdio), pour vérifier la
logique réelle (registre d'outils, appel, gestion d'erreur) sans dépendre
du socket Docker ni des images mcp/* réelles.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import StdioServerParameters

TEST_SERVER_PATH = Path(__file__).parent / "fixtures" / "echo_server.py"
TEST_HTTP_SERVER_PATH = Path(__file__).parent / "fixtures" / "echo_http_server.py"


@pytest.fixture(autouse=True)
def override_servers(monkeypatch):
    import app.main as main_mod

    main_mod.SERVERS = {
        "echo": {
            "transport": "stdio",
            "params": StdioServerParameters(command=sys.executable, args=[str(TEST_SERVER_PATH)]),
        },
    }
    main_mod._tool_registry.clear()
    yield
    main_mod._tool_registry.clear()


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
    raise TimeoutError(f"le serveur de test n'a pas démarré sur le port {port}")


@pytest.fixture
def echo_http_server():
    """Lance le serveur MCP de test en Streamable HTTP, exige le token 'secret-token'."""
    port = _free_port()
    token = "secret-token"
    proc = subprocess.Popen([sys.executable, str(TEST_HTTP_SERVER_PATH), str(port), token])
    try:
        _wait_for_port(port)
        yield {"url": f"http://127.0.0.1:{port}/mcp", "token": token}
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def echo_http_server_with_model_space():
    """Comme echo_http_server, mais exige en plus GhostDesk-Model-Space: '1000'."""
    port = _free_port()
    token = "secret-token"
    model_space = "1000"
    proc = subprocess.Popen(
        [sys.executable, str(TEST_HTTP_SERVER_PATH), str(port), token, model_space]
    )
    try:
        _wait_for_port(port)
        yield {"url": f"http://127.0.0.1:{port}/mcp", "token": token, "model_space": model_space}
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def echo_http_server_rejecting_model_space_header():
    """Comme echo_http_server, mais échoue si un header GhostDesk-Model-Space est reçu."""
    port = _free_port()
    token = "secret-token"
    proc = subprocess.Popen(
        [sys.executable, str(TEST_HTTP_SERVER_PATH), str(port), token, ""]
    )
    try:
        _wait_for_port(port)
        yield {"url": f"http://127.0.0.1:{port}/mcp", "token": token}
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def _client():
    import app.main as main_mod
    return TestClient(main_mod.app)


def test_health():
    resp = _client().get("/health")
    assert resp.status_code == 200


def test_list_tools_builds_registry():
    resp = _client().get("/tools")
    assert resp.status_code == 200
    assert resp.json()["tools"] == {"echo": "echo"}


def test_tools_schema_exposes_description_and_input_schema():
    """
    langgraph-agent consomme ce schéma pour lier les outils au LLM via
    bind_tools (voir services/langgraph-agent/app/graph.py). Sans
    description/inputSchema, le LLM ne peut pas savoir qu'un outil existe ni
    quels arguments il attend.
    """
    resp = _client().get("/tools/schema")
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    assert tools == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Renvoie le message reçu, préfixé de 'echo: '.",
                "parameters": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            },
        }
    ]


def test_call_known_tool_returns_result():
    resp = _client().post("/call", json={"tool": "echo", "arguments": {"message": "bonjour"}})
    assert resp.status_code == 200
    content = resp.json()["content"]
    assert content[0]["text"] == "echo: bonjour"


def test_call_unknown_tool_returns_404():
    resp = _client().post("/call", json={"tool": "inconnu", "arguments": {}})
    assert resp.status_code == 404
    assert "inconnu" in resp.json()["detail"]


def test_http_server_list_and_call_with_valid_token(echo_http_server):
    import app.main as main_mod

    main_mod.SERVERS["desktop"] = {
        "transport": "http",
        "url": echo_http_server["url"],
        "token": echo_http_server["token"],
    }

    resp = _client().get("/tools")
    assert resp.status_code == 200
    assert resp.json()["tools"]["echo"] == "desktop"

    resp = _client().post("/call", json={"tool": "echo", "arguments": {"message": "bonjour"}})
    assert resp.status_code == 200
    assert resp.json()["content"][0]["text"] == "echo: bonjour"


def test_http_server_sends_model_space_header(echo_http_server_with_model_space):
    """
    Nécessaire aux modèles Qwen (voir GHOSTDESK_MODEL_SPACE dans app/main.py) :
    sans ce header, GhostDesk interprète les coordonnées de clic en pixels
    écran natifs au lieu du repère normalisé 0-1000 utilisé par ces modèles,
    et les clics atterrissent à côté de leur cible.
    """
    import app.main as main_mod

    main_mod.SERVERS["desktop"] = {
        "transport": "http",
        "url": echo_http_server_with_model_space["url"],
        "token": echo_http_server_with_model_space["token"],
        "model_space": echo_http_server_with_model_space["model_space"],
    }

    resp = _client().post("/call", json={"tool": "echo", "arguments": {"message": "bonjour"}})
    assert resp.status_code == 200
    assert resp.json()["content"][0]["text"] == "echo: bonjour"


def test_http_server_omits_model_space_header_when_unset(echo_http_server_rejecting_model_space_header):
    """
    GHOSTDESK_MODEL_SPACE="" (modèle frontière travaillant nativement en
    pixels écran, ex. Claude/GPT-4o) : le header ne doit JAMAIS être envoyé,
    pas seulement être absent de la config par défaut — server["model_space"]
    falsy (chaîne vide) doit empêcher tout ajout du header, voir
    _run_on_server dans app/main.py.
    """
    import app.main as main_mod

    main_mod.SERVERS["desktop"] = {
        "transport": "http",
        "url": echo_http_server_rejecting_model_space_header["url"],
        "token": echo_http_server_rejecting_model_space_header["token"],
        "model_space": "",
    }

    resp = _client().post("/call", json={"tool": "echo", "arguments": {"message": "bonjour"}})
    assert resp.status_code == 200
    assert resp.json()["content"][0]["text"] == "echo: bonjour"


def test_http_server_wrong_token_fails(echo_http_server):
    import app.main as main_mod

    main_mod.SERVERS = {
        "desktop": {
            "transport": "http",
            "url": echo_http_server["url"],
            "token": "mauvais-token",
        },
    }

    resp = _client().get("/tools")
    assert resp.status_code == 200
    assert resp.json()["tools"] == {}


def test_ocr_server_schema_exposed_and_callable(echo_http_server):
    """
    Le serveur "ocr" (services/ocr-service, find_text/read_screen) suit le
    même mécanisme que "desktop"/GhostDesk : connexion HTTP persistante
    plutôt qu'un conteneur spawné à la demande. Le faux serveur echo tient
    lieu d'ocr-service ici : ce test vérifie le câblage générique de
    mcp-client (registre, schéma, appel), pas la logique OCR elle-même
    (couverte par la suite de tests d'ocr-service).
    """
    import app.main as main_mod

    main_mod.SERVERS["ocr"] = {
        "transport": "http",
        "url": echo_http_server["url"],
        "token": echo_http_server["token"],
    }

    resp = _client().get("/tools")
    assert resp.status_code == 200
    assert resp.json()["tools"]["echo"] == "ocr"

    resp = _client().get("/tools/schema")
    assert resp.status_code == 200
    names = [t["function"]["name"] for t in resp.json()["tools"]]
    assert "echo" in names

    resp = _client().post("/call", json={"tool": "echo", "arguments": {"message": "bonjour"}})
    assert resp.status_code == 200
    assert resp.json()["content"][0]["text"] == "echo: bonjour"


def test_ocr_server_wrong_token_fails(echo_http_server):
    import app.main as main_mod

    main_mod.SERVERS = {
        "ocr": {
            "transport": "http",
            "url": echo_http_server["url"],
            "token": "mauvais-token",
        },
    }

    resp = _client().get("/tools")
    assert resp.status_code == 200
    assert resp.json()["tools"] == {}
