"""
MCP Client : point d'entrée unique du LangGraph Agent vers les serveurs MCP.

Les images officielles mcp/* (filesystem, git, playwright) et l'image
mcp-terminal construite localement communiquent en STDIO. Ce service les
spawn donc à la demande, via `docker run -i --rm ...` sur le socket Docker
monté depuis l'hôte, plutôt que de les traiter comme des serveurs réseau
persistants.

⚠️ Monter /var/run/docker.sock dans un conteneur équivaut à lui donner un
accès root sur l'hôte (le conteneur peut lancer n'importe quel autre
conteneur, y compris privilégié). En prod, préférer une alternative type
Docker socket proxy (ex: tecnativa/docker-socket-proxy) qui restreint les
opérations autorisées (uniquement `create`/`start`/`attach` sur des images
whitelistées), plutôt que d'exposer le socket brut.

GhostDesk (serveur "desktop") est différent des autres : c'est un serveur
HTTP persistant avec état (bureau virtuel, session VNC), pas un process
ponctuel. Il tourne en continu comme service docker-compose à part, et
mcp-client s'y connecte en Streamable HTTP au lieu de spawn un container.
"""

import asyncio
import json
import os
from contextlib import AsyncExitStack

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

WORKSPACE_HOST_PATH = os.environ.get("WORKSPACE_HOST_PATH", "./workspace")

SERVERS = {
    "filesystem": {
        "transport": "stdio",
        "params": StdioServerParameters(
            command="docker",
            args=[
                "run", "-i", "--rm",
                "-v", f"{WORKSPACE_HOST_PATH}:/projects",
                # Volume PARTAGÉ en LECTURE SEULE avec playwright-mcp (voir
                # docker-compose.yml, --output-dir) : donne à l'agent un
                # chemin de lecture DOCUMENTÉ pour un fichier téléchargé par
                # le navigateur, plutôt que de deviner un chemin interne au
                # conteneur playwright-mcp (voir HISTORY.md "Phase
                # 1d-révisée", T5). ":ro" car ce serveur ne doit jamais
                # pouvoir écrire dans les téléchargements de l'agent web.
                "-v", "agent-downloads:/downloads:ro",
                os.environ.get("MCP_FILESYSTEM_IMAGE", "mcp/filesystem:latest"),
                "/projects",
                "/downloads",
            ],
        ),
    },
    "git": {
        "transport": "stdio",
        "params": StdioServerParameters(
            command="docker",
            args=[
                "run", "-i", "--rm",
                "-v", f"{WORKSPACE_HOST_PATH}:/workspace",
                os.environ.get("MCP_GIT_IMAGE", "mcp/git:latest"),
            ],
        ),
    },
    "browser": {
        # Contrairement aux autres serveurs stdio ci-dessus, "browser" est un
        # serveur HTTP persistant (comme "desktop"/"ocr" plus bas) : un spawn
        # éphémère (`docker run --rm` par appel) redémarrait un navigateur
        # tout neuf à CHAQUE appel d'outil, sans continuité d'état entre
        # `browser_navigate` et l'appel suivant — voir BUGS.md. L'image
        # mcp/playwright officielle supporte un mode serveur HTTP natif
        # (`--port`, endpoint Streamable HTTP `/mcp`), utilisé ici via le
        # service docker-compose dédié `playwright-mcp`.
        "transport": "http",
        "url": os.environ.get("MCP_PLAYWRIGHT_URL", "http://playwright-mcp:8931/mcp"),
        "token": "",
        # Playwright MCP scope son contexte navigateur (page, cookies,
        # historique) à la SESSION MCP, pas au process serveur : passer par
        # une session éphémère par appel (comme les autres serveurs http)
        # recrée un `about:blank` à chaque fois même une fois le serveur
        # rendu persistant (constaté empiriquement). Nécessite donc de
        # garder une session ouverte entre les appels, voir
        # `_get_persistent_session` ci-dessous.
        "persistent_session": True,
    },
    "terminal": {
        "transport": "stdio",
        "params": StdioServerParameters(
            command="docker",
            args=[
                "run", "-i", "--rm",
                "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                "-v", f"{WORKSPACE_HOST_PATH}:/workspace",
                os.environ.get("MCP_TERMINAL_IMAGE", "mcp-terminal:local"),
            ],
        ),
    },
    "desktop": {
        "transport": "http",
        "url": os.environ.get("MCP_GHOSTDESK_URL", "http://ghostdesk:3000/mcp"),
        "token": os.environ.get("GHOSTDESK_AUTH_TOKEN", ""),
        # Sans cet en-tête, GhostDesk attend des coordonnées en pixels écran
        # natifs (1280x1024 ici) ; les modèles Qwen raisonnent eux nativement
        # en repère normalisé 0-1000 et leurs clics atterrissent alors
        # complètement à côté de la cible (documenté par GhostDesk). Les
        # modèles frontière (Claude, GPT-4o) fonctionnent nativement en
        # pixels écran et n'en ont pas besoin — d'où la variable d'env
        # plutôt qu'une valeur figée, à vider si le modèle servi change.
        "model_space": os.environ.get("GHOSTDESK_MODEL_SPACE", "1000"),
    },
    "ocr": {
        # Comme "desktop" ci-dessus : serveur HTTP persistant (ocr-service),
        # pas un conteneur spawné à la demande. Pas de header
        # GhostDesk-Model-Space ici : ocr-service convertit déjà lui-même ses
        # coordonnées vers le repère 0-1000 avant de répondre (OCR_COORD_SPACE,
        # voir services/ocr-service/app/coords.py), ce header n'a de sens que
        # pour les appels adressés directement à GhostDesk.
        "transport": "http",
        "url": os.environ.get("MCP_OCR_URL", "http://ocr-service:8004/mcp"),
        "token": os.environ.get("OCR_AUTH_TOKEN", ""),
    },
}

