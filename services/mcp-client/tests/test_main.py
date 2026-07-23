"""
Tests de mcp-client : le registre de SERVERS est remplacé par un vrai petit
serveur MCP de test (process Python, transport stdio), pour vérifier la
logique réelle (registre d'outils, appel, gestion d'erreur) sans dépendre
du socket Docker ni des images mcp/* réelles.
"""

import asyncio
import json
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


class _FakeSession:
    def __init__(self, id_: int):
        self.id = id_


def _patch_open_session(main_mod, monkeypatch):
    """
    Remplace _open_session par une fabrique de sessions factices comptées :
    permet de vérifier QUI (persistant vs éphémère) rouvre une session sans
    dépendre d'un vrai serveur MCP ni du protocole réseau.
    """
    calls = {"n": 0}

    async def fake_open_session(server_name, stack):
        calls["n"] += 1
        return _FakeSession(calls["n"])

    monkeypatch.setattr(main_mod, "_open_session", fake_open_session)
    return calls


def test_persistent_session_reused_across_calls(monkeypatch):
    """
    Le serveur "browser" (Playwright) scope son état navigateur à la SESSION
    MCP, pas au process serveur (voir BUGS.md) : mcp-client doit donc réutiliser
    la même session entre deux appels d'outils plutôt que d'en rouvrir une à
    chaque fois, sans quoi l'état (page visitée...) serait perdu entre deux
    appels malgré un serveur HTTP persistant.
    """
    import app.main as main_mod

    main_mod.SERVERS = {
        "browser": {"transport": "http", "url": "http://unused", "token": "", "persistent_session": True},
    }
    main_mod._persistent_sessions.clear()
    main_mod._persistent_locks["browser"] = asyncio.Lock()
    calls = _patch_open_session(main_mod, monkeypatch)

    async def action(session):
        return session.id

    async def run():
        first = await main_mod._run_on_server("browser", action)
        second = await main_mod._run_on_server("browser", action)
        return first, second

    first, second = asyncio.run(run())
    assert first == second == 1
    assert calls["n"] == 1


def test_ephemeral_server_opens_new_session_per_call(monkeypatch):
    """Sans persistent_session, chaque appel doit garder son comportement d'origine : une session neuve à chaque fois."""
    import app.main as main_mod

    main_mod.SERVERS = {
        "desktop": {"transport": "http", "url": "http://unused", "token": ""},
    }
    calls = _patch_open_session(main_mod, monkeypatch)

    async def action(session):
        return session.id

    async def run():
        first = await main_mod._run_on_server("desktop", action)
        second = await main_mod._run_on_server("desktop", action)
        return first, second

    first, second = asyncio.run(run())
    assert (first, second) == (1, 2)
    assert calls["n"] == 2


def test_persistent_session_dropped_and_reopened_after_error(monkeypatch):
    """
    Si l'action échoue (session probablement morte, ex. serveur redémarré),
    la session en cache doit être jetée : le prochain appel doit en rouvrir
    une neuve plutôt que de rester bloqué sur une connexion cassée.
    """
    import app.main as main_mod

    main_mod.SERVERS = {
        "browser": {"transport": "http", "url": "http://unused", "token": "", "persistent_session": True},
    }
    main_mod._persistent_sessions.clear()
    main_mod._persistent_locks["browser"] = asyncio.Lock()
    calls = _patch_open_session(main_mod, monkeypatch)

    async def failing_action(session):
        raise RuntimeError("session cassée")

    async def ok_action(session):
        return session.id

    async def run():
        with pytest.raises(RuntimeError):
            await main_mod._run_on_server("browser", failing_action)
        return await main_mod._run_on_server("browser", ok_action)

    result = asyncio.run(run())
    assert result == 2  # nouvelle session rouverte, pas la première réutilisée
    assert calls["n"] == 2
    # la session rouverte (la 2e) est bien celle mise en cache pour le prochain appel
    assert main_mod._persistent_sessions["browser"][1].id == 2


# ─────────────────────────────────────────────────────────────────────────
# browser_extract (Phase 1d-révisée, voir HISTORY.md "correctif extraction") :
# outil synthétique dispatché en interne vers browser_evaluate avec un
# template JS FIXE — le modèle ne fournit jamais de code, seulement un texte
# à chercher.
# ─────────────────────────────────────────────────────────────────────────

BROWSER_EVALUATE_ECHO_SERVER_PATH = Path(__file__).parent / "fixtures" / "browser_evaluate_echo_server.py"


def test_build_extract_function_embeds_query_as_escaped_json_string():
    """Fonction pure : la requête est interpolée via json.dumps (syntaxe de
    chaîne JSON = syntaxe de chaîne JS valide), jamais concaténée brute — un
    guillemet ou un backslash dans la requête ne peut donc jamais faire
    "s'échapper" du littéral de chaîne vers du code JS arbitraire."""
    import app.main as main_mod

    js = main_mod._build_extract_function('") ; alert(1); ("')
    assert json.dumps('") ; alert(1); ("') in js
    assert js.count("const query =") == 1
    assert "document.createTreeWalker" in js


@pytest.fixture
def browser_evaluate_echo_server():
    import app.main as main_mod

    main_mod.SERVERS = {
        "browser": {
            "transport": "stdio",
            "params": StdioServerParameters(
                command=sys.executable, args=[str(BROWSER_EVALUATE_ECHO_SERVER_PATH)]
            ),
        },
    }
    main_mod._tool_registry.clear()
    yield
    main_mod._tool_registry.clear()


def test_browser_extract_is_registered_when_browser_server_present(browser_evaluate_echo_server):
    resp = _client().get("/tools/schema")
    names = {t["function"]["name"] for t in resp.json()["tools"]}
    assert "browser_extract" in names
    assert "browser_evaluate" in names  # le vrai outil reste exposé tel quel, pas remplacé


def test_browser_extract_dispatches_to_browser_evaluate_with_fixed_template(browser_evaluate_echo_server):
    """Le serveur de test renvoie tel quel le JS reçu (voir
    browser_evaluate_echo_server.py) : permet de vérifier le template
    généré SANS dépendre d'un vrai navigateur."""
    import app.main as main_mod

    resp = _client().post("/call", json={"tool": "browser_extract", "arguments": {"query": "KX-4471"}})
    assert resp.status_code == 200
    text = resp.json()["content"][0]["text"]
    assert text == main_mod._build_extract_function("KX-4471")
    assert json.dumps("KX-4471") in text


# ─────────────────────────────────────────────────────────────────────────
# POST /reset-session/{server_name} (Phase 1d-révisée, voir HISTORY.md
# "isolation entre tâches") : purge une session persistante (état
# navigateur/onglets pour "browser") entre deux tâches du harnais.
# ─────────────────────────────────────────────────────────────────────────


def test_reset_session_drops_cache_and_next_call_reopens_fresh(monkeypatch):
    import app.main as main_mod

    main_mod.SERVERS = {
        "browser": {"transport": "http", "url": "http://unused", "token": "", "persistent_session": True},
    }
    main_mod._persistent_sessions.clear()
    main_mod._persistent_locks["browser"] = asyncio.Lock()
    calls = _patch_open_session(main_mod, monkeypatch)

    async def action(session):
        return session.id

    async def run():
        first = await main_mod._run_on_server("browser", action)
        return first

    first = asyncio.run(run())
    assert first == 1

    resp = _client().post("/reset-session/browser")
    assert resp.status_code == 200
    assert "browser" not in main_mod._persistent_sessions

    second = asyncio.run(run())
    assert second == 2  # nouvelle session rouverte, pas l'ancienne réutilisée
    assert calls["n"] == 2


def test_reset_session_unknown_server_is_404():
    main_mod_resp = _client().post("/reset-session/does-not-exist")
    assert main_mod_resp.status_code == 404


def test_reset_session_non_persistent_server_is_404():
    """echo (fixture par défaut) n'est pas configuré en session persistante :
    rien à réinitialiser, 404 plutôt qu'un no-op silencieux qui masquerait
    une faute de frappe côté appelant."""
    resp = _client().post("/reset-session/echo")
    assert resp.status_code == 404
