"""
Serveur MCP minimal en transport Streamable HTTP, utilisé uniquement comme
fixture pour tester le support HTTP de mcp-client (le pendant HTTP de
echo_server.py, qui lui teste le transport stdio).

Usage : python3 echo_http_server.py <port> <token_attendu>

Exige un header `Authorization: Bearer <token_attendu>` sur chaque requête,
pour vérifier que mcp-client transmet bien le bearer token configuré.
"""

import sys

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

mcp = FastMCP("echo-http")


@mcp.tool()
def echo(message: str) -> str:
    """Renvoie le message reçu, préfixé de 'echo: '."""
    return f"echo: {message}"


class RequireBearerToken:
    def __init__(self, app: ASGIApp, expected_token: str):
        self.app = app
        self.expected_token = expected_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        auth = headers.get(b"authorization", b"").decode()
        if auth != f"Bearer {self.expected_token}":
            response = PlainTextResponse("token invalide", status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def build_app(expected_token: str) -> Starlette:
    inner = mcp.streamable_http_app()
    return RequireBearerToken(inner, expected_token)


if __name__ == "__main__":
    port = int(sys.argv[1])
    expected_token = sys.argv[2]
    uvicorn.run(build_app(expected_token), host="127.0.0.1", port=port, log_level="warning")
