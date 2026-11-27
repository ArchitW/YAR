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
from typing import Any

import httpx

from ..core.config import router_settings

logger = logging.getLogger(__name__)

ROUTES = ("local_kb", "web_search", "general_chat")

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