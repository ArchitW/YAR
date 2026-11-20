"""Unit and integration tests for Memory and Dreaming REST Router."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.memory import MemoryEdge, MemoryNode
from app.models.user import User, Workspace
from app.services.memory import MemoryService

# Test DB fixture
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
# Test Cases
# ---------------------------------------------------------------------------

def test_list_memories_pagination_and_filtering(client, db):
    # Setup test memory nodes
    MemoryService.add_node(db, workspace_id=1, node_type="episodic_memory", name="E1", content="Message 1")
    MemoryService.add_node(db, workspace_id=1, node_type="user_preference", name="P1", content="Preference 1")
    MemoryService.add_node(db, workspace_id=1, node_type="user_preference", name="P2", content="Preference 2")
    inv_node = MemoryService.add_node(db, workspace_id=1, node_type="episodic_memory", name="E2", content="Old noise")
    MemoryService.invalidate_node(db, inv_node.id, reason="pruned")
    db.commit()

    # 1. Default listing: excludes invalidated
    res = client.get("/memory?workspace_id=1")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3

    # 2. Type filter
    res_pref = client.get("/memory?workspace_id=1&node_type=user_preference")
    assert res_pref.status_code == 200
    data_pref = res_pref.json()
    assert data_pref["total"] == 2
    assert all(item["node_type"] == "user_preference" for item in data_pref["items"])

    # 3. Pagination
    res_page = client.get("/memory?workspace_id=1&limit=2&offset=0")
    assert res_page.status_code == 200
    assert len(res_page.json()["items"]) == 2

    # 4. Include invalidated
    res_inv = client.get("/memory?workspace_id=1&include_invalidated=true")
    assert res_inv.status_code == 200
    assert res_inv.json()["total"] == 4


def test_get_entities_dossier(client, db):
    MemoryService.add_node(
        db, workspace_id=1, node_type="user_preference", name="Code Style", content="Concise type hints", importance_score=0.9
    )
    MemoryService.add_node(
        db, workspace_id=1, node_type="concept", name="Architecture", content="FastAPI SQLite Qdrant", importance_score=0.8
    )
    db.commit()

    res = client.get("/memory/entities?workspace_id=1")
    assert res.status_code == 200
    dossier = res.json()
    assert len(dossier) == 2
    assert dossier[0]["importance_score"] >= dossier[1]["importance_score"]
    assert any("Concise type hints" in d["content"] for d in dossier)


def test_patch_entity_updates_attributes(client, db):
    node = MemoryService.add_node(
        db, workspace_id=1, node_type="user_preference", name="Style", content="Use tabs", importance_score=0.6
    )
    db.commit()

    patch_payload = {
        "name": "Updated Style",
        "content": "Use 4 spaces for indentation",
        "importance_score": 0.95,
        "properties": {"indent_size": 4},
    }
    res = client.patch(f"/memory/entities/{node.id}", json=patch_payload)
    assert res.status_code == 200
    updated = res.json()
    assert updated["name"] == "Updated Style"
    assert updated["content"] == "Use 4 spaces for indentation"
    assert updated["importance_score"] == 0.95
    assert updated["properties"]["indent_size"] == 4

    # Verify 404 for invalid node
    res_404 = client.patch("/memory/entities/non-existent-uuid", json=patch_payload)
    assert res_404.status_code == 404


def test_delete_memory_right_to_forget(client, db):
    node = MemoryService.add_node(
        db, workspace_id=1, node_type="user_preference", name="Sensitive fact", content="User phone number 555-0199"
    )
    db.commit()

    # Soft delete (Right to Forget)
    with patch("app.routers.memory._sync_qdrant_deletion") as mock_qdrant_sync:
        res = client.delete(f"/memory/{node.id}")
        assert res.status_code == 200
        assert res.json()["deleted"] is True
        assert res.json()["hard_delete"] is False
        assert mock_qdrant_sync.called

    # Confirm node is soft-invalidated
    db.refresh(node)
    assert node.invalidated_at is not None

    # Hard delete
    node_hard = MemoryService.add_node(
        db, workspace_id=1, node_type="episodic_memory", name="Ephemeral", content="Delete forever"
    )
    db.commit()
    res_hard = client.delete(f"/memory/{node_hard.id}?hard_delete=true")
    assert res_hard.status_code == 200
    assert db.get(MemoryNode, node_hard.id) is None

    # 404 for missing
    res_missing = client.delete("/memory/missing-uuid")
    assert res_missing.status_code == 404


def test_trigger_dream_cycle_endpoint(client, db):
    with patch("app.routers.memory.NREMConsolidator.consolidate", return_value={"pruned_noise_count": 2}) as mock_nrem, \
         patch("app.routers.memory.REMDreamer.run_dream_cycle", return_value={"indexed_dream_count": 1}) as mock_rem:
        res = client.post(
            "/memory/dream",
            json={"workspace_id": 1, "run_nrem": True, "run_rem": True, "max_dreams": 2},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["workspace_id"] == 1
        assert data["nrem"]["pruned_noise_count"] == 2
        assert data["rem"]["indexed_dream_count"] == 1
        assert mock_nrem.called
        assert mock_rem.called


def test_get_dream_status(client, db):
    MemoryService.add_node(db, workspace_id=1, node_type="episodic_memory", name="E1", content="Active episodic")
    MemoryService.add_node(db, workspace_id=1, node_type="user_preference", name="P1", content="Active preference")
    dream_node = MemoryService.add_node(db, workspace_id=1, node_type="dream_insight", name="D1", content="Dream insight")
    inv_node = MemoryService.add_node(db, workspace_id=1, node_type="episodic_memory", name="E2", content="Pruned noise")
    MemoryService.invalidate_node(db, inv_node.id)

    # Edge between E1 and dream_node
    MemoryService.add_edge(db, workspace_id=1, source_id=dream_node.id, target_id=inv_node.id, relation_type="synthesizes")
    db.commit()

    res = client.get("/memory/dream/status?workspace_id=1")
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["workspace_id"] == 1
    assert status_data["total_memories"] == 4
    assert status_data["active_nodes"] == 3
    assert status_data["invalidated_nodes"] == 1
    assert status_data["counts_by_type"]["episodic_memory"] == 1
    assert status_data["counts_by_type"]["user_preference"] == 1
    assert status_data["counts_by_type"]["dream_insight"] == 1
    assert status_data["total_edges"] == 1  # 1 synthesizes edge
