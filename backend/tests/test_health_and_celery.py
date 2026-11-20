"""Unit and integration tests for Health check endpoints and Celery tasks (TKT-006)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.celery_app import celery_app
from app.core.database import Base, get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.connector import Connector
from app.models.user import User, Workspace
from app.tasks import (
    cleanup_old_audit_logs_task,
    run_dream_cycle_task,
    sync_connector_task,
)

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
    ws = Workspace(id=1, name="Health Test WS", description="Testing")
    session.add(ws)
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
# 1. Health Probe Endpoint Tests
# ---------------------------------------------------------------------------

def test_health_check_all_healthy(client, monkeypatch):
    monkeypatch.setattr("app.routers.health.check_redis", lambda: ("ok", None))
    monkeypatch.setattr("app.routers.health.check_qdrant", lambda: ("ok", None))

    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["services"]["database"] == "ok"
    assert data["services"]["redis"] == "ok"
    assert data["services"]["qdrant"] == "ok"
    assert "timestamp" in data


def test_health_check_degraded_when_redis_or_qdrant_down(client, monkeypatch):
    monkeypatch.setattr("app.routers.health.check_redis", lambda: ("error", "Connection refused"))
    monkeypatch.setattr("app.routers.health.check_qdrant", lambda: ("ok", None))

    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "degraded"
    assert "error" in data["services"]["redis"]
    assert data["services"]["qdrant"] == "ok"


def test_health_check_error_when_db_fails(client, monkeypatch):
    monkeypatch.setattr("app.routers.health.check_database", lambda db: ("error", "Database down"))
    monkeypatch.setattr("app.routers.health.check_redis", lambda: ("ok", None))
    monkeypatch.setattr("app.routers.health.check_qdrant", lambda: ("ok", None))

    res = client.get("/health")
    assert res.status_code == 503
    data = res.json()
    assert data["status"] == "error"
    assert "error" in data["services"]["database"]


def test_liveness_probe(client):
    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# 2. Celery Worker Task Tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def configure_celery_eager():
    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
    yield
    celery_app.conf.update(task_always_eager=False, task_eager_propagates=False)


def test_cleanup_old_audit_logs_task(monkeypatch):
    mock_prune = MagicMock(return_value=5)
    monkeypatch.setattr("app.services.audit.AuditService.prune_retention", mock_prune)

    result = cleanup_old_audit_logs_task.delay(retention_days=7)
    assert result.successful()
    assert result.result["status"] == "success"
    assert result.result["pruned_count"] == 5


def test_sync_connector_task_missing_connector():
    result = sync_connector_task.delay(connector_id=99999, workspace_id=1)
    assert result.successful()
    assert result.result["status"] == "error"
    assert "not found" in result.result["message"]


def test_run_dream_cycle_task(monkeypatch):
    mock_nrem = MagicMock(return_value={"pruned_count": 2})
    mock_rem = MagicMock(return_value={"dreams_created": 1})
    monkeypatch.setattr("app.services.dreaming.nrem.NREMConsolidator.consolidate", mock_nrem)
    monkeypatch.setattr("app.services.dreaming.rem.REMDreamer.run_dream_cycle", mock_rem)

    result = run_dream_cycle_task.delay(workspace_id=1, run_nrem=True, run_rem=True)
    assert result.successful()
    assert result.result["status"] == "success"
    assert result.result["nrem"]["pruned_count"] == 2
    assert result.result["rem"]["dreams_created"] == 1
