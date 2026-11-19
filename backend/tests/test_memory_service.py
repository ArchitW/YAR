"""Comprehensive tests for Cognitive Memory Service, Node/Edge Graph, and Chat Integration."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.memory import MemoryEdge, MemoryNode
from app.services.memory import (
    MemoryService,
    calculate_recency_score,
    calculate_lexical_relevance,
    score_importance,
)

# ---------------------------------------------------------------------------
# Test DB fixture (in-memory SQLite with StaticPool)
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
# Unit Tests for Scoring Functions
# ---------------------------------------------------------------------------

def test_score_importance():
    # Transient noise
    assert score_importance("ok") == 0.2
    assert score_importance("thanks!") == 0.2
    assert score_importance("got it") == 0.2

    # High importance patterns
    assert score_importance("I prefer concise code without boilerplate") >= 0.8
    assert score_importance("Always use SQLite for local caching") >= 0.8
    assert score_importance("We decided to switch away from Passlib") >= 0.8

    # Default questions
    assert score_importance("Where is the user configuration file?") == 0.5


def test_calculate_recency_score():
    now = datetime.now(timezone.utc)

    # Accessed just now -> score ~ 1.0
    assert pytest.approx(calculate_recency_score(now, half_life_hours=72.0), abs=0.01) == 1.0

    # Accessed 72 hours ago -> score ~ 0.5
    past_72h = now - timedelta(hours=72)
    assert pytest.approx(calculate_recency_score(past_72h, half_life_hours=72.0), abs=0.02) == 0.5

    # Accessed 144 hours ago -> score ~ 0.25
    past_144h = now - timedelta(hours=144)
    assert pytest.approx(calculate_recency_score(past_144h, half_life_hours=72.0), abs=0.02) == 0.25


def test_calculate_lexical_relevance():
    query = "vector database Qdrant"
    text_match = "We use Qdrant for vector database storage and hybrid retrieval"
    text_unrelated = "Frontend styling uses Tailwind CSS and shadcn"

    rel_match = calculate_lexical_relevance(query, text_match)
    rel_unrelated = calculate_lexical_relevance(query, text_unrelated)

    assert rel_match > 0.4
    assert rel_unrelated == 0.0


# ---------------------------------------------------------------------------
# Memory Node and Edge Persistence Tests
# ---------------------------------------------------------------------------

def test_add_node_and_directed_edge(db):
    node_user = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="entity",
        name="User",
        content="Primary user entity",
    )
    node_pref = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="user_preference",
        name="Language Preference",
        content="Prefers Python 3.12 with type annotations",
        importance_score=0.9,
    )
    edge = MemoryService.add_edge(
        db=db,
        workspace_id=1,
        source_id=node_user.id,
        target_id=node_pref.id,
        relation_type="prefers",
        weight=1.0,
    )
    db.commit()

    assert node_user.id is not None
    assert node_pref.id is not None
    assert edge.source_id == node_user.id
    assert edge.target_id == node_pref.id
    assert edge.relation_type == "prefers"

    # Verify ORM relationship traversal
    reloaded_user = db.get(MemoryNode, node_user.id)
    assert len(reloaded_user.out_edges) == 1
    assert reloaded_user.out_edges[0].target_id == node_pref.id


def test_record_interaction_auto_extracts_preference(db):
    # Standard interaction
    m1 = MemoryService.record_interaction(
        db=db,
        workspace_id=1,
        role="user",
        content="What is the total revenue for Q3?",
    )
    assert m1.node_type == "episodic_memory"
    assert m1.importance_score == 0.5

    # High salience preference interaction
    m2 = MemoryService.record_interaction(
        db=db,
        workspace_id=1,
        role="user",
        content="I prefer concise Rust code over verbose object-oriented patterns",
    )
    db.commit()

    assert m2.importance_score >= 0.8
    # Should have auto-extracted a user_preference node
    dossier = MemoryService.get_active_dossier(db, workspace_id=1)
    assert len(dossier) >= 1
    pref_entry = next(d for d in dossier if d["node_type"] == "user_preference")
    assert "concise Rust code" in pref_entry["content"]


def test_retrieve_memories_tri_factor(db):
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=10)

    # 1. Old memory about PostgreSQL
    m_old = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="episodic_memory",
        name="Old DB discussion",
        content="Discussed deploying PostgreSQL on AWS RDS",
        importance_score=0.5,
    )
    m_old.last_accessed_at = old_time

    # 2. Fresh memory about Qdrant
    m_fresh = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="episodic_memory",
        name="Vector DB choice",
        content="Adopted Qdrant for vector similarity search",
        importance_score=0.9,
    )
    m_fresh.last_accessed_at = now
    db.commit()

    # Search for vector search
    results = MemoryService.retrieve_memories(db, workspace_id=1, query="vector similarity Qdrant", top_k=2)
    assert len(results) > 0
    top_result = results[0]
    assert top_result["id"] == m_fresh.id
    assert top_result["retrieval_score"] > 0.5
    # Access count incremented
    assert top_result["access_count"] >= 2


def test_invalidation_and_superseding(db):
    old_pref = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="user_preference",
        name="DB Preference",
        content="Use MySQL for relational storage",
    )
    db.commit()

    # Verify it is in active dossier
    assert len(MemoryService.get_active_dossier(db, workspace_id=1)) == 1

    # New preference supersedes old
    new_pref = MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="user_preference",
        name="DB Preference",
        content="Switched from MySQL to SQLite for local development",
    )
    # Invalidate old with superseding link
    MemoryService.invalidate_node(
        db=db,
        node_id=old_pref.id,
        superseded_by_id=new_pref.id,
        reason="user_updated_decision",
    )
    db.commit()

    # Active dossier should only contain new_pref
    dossier = MemoryService.get_active_dossier(db, workspace_id=1)
    assert len(dossier) == 1
    assert dossier[0]["id"] == new_pref.id
    assert "SQLite" in dossier[0]["content"]

    # Verify supersedes edge exists
    edge = db.query(MemoryEdge).filter_by(source_id=new_pref.id, target_id=old_pref.id).first()
    assert edge is not None
    assert edge.relation_type == "supersedes"


def test_graph_neighborhood_traversal(db):
    # A -> B -> C
    node_a = MemoryService.add_node(db=db, workspace_id=1, node_type="concept", name="A", content="Node A")
    node_b = MemoryService.add_node(db=db, workspace_id=1, node_type="concept", name="B", content="Node B")
    node_c = MemoryService.add_node(db=db, workspace_id=1, node_type="concept", name="C", content="Node C")

    MemoryService.add_edge(db=db, workspace_id=1, source_id=node_a.id, target_id=node_b.id, relation_type="depends_on")
    MemoryService.add_edge(db=db, workspace_id=1, source_id=node_b.id, target_id=node_c.id, relation_type="depends_on")
    db.commit()

    # Depth 1 from A -> contains A and B
    subgraph_1 = MemoryService.traverse_neighborhood(db, root_node_id=node_a.id, max_depth=1)
    node_names_1 = {n["name"] for n in subgraph_1["nodes"]}
    assert node_names_1 == {"A", "B"}

    # Depth 2 from A -> contains A, B, and C
    subgraph_2 = MemoryService.traverse_neighborhood(db, root_node_id=node_a.id, max_depth=2)
    node_names_2 = {n["name"] for n in subgraph_2["nodes"]}
    assert node_names_2 == {"A", "B", "C"}
    assert len(subgraph_2["edges"]) == 2


# ---------------------------------------------------------------------------
# Integration Test: Chat Router with Cognitive Memory Stream
# ---------------------------------------------------------------------------

FAKE_GROUNDED_ANSWER = {
    "answer": "Grounded response citing [1].",
    "citations": [{"index": 1, "file_name": "guide.txt", "text": "fact"}],
    "provider": "fake_llm",
    "model": "model_v1",
    "degraded": False,
}


def test_chat_router_records_memory_and_injects_dossier(client, db):
    # 1. Pre-seed a living dossier user preference
    MemoryService.add_node(
        db=db,
        workspace_id=1,
        node_type="user_preference",
        name="User Code Style",
        content="Always write Python with modern type hints and Google docstrings",
        importance_score=0.9,
    )
    db.commit()

    # 2. Mock retrieve & LLM provider to capture the passed prompt
    captured_prompts = []

    class MockLLM:
        name = "mock_provider"
        model = "mock_model"

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            captured_prompts.append((system_prompt, user_prompt))
            return "Based on your documents, here is the answer [1]."

    fake_hits = [{"document_id": 1, "file_name": "doc.txt", "text": "Relevant chunk text"}]

    with patch("app.services.chat.retrieve", return_value=fake_hits), \
         patch("app.services.chat.get_provider", return_value=MockLLM()):

        response = client.post(
            "/chat",
            json={"workspace_id": 1, "message": "How do we format docstrings?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Based on your documents, here is the answer [1]."

        # 3. Verify user message and assistant message were logged in memory_nodes
        nodes = db.query(MemoryNode).filter_by(workspace_id=1, node_type="episodic_memory").all()
        assert len(nodes) == 2  # 1 user + 1 assistant
        user_memory = next(n for n in nodes if "How do we format" in n.content)
        assert user_memory is not None

        # 4. Verify that prompt sent to LLM included the Active User & Workspace Dossier
        assert len(captured_prompts) == 1
        _, user_prompt = captured_prompts[0]
        assert "Active User & Workspace Dossier" in user_prompt
        assert "Always write Python with modern type hints" in user_prompt
