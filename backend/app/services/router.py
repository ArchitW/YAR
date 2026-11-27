"""Small decision router (e.g. Kev-0.8B) that classifies a query into a route.

The router is a *decision* model: it scores a fixed set of options and returns a
calibrated probability per option. It never generates text. We use it to pick how
to answer a query:

- ``local_kb``    → ground the answer in the workspace's indexed documents.
- ``web_search``  → force the agentic web (SearXNG) fallback.
- ``general_chat``→ answer conversationally from the model's general knowledge.

It is config-gated (``DECISION_ROUTER_ENABLED``) and any failure (disabled,
unreachable, bad payload) returns ``route=None`` so callers fall back to the
built-in heuristics. This keeps a missing router server from ever breaking chat.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..core.config import router_settings, searxng_settings

logger = logging.getLogger(__name__)

ROUTES = ("local_kb", "web_search", "general_chat")

_DOC_ANCHOR_RE = re.compile(
    r"\b("
    r"this (book|doc|document|file|pdf|epub|paper|article|text|note|notes|chapter|section)|"
    r"the (book|doc|document|file|pdf|epub|paper|article|author|chapter|section|uploaded)|"
    r"my (docs|documents|files|notes|uploads|knowledge base|kb)|"
    r"in the (text|context|sources|documents|files)|"
    r"according to|summarize|from my files|who is this author|what is this book"
    r")\b",
    re.IGNORECASE,
)

_CAPABILITY_RE = re.compile(
    r"^(are you able to|can you|do you|how do you|what can you|who are you)\b"
    r"|^(hi|hello|hey|thanks|thank you)[!.,\s]*$",
    re.IGNORECASE,
)

_WEB_INTENT_RE = re.compile(
    r"\b(search the web|search online|search the internet|look up online|latest news|current weather|today'?s)\b",
    re.IGNORECASE,
)

_ROUTE_PROTOTYPES: dict[str, list[str]] = {
    "local_kb": [
        "Summarize the uploaded document or book",
        "What does this file say about the main topic?",
        "Who is the author of this book and what are its chapters?",
        "Find details in my workspace notes and indexed PDFs",
    ],
    "general_chat": [
        "What is the capital of France?",
        "Who is Will Smith?",
        "Explain how photosynthesis works in simple terms",
        "Write a Python function to reverse a string",
        "Are you able to help me with general questions?",
    ],
    "web_search": [
        "Search the web for the latest AI news today",
        "What is the current weather in Tokyo right now?",
        "Look up recent stock prices online",
    ],
}

_PROTO_VECTORS: dict[str, list[list[float]]] | None = None


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _get_prototype_vectors() -> dict[str, list[list[float]]] | None:
    global _PROTO_VECTORS
    if _PROTO_VECTORS is not None:
        return _PROTO_VECTORS
    try:
        from .embeddings import embed

        flat_texts: list[str] = []
        slices: list[tuple[str, int, int]] = []
        for route_name, utterances in _ROUTE_PROTOTYPES.items():
            start = len(flat_texts)
            flat_texts.extend(utterances)
            slices.append((route_name, start, len(flat_texts)))
        vecs = embed(flat_texts)
        _PROTO_VECTORS = {
            name: vecs[start:end] for name, start, end in slices
        }
        return _PROTO_VECTORS
    except Exception:
        logger.debug("Semantic prototype embedding unavailable", exc_info=True)
        return None


def classify_query(query: str) -> dict[str, Any]:
    """In-process low-latency query classifier (rules + BGE-M3 semantic routing).

    Used when the external decision router is disabled or unreachable.
    Returns ``{"route": str, "confidence": float, "source": str}``.
    """
    text = (query or "").strip()
    if not text:
        return {"route": "general_chat", "confidence": 1.0, "source": "heuristic"}

    if _DOC_ANCHOR_RE.search(text):
        return {"route": "local_kb", "confidence": 0.95, "source": "heuristic"}

    if _CAPABILITY_RE.search(text):
        return {"route": "general_chat", "confidence": 0.9, "source": "heuristic"}

    if _WEB_INTENT_RE.search(text):
        target = "web_search" if searxng_settings().get("enabled") else "general_chat"
        return {"route": target, "confidence": 0.9, "source": "heuristic"}

    protos = _get_prototype_vectors()
    if protos is not None:
        try:
            from .embeddings import embed

            q_vec = embed([text])[0]
            scores = {
                name: max(_dot(q_vec, p_vec) for p_vec in p_vecs)
                for name, p_vecs in protos.items()
            }
            best_route = max(scores, key=lambda k: scores[k])
            best_score = scores[best_route]
            sorted_scores = sorted(scores.values(), reverse=True)
            margin = best_score - (sorted_scores[1] if len(sorted_scores) > 1 else 0.0)
            if best_route == "web_search" and not searxng_settings().get("enabled"):
                best_route = "general_chat"
            if best_route == "general_chat" and best_score >= 0.45 and margin >= 0.02:
                return {"route": "general_chat", "confidence": round(best_score, 3), "source": "semantic"}
            if best_route == "web_search" and best_score >= 0.50 and margin >= 0.03:
                return {"route": "web_search", "confidence": round(best_score, 3), "source": "semantic"}
            return {"route": "local_kb", "confidence": round(best_score, 3), "source": "semantic"}
        except Exception:
            logger.debug("Semantic query classification failed", exc_info=True)

    return {"route": "local_kb", "confidence": 0.5, "source": "fallback"}

_QUESTION_INSTRUCTIONS = (
    "How should this query be answered? "
    "local_kb: the answer is likely in the user's indexed documents. "
    "web_search: the answer needs current or external information. "
    "general_chat: a conversational reply from general knowledge is fine."
)


def route_query(state: str) -> dict[str, Any]:
    """Return ``{"route": str|None, "confidence": float, "source": str}``.

    ``source`` is ``"router"`` when the decision model answered, ``"disabled"`` when
    the router is off, or ``"unavailable"`` when the call failed.
    """
    cfg = router_settings()
    if not cfg["enabled"]:
        return {"route": None, "confidence": 0.0, "source": "disabled"}

    base = cfg["base_url"]
    payload = {
        "model": cfg["model"],
        "state": state,
        "questions": {
            "route": {
                "type": "choice",
                "instructions": _QUESTION_INSTRUCTIONS,
                "options": list(ROUTES),
            }
        },
    }

    try:
        with httpx.Client(timeout=cfg["timeout"]) as client:
            resp = client.post(f"{base}/v1/systemone", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # network/HTTP/JSON — fall back, never crash chat
        logger.warning("Decision router unavailable at %s: %s", base, exc)
        return {"route": None, "confidence": 0.0, "source": "unavailable"}

    choice, confidence = _parse_choice(data)
    if choice not in ROUTES:
        logger.warning("Decision router returned unknown route: %r", choice)
        return {"route": None, "confidence": confidence, "source": "unavailable"}
    return {"route": choice, "confidence": confidence, "source": "router"}


def _parse_choice(data: dict[str, Any]) -> tuple[str | None, float]:
    """Best-effort extraction of the chosen option + confidence from a response.

    Handles the documented ``choices.<name>.choice`` shape as well as a few
    common variants so a minor schema drift degrades gracefully.
    """
    choices = data.get("choices") if isinstance(data, dict) else None
    node = None
    if isinstance(choices, dict):
        node = choices.get("route")
    if node is None and isinstance(data, dict):
        node = data.get("route") or data.get("choice")
    if isinstance(node, dict):
        choice = node.get("choice") or node.get("value")
        confidence = node.get("confidence", node.get("probability", 0.0))
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        return (choice, confidence)
    if isinstance(node, str):
        return (node, 0.0)
    return (None, 0.0)