"""GET / : page statique unique, non testée en détail (voir README) — on
vérifie seulement qu'elle répond bien en HTML."""

import httpx
import pytest


@pytest.mark.asyncio
async def test_index_returns_html():
    import app.main as main_mod

    transport = httpx.ASGITransport(app=main_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
