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
                os.environ.get("MCP_FILESYSTEM_IMAGE", "mcp/filesystem:latest"),
                "/projects",
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
        "transport": "stdio",
        "params": StdioServerParameters(
            command="docker",
            args=["run", "-i", "--rm", os.environ.get("MCP_BROWSER_IMAGE", "mcp/playwright:latest")],
        ),
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
    },
}

app = FastAPI(title="MCP Client")

# registre {nom_outil: {"server", "description", "inputSchema"}}, construit
# paresseusement au 1er appel (description/inputSchema nécessaires pour que
# langgraph-agent puisse lier ces outils au LLM via bind_tools — sans quoi le
# modèle ignore purement et simplement que ces outils existent).
_tool_registry: dict[str, dict] = {}


async def _run_on_server(server_name: str, action):
    """Ouvre une session éphémère (stdio ou HTTP selon le serveur), exécute `action`, ferme tout proprement."""
    server = SERVERS[server_name]
    async with AsyncExitStack() as stack:
        if server["transport"] == "stdio":
            read, write = await stack.enter_async_context(stdio_client(server["params"]))
        else:
            headers = {"Authorization": f"Bearer {server['token']}"}
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(server["url"], headers=headers)
            )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return await action(session)


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


class CallRequest(BaseModel):
    tool: str
    arguments: dict = {}


@app.get("/health")
async def health():
    return {"status": "ok"}


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

    result = await _run_on_server(
        tool_info["server"], lambda s: s.call_tool(request.tool, request.arguments)
    )
    return {"content": [block.model_dump() for block in result.content]}
