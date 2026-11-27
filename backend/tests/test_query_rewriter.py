"""Tests for conversational query rewriting and HyDE (TKT-018)."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.chat import ChatMessage
from app.models.user import Workspace
from app.services.chat import answer_query, stream_answer_query
from app.services.providers import ProviderError
from app.services.query import QueryRewriter
from app.services.retrieval import retrieve


# ---------------------------------------------------------------------------
# Test DB fixture (in-memory SQLite)
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


class FakeLLM:
    def __init__(self, responses: list[str] | None = None, should_fail: bool = False):
        self.responses = responses or ["Rewritten Standalone Query"]
        self.call_count = 0
        self.should_fail = should_fail
        self.name = "fake-llm"
        self.model = "test-model"

    def complete(self, system: str, user: str) -> str:
        if self.should_fail:
            raise ProviderError("LLM simulation failure")
        resp = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return resp


# ---------------------------------------------------------------------------
# 1. Needs Rewriting Heuristic
# ---------------------------------------------------------------------------

class TestNeedsRewriting:
    def test_pronouns_trigger_rewriting(self):
        assert QueryRewriter.needs_rewriting("How does it compare?") is True
        assert QueryRewriter.needs_rewriting("Tell me more about that") is True
        assert QueryRewriter.needs_rewriting("What did they decide?") is True
        assert QueryRewriter.needs_rewriting("Why?") is True
        assert QueryRewriter.needs_rewriting("How so?") is True

    def test_standalone_queries_skip_rewriting(self):
        assert (
            QueryRewriter.needs_rewriting("What is the architecture of the Qdrant vector database system?")
            is False
        )


# ---------------------------------------------------------------------------
# 2. Query Rewriter Service
# ---------------------------------------------------------------------------

class TestQueryRewriterService:
    def test_rewrite_empty_history_returns_original(self):
        provider = FakeLLM()
        res = QueryRewriter.rewrite_conversational_query([], "How does it work?", provider=provider)
        assert res == "How does it work?"
        assert provider.call_count == 0

    def test_rewrite_disabled_setting_returns_original(self):
        provider = FakeLLM()
        with patch("app.services.query.query_rewriter_settings", return_value={"rewrite_enabled": False}):
            res = QueryRewriter.rewrite_conversational_query(
                [{"role": "user", "content": "What is Qdrant?"}],
                "How does it work?",
                provider=provider,
            )
            assert res == "How does it work?"
            assert provider.call_count == 0

    def test_rewrite_with_history_produces_standalone_query(self):
        provider = FakeLLM(responses=["Standalone Search Query: What is the indexing mechanism of Qdrant?"])
        history = [
            {"role": "user", "content": "What is Qdrant?"},
            {"role": "assistant", "content": "Qdrant is a vector similarity search engine."},
        ]

        res = QueryRewriter.rewrite_conversational_query(history, "How does it index data?", provider=provider)
        assert res == "What is the indexing mechanism of Qdrant?"
        assert provider.call_count == 1

    def test_rewrite_provider_error_falls_back_to_original(self):
        failing_provider = FakeLLM(should_fail=True)
        history = [{"role": "user", "content": "Hello"}]

        res = QueryRewriter.rewrite_conversational_query(
            history, "How does it compare?", provider=failing_provider
        )
        assert res == "How does it compare?"


# ---------------------------------------------------------------------------
# 3. HyDE Generation
# ---------------------------------------------------------------------------

class TestHyDEGeneration:
    def test_hyde_disabled_by_default(self):
        provider = FakeLLM()
        res = QueryRewriter.generate_hyde("What is late chunking?", provider=provider)
        assert res is None
        assert provider.call_count == 0

    def test_hyde_enabled_generates_hypothetical_passage(self):
        provider = FakeLLM(responses=["Late chunking uses token span pooling from full document attention."])
        with patch("app.services.query.query_rewriter_settings", return_value={"hyde_enabled": True}):
            res = QueryRewriter.generate_hyde("What is late chunking?", provider=provider)
            assert res == "Late chunking uses token span pooling from full document attention."
            assert provider.call_count == 1

    def test_hyde_provider_error_returns_none(self):
        failing_provider = FakeLLM(should_fail=True)
        with patch("app.services.query.query_rewriter_settings", return_value={"hyde_enabled": True}):
            res = QueryRewriter.generate_hyde("What is late chunking?", provider=failing_provider)
            assert res is None


# ---------------------------------------------------------------------------
# 4. Retrieval Integration with Rewritten Query & HyDE
# ---------------------------------------------------------------------------

class TestRetrievalWithTransformation:
    @patch("app.services.retrieval._query_qdrant")
    @patch("app.services.retrieval.embed_sparse")
    @patch("app.services.retrieval.embed")
    def test_retrieve_uses_rewritten_query_and_hyde(self, mock_embed, mock_sparse, mock_qdrant):
        mock_embed.return_value = [[0.1, 0.2]]
        mock_sparse.return_value = {"indices": [1], "values": [0.5]}
        mock_point = MagicMock()
        mock_point.id = 1
        mock_point.payload = {"file_name": "guide.txt", "text": "Qdrant vector engine"}
        mock_qdrant.return_value = [mock_point]

        hits = retrieve(
            workspace_id=1,
            query="How does it work?",
            rewritten_query="What is the architecture of Qdrant?",
            hyde_passage="Qdrant uses HNSW graphs for vector indexing.",
            mode="hybrid",
        )

        assert len(hits) == 1
        assert hits[0]["file_name"] == "guide.txt"
        # Verify embed was called for both rewritten query and hyde passage
        assert mock_embed.call_count >= 2


# ---------------------------------------------------------------------------
# 5. Multi-turn Chat Integration with DB History
# ---------------------------------------------------------------------------

class TestMultiTurnChatQueryRewriting:
    @patch("app.services.chat.retrieve")
    def test_answer_query_rewrites_pronoun_with_db_history(self, mock_ret, db):
        mock_ret.return_value = [{"text": "Titan spec.", "file_name": "titan.md", "chunk_index": 0}]

        # Seed previous interaction into DB
        db.add(ChatMessage(workspace_id=1, role="user", content="Tell me about Project Titan."))
        db.add(ChatMessage(workspace_id=1, role="assistant", content="Project Titan is our new autonomous vehicle."))
        db.commit()

        provider = FakeLLM(responses=[
            "What are the specifications of Project Titan?",  # query rewrite response
            "Titan has 500hp [1].",  # answer completion
        ])

        ans = answer_query(workspace_id=1, message="What are its specifications?", provider=provider, db=db)

        assert ans["answer"] == "Titan has 500hp [1]."
        # Verify retrieve was called with the rewritten query
        call_kwargs = mock_ret.call_args.kwargs
        assert call_kwargs.get("rewritten_query") == "What are the specifications of Project Titan?"
