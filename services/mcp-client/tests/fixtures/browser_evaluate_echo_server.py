"""
Serveur MCP minimal simulant le serveur "browser" (Playwright) pour les
tests de browser_extract (voir services/mcp-client/app/main.py) : expose un
seul outil browser_evaluate qui renvoie tel quel le JS reçu, pour vérifier
que le wrapper construit et transmet le bon template SANS dépendre d'un
vrai navigateur.
"""

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("browser")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="browser_evaluate",
            description="Evaluate JavaScript expression on page or element",
            inputSchema={
                "type": "object",
                "properties": {"function": {"type": "string"}},
                "required": ["function"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    return [TextContent(type="text", text=arguments.get("function", ""))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
