"""LLM provider gateway.

Configuration comes only from the environment; no credentials or provider
URLs are stored in the repository.
"""

from __future__ import annotations

import json
from typing import Iterator, Protocol

import httpx

from ..core.config import llm_settings


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a completion."""


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, system_prompt: str, user_prompt: str) -> str: ...

    def stream_complete(self, system_prompt: str, user_prompt: str) -> Iterator[str]: ...


class OpenAICompatibleProvider:
    """Client for any OpenAI-compatible /chat/completions endpoint.

    Works with llama.cpp server, Ollama, vLLM and hosted OpenAI-compatible APIs.
    """

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"provider request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("provider returned invalid JSON") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "provider response did not contain choices[0].message.content"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("provider returned an empty completion")
        return content.strip()

    def stream_complete(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        line = line.strip()
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content")
                                if content:
                                    yield content
                            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                                continue
        except httpx.HTTPError as exc:
            raise ProviderError(f"provider stream request failed: {exc}") from exc


def get_provider() -> LLMProvider | None:
    """Return the configured provider, or None when none is configured."""
    settings = llm_settings()
    if not settings["base_url"] or not settings["model"]:
        return None
    return OpenAICompatibleProvider(
        base_url=settings["base_url"],
        model=settings["model"],
        api_key=settings["api_key"] or None,
        timeout=float(settings["timeout"]),
    )
