"""Tests for streaming chat transport and progressive token delivery (TKT-016)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.chat import ChatMessage
from app.services.chat import NO_CONTEXT_ANSWER, stream_answer_query
from app.services.providers import OpenAICompatibleProvider, ProviderError


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
# 1. Tests for OpenAICompatibleProvider.stream_complete
# ---------------------------------------------------------------------------

class TestProviderStreaming:
    def test_stream_complete_yields_tokens(self):
        provider = OpenAICompatibleProvider(base_url="http://fake-llm", model="test-model")

        mock_lines = [
            b'data: {"choices": [{"delta": {"content": "Hello"}}]}',
            b"",
            b'data: {"choices": [{"delta": {"content": " world"}}]}',
            b'data: [DONE]',
        ]

        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [line.decode("utf-8") for line in mock_lines]
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with patch("httpx.Client", return_value=mock_client):
            tokens = list(provider.stream_complete("system prompt", "user query"))
            assert tokens == ["Hello", " world"]

    def test_stream_complete_http_error_raises_provider_error(self):
        import httpx

        provider = OpenAICompatibleProvider(base_url="http://fake-llm", model="test-model")

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.stream.side_effect = httpx.ConnectError("connection refused")

        with patch("httpx.Client", return_value=mock_client):
            with pytest.raises(ProviderError):
                list(provider.stream_complete("system", "user"))


# ---------------------------------------------------------------------------
# 2. Tests for stream_answer_query service
# ---------------------------------------------------------------------------

class FakeStreamingProvider:
    name = "fake-streamer"
    model = "stream-v1"

    def __init__(self, tokens: list[str] | None = None, should_fail: bool = False):
        self.tokens = tokens or ["Streamed", " answer", " [1]."]
        self.should_fail = should_fail

    def complete(self, system: str, user: str) -> str:
        if self.should_fail:
            raise ProviderError("LLM failed")
        return "".join(self.tokens)

    def stream_complete(self, system: str, user: str):
        if self.should_fail:
            raise ProviderError("Streaming connection broken")
        for t in self.tokens:
            yield t


class TestStreamAnswerQueryService:
    @patch("app.services.chat.retrieve", return_value=[])
    def test_stream_no_context_yields_refusal(self, mock_ret):
        events = list(stream_answer_query(workspace_id=1, message="Anything?"))
        assert len(events) == 3
        assert events[0]["type"] == "init"
        assert events[0]["citations"] == []
        assert events[1]["type"] == "token"
        assert events[1]["token"] == NO_CONTEXT_ANSWER
        assert events[2]["type"] == "done"
        assert events[2]["answer"] == NO_CONTEXT_ANSWER

    @patch("app.services.chat.retrieve")
    def test_stream_with_provider_yields_progressive_tokens(self, mock_ret):
        mock_ret.return_value = [
            {"text": "YAR is a RAG system.", "file_name": "about.txt", "chunk_index": 0}
        ]
        provider = FakeStreamingProvider(tokens=["YAR", " is", " great", " [1]."])

        events = list(stream_answer_query(workspace_id=1, message="What is YAR?", provider=provider))

        types = [e["type"] for e in events]
        assert types == ["init", "token", "token", "token", "token", "done"]

        assert events[0]["type"] == "init"
        assert len(events[0]["citations"]) == 1
        assert events[0]["citations"][0]["file_name"] == "about.txt"

        tokens = [e["token"] for e in events if e["type"] == "token"]
        assert "".join(tokens) == "YAR is great [1]."

        done_event = events[-1]
        assert done_event["answer"] == "YAR is great [1]."
        assert done_event["degraded"] is False
        assert done_event["provider"] == "fake-streamer"

    @patch("app.services.chat.retrieve")
    def test_stream_extractive_fallback_when_no_provider(self, mock_ret):
        mock_ret.return_value = [
            {"text": "Relevant excerpt line.", "file_name": "data.txt", "chunk_index": 1}
        ]

        with patch("app.services.chat.get_provider", return_value=None):
            events = list(stream_answer_query(workspace_id=1, message="What is this?"))

        assert events[0]["type"] == "init"
        assert events[0]["degraded"] is True
        assert events[0]["provider"] == "extractive"

        done = events[-1]
        assert done["type"] == "done"
        assert "Based on your documents:" in done["answer"]
        assert done["degraded"] is True

    @patch("app.services.chat.retrieve")
    def test_stream_provider_error_falls_back_gracefully(self, mock_ret):
        mock_ret.return_value = [
            {"text": "Fallback context chunk.", "file_name": "guide.txt", "chunk_index": 0}
        ]
        failing_provider = FakeStreamingProvider(should_fail=True)

        events = list(stream_answer_query(workspace_id=1, message="Hello?", provider=failing_provider))

        assert events[0]["type"] == "init"
        done = events[-1]
        assert done["type"] == "done"
        assert done["degraded"] is True
        assert "Fallback context chunk." in done["answer"]


# ---------------------------------------------------------------------------
# 3. Tests for POST /chat/stream router endpoint
# ---------------------------------------------------------------------------

class TestChatStreamRouter:
    def test_chat_stream_empty_message_rejected(self, client):
        resp = client.post("/chat/stream", json={"workspace_id": 1, "message": ""})
        assert resp.status_code == 422

    @patch("app.routers.chat.stream_answer_query")
    def test_chat_stream_emits_sse_and_persists_messages(self, mock_stream, client, db):
        mock_events = [
            {"type": "init", "citations": [{"index": 1, "file_name": "f.txt"}], "provider": "streamer", "model": "m1", "degraded": False},
            {"type": "token", "token": "Streaming "},
            {"type": "token", "token": "response!"},
            {"type": "done", "answer": "Streaming response!", "citations": [{"index": 1, "file_name": "f.txt"}], "provider": "streamer", "model": "m1", "degraded": False},
        ]
        mock_stream.return_value = iter(mock_events)

        resp = client.post("/chat/stream", json={"workspace_id": 1, "message": "Stream this"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        # Parse SSE lines
        lines = [line.strip() for line in resp.text.split("\n") if line.strip()]
        data_events = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]

        assert len(data_events) == 4
        assert data_events[0]["type"] == "init"
        assert data_events[1]["token"] == "Streaming "
        assert data_events[2]["token"] == "response!"
        assert data_events[3]["type"] == "done"

        # Verify DB persistence
        msgs = db.query(ChatMessage).order_by(ChatMessage.id).all()
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "Stream this"
        assert msgs[1].role == "assistant"
        assert msgs[1].content == "Streaming response!"
        assert msgs[1].provider == "streamer"
        assert msgs[1].degraded is False
