import os

import pytest

os.environ["LLM_BASE_URL"] = "http://fake-vllm/v1"
os.environ["CONTEXT_MANAGER_URL"] = "http://fake-context-manager"
os.environ["SKILL_MANAGER_URL"] = "http://fake-skill-manager"
os.environ["MCP_CLIENT_URL"] = "http://fake-mcp-client"


@pytest.fixture(autouse=True)
def _reset_tools_schema_cache():
    """
    app.graph met en cache le schéma d'outils récupéré de mcp-client pour la
    durée du process (voir _get_bound_llm) : sans ce reset, un seul test
    déclencherait l'appel HTTP réel et tous les autres réutiliseraient
    silencieusement sa valeur, cassant l'isolation entre tests.
    """
    import app.graph as g

    g._tools_schema_cache = None
    yield
    g._tools_schema_cache = None
