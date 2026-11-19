"""Tests for chat router: persistence and history."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.chat import ChatMessage


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


FAKE_ANSWER = {
    "answer": "The answer is 42 [1].",
    "citations": [{"index": 1, "file_name": "guide.txt", "text": "42"}],
    "provider": "fake",
    "model": "test-model",
    "degraded": False,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChatPersistence:
    @patch("app.routers.chat.answer_query", return_value=FAKE_ANSWER)
    def test_post_persists_user_and_assistant_messages(self, mock_aq, client, db):
        resp = client.post("/chat", json={"workspace_id": 1, "message": "What is 42?"})
        assert resp.status_code == 200

        msgs = db.query(ChatMessage).order_by(ChatMessage.id).all()
        assert len(msgs) == 2

        assert msgs[0].role == "user"
        assert msgs[0].content == "What is 42?"
        assert msgs[0].workspace_id == 1

        assert msgs[1].role == "assistant"
        assert msgs[1].content == "The answer is 42 [1]."
        assert msgs[1].provider == "fake"
        assert msgs[1].degraded is False

    @patch("app.routers.chat.answer_query", return_value=FAKE_ANSWER)
    def test_empty_message_rejected(self, mock_aq, client):
        resp = client.post("/chat", json={"workspace_id": 1, "message": ""})
        assert resp.status_code == 422


class TestChatHistory:
    @patch("app.routers.chat.answer_query", return_value=FAKE_ANSWER)
    def test_history_returns_persisted_messages(self, mock_aq, client):
        client.post("/chat", json={"workspace_id": 1, "message": "Hello"})

        resp = client.get("/chat/history", params={"workspace_id": 1})
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2
        assert items[0]["role"] == "user"
        assert items[0]["content"] == "Hello"
        assert items[1]["role"] == "assistant"

    @patch("app.routers.chat.answer_query", return_value=FAKE_ANSWER)
    def test_history_scoped_to_workspace(self, mock_aq, client):
        client.post("/chat", json={"workspace_id": 1, "message": "ws1"})
        client.post("/chat", json={"workspace_id": 2, "message": "ws2"})

        resp = client.get("/chat/history", params={"workspace_id": 1})
        items = resp.json()
        assert len(items) == 2  # only ws1 user+assistant

    def test_history_empty_workspace(self, client):
        resp = client.get("/chat/history", params={"workspace_id": 999})
        assert resp.status_code == 200
        assert resp.json() == []
