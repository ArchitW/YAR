"""Unit and integration tests for REM Associative Dreaming & Synthetic Rehearsal Engine."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.document import Document
from app.models.memory import MemoryNode
from app.models.user import User, Workspace
from app.services.chat import build_context
from app.services.dreaming.rem import REMDreamer, compute_cosine_similarity
from app.services.retrieval import retrieve

# In-memory SQLite fixture
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
# Cosine Similarity & Pair Sampling Tests
# ---------------------------------------------------------------------------

def test_compute_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]

    assert pytest.approx(compute_cosine_similarity(v1, v2), 0.01) == 1.0
    assert pytest.approx(compute_cosine_similarity(v1, v3), 0.01) == 0.0
    assert compute_cosine_similarity([], [1.0]) == 0.0
    assert compute_cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test_sample_associative_pairs_filters_same_file_and_out_of_band_similarity():
    chunks = [
        {"id": "c1", "file_name": "backend.py", "text": "Python FastAPI application setup"},
        {"id": "c2", "file_name": "backend.py", "text": "Python FastAPI routes setup"},
        {"id": "c3", "file_name": "database.py", "text": "SQLAlchemy database connection pool"},
    ]

    with patch("app.services.dreaming.rem.embed") as mock_embed:
        # Mock embeddings: c1 & c2 similar (same file), c1 & c3 in associative sweet spot (~0.65), c2 & c3 low similarity (~0.065)
        mock_embed.return_value = [
            [1.0, 0.0, 0.0],
            [0.1, 0.99, 0.0],
            [0.65, 0.0, 0.76],
        ]
        pairs = REMDreamer.sample_associative_pairs(workspace_id=1, chunks=chunks, min_similarity=0.55, max_similarity=0.78)

        # Same file pair (c1, c2) must be excluded, (c2, c3) is below 0.55 -> only (c1, c3) matches
        assert len(pairs) == 1
        chunk_a, chunk_b, sim = pairs[0]
        assert chunk_a["file_name"] != chunk_b["file_name"]
        assert 0.55 <= sim <= 0.78


# ---------------------------------------------------------------------------
# Insight Synthesis & Synthetic QA Tests
# ---------------------------------------------------------------------------

def test_synthesize_cross_document_insights_extractive_fallback():
    chunk_a = {"id": "c1", "file_name": "auth.py", "text": "JWT tokens signed using RSA key"}
    chunk_b = {"id": "c2", "file_name": "gateway.py", "text": "Reverse proxy routes requests to upstream APIs"}

    insight = REMDreamer.synthesize_cross_document_insights(workspace_id=1, chunk_a=chunk_a, chunk_b=chunk_b, provider=None)
    assert "auth.py" in insight["title"]
    assert "gateway.py" in insight["title"]
    assert "c1" in insight["cited_chunk_ids"]
    assert "c2" in insight["cited_chunk_ids"]
    assert len(insight["synthesis"]) > 0


def test_synthesize_cross_document_insights_with_llm_provider():
    chunk_a = {"id": "c1", "file_name": "auth.py", "text": "JWT tokens signed with RSA key"}
    chunk_b = {"id": "c2", "file_name": "gateway.py", "text": "Reverse proxy verifies authorization header"}

    mock_provider = MagicMock()
    mock_provider.name = "mock-llm"
    mock_provider.model = "test-model"
    mock_provider.complete.return_value = "The gateway validates RSA tokens minted by auth service before forwarding."

    insight = REMDreamer.synthesize_cross_document_insights(
        workspace_id=1, chunk_a=chunk_a, chunk_b=chunk_b, provider=mock_provider
    )
    assert "gateway validates RSA tokens" in insight["synthesis"]
    assert insight["cited_chunk_ids"] == ["c1", "c2"]


def test_generate_synthetic_qa():
    chunk_a = {"id": "c1", "file_name": "auth.py", "text": "JWT auth"}
    chunk_b = {"id": "c2", "file_name": "gateway.py", "text": "API gateway"}
    insight = {"synthesis": "The gateway delegates authentication to the auth service."}

    qa = REMDreamer.generate_synthetic_qa(1, chunk_a, chunk_b, insight, provider=None)
    assert "question" in qa
    assert "answer" in qa
    assert "auth.py" in qa["question"] or "gateway.py" in qa["question"]
    assert "auth.py" in qa["answer"] or "gateway.py" in qa["answer"]


# ---------------------------------------------------------------------------
# Relational Graph & Qdrant Indexing Tests
# ---------------------------------------------------------------------------

def test_index_dream_insight_persists_to_graph_and_qdrant(db):
    dream_data = {
        "title": "Cross-System Auth Architecture",
        "synthesis": "Auth tokens are verified centrally at the API gateway layer.",
        "multi_hop_query": "How is authentication handled across services?",
        "synthetic_answer": "Via centralized token verification at the gateway.",
        "cited_chunk_ids": ["chunk_1", "chunk_2"],
        "source_files": ["auth.py", "gateway.py"],
    }

    mock_qdrant = MagicMock()

    with patch("app.services.dreaming.rem.embed", return_value=[[0.1] * 1024]), \
         patch("app.services.dreaming.rem.embed_sparse", return_value={"indices": [1], "values": [0.5]}):
        node = REMDreamer.index_dream_insight(
            db=db,
            workspace_id=1,
            dream_data=dream_data,
            qdrant_client=mock_qdrant,
        )

    db.commit()

    # Verify Relational MemoryNode persistence
    assert node.id is not None
    assert node.node_type == "dream_insight"
    assert node.name == "Cross-System Auth Architecture"
    assert node.properties["multi_hop_query"] == "How is authentication handled across services?"
    assert node.properties["cited_chunk_ids"] == ["chunk_1", "chunk_2"]

    # Verify Qdrant upsert call with is_dream=True
    assert mock_qdrant.upsert.called
    args, kwargs = mock_qdrant.upsert.call_args
    points = kwargs["points"]
    assert len(points) == 1
    point = points[0]
    assert point.payload["is_dream"] is True
    assert point.payload["workspace_id"] == 1
    assert point.payload["dream_insight_id"] == node.id


# ---------------------------------------------------------------------------
# Retrieval and Chat Provenance Verification Tests
# ---------------------------------------------------------------------------

def test_retrieval_and_chat_provenance_badge():
    raw_hit = {
        "id": "point-1",
        "score": 0.95,
        "document_id": 10,
        "file_name": "Dream Insight: Cross-Service Latency",
        "text": "Cross-service latency is mitigated by connection pooling.",
        "is_dream": True,
        "dream_title": "Cross-Service Latency Synergy",
    }

    context_str, citations = build_context([raw_hit])

    # Citation must carry is_dream flag
    assert len(citations) == 1
    assert citations[0]["is_dream"] is True

    # Context block must clearly display dream provenance
    assert "[Dream Insight: Cross-Service Latency Synergy]" in context_str
    assert "Cross-service latency is mitigated by connection pooling." in context_str


# ---------------------------------------------------------------------------
# End-to-End Dream Cycle Tests
# ---------------------------------------------------------------------------

def test_run_dream_cycle_end_to_end(db):
    doc1 = Document(
        workspace_id=1,
        name="finance.txt",
        content="The quarterly revenue increased by 25 percent driven by enterprise SaaS subscriptions.",
        status="indexed",
    )
    doc2 = Document(
        workspace_id=1,
        name="sales.txt",
        content="Enterprise customer onboarding accelerated following the new contract signing.",
        status="indexed",
    )
    db.add_all([doc1, doc2])
    db.commit()

    mock_qdrant = MagicMock()

    with patch("app.services.dreaming.rem.embed", side_effect=[
        # Embedding for pair sampling
        [[1.0, 0.0], [0.65, 0.75]],
        # Embedding for dream indexing
        [[0.1] * 1024],
    ]), patch("app.services.dreaming.rem.embed_sparse", return_value={"indices": [10], "values": [0.8]}):
        stats = REMDreamer.run_dream_cycle(
            db=db,
            workspace_id=1,
            max_dreams=1,
            qdrant_client=mock_qdrant,
        )

    assert stats["workspace_id"] == 1
    assert stats["pairs_sampled"] == 1
    assert stats["indexed_dream_count"] == 1
    assert len(stats["dream_node_ids"]) == 1

    # Verify node in DB
    dream_node = db.get(MemoryNode, stats["dream_node_ids"][0])
    assert dream_node is not None
    assert dream_node.node_type == "dream_insight"


def test_sample_associative_pairs_empty_or_single_chunk():
    assert REMDreamer.sample_associative_pairs(1, []) == []
    assert REMDreamer.sample_associative_pairs(1, [{"id": "c1", "file_name": "a.txt", "text": "hello"}]) == []


def test_generate_synthetic_qa_with_llm_provider():
    chunk_a = {"id": "c1", "file_name": "pricing.pdf", "text": "Tier 1 costs $10"}
    chunk_b = {"id": "c2", "file_name": "features.pdf", "text": "Tier 1 includes 5 users"}
    insight = {"synthesis": "Tier 1 pricing correlates with 5 users limit"}

    mock_llm = MagicMock()
    mock_llm.complete.return_value = "Q: What is the cost per user in Tier 1?\nA: It costs $10 for 5 users ($2/user)."

    qa = REMDreamer.generate_synthetic_qa(1, chunk_a, chunk_b, insight, provider=mock_llm)
    assert qa["question"] == "What is the cost per user in Tier 1?"
    assert "It costs $10 for 5 users" in qa["answer"]


def test_load_workspace_chunks_empty_docs(db):
    doc_empty = Document(workspace_id=99, name="empty.txt", content="", status="indexed")
    db.add(doc_empty)
    db.commit()

    chunks = REMDreamer.load_workspace_chunks(db, workspace_id=99)
    assert chunks == []

