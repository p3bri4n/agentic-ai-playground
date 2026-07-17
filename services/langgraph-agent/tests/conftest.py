import os
import shutil
import tempfile

import pytest

os.environ["LLM_BASE_URL"] = "http://fake-vllm/v1"
os.environ["CONTEXT_MANAGER_URL"] = "http://fake-context-manager"
os.environ["SKILL_MANAGER_URL"] = "http://fake-skill-manager"
os.environ["MCP_CLIENT_URL"] = "http://fake-mcp-client"
# Le défaut de production (/workspace/.audit) n'existe pas dans l'environnement
# de test et ne doit de toute façon jamais être touché par les tests — voir
# app/audit_log.py. Un répertoire temporaire dédié, nettoyé à la fin de la
# session de tests (voir _reset_audit_log_dir plus bas pour le nettoyage
# ENTRE chaque test).
os.environ["AUDIT_LOG_DIR"] = tempfile.mkdtemp(prefix="langgraph-agent-audit-test-")


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


@pytest.fixture(autouse=True)
def _reset_recent_threads():
    """
    app.main._recent_threads (Phase 3, registre des threads récents pour le
    dashboard d'observabilité, voir GET /threads/recent) est un dict module-
    level : sans reset, un test qui vérifie l'ordre/le contenu verrait
    aussi les threads touchés par les tests précédents.
    """
    import app.main as main_mod

    main_mod._recent_threads.clear()
    yield
    main_mod._recent_threads.clear()


@pytest.fixture(autouse=True)
def _reset_audit_log_dir():
    """
    Vide le répertoire d'audit de test avant chaque test, pour qu'un test qui
    compte des entrées (ex. GET /audit) ne voie jamais celles écrites par un
    test précédent — app.audit_log lit AUDIT_LOG_DIR dynamiquement à chaque
    appel (pas de cache), donc il suffit de vider le contenu du répertoire.
    """
    import app.audit_log as audit_log

    shutil.rmtree(audit_log.AUDIT_LOG_DIR, ignore_errors=True)
    os.makedirs(audit_log.AUDIT_LOG_DIR, exist_ok=True)
    yield
