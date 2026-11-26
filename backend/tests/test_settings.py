"""Tests for unified /settings GET and PATCH endpoints."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_settings_never_leaks_secrets(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret-value")
    monkeypatch.setenv("JWT_SECRET", "jwt-super-secret-value")

    res = client.get("/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["has_api_key"] is True
    assert data["has_jwt_secret"] is True
    assert "sk-super-secret-value" not in res.text
    assert "jwt-super-secret-value" not in res.text
    assert data["compute_device"] in ("cuda", "mps", "cpu")


def test_patch_settings_updates_and_validates(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.config.BASE_DIR", str(tmp_path))

    bad = client.patch("/settings", json={"llm_base_url": "ftp://invalid-host"})
    assert bad.status_code == 400

    res = client.patch(
        "/settings",
        json={
            "llm_base_url": "http://localhost:20128/v1/",
            "llm_model": "qwen-plus",
            "hyde_enabled": True,
            "web_search_confidence_threshold": 0.42,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["llm_base_url"] == "http://localhost:20128/v1"
    assert data["llm_model"] == "qwen-plus"
    assert data["hyde_enabled"] is True
    assert data["web_search_confidence_threshold"] == 0.42
    assert (tmp_path / ".env").exists()
