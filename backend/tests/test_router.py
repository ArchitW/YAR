from typing import Any

import pytest

from app.services import router as router_mod


class _FakeResp:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._data


class _FakeClient:
    def __init__(self, data: dict[str, Any] | None = None, error: Exception | None = None):
        self._data = data
        self._error = error
        self.last_url: str | None = None
        self.last_payload: dict[str, Any] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url: str, json: dict[str, Any]):
        self.last_url = url
        self.last_payload = json
        if self._error:
            raise self._error
        return _FakeResp(self._data or {})


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router_mod,
        "router_settings",
        lambda: {
            "enabled": True,
            "base_url": "http://127.0.0.1:8008",
            "model": "kev-latest",
            "timeout": 5.0,
        },
    )


def test_router_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router_mod,
        "router_settings",
        lambda: {"enabled": False, "base_url": "", "model": "", "timeout": 1.0},
    )
    result = router_mod.route_query("What is a GPU?")
    assert result["route"] is None
    assert result["source"] == "disabled"


def test_router_parses_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    fake = _FakeClient(
        data={"choices": {"route": {"choice": "general_chat", "confidence": 0.91}}}
    )
    monkeypatch.setattr(router_mod.httpx, "Client", lambda *a, **k: fake)

    result = router_mod.route_query("Tell me about the new RTX card")

    assert result["route"] == "general_chat"
    assert result["confidence"] == 0.91
    assert result["source"] == "router"
    # It must call the System One endpoint with the three route options.
    assert fake.last_url.endswith("/v1/systemone")
    opts = fake.last_payload["questions"]["route"]["options"]
    assert set(opts) == {"local_kb", "web_search", "general_chat"}


def test_router_unreachable_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    fake = _FakeClient(error=RuntimeError("connection refused"))
    monkeypatch.setattr(router_mod.httpx, "Client", lambda *a, **k: fake)

    result = router_mod.route_query("anything")

    assert result["route"] is None
    assert result["source"] == "unavailable"


def test_router_unknown_route_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    fake = _FakeClient(data={"choices": {"route": {"choice": "nonsense", "confidence": 0.5}}})
    monkeypatch.setattr(router_mod.httpx, "Client", lambda *a, **k: fake)

    result = router_mod.route_query("anything")

    assert result["route"] is None
    assert result["source"] == "unavailable"