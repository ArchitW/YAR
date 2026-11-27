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


def test_classify_query_doc_anchor_routes_to_local_kb() -> None:
    res = router_mod.classify_query("who is this author and why he is very famous?")
    assert res["route"] == "local_kb"
    assert res["source"] == "heuristic"


def test_classify_query_capability_routes_to_general_chat() -> None:
    res = router_mod.classify_query("are you able to search internet for me?")
    assert res["route"] == "general_chat"
    assert res["source"] == "heuristic"


def test_classify_query_semantic_routes_general_question(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_embed(texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            tl = t.lower()
            if "france" in tl or "smith" in tl or "general" in tl or "python" in tl or "photosynthesis" in tl:
                out.append([1.0, 0.0, 0.0])
            elif "weather" in tl or "stock" in tl or "news" in tl:
                out.append([0.0, 1.0, 0.0])
            else:
                out.append([0.0, 0.0, 1.0])
        return out

    monkeypatch.setattr(router_mod, "_PROTO_VECTORS", None)
    import app.services.embeddings as emb_mod

    monkeypatch.setattr(emb_mod, "embed", _fake_embed)

    res = router_mod.classify_query("what is capital of france?")
    assert res["route"] == "general_chat"
    assert res["source"] == "semantic"


def test_refusal_suppresses_citations() -> None:
    from app.services.chat import _is_refusal

    assert _is_refusal("The indexed documents do not appear to cover it.") is True
    assert _is_refusal("Based on [1], Seneca was a Roman Stoic philosopher.") is False