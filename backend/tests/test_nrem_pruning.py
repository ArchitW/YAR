"""Unit and integration tests for NREM Synaptic Pruning & Deduplication Engine."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.memory import MemoryEdge, MemoryNode
from app.models.user import User, Workspace
from app.services.dreaming.nrem import (
    NREMConsolidator,
    calculate_jaccard_similarity,
    extract_preference_topic,
    is_contradiction,
)
from app.services.memory import MemoryService

# In-memory test database fixture
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


# ---------------------------------------------------------------------------
# Unit tests for similarity and contradiction detection
# ---------------------------------------------------------------------------

def test_calculate_jaccard_similarity():
    assert calculate_jaccard_similarity("hello world", "hello world") == 1.0
    assert calculate_jaccard_similarity("hello world", "completely different text") == 0.0
    assert calculate_jaccard_similarity("", "something") == 0.0

    # High overlap
    sim = calculate_jaccard_similarity(
        "We deploy the backend on Ubuntu 24.04 LTS",
        "We deploy the backend on Ubuntu 24.04",
    )
    assert sim >= 0.8


def test_extract_preference_topic():
    top_db = extract_preference_topic("I prefer SQLite database for testing")
    assert top_db is not None
    assert top_db[0] in ("database", "db")

    top_never = extract_preference_topic("Never use passlib")
    assert top_never == ("use_passlib", "forbidden")

    top_always = extract_preference_topic("Always use bcrypt")
    assert top_always == ("use_bcrypt", "required")


def test_is_contradiction(db):
    node1 = MemoryNode(
        workspace_id=1,
        node_type="user_preference",
        name="DB Preference",
        content="I prefer SQLite database",
        importance_score=0.9,
        properties={"attribute_key": "database", "attribute_value": "sqlite"},
    )
    node2 = MemoryNode(
        workspace_id=1,
        node_type="user_preference",
        name="DB Preference Updated",
        content="I prefer Postgres database",
        importance_score=0.9,
        properties={"attribute_key": "database", "attribute_value": "postgres"},
    )
    assert is_contradiction(node1, node2) is True

    # Same value is not a contradiction
    node3 = MemoryNode(
        workspace_id=1,
        node_type="user_preference",
        name="DB Preference",
        content="I prefer SQLite database",
        importance_score=0.9,
        properties={"attribute_key": "database", "attribute_value": "sqlite"},
    )
    assert is_contradiction(node1, node3) is False


# ---------------------------------------------------------------------------
# NREM Noise Pruning Tests
# ---------------------------------------------------------------------------

def test_prune_noise_removes_old_transient_acknowledgments(db):
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=50)

    # 1. Old transient noise (should be pruned)
    noise_old = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="episodic_memory",
        name="User acknowledgment",
        content="ok thanks!",
        importance_score=0.2,
    )
    noise_old.created_at = old_time

    # 2. Recent transient noise (should NOT be pruned)
    noise_recent = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="episodic_memory",
        name="Recent acknowledgment",
        content="got it",
        importance_score=0.2,
    )
    noise_recent.created_at = now - timedelta(hours=2)

    # 3. Old high-salience decision (should NOT be pruned)
    decision_old = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="episodic_memory",
        name="Architecture decision",
        content="We decided to use native bcrypt with 72-byte truncation",
        importance_score=0.85,
    )
    decision_old.created_at = old_time

    db.commit()

    pruned_count = NREMConsolidator.prune_noise(db, workspace_id=1, threshold_hours=48.0)
    assert pruned_count == 1

    # Reload from DB
    reloaded_noise_old = db.get(MemoryNode, noise_old.id)
    assert reloaded_noise_old.invalidated_at is not None
    assert reloaded_noise_old.properties.get("pruned") is True

    reloaded_noise_recent = db.get(MemoryNode, noise_recent.id)
    assert reloaded_noise_recent.invalidated_at is None

    reloaded_decision_old = db.get(MemoryNode, decision_old.id)
    assert reloaded_decision_old.invalidated_at is None


# ---------------------------------------------------------------------------
# NREM Deduplication Tests
# ---------------------------------------------------------------------------

def test_deduplicate_clusters_and_merges_access_counts(db):
    now = datetime.now(timezone.utc)

    # Primary memory
    node_a = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="episodic_memory",
        name="Deployment config A",
        content="We deploy the API on Ubuntu 24.04 LTS servers",
        importance_score=0.7,
    )
    node_a.created_at = now - timedelta(hours=10)
    node_a.access_count = 2

    # Near-duplicate memory
    node_b = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="episodic_memory",
        name="Deployment config B",
        content="We deploy the API on Ubuntu 24.04 LTS",
        importance_score=0.6,
    )
    node_b.created_at = now - timedelta(hours=5)
    node_b.access_count = 3

    db.commit()

    deduped_count = NREMConsolidator.deduplicate(db, workspace_id=1, similarity_threshold=0.8)
    assert deduped_count == 1

    db.refresh(node_a)
    db.refresh(node_b)

    # Node A is canonical (higher importance): access_count merged (2 + 3 = 5)
    assert node_a.access_count == 5
    assert node_a.invalidated_at is None

    # Node B is superseded
    assert node_b.invalidated_at is not None

    # Check superseding edge
    edge = db.query(MemoryEdge).filter_by(source_id=node_a.id, target_id=node_b.id).first()
    assert edge is not None
    assert edge.relation_type == "supersedes"


# ---------------------------------------------------------------------------
# Contradiction Resolution Tests
# ---------------------------------------------------------------------------

def test_resolve_contradictions_invalidates_older_and_links_supersedes_edge(db):
    now = datetime.now(timezone.utc)

    # Fact 1 (Older): "We use SQLite database"
    fact1 = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="user_preference",
        name="DB Selection 1",
        content="I prefer SQLite database",
        importance_score=0.9,
        properties={"attribute_key": "database", "attribute_value": "sqlite"},
    )
    fact1.created_at = now - timedelta(hours=20)

    # Fact 2 (Newer): "Switched from SQLite to Postgres"
    fact2 = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="user_preference",
        name="DB Selection 2",
        content="Switched from SQLite to Postgres database",
        importance_score=0.95,
        properties={"attribute_key": "database", "attribute_value": "postgres"},
    )
    fact2.created_at = now - timedelta(hours=1)

    db.commit()

    resolved_count = NREMConsolidator.resolve_contradictions(db, workspace_id=1)
    assert resolved_count == 1

    db.refresh(fact1)
    db.refresh(fact2)

    # Older fact is invalidated
    assert fact1.invalidated_at is not None

    # Newer fact remains active
    assert fact2.invalidated_at is None

    # Verify edge
    edge = db.query(MemoryEdge).filter_by(source_id=fact2.id, target_id=fact1.id).first()
    assert edge is not None
    assert edge.relation_type == "supersedes"


def test_dossier_reflects_latest_superseding_fact(db):
    now = datetime.now(timezone.utc)

    pref1 = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="user_preference",
        name="Formatting",
        content="I prefer verbose explanations",
        importance_score=0.8,
        properties={"attribute_key": "preference", "attribute_value": "verbose explanations"},
    )
    pref1.created_at = now - timedelta(hours=10)

    pref2 = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="user_preference",
        name="Formatting Updated",
        content="I prefer concise explanations",
        importance_score=0.9,
        properties={"attribute_key": "preference", "attribute_value": "concise explanations"},
    )
    pref2.created_at = now - timedelta(hours=1)

    db.commit()

    # Before resolution: both in dossier
    assert len(MemoryService.get_active_dossier(db, workspace_id=1)) == 2

    # Run resolution
    NREMConsolidator.resolve_contradictions(db, workspace_id=1)

    # After resolution: only latest active fact in dossier
    dossier = MemoryService.get_active_dossier(db, workspace_id=1)
    assert len(dossier) == 1
    assert dossier[0]["id"] == pref2.id
    assert "concise" in dossier[0]["content"]


# ---------------------------------------------------------------------------
# Living Dossier Synchronization Tests
# ---------------------------------------------------------------------------

def test_sync_to_dossier_extracts_preferences_and_invariants(db):
    # Episodic conversation turn
    episodic = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="episodic_memory",
        name="User message",
        content="I prefer Python FastAPI over Flask",
        importance_score=0.85,
    )
    db.commit()

    synced_nodes = NREMConsolidator.sync_to_dossier(db, workspace_id=1)
    assert len(synced_nodes) >= 1

    dossier_node = synced_nodes[0]
    assert dossier_node.node_type == "user_preference"
    assert "Python FastAPI" in dossier_node.content

    # Check extracted_from edge
    edge = db.query(MemoryEdge).filter_by(source_id=episodic.id, target_id=dossier_node.id).first()
    assert edge is not None
    assert edge.relation_type == "extracted_from"

    # Verify episodic node marked as synced
    db.refresh(episodic)
    assert episodic.properties.get("dossier_synced") is True

    # Subsequent sync does not duplicate
    second_sync = NREMConsolidator.sync_to_dossier(db, workspace_id=1)
    assert len(second_sync) == 0


# ---------------------------------------------------------------------------
# Full Consolidation Cycle & Isolation Tests
# ---------------------------------------------------------------------------

def test_consolidate_full_cycle_and_workspace_isolation(db):
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=72)

    # Workspace 1: Noise to prune
    w1_noise = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="episodic_memory",
        name="Noise",
        content="ok",
        importance_score=0.2,
    )
    w1_noise.created_at = old_time

    # Workspace 2: Noise that should remain untouched when running on workspace 1
    w2_noise = MemoryService.add_node(
        db=db,
        workspace_id=2,
        node_type="episodic_memory",
        name="Noise W2",
        content="ok",
        importance_score=0.2,
    )
    w2_noise.created_at = old_time

    # Workspace 1: High-salience preference to sync
    MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="episodic_memory",
        name="Decision",
        content="Our rule is always write type annotations",
        importance_score=0.85,
    )

    db.commit()

    stats = NREMConsolidator.consolidate(db, workspace_id=1, threshold_hours=48.0)
    assert stats["workspace_id"] == 1
    assert stats["pruned_noise_count"] == 1
    assert stats["synced_dossier_count"] >= 1

    # Verify Workspace 2 noise is untouched
    db.refresh(w2_noise)
    assert w2_noise.invalidated_at is None
    assert w2_noise.properties.get("pruned") is not True


def test_empty_workspace_consolidation(db):
    stats = NREMConsolidator.consolidate(db, workspace_id=999)
    assert stats["workspace_id"] == 999
    assert stats["pruned_noise_count"] == 0
    assert stats["deduplicated_count"] == 0
    assert stats["contradictions_resolved_count"] == 0
    assert stats["synced_dossier_count"] == 0


def test_prune_noise_preserves_non_episodic_types(db):
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=100)

    # Low-importance concept (should NOT be pruned by episodic noise filter)
    concept = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="concept",
        name="Minor concept",
        content="some minor concept",
        importance_score=0.2,
    )
    concept.created_at = old_time
    db.commit()

    pruned = NREMConsolidator.prune_noise(db, workspace_id=1, threshold_hours=48.0)
    assert pruned == 0
    db.refresh(concept)
    assert concept.invalidated_at is None


def test_deduplicate_triplet_cluster(db):
    now = datetime.now(timezone.utc)

    # 3 near-identical nodes
    n1 = MemoryService.add_node(db, 1, "episodic_memory", "Fact A", "The server runs on port 8000 in production", importance_score=0.7)
    n1.created_at = now - timedelta(hours=3)
    n2 = MemoryService.add_node(db, 1, "episodic_memory", "Fact B", "The server runs on port 8000 in production mode", importance_score=0.75)
    n2.created_at = now - timedelta(hours=2)
    n3 = MemoryService.add_node(db, 1, "episodic_memory", "Fact C", "The server runs on port 8000 production", importance_score=0.6)
    n3.created_at = now - timedelta(hours=1)
    db.commit()

    deduped = NREMConsolidator.deduplicate(db, workspace_id=1, similarity_threshold=0.75)
    assert deduped == 2

    # n2 has highest importance (0.75), so it should remain active
    db.refresh(n2)
    assert n2.invalidated_at is None

