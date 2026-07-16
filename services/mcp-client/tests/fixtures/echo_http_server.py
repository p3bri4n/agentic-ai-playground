"""
Serveur MCP minimal en transport Streamable HTTP, utilisé uniquement comme
fixture pour tester le support HTTP de mcp-client (le pendant HTTP de
echo_server.py, qui lui teste le transport stdio).

Usage : python3 echo_http_server.py <port> <token_attendu>

Exige un header `Authorization: Bearer <token_attendu>` sur chaque requête,
pour vérifier que mcp-client transmet bien le bearer token configuré.

Usage : python3 echo_http_server.py <port> <token_attendu> [model_space_attendu]
Si un 3e argument est fourni et non vide, exige aussi un header
`GhostDesk-Model-Space: <model_space_attendu>` (voir GHOSTDESK_MODEL_SPACE
dans app/main.py — nécessaire aux modèles Qwen pour que leurs coordonnées de
clic, raisonnées en repère normalisé 0-1000, soient interprétées correctement
par GhostDesk plutôt qu'en pixels écran natifs). Si ce 3e argument est la
chaîne vide, exige au contraire que le header soit ABSENT (cas
GHOSTDESK_MODEL_SPACE="" — modèle frontière travaillant nativement en pixels
écran, voir README).
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
    def __init__(self, app: ASGIApp, expected_token: str, expected_model_space: str | None = None):
        self.app = app
        self.expected_token = expected_token
        self.expected_model_space = expected_model_space

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
        if self.expected_model_space is not None:
            header_present = b"ghostdesk-model-space" in headers
            if self.expected_model_space == "":
                # cas GHOSTDESK_MODEL_SPACE="" : le header ne doit JAMAIS être envoyé
                if header_present:
                    response = PlainTextResponse("model-space header inattendu", status_code=401)
                    await response(scope, receive, send)
                    return
            else:
                model_space = headers.get(b"ghostdesk-model-space", b"").decode()
                if model_space != self.expected_model_space:
                    response = PlainTextResponse("model-space invalide", status_code=401)
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def build_app(expected_token: str, expected_model_space: str | None = None) -> Starlette:
    inner = mcp.streamable_http_app()
    return RequireBearerToken(inner, expected_token, expected_model_space)


if __name__ == "__main__":
    port = int(sys.argv[1])
    expected_token = sys.argv[2]
    expected_model_space = sys.argv[3] if len(sys.argv) > 3 else None
    uvicorn.run(
        build_app(expected_token, expected_model_space), host="127.0.0.1", port=port, log_level="warning"
    )
