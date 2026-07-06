"""
Tests de skill-manager : chargement des skills depuis le disque et matching
mot-clé. SKILLS_DIR est redirigé vers un dossier temporaire via monkeypatch
pour ne dépendre d'aucun état sur le système de fichiers réel.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    docx_dir = tmp_path / "docx"
    docx_dir.mkdir()
    (docx_dir / "SKILL.md").write_text(
        "---\ndescription: Use this skill whenever the user wants to create or edit "
        "Word documents (.docx)\n---\n# DOCX skill\nContent here.\n",
        encoding="utf-8",
    )

    pptx_dir = tmp_path / "pptx"
    pptx_dir.mkdir()
    (pptx_dir / "SKILL.md").write_text(
        "---\ndescription: Use this skill for creating PowerPoint presentations and "
        "slide decks\n---\n# PPTX skill\nContent here.\n",
        encoding="utf-8",
    )

    import app.main as main_mod
    monkeypatch.setattr(main_mod, "SKILLS_DIR", tmp_path)
    return tmp_path


def test_load_skills_returns_all_skills(skills_dir):
    import app.main as main_mod
    skills = main_mod.load_skills()
    assert set(skills.keys()) == {"docx", "pptx"}
    assert "Word" in skills["docx"]["description"]


def test_health_endpoint(skills_dir):
    import app.main as main_mod
    client = TestClient(main_mod.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_list_skills_endpoint(skills_dir):
    import app.main as main_mod
    client = TestClient(main_mod.app)
    resp = client.get("/skills")
    assert resp.status_code == 200
    names = {s["name"] for s in resp.json()["skills"]}
    assert names == {"docx", "pptx"}


def test_match_finds_relevant_skill(skills_dir):
    import app.main as main_mod
    client = TestClient(main_mod.app)
    resp = client.post("/match", json={"query": "Peux-tu créer un document Word ?"})
    assert resp.status_code == 200
    assert resp.json()["skill"]["name"] == "docx"


def test_match_returns_none_when_no_overlap(skills_dir):
    import app.main as main_mod
    client = TestClient(main_mod.app)
    resp = client.post("/match", json={"query": "Quelle est la météo à Paris ?"})
    assert resp.status_code == 200
    assert resp.json()["skill"] is None
