import httpx
import pytest

from app.services import providers
from app.services.providers import OpenAICompatibleProvider, ProviderError


def mock_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        providers.httpx,
        "Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )


def test_complete_parses_content_and_sends_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization", "")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "  hello  "}}]})

    mock_client(monkeypatch, handler)
    provider = OpenAICompatibleProvider("http://llm.test/v1", "llama", api_key="secret-token")

    assert provider.complete("system", "user") == "hello"
    assert seen["authorization"] == "Bearer secret-token"
    assert seen["url"] == "http://llm.test/v1/chat/completions"


def test_complete_raises_provider_error_on_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client(monkeypatch, lambda request: httpx.Response(503, text="unavailable"))
    provider = OpenAICompatibleProvider("http://llm.test/v1", "llama")

    with pytest.raises(ProviderError, match="provider request failed"):
        provider.complete("system", "user")


def test_complete_raises_provider_error_on_unexpected_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client(monkeypatch, lambda request: httpx.Response(200, json={"choices": []}))
    provider = OpenAICompatibleProvider("http://llm.test/v1", "llama")

    with pytest.raises(ProviderError, match="choices"):
        provider.complete("system", "user")
