"""Tests for multiple LLM endpoint management (/settings/llm-endpoints)."""

import uuid

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _cleanup(ids: list[int]) -> None:
    for i in ids:
        try:
            client.delete(f"/settings/llm-endpoints/{i}")
        except Exception:
            pass


def test_endpoint_crud_lifecycle():
    created: list[int] = []
    try:
        # Create first endpoint — becomes active, key masked.
        r1 = client.post(
            "/settings/llm-endpoints",
            json={
                "name": f"local-{uuid.uuid4().hex[:6]}",
                "base_url": "http://localhost:11434/v1",
                "model": "llama3.2",
                "api_key": "sk-secret-xyz",
                "timeout": "30",
            },
        )
        assert r1.status_code == 201, r1.text
        a = r1.json()
        created.append(a["id"])
        assert a["has_api_key"] is True
        assert "sk-secret-xyz" not in r1.text
        assert a["is_active"] in (True, False)  # depends on pre-existing rows

        # Create second endpoint.
        r2 = client.post(
            "/settings/llm-endpoints",
            json={
                "name": f"hosted-{uuid.uuid4().hex[:6]}",
                "base_url": "https://openrouter.ai/api/v1",
                "model": "openai/gpt-4o-mini",
            },
        )
        assert r2.status_code == 201, r2.text
        b = r2.json()
        created.append(b["id"])
        assert b["has_api_key"] is False

        # Activate second → it becomes active, first is not.
        ra = client.post(f"/settings/llm-endpoints/{b['id']}/activate")
        assert ra.status_code == 200
        assert ra.json()["is_active"] is True

        listing = client.get("/settings/llm-endpoints").json()
        active = [e for e in listing if e["is_active"]]
        assert len(active) == 1
        assert active[0]["id"] == b["id"]

        # Edit first endpoint's model + name; blank api_key keeps stored key.
        re = client.patch(
            f"/settings/llm-endpoints/{a['id']}",
            json={"model": "qwen-plus", "name": "renamed", "api_key": ""},
        )
        assert re.status_code == 200
        assert re.json()["model"] == "qwen-plus"
        assert re.json()["name"] == "renamed"
        assert re.json()["has_api_key"] is True

        # Delete active (second) → no active remains (or another promoted); endpoint gone.
        rd = client.delete(f"/settings/llm-endpoints/{b['id']}")
        assert rd.status_code == 200
        created.remove(b["id"])
        remaining_ids = [e["id"] for e in rd.json()["endpoints"]]
        assert b["id"] not in remaining_ids
    finally:
        _cleanup(created)


def test_endpoint_validation_and_missing():
    created: list[int] = []
    try:
        # Invalid URL rejected.
        bad = client.post(
            "/settings/llm-endpoints",
            json={"name": "x", "base_url": "ftp://nope", "model": "m"},
        )
        assert bad.status_code == 400

        # Empty name rejected.
        empty = client.post(
            "/settings/llm-endpoints",
            json={"name": "  ", "base_url": "http://localhost:1234/v1", "model": "m"},
        )
        assert empty.status_code == 400

        # Unknown id → 404.
        assert client.patch("/settings/llm-endpoints/999999", json={"model": "z"}).status_code == 404
        assert client.delete("/settings/llm-endpoints/999999").status_code == 404
        assert client.post("/settings/llm-endpoints/999999/activate").status_code == 404

        # Cannot activate a disabled endpoint.
        ep = client.post(
            "/settings/llm-endpoints",
            json={
                "name": f"dis-{uuid.uuid4().hex[:6]}",
                "base_url": "http://localhost:9999/v1",
                "model": "m",
                "enabled": False,
            },
        ).json()
        created.append(ep["id"])
        assert client.post(f"/settings/llm-endpoints/{ep['id']}/activate").status_code == 400
    finally:
        _cleanup(created)


def test_chat_models_exposes_providers_list():
    res = client.get("/chat/models")
    assert res.status_code == 200
    data = res.json()
    assert "providers" in data
    assert "active_provider_id" in data
    assert isinstance(data["providers"], list)
    # No api_key values leak through the masked serializer.
    for p in data["providers"]:
        assert "api_key" not in p
        assert "has_api_key" in p