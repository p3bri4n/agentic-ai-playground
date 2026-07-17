"""
Faux serveur MCP GhostDesk, en Streamable HTTP (le pendant HTTP fake de
GhostDesk utilisé aussi par mcp-client, voir services/mcp-client/tests/
fixtures/echo_http_server.py) : expose uniquement le tool screen_shot(format)
attendu par ocr-service (voir app/main.py, _capture_screen), et retourne une
image PNG de taille CONNUE (WIDTH x HEIGHT passés en argument), pour permettre
des assertions déterministes sur la conversion de coordonnées côté ocr-service
(app/coords.py) sans dépendre d'un vrai bureau GhostDesk.

Usage : python3 fake_ghostdesk_server.py <port> <token_attendu> <width> <height>
"""

import io
import sys

import uvicorn
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

mcp = FastMCP("fake-ghostdesk")

_png_bytes: bytes = b""


@mcp.tool()
def screen_shot(format: str = "png") -> Image:
    return Image(data=_png_bytes, format="png")


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


def build_app(expected_token: str) -> ASGIApp:
    return RequireBearerToken(mcp.streamable_http_app(), expected_token)


if __name__ == "__main__":
    port = int(sys.argv[1])
    token = sys.argv[2]
    width = int(sys.argv[3])
    height = int(sys.argv[4])

    buffer = io.BytesIO()
    PILImage.new("RGB", (width, height), color="white").save(buffer, format="PNG")
    _png_bytes = buffer.getvalue()

    uvicorn.run(build_app(token), host="127.0.0.1", port=port, log_level="warning")
