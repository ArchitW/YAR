"""Tests for editing extracted document text and reindexing (Master KB curation)."""

import io

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models.document import Document

client = TestClient(app)


def _make_workspace() -> int:
    res = client.post("/workspaces?name=DocEditTest&description=tmp")
    return res.json()["id"]


def test_patch_cleans_text_and_reindex():
    ws_id = _make_workspace()
    db = SessionLocal()
    doc_id = None
    try:
        doc = Document(
            workspace_id=ws_id,
            is_master=True,
            name="edit-me.txt",
            file_type="text/plain",
            status="indexed",
            size_bytes=10,
            content="placeholder",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        doc_id = doc.id

        # Patch with messy content (extra spaces, CRLF, control char) → cleaned.
        messy = "Hello   world\r\n\x07This  is\tclean text."
        pr = client.patch(f"/documents/{doc_id}", json={"content": messy, "name": "renamed.txt"})
        assert pr.status_code == 200, pr.text
        body = pr.json()
        assert body["name"] == "renamed.txt"
        assert "   " not in body["content"]
        assert "\x07" not in body["content"]
        assert body["status"] == "indexed"

        # Reindex rebuilds vectors from stored content.
        rr = client.post(f"/documents/{doc_id}/reindex")
        assert rr.status_code == 200, rr.text
        assert isinstance(rr.json()["chunks"], int)

        # 404s for unknown ids.
        assert client.patch("/documents/999999", json={"name": "x"}).status_code == 404
        assert client.post("/documents/999999/reindex").status_code == 404
        # Empty name rejected.
        assert client.patch(f"/documents/{doc_id}", json={"name": "  "}).status_code == 400
    finally:
        if doc_id is not None:
            client.delete(f"/documents/{doc_id}")
        db.close()


def test_duplicate_upload_rejected():
    ws_id = _make_workspace()
    files = {"file": ("dup.txt", io.BytesIO(b"hello world"), "text/plain")}
    r1 = client.post(f"/documents/upload?workspace_id={ws_id}", files=files)
    assert r1.status_code == 200, r1.text
    doc_id = r1.json()["id"]
    try:
        files2 = {"file": ("dup.txt", io.BytesIO(b"hello world"), "text/plain")}
        r2 = client.post(f"/documents/upload?workspace_id={ws_id}", files=files2)
        assert r2.status_code == 409, r2.text
        assert "already exists" in r2.json()["detail"]
    finally:
        client.delete(f"/documents/{doc_id}")