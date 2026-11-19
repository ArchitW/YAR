from typing import Any

import pytest

from app.services import chat
from app.services.providers import ProviderError


class FakeProvider:
    name = "fake"
    model = "test-model"

    def __init__(self, reply: str = "Grounded answer [1]", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if self.error:
            raise self.error
        return self.reply


def hit(text: str = "Revenue grew 12% in Q3.", file_name: str = "report.pdf", chunk_index: int = 0) -> dict[str, Any]:
    return {
        "document_id": 7,
        "file_name": file_name,
        "chunk_index": chunk_index,
        "text": text,
        "chunk_text": text,
        "score": 0.9,
    }


@pytest.fixture
def hits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    found = [hit(), hit("Costs fell 3%.", file_name="notes.txt", chunk_index=4)]
    monkeypatch.setattr(chat, "retrieve", lambda *args, **kwargs: found)
    return found


def test_refuses_without_retrieved_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat, "retrieve", lambda *args, **kwargs: [])
    provider = FakeProvider()

    result = chat.answer_query(1, "What is revenue?", provider=provider)

    assert result["provider"] == "none"
    assert result["citations"] == []
    assert result["answer"] == chat.NO_CONTEXT_ANSWER
    assert provider.calls == []


def test_answers_from_provider_with_numbered_citations(hits: list[dict[str, Any]]) -> None:
    provider = FakeProvider(reply="Revenue grew 12% in Q3 [1].")

    result = chat.answer_query(1, "How did revenue move?", provider=provider)

    assert result["answer"] == "Revenue grew 12% in Q3 [1]."
    assert result["provider"] == "fake"
    assert result["model"] == "test-model"
    assert result["degraded"] is False
    assert [c["index"] for c in result["citations"]] == [1, 2]

    system_prompt, user_prompt = provider.calls[0]
    assert "untrusted data" in system_prompt
    assert "[1] report.pdf (chunk 0)" in user_prompt
    assert "Revenue grew 12% in Q3." in user_prompt


def test_falls_back_to_extractive_answer_when_provider_fails(
    hits: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    provider = FakeProvider(error=ProviderError("connection refused"))

    result = chat.answer_query(1, "How did revenue move?", provider=provider)

    assert result["provider"] == "extractive"
    assert result["degraded"] is True
    assert "[1] Revenue grew 12% in Q3." in result["answer"]
    assert len(result["citations"]) == 2
    assert "serving extractive fallback" in caplog.text


def test_build_context_skips_empty_chunks_and_numbers_what_remains() -> None:
    context, citations = chat.build_context([hit(text="   "), hit(text="Kept.", chunk_index=3)])

    assert len(citations) == 1
    assert citations[0]["index"] == 1
    assert context.startswith("[1] report.pdf (chunk 3)")


def test_get_provider_returns_none_without_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    from app.services.providers import get_provider

    assert get_provider() is None