# Outil de LOCALISATION/EXTRACTION CIBLÉE (Phase 1d-révisée, voir HISTORY.md
# "correctif extraction") : le MCP Playwright officiel n'expose aucun outil
# "cherche ce texte et donne son contexte" (vérifié : browser_click/hover/
# select_option exigent tous une cible déjà localisée ; seuls
# browser_evaluate/browser_run_code_unsafe permettent de chercher, au prix
# de code JS arbitraire, tier ENGAGEMENT). Constaté en conditions réelles
# (T1/T10, campagne post-1d) que rendre ces deux outils jamais accordables
# pour la session (voir approval_policy.NEVER_GRANTABLE_TOOLS côté
# langgraph-agent) a fait disparaître leur usage — remplacé par une
# exploration manuelle (ctrl+f, parcours page par page) nettement moins
# fiable. La VOIE PROPRE reçoit ici la capacité de la béquille : un
# TEMPLATE JS FIXE (jamais de code fourni par le modèle, seulement un texte
# à chercher, interpolé via json.dumps — donc échappé comme une chaîne JS
# valide, aucune injection de code possible) qui parcourt les nœuds texte de
# la page et renvoie les occurrences avec leur contexte proche (texte du
# parent, lien englobant s'il existe). Le modèle ne voit jamais ce template,
# seulement le paramètre "query".
_BROWSER_EXTRACT_JS_TEMPLATE = """() => {{
  const query = {query_json};
  const q = query.toLowerCase();
  const results = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {{
    const text = (node.textContent || '').trim();
    if (!text || !text.toLowerCase().includes(q)) continue;
    const parent = node.parentElement;
    const link = parent ? parent.closest('a') : null;
    results.push({{
      text: text.slice(0, 300),
      parent_tag: parent ? parent.tagName.toLowerCase() : null,
      parent_text: parent ? parent.textContent.trim().slice(0, 300) : null,
      link_href: link ? link.getAttribute('href') : null,
    }});
    if (results.length >= 20) break;
  }}
  return JSON.stringify(results);
}}"""


