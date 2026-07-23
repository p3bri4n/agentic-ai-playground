"""
GET /tools/schema (langgraph-agent) : noms d'outils tels qu'EFFECTIVEMENT vus
par ce process (_tools_schema_cache), distinct du schéma servi par mcp-client
au moment de l'appel — voir le docstring de la route (app/main.py) et
HISTORY.md "bug de cache de schéma d'outils" pour la raison d'être de cette
distinction. Sert de brique au préambule de campagne du harnais
(tests_integration/campaign_preflight.py, Itération 0 du brief Phase 1
« cœur cognitif », docs/briefs/phase-1-coeur-cognitif.md).
"""

import httpx
import pytest
import respx


@pytest.mark.asyncio
async def test_tools_schema_returns_sorted_names_from_cache():
    import app.main as main_mod

    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-mcp-client/tools/schema").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tools": [
                        {
                            "type": "function",
                            "function": {"name": "browser_navigate", "description": "", "parameters": {}},
                        },
                        {
                            "type": "function",
                            "function": {"name": "app_list", "description": "", "parameters": {}},
                        },
                    ]
                },
            )
        )

        transport = httpx.ASGITransport(app=main_mod.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/tools/schema")

        assert resp.status_code == 200
        assert resp.json() == {"tools": ["app_list", "browser_navigate"]}


@pytest.mark.asyncio
async def test_tools_schema_empty_when_mcp_client_unreachable():
    """mcp-client injoignable (ConnectError) : _get_tools_schema dégrade déjà
    silencieusement à une liste vide (voir app/graph.py) — cet endpoint
    reflète donc {"tools": []}, jamais une 500, cohérent avec la convention
    lecture seule de /pending et /context."""
    import app.main as main_mod

    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://fake-mcp-client/tools/schema").mock(side_effect=httpx.ConnectError("down"))

        transport = httpx.ASGITransport(app=main_mod.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/tools/schema")

        assert resp.status_code == 200
        assert resp.json() == {"tools": []}
