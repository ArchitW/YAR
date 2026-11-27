import httpx
import pytest

from app.services import providers
from app.services.providers import (
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderError,
    get_provider,
)
from fastapi.testclient import TestClient
from app.main import app


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


# ---------------------------------------------------------------------------
# Ollama Autodiscovery Tests (TKT-023)
# ---------------------------------------------------------------------------

def test_ollama_discover_models_parses_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tags = {
        "models": [
            {"name": "llama3.2:latest", "model": "llama3.2:latest"},
            {"name": "qwen2.5:7b", "model": "qwen2.5:7b"},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:11434/api/tags"
        return httpx.Response(200, json=fake_tags)

    mock_client(monkeypatch, handler)
    models = OllamaProvider.discover_models("http://localhost:11434")
    assert models == ["llama3.2:latest", "qwen2.5:7b"]


def test_ollama_offline_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Failed to connect to localhost")

    mock_client(monkeypatch, handler)
    models = OllamaProvider.discover_models("http://localhost:11434")
    assert models == []
    assert OllamaProvider.is_online("http://localhost:11434") is False


def test_ollama_is_online(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    mock_client(monkeypatch, handler)
    assert OllamaProvider.is_online("http://localhost:11434") is True


def test_get_provider_autodiscovers_ollama_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_AUTODISCOVER", "true")

    monkeypatch.setattr(
        OllamaProvider,
        "discover_models",
        classmethod(lambda cls, base_url, timeout=3.0: ["llama3.2:latest"]),
    )

    provider = get_provider()
    assert provider is not None
    assert provider.name == "ollama"
    assert provider.model == "llama3.2:latest"


def test_chat_models_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        OllamaProvider,
        "discover_models",
        classmethod(lambda cls, base_url, timeout=3.0: ["mistral:latest"]),
    )
    monkeypatch.setattr(
        OllamaProvider,
        "is_online",
        classmethod(lambda cls, base_url, timeout=2.0: True),
    )

    client = TestClient(app)
    res = client.get("/chat/models")
    assert res.status_code == 200
    data = res.json()
    assert data["ollama_online"] is True
    assert "mistral:latest" in data["local_models"]