def _build_extract_function(query: str) -> str:
    """Fonction pure (testable sans aucun serveur MCP réel) : construit le
    JS fixe ci-dessus avec `query` interpolé via `json.dumps` — une syntaxe
    de chaîne JSON est une syntaxe de chaîne JS valide, donc cet
    échappement est suffisant pour empêcher toute évasion de la chaîne
    littérale (guillemets, backslashs, retours à la ligne dans la requête)."""
    return _BROWSER_EXTRACT_JS_TEMPLATE.format(query_json=json.dumps(query))


_BROWSER_EXTRACT_TOOL = {
    "server": "browser",  # dispatché en interne vers browser_evaluate, voir call_tool()
    "description": (
        "Cherche un TEXTE (pas du code) dans la page actuelle — référence "
        "produit, prix, nom, mot-clé — et renvoie les occurrences avec leur "
        "contexte proche (texte du parent, lien englobant si présent). "
        "Pour trouver une valeur précise dans une page, utilise CET outil : "
        "pas de parcours manuel page par page, pas de raccourci "
        "clavier de recherche (ctrl+f)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Texte exact ou partiel à chercher (ex: une référence produit, un nom).",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

app = FastAPI(title="MCP Client")

# registre {nom_outil: {"server", "description", "inputSchema"}}, construit
# paresseusement au 1er appel (description/inputSchema nécessaires pour que
# langgraph-agent puisse lier ces outils au LLM via bind_tools — sans quoi le
# modèle ignore purement et simplement que ces outils existent).
_tool_registry: dict[str, dict] = {}

# Sessions MCP gardées ouvertes entre deux appels HTTP, pour les serveurs où
# l'état (navigateur, page) vit dans la session plutôt que dans le process
# serveur — voir "persistent_session" sur l'entrée "browser" ci-dessus.
_persistent_sessions: dict[str, tuple[AsyncExitStack, ClientSession]] = {}
_persistent_locks: dict[str, asyncio.Lock] = {
    name: asyncio.Lock() for name, server in SERVERS.items() if server.get("persistent_session")
}


def _http_headers(server: dict) -> dict:
    headers = {}
    if server.get("token"):
        headers["Authorization"] = f"Bearer {server['token']}"
    if server.get("model_space"):
        headers["GhostDesk-Model-Space"] = server["model_space"]
    return headers


async def _open_session(server_name: str, stack: AsyncExitStack) -> ClientSession:
    server = SERVERS[server_name]
    if server["transport"] == "stdio":
        read, write = await stack.enter_async_context(stdio_client(server["params"]))
    else:
        read, write, _ = await stack.enter_async_context(
            streamablehttp_client(server["url"], headers=_http_headers(server))
        )
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


async def _get_persistent_session(server_name: str) -> ClientSession:
    """Réutilise la session existante si vivante, en ouvre une nouvelle sinon."""
    async with _persistent_locks[server_name]:
        cached = _persistent_sessions.get(server_name)
        if cached is not None:
            return cached[1]
        stack = AsyncExitStack()
        try:
            session = await _open_session(server_name, stack)
        except Exception:
            await stack.aclose()
            raise
        _persistent_sessions[server_name] = (stack, session)
        return session


async def _drop_persistent_session(server_name: str) -> None:
    cached = _persistent_sessions.pop(server_name, None)
    if cached is not None:
        await cached[0].aclose()


async def _run_on_server(server_name: str, action):
    """Exécute `action` sur le serveur : session persistante si configurée, éphémère sinon."""
    server = SERVERS[server_name]
    if server.get("persistent_session"):
        session = await _get_persistent_session(server_name)
        try:
            return await action(session)
        except Exception:
            # connexion probablement morte (serveur redémarré...) : on la jette,
            # le prochain appel en rouvrira une neuve plutôt que de rester bloqué
            await _drop_persistent_session(server_name)
            raise
    async with AsyncExitStack() as stack:
        session = await _open_session(server_name, stack)
        return await action(session)


@app.on_event("shutdown")
async def _close_persistent_sessions():
    for server_name in list(_persistent_sessions):
        await _drop_persistent_session(server_name)


async def _refresh_registry():
    for server_name in SERVERS:
        try:
            tools = await _run_on_server(server_name, lambda s: s.list_tools())
            for tool in tools.tools:
                _tool_registry[tool.name] = {
                    "server": server_name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema or {"type": "object", "properties": {}},
                }
        except Exception:
            # un serveur indisponible ne doit pas bloquer le démarrage des autres
            continue
    # Outil synthétique (voir _BROWSER_EXTRACT_TOOL ci-dessus) : n'existe sur
    # aucun serveur MCP réel, ajouté après coup pour ne jamais être écrasé
    # par un rafraîchissement qui ne verrait, lui, que les serveurs réels.
    if "browser" in SERVERS:
        _tool_registry["browser_extract"] = _BROWSER_EXTRACT_TOOL


class CallRequest(BaseModel):
    tool: str
    arguments: dict = {}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/reset-session/{server_name}")
async def reset_session(server_name: str):
    """
    Réinitialisation explicite d'une session PERSISTANTE (Phase 1d-révisée,
    voir HISTORY.md "isolation entre tâches") : jette la session en cache
    (`_drop_persistent_session`), le prochain appel en rouvrira une neuve.
    Sans ce point d'entrée, seul un redémarrage complet du service (ou une
    exception fortuite pendant un appel) purgeait l'état d'une session
    persistante — pour "browser" (playwright-mcp), cela signifiait des
    onglets/URL laissés ouverts d'une tâche à l'autre, silencieusement
    visibles dans le snapshot de la tâche SUIVANTE (constaté en conditions
    réelles : un onglet "Science | Books to Scrape" resté ouvert après T10
    polluait le snapshot de T7 dans une répétition ultérieure, plusieurs
    campagnes/heures plus tard).
    404 si `server_name` n'est pas configuré en session persistante (rien à
    réinitialiser) plutôt qu'un no-op silencieux — évite qu'un nom de
    serveur mal orthographié passe inaperçu côté appelant (le harnais de
    tâches web, voir tests_integration/test_web_tasks.py).
    """
    if not SERVERS.get(server_name, {}).get("persistent_session"):
        raise HTTPException(
            status_code=404,
            detail=f"'{server_name}' n'est pas configuré en session persistante.",
        )
    await _drop_persistent_session(server_name)
    return {"status": "reset"}


@app.get("/tools")
async def list_all_tools():
    """{nom_outil: nom_serveur} — vue simple utilisée pour l'inspection/debug."""
    await _refresh_registry()
    return {"tools": {name: info["server"] for name, info in _tool_registry.items()}}


@app.get("/tools/schema")
async def list_tools_schema():
    """
    Schéma au format OpenAI function-calling (utilisé par langgraph-agent pour
    lier les outils au LLM via bind_tools — voir app/graph.py).
    """
    await _refresh_registry()
    return {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": info["description"],
                    "parameters": info["inputSchema"],
                },
            }
            for name, info in _tool_registry.items()
        ]
    }


@app.post("/call")
async def call_tool(request: CallRequest):
    if request.tool not in _tool_registry:
        await _refresh_registry()
    tool_info = _tool_registry.get(request.tool)
    if not tool_info:
        raise HTTPException(status_code=404, detail=f"Outil inconnu : {request.tool}")

    if request.tool == "browser_extract":
        # Dispatché en interne vers browser_evaluate avec un template JS FIXE
        # (voir _build_extract_function) : le modèle ne fournit jamais de
        # code, seulement le texte à chercher.
        js_function = _build_extract_function(request.arguments.get("query", ""))
        result = await _run_on_server(
            "browser", lambda s: s.call_tool("browser_evaluate", {"function": js_function})
        )
        return {"content": [block.model_dump() for block in result.content]}

    result = await _run_on_server(
        tool_info["server"], lambda s: s.call_tool(request.tool, request.arguments)
    )
    return {"content": [block.model_dump() for block in result.content]}
