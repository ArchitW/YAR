"""Unit and integration tests for Trace IDs, Audit Logs, Exports & Connectors (TKT-012)."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import ChatMessage
from app.models.connector import Connector
from app.models.document import Document
from app.models.user import User, Workspace
from app.services.audit import AuditService
from app.services.connectors.filesystem import FilesystemConnectorService
from app.services.export import ExportService

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    session = TestSession()
    ws = Workspace(id=1, name="Test Workspace", description="Test")
    user = User(id=1, email="test@example.com", role="user")
    session.add_all([ws, user])
    session.commit()
    session.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. Trace ID Middleware Tests
# ---------------------------------------------------------------------------

def test_trace_id_generated_and_returned_in_header(client):
    response = client.get("/workspaces")
    assert response.status_code == 200
    assert "X-Trace-ID" in response.headers
    assert "X-Response-Time" in response.headers
    assert len(response.headers["X-Trace-ID"]) > 10


def test_trace_id_propagated_from_inbound_header(client):
    custom_trace = "custom-client-trace-12345"
    response = client.get("/workspaces", headers={"X-Trace-ID": custom_trace})
    assert response.status_code == 200
    assert response.headers["X-Trace-ID"] == custom_trace


# ---------------------------------------------------------------------------
# 2. Audit Logging Tests
# ---------------------------------------------------------------------------

def test_audit_service_record_and_query(db_session):
    entry = AuditService.record(
        db=db_session,
        event_type="document.upload",
        summary="Uploaded contract.pdf",
        status="success",
        workspace_id=1,
        user_id=1,
        metadata={"filename": "contract.pdf", "size": 1024},
    )
    assert entry is not None
    assert entry.id is not None
    assert entry.event_type == "document.upload"

    logs, total = AuditService.get_logs(db=db_session, workspace_id=1)
    assert total == 1
    assert logs[0].summary == "Uploaded contract.pdf"
    assert logs[0].metadata_json["size"] == 1024


def test_audit_logs_rest_endpoints(client, db_session):
    # Seed audit logs
    AuditService.record(db_session, "auth.login", "User logged in", status="success", workspace_id=1)
    AuditService.record(db_session, "document.upload", "Uploaded doc", status="success", workspace_id=1)
    AuditService.record(db_session, "chat.query", "Failed query", status="failure", workspace_id=2)

    # 1. List all
    res = client.get("/audit-logs")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3

    # 2. Filter by workspace
    res_ws = client.get("/audit-logs?workspace_id=1")
    assert res_ws.status_code == 200
    data_ws = res_ws.json()
    assert data_ws["total"] == 2

    # 3. Filter by event_type
    res_type = client.get("/audit-logs?event_type=chat.query")
    assert res_type.status_code == 200
    assert res_type.json()["total"] == 1
    assert res_type.json()["items"][0]["status"] == "failure"

    # 4. Get by ID
    log_id = data["items"][0]["id"]
    res_single = client.get(f"/audit-logs/{log_id}")
    assert res_single.status_code == 200
    assert res_single.json()["id"] == log_id

    # 5. Get non-existent
    res_404 = client.get("/audit-logs/99999")
    assert res_404.status_code == 404


def test_audit_logs_retention_prune(client, db_session):
    # Add an old audit log (10 days ago) and a recent one (today)
    old_entry = AuditLog(
        trace_id="old-trace",
        workspace_id=1,
        event_type="system.old",
        status="success",
        summary="Old event",
        metadata_json={},
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    new_entry = AuditLog(
        trace_id="new-trace",
        workspace_id=1,
        event_type="system.new",
        status="success",
        summary="Recent event",
        metadata_json={},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([old_entry, new_entry])
    db_session.commit()

    # Run prune with 7-day retention
    res = client.post("/audit-logs/prune?retention_days=7")
    assert res.status_code == 200
    assert res.json()["pruned_count"] == 1

    # Only new_entry should remain
    logs, total = AuditService.get_logs(db_session)
    assert total == 1
    assert logs[0].event_type == "system.new"


# ---------------------------------------------------------------------------
# 3. Export Service Tests
# ---------------------------------------------------------------------------

def test_chat_export_markdown(client, db_session):
    # Seed chat messages with citations
    m1 = ChatMessage(workspace_id=1, role="user", content="What is the net profit?")
    m2 = ChatMessage(
        workspace_id=1,
        role="assistant",
        content="Net profit is $4.2M.",
        citations=[
            {
                "index": 1,
                "file_name": "q3_report.pdf",
                "page_number": 4,
                "section": "Financial Highlights",
                "chunk_index": 2,
                "score": 0.892,
                "text": "Net income rose to $4.2M in Q3.",
            }
        ],
        provider="ollama",
        model="llama3",
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    res = client.get("/chat/export?workspace_id=1&format=markdown")
    assert res.status_code == 200
    assert "attachment" in res.headers["Content-Disposition"]
    assert res.headers["Content-Disposition"].endswith('.md"')

    content = res.text
    assert "# YAR Knowledge Chat Export: Test Workspace" in content
    assert "What is the net profit?" in content
    assert "Net profit is $4.2M." in content
    assert "q3_report.pdf" in content
    assert "Financial Highlights" in content
    assert "> Net income rose to $4.2M in Q3." in content


def test_chat_export_json_and_txt(client, db_session):
    m1 = ChatMessage(workspace_id=1, role="user", content="List architecture goals")
    m2 = ChatMessage(workspace_id=1, role="assistant", content="Reliability and local first.")
    db_session.add_all([m1, m2])
    db_session.commit()

    # JSON export
    res_json = client.get("/chat/export?workspace_id=1&format=json")
    assert res_json.status_code == 200
    data = res_json.json()
    assert data["workspace_id"] == 1
    assert data["total_messages"] == 2
    assert data["messages"][0]["content"] == "List architecture goals"

    # TXT export
    res_txt = client.get("/chat/export?workspace_id=1&format=txt")
    assert res_txt.status_code == 200
    assert "USER:" in res_txt.text
    assert "ASSISTANT:" in res_txt.text

    # Invalid format
    res_bad = client.get("/chat/export?workspace_id=1&format=unsupported_format")
    assert res_bad.status_code == 400


# ---------------------------------------------------------------------------
# 4. Connectors Framework Tests
# ---------------------------------------------------------------------------

def test_connectors_crud_and_sync(client, db_session, monkeypatch):
    # 1. Create connector
    res = client.post(
        "/connectors",
        json={
            "workspace_id": 1,
            "name": "Local Research Folder",
            "type": "filesystem",
            "config": {"folder_path": "/tmp/test-folder", "recursive": True},
        },
    )
    assert res.status_code == 200
    conn_id = res.json()["id"]
    assert res.json()["status"] == "active"

    # 2. List connectors
    list_res = client.get("/connectors?workspace_id=1")
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    # 3. Test sync with temporary folder containing valid documents
    with tempfile.TemporaryDirectory() as temp_dir:
        doc1 = os.path.join(temp_dir, "overview.txt")
        with open(doc1, "w") as f:
            f.write("System architecture for offline knowledge retrieval.")

        doc2 = os.path.join(temp_dir, "notes.md")
        with open(doc2, "w") as f:
            f.write("Important invariant: Always ground answers with verified source citations.")

        # Update connector folder path
        conn = db_session.get(Connector, conn_id)
        conn.config_json = {"folder_path": temp_dir}
        db_session.commit()

        # Mock embedding & Qdrant calls for fast unit test
        monkeypatch.setattr(
            "app.services.connectors.filesystem.embed_late_chunks",
            lambda text, ctxs, original_chunks: [[0.1] * 1024 for _ in ctxs],
        )
        monkeypatch.setattr(
            "app.services.connectors.filesystem.embed_sparse",
            lambda text: {"indices": [1], "values": [0.5]},
        )
        mock_qdrant = MagicMock()
        monkeypatch.setattr("app.services.connectors.filesystem.qdrant", mock_qdrant)
        monkeypatch.setattr("app.services.connectors.filesystem.ensure_collection", lambda *args, **kwargs: None)

        sync_res = client.post(f"/connectors/{conn_id}/sync")
        assert sync_res.status_code == 200
        sync_data = sync_res.json()
        assert sync_data["status"] == "success"
        assert sync_data["stats"]["files_indexed"] == 2
        assert "overview.txt" in sync_data["stats"]["indexed_files"]
        assert "notes.md" in sync_data["stats"]["indexed_files"]

        # Verify documents were added to workspace
        docs = db_session.query(Document).filter(Document.workspace_id == 1).all()
        assert len(docs) == 2

        # Verify audit log recorded connector.sync
        logs, _ = AuditService.get_logs(db_session, event_type="connector.sync")
        assert len(logs) >= 1
        assert "Local Research Folder" in logs[0].summary

    # 4. Delete connector
    del_res = client.delete(f"/connectors/{conn_id}")
    assert del_res.status_code == 200
    assert client.get("/connectors?workspace_id=1").json() == []


def test_document_deletion_with_audit(client, db_session, monkeypatch):
    # Seed a document
    doc = Document(workspace_id=1, name="legacy_doc.pdf", status="indexed", size_bytes=500, content="old")
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    mock_qdrant = MagicMock()
    monkeypatch.setattr("app.routers.documents.qdrant", mock_qdrant)

    res = client.delete(f"/documents/{doc.id}")
    assert res.status_code == 200
    assert res.json()["deleted"] is True

    # Assert document removed from DB
    assert db_session.get(Document, doc.id) is None

    # Assert audit log recorded
    logs, _ = AuditService.get_logs(db_session, event_type="document.delete")
    assert len(logs) == 1
    assert "legacy_doc.pdf" in logs[0].summary
