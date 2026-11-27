"""Tests for Automated Faithfulness, Hallucination Guardrails, and PII Sanitization (TKT-022)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.user import Workspace
from app.services.guardrails import FaithfulnessVerifier, PIISanitizer


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
# PII Sanitizer Unit Tests
# ---------------------------------------------------------------------------

class TestPIISanitizer:
    def test_sanitize_emails(self):
        text = "Contact alice.smith@example.org or bob_123@work-domain.co.uk for inquiries."
        sanitized, counts = PIISanitizer.sanitize(text)
        assert "[EMAIL_REDACTED]" in sanitized
        assert "alice.smith@example.org" not in sanitized
        assert "bob_123@work-domain.co.uk" not in sanitized
        assert counts["emails"] == 2
        assert counts["total"] == 2

    def test_sanitize_ssn(self):
        text = "Applicant SSN is 123-45-6789 and secondary is 987-65-4321."
        sanitized, counts = PIISanitizer.sanitize(text)
        assert "[SSN_REDACTED]" in sanitized
        assert "123-45-6789" not in sanitized
        assert counts["ssn"] == 2

    def test_sanitize_credit_cards(self):
        text = "Card number: 4111 2222 3333 4444 or 5500-0000-0000-0004 for billing."
        sanitized, counts = PIISanitizer.sanitize(text)
        assert "[CREDIT_CARD_REDACTED]" in sanitized
        assert "4111 2222 3333 4444" not in sanitized
        assert counts["credit_cards"] == 2

    def test_sanitize_phone_numbers(self):
        text = "Call customer support at 555-123-4567 or (800) 555-9999 immediately."
        sanitized, counts = PIISanitizer.sanitize(text)
        assert "[PHONE_REDACTED]" in sanitized
        assert "555-123-4567" not in sanitized
        assert counts["phones"] >= 1

    def test_has_pii(self):
        assert PIISanitizer.has_pii("Send email to user@domain.com") is True
        assert PIISanitizer.has_pii("Nothing sensitive here at all.") is False


# ---------------------------------------------------------------------------
# Faithfulness Verifier Unit Tests
# ---------------------------------------------------------------------------

class TestFaithfulnessVerifier:
    def test_extract_claims(self):
        answer = (
            "Based on your documents, the system uses Qdrant for vector storage [1]. "
            "It also utilizes Redis for caching session states [2].\n"
            "- Additionally, PostgreSQL maintains relational integrity."
        )
        claims = FaithfulnessVerifier.extract_claims(answer)
        assert len(claims) >= 2
        # Citation brackets and markdown lists should be stripped
        assert not any("[1]" in c for c in claims)
        assert not any("[2]" in c for c in claims)

    def test_faithful_grounded_answer(self):
        context = (
            "Qdrant provides hybrid dense and sparse vector indexing. "
            "PostgreSQL stores user accounts and workspace configuration."
        )
        answer = "Qdrant provides hybrid dense and sparse vector indexing [1]."
        citations = [{"text": context, "index": 1}]

        result = FaithfulnessVerifier.verify(answer, context, citations)
        assert result.is_faithful is True
        assert result.score >= 0.8
        assert len(result.unsupported_claims) == 0
        assert result.flagged is False

    def test_hallucinated_unsupported_answer(self):
        context = "The application runs on Docker containers managed via Docker Compose."
        answer = (
            "The architecture utilizes quantum flux capacitors with tachyon teleportation [1]. "
            "It automatically synthesizes hyperdimensional wormholes."
        )
        citations = [{"text": context, "index": 1}]

        result = FaithfulnessVerifier.verify(answer, context, citations)
        assert result.is_faithful is False
        assert result.score < 0.65
        assert len(result.unsupported_claims) > 0
        assert result.flagged is True


# ---------------------------------------------------------------------------
# Integration Tests: Chat Route & Audit Logging
# ---------------------------------------------------------------------------

def test_chat_faithfulness_and_audit_logging(client, db):
    ws = Workspace(name="Guardrail Workspace")
    db.add(ws)
    db.commit()

    class FaithfulMockLLM:
        name = "faithful_llm"
        model = "v1"

        def complete(self, sys: str, prompt: str) -> str:
            return "Solar panels generate renewable electric power from sunlight [1]."

    fake_hits = [
        {
            "document_id": 1,
            "file_name": "solar.txt",
            "text": "Solar panels generate renewable electric power from sunlight efficiently.",
        }
    ]

    with patch("app.services.chat.retrieve", return_value=fake_hits), \
         patch("app.services.chat.get_provider", return_value=FaithfulMockLLM()):

        resp = client.post(
            "/chat",
            json={"workspace_id": ws.id, "message": "How do solar panels work?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["faithfulness_score"] is not None
        assert data["faithfulness_score"] >= 0.8
        assert data["hallucination_detected"] is False

        # Verify AuditLog recorded the verification metrics
        log_entry = (
            db.query(AuditLog)
            .filter_by(workspace_id=ws.id, event_type="chat.query")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert log_entry is not None
        assert log_entry.status == "success"
        assert log_entry.metadata_json.get("faithfulness_score") >= 0.8
        assert log_entry.metadata_json.get("hallucination_detected") is False


def test_chat_hallucination_flagged_with_warning(client, db):
    ws = Workspace(name="Hallucination Test WS")
    db.add(ws)
    db.commit()

    class HallucinatingMockLLM:
        name = "hallucinating_llm"
        model = "v1"

        def complete(self, sys: str, prompt: str) -> str:
            return "Unicorn dividends yield 500% profits quarterly on Martian space stations."

    fake_hits = [
        {
            "document_id": 2,
            "file_name": "quarterly.txt",
            "text": "Standard treasury bonds yielded 3.5 percent during the fourth quarter.",
        }
    ]

    with patch("app.services.chat.retrieve", return_value=fake_hits), \
         patch("app.services.chat.get_provider", return_value=HallucinatingMockLLM()):

        resp = client.post(
            "/chat",
            json={"workspace_id": ws.id, "message": "What were the dividends?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hallucination_detected"] is True
        assert data["faithfulness_score"] < 0.65
        assert "Verification Notice" in data["answer"]

        # AuditLog status should be 'warning'
        log_entry = (
            db.query(AuditLog)
            .filter_by(workspace_id=ws.id, event_type="chat.query")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert log_entry is not None
        assert log_entry.status == "warning"
        assert log_entry.metadata_json.get("hallucination_detected") is True
