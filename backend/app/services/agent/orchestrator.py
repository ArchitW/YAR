"""Agentic reasoning and metasearch orchestrator (TKT-020)."""

from __future__ import annotations

import logging
import re
from typing import Any

from ...core.config import searxng_settings
from ..tools.searxng import SearXNGSearchTool

logger = logging.getLogger(__name__)

EXPLICIT_WEB_TRIGGERS = [
    r"\bsearch (?:the )?web\b",
    r"\bsearch online\b",
    r"\blook up on(?:line| Google)?\b",
    r"\blatest news\b",
    r"\bcurrent (?:weather|price|stock|events?|status)\b",
    r"\btoday'?s\b",
    r"\breal-?time\b",
    r"\bbrowse (?:the )?web\b",
]


class AgenticOrchestrator:
    """Orchestrates local document retrieval and autonomous web metasearch fallback."""

    @staticmethod
    def is_explicit_web_query(query: str) -> bool:
        """Check if query explicitly requests external web search."""
        q_lower = query.lower().strip()
        return any(re.search(pat, q_lower) for pat in EXPLICIT_WEB_TRIGGERS)

    @classmethod
    def should_search_web(
        cls,
        query: str,
        hits: list[dict[str, Any]],
        confidence_threshold: float | None = None,
    ) -> bool:
        """Determine whether to trigger web search based on intent or low document confidence."""
        settings = searxng_settings()
        if not settings.get("enabled", True):
            return False

        if cls.is_explicit_web_query(query):
            return True

        # Check local document retrieval confidence
        threshold = confidence_threshold if confidence_threshold is not None else settings.get("confidence_threshold", 0.25)
        if not hits:
            return True

        max_score = max((float(h.get("score") or 0.0) for h in hits), default=0.0)
        return max_score < threshold

    @classmethod
    def execute_web_fallback(
        cls,
        query: str,
        existing_citations: list[dict[str, Any]],
        search_tool: SearXNGSearchTool | None = None,
        num_results: int = 4,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Query SearXNG / DuckDuckGo and format web citations."""
        if not searxng_settings().get("enabled", True):
            return "", []
        tool = search_tool or SearXNGSearchTool()
        results = tool.search(query, num_results=num_results)
        if not results:
            return "", []

        web_blocks: list[str] = []
        web_citations: list[dict[str, Any]] = []

        start_index = len(existing_citations) + 1
        for i, r in enumerate(results):
            idx = start_index + i
            citation = {
                "index": idx,
                "is_web": True,
                "title": r.get("title") or "Web Source",
                "url": r.get("url") or "",
                "file_name": r.get("title") or "Web Search",
                "text": r.get("snippet") or "",
                "chunk_text": r.get("snippet") or "",
                "source": r.get("source", "searxng"),
            }
            web_citations.append(citation)
            web_blocks.append(
                f"[{idx}] [Web Source: {citation['title']}] ({citation['url']})\n{citation['text']}"
            )

        return "\n\n".join(web_blocks), web_citations
