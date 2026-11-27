"""Tests for SearXNG Web Knowledge Ingestion Connector and Celery Sync (TKT-021)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.connector import Connector
from app.models.document import Document
from app.models.user import Workspace
from app.services.connectors.searxng import SearXNGConnectorService
from app.tasks import sync_connector_task


# ---------------------------------------------------------------------------
# Test DB fixture
# ---------------------------------------------------------------------------

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# SearXNG Connector Tests
# ---------------------------------------------------------------------------

class TestSearXNGConnector:
    def test_create_searxng_connector(self, client, db):
        ws = Workspace(name="SearXNG Workspace")
        db.add(ws)
        db.commit()

        resp = client.post(
            "/connectors",
            json={
                "workspace_id": ws.id,
                "name": "Multimodal RAG Web Monitor",
                "type": "searxng",
                "config": {
                    "queries": ["multimodal RAG research", "vector indexing"],
                    "categories": "science,it",
                    "max_results": 3,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Multimodal RAG Web Monitor"
        assert data["type"] == "searxng"
        assert data["config"]["max_results"] == 3

    def test_sync_searxng_connector_and_deduplication(self, client, db, monkeypatch):
        ws = Workspace(name="Sync Test WS")
        db.add(ws)
        db.commit()

        conn = Connector(
            workspace_id=ws.id,
            name="AI Research Feed",
            type="searxng",
            config_json={
                "queries": ["ColPali visual RAG"],
                "categories": "science",
                "max_results": 2,
            },
            status="active",
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        # Mock SearXNG search tool results
        mock_results = [
            {
                "title": "ColPali: Efficient Document Retrieval",
                "url": "https://arxiv.org/abs/2407.01449",
                "snippet": "ColPali leverages Vision Language Models for end-to-end visual document retrieval.",
                "source": "searxng",
            },
            {
                "title": "Byaldi: RAG Library for ColPali",
                "url": "https://github.com/answerdotai/byaldi",
                "snippet": "Byaldi makes multimodal RAG easy using ColPali late interaction multi-vector retrieval.",
                "source": "searxng",
            },
        ]

        monkeypatch.setattr(
            "app.services.connectors.searxng.SearXNGSearchTool.search",
            lambda *args, **kwargs: mock_results,
        )

        # Mock vector embeddings and Qdrant
        monkeypatch.setattr(
            "app.services.connectors.searxng.embed_late_chunks",
            lambda text, ctxs, original_chunks: [[0.05] * 1024 for _ in ctxs],
        )
        monkeypatch.setattr(
            "app.services.connectors.searxng.embed_sparse",
            lambda text: {"indices": [10], "values": [0.8]},
        )
        mock_qdrant = MagicMock()
        monkeypatch.setattr("app.services.connectors.searxng.qdrant", mock_qdrant)
        monkeypatch.setattr("app.services.connectors.searxng.ensure_collection", lambda *args, **kwargs: None)

        # 1. First sync -> Should index 2 new documents
        res = client.post(f"/connectors/{conn.id}/sync")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["stats"]["documents_indexed"] == 2
        assert data["stats"]["documents_skipped"] == 0

        # Check documents created in DB
        docs = db.query(Document).filter(Document.workspace_id == ws.id).all()
        assert len(docs) == 2
        assert any("ColPali" in d.name for d in docs)
        assert any("arxiv.org" in d.content for d in docs)

        # Check AuditLog
        log_entry = (
            db.query(AuditLog)
            .filter_by(workspace_id=ws.id, event_type="connector.sync")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert log_entry is not None
        assert log_entry.status == "success"
        assert log_entry.metadata_json["documents_indexed"] == 2

        # 2. Second sync with identical search results -> Should deduplicate and skip both
        res2 = client.post(f"/connectors/{conn.id}/sync")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["status"] == "success"
        assert data2["stats"]["documents_indexed"] == 0
        assert data2["stats"]["documents_skipped"] == 2

        # Total documents count remains 2
        assert db.query(Document).filter(Document.workspace_id == ws.id).count() == 2

    def test_sync_empty_queries_fails_gracefully(self, db):
        conn = Connector(
            workspace_id=1,
            name="Empty Queries Connector",
            type="searxng",
            config_json={"queries": []},
            status="active",
        )
        db.add(conn)
        db.commit()

        result = SearXNGConnectorService.sync_connector(db, conn)
        assert result["status"] == "error"
        assert "No search queries" in result["error"]
        assert conn.status == "error"

    def test_celery_sync_connector_task(self, db, monkeypatch):
        conn = Connector(
            workspace_id=1,
            name="Celery Test Connector",
            type="searxng",
            config_json={"queries": ["Qdrant hybrid search"]},
            status="active",
        )
        db.add(conn)
        db.commit()

        monkeypatch.setattr(
            "app.services.connectors.searxng.SearXNGSearchTool.search",
            lambda *args, **kwargs: [],
        )

        with patch("app.tasks.SessionLocal", return_value=db):
            result = sync_connector_task(connector_id=conn.id, workspace_id=1)
            assert result["status"] == "success"
            assert result["stats"]["queries_executed"] == 1
