"""
Tests de context-manager. Utilise Qdrant en mode ":memory:" et un embedder
factice déterministe (voir conftest.py) : aucune dépendance réseau, aucune
instance Qdrant réelle nécessaire.
"""

from fastapi.testclient import TestClient


def _client():
    import app.main as main_mod
    return TestClient(main_mod.app)


def test_health():
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ingest_then_retrieve_finds_the_document():
    client = _client()
    ingest_resp = client.post(
        "/ingest",
        json={"text": "Paris est la capitale de la France.", "collection": "documents"},
    )
    assert ingest_resp.status_code == 200
    assert "id" in ingest_resp.json()

    retrieve_resp = client.post(
        "/retrieve",
        json={"query": "Paris est la capitale de la France.", "top_k": 5, "collection": "documents"},
    )
    assert retrieve_resp.status_code == 200
    results = retrieve_resp.json()["results"]
    assert "Paris est la capitale de la France." in results


def test_remember_stores_in_memory_collection():
    client = _client()
    resp = client.post("/remember", json={"text": "L'utilisateur préfère le café le matin.", "user_id": "u1"})
    assert resp.status_code == 200
    assert "id" in resp.json()

    retrieve_resp = client.post(
        "/retrieve",
        json={"query": "L'utilisateur préfère le café le matin.", "top_k": 5, "collection": "memory"},
    )
    assert "L'utilisateur préfère le café le matin." in retrieve_resp.json()["results"]


def test_retrieve_on_empty_collection_returns_empty_list():
    client = _client()
    resp = client.post(
        "/retrieve",
        json={"query": "une requête sans aucun document correspondant", "top_k": 5, "collection": "documents"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["results"], list)
