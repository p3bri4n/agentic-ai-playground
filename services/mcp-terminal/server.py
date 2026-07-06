"""
Serveur MCP "Terminal" minimal, en STDIO.

⚠️ CHOIX DE SÉCURITÉ DÉLIBÉRÉ : il n'existe pas d'outil "run_any_command".
Seule une liste blanche de commandes en lecture seule est exposée. Étendre
cette liste avec prudence : chaque commande ajoutée est une nouvelle surface
d'attaque potentielle pour l'agent (ou pour un prompt injecté via un document
qu'il aurait lu).
"""

import asyncio
import os
import subprocess

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

ALLOWED_COMMANDS = {
    "ls": ["ls", "-la"],
    "pwd": ["pwd"],
    "cat": ["cat"],          # argument = chemin de fichier, restreint à /workspace via le check ci-dessous
    "git_status": ["git", "-C", "/workspace", "status"],
}

WORKSPACE_ROOT = os.environ.get("MCP_TERMINAL_WORKSPACE_ROOT", "/workspace")

server = Server("mcp-terminal")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="run_command",
            description=(
                "Exécute une commande PARMI une liste blanche stricte "
                f"({', '.join(ALLOWED_COMMANDS)}). Toute autre commande est refusée."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "enum": list(ALLOWED_COMMANDS)},
                    "arg": {"type": "string", "description": "Argument optionnel (ex: chemin pour cat)"},
                },
                "required": ["command"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "run_command":
        return [TextContent(type="text", text=f"Outil inconnu : {name}")]

    command_key = arguments.get("command")
    if command_key not in ALLOWED_COMMANDS:
        return [TextContent(type="text", text=f"Commande refusée (liste blanche) : {command_key}")]

    cmd = list(ALLOWED_COMMANDS[command_key])

    arg = arguments.get("arg")
    if command_key == "cat" and arg:
        candidate = os.path.realpath(os.path.join(WORKSPACE_ROOT, arg))
        if not candidate.startswith(os.path.realpath(WORKSPACE_ROOT) + os.sep):
            return [TextContent(type="text", text="Chemin refusé : doit rester dans /workspace")]
        cmd.append(candidate)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = result.stdout or result.stderr
    except Exception as exc:
        output = f"Erreur d'exécution : {exc}"

    return [TextContent(type="text", text=output)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
