"""Conversational query rewriting and HyDE (Hypothetical Document Embeddings) service (TKT-018)."""

from __future__ import annotations

import logging
import re
from typing import Any

from ..core.config import query_rewriter_settings
from .providers import LLMProvider, ProviderError

logger = logging.getLogger(__name__)

PRONOUN_TRIGGERS = {
    "it",
    "its",
    "they",
    "them",
    "their",
    "theirs",
    "that",
    "this",
    "these",
    "those",
    "he",
    "him",
    "his",
    "she",
    "her",
    "hers",
    "the former",
    "the latter",
    "first one",
    "second one",
    "tell me more",
    "explain that",
    "what about",
    "how does it",
    "compare them",
    "why did",
    "how so",
}

REWRITE_SYSTEM_PROMPT = """You are an expert search query reformulator. Your job is to rewrite the latest user follow-up question into a single, complete, standalone search query that contains all necessary entities and context from the conversation history.

Rules:
- Resolve all pronouns ("it", "they", "that", "this", "them", etc.) to the specific names, topics, or concepts they refer to.
- Keep the rewritten query concise, factual, and optimized for document search retrieval.
- DO NOT answer the question.
- DO NOT include conversational filler or explanations.
- Output ONLY the rewritten standalone query, nothing else.
"""

HYDE_SYSTEM_PROMPT = """You are a search assistant. Write a short 1-2 sentence hypothetical document excerpt that directly answers the question. Focus on using realistic technical and descriptive vocabulary likely to appear in documentation. Do not include introductory filler.
"""


class QueryRewriter:
    """Handles conversational query expansion, pronoun resolution, and HyDE."""

    @staticmethod
    def needs_rewriting(query: str) -> bool:
        """Heuristic check to determine if query has pronouns or context dependencies."""
        q_lower = query.lower().strip()
        words = re.findall(r"\b\w+\b", q_lower)

        # Very short queries (e.g. "why?", "tell me more", "how so?") almost always need context
        if len(words) <= 3:
            return True

        # Check for pronoun triggers
        for trigger in PRONOUN_TRIGGERS:
            if " " in trigger and trigger in q_lower:
                return True
            if trigger in words:
                return True

        return False

    @classmethod
    def rewrite_conversational_query(
        cls,
        history: list[dict[str, str]],
        query: str,
        provider: LLMProvider | None = None,
    ) -> str:
        """Rewrite a conversational follow-up query into a standalone search query.

        If history is empty, rewriting is disabled, or query is already standalone,
        returns the original query without LLM overhead.
        """
        settings = query_rewriter_settings()
        if not settings.get("rewrite_enabled", True):
            return query.strip()

        if not history:
            return query.strip()

        # BUG FIX [2026-11-28]: Avoid unnecessary LLM rewrite on standalone 4-6 word queries.
        # Root cause: `> 6` sent pronoun-free 4-6 word queries through an extra blocking LLM rewrite call.
        # Fix: Align threshold with needs_rewriting() (which already flags <= 3 words and pronoun triggers).
        # Watch for: Short non-pronoun follow-up queries of 4+ words that rely on implicit context.
        if not cls.needs_rewriting(query) and len(query.split()) >= 4:
            return query.strip()

        if provider is None:
            return query.strip()

        # Format recent history (limit to last 4 turns)
        history_lines = []
        for msg in history[-4:]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = str(msg.get("content") or "").strip()
            if content:
                # Truncate assistant responses to keep prompt lean
                if len(content) > 300:
                    content = content[:300] + "..."
                history_lines.append(f"{role}: {content}")

        if not history_lines:
            return query.strip()

        formatted_history = "\n".join(history_lines)
        user_prompt = (
            f"Conversation History:\n{formatted_history}\n\n"
            f"Latest User Question:\n{query.strip()}\n\n"
            f"Standalone Search Query:"
        )

        try:
            rewritten = provider.complete(REWRITE_SYSTEM_PROMPT, user_prompt)
            cleaned = rewritten.strip().strip('"\'`')
            # Remove any prefix the model might have echoed
            if cleaned.lower().startswith("standalone search query:"):
                cleaned = cleaned[24:].strip()
            if cleaned:
                logger.info("Rewrote conversational query '%s' -> '%s'", query, cleaned)
                return cleaned
        except (ProviderError, Exception) as exc:
            logger.warning("Query rewriting failed; falling back to original query: %s", exc)

        return query.strip()

    @classmethod
    def generate_hyde(
        cls,
        query: str,
        provider: LLMProvider | None = None,
    ) -> str | None:
        """Generate a hypothetical answer passage (HyDE) to bridge vocabulary gaps."""
        settings = query_rewriter_settings()
        if not settings.get("hyde_enabled", False):
            return None

        if provider is None or not query.strip():
            return None

        user_prompt = f"Question: {query.strip()}\n\nHypothetical Passage:"
        try:
            hyde = provider.complete(HYDE_SYSTEM_PROMPT, user_prompt)
            cleaned = hyde.strip().strip('"\'`')
            if cleaned:
                logger.info("Generated HyDE passage for query '%s'", query)
                return cleaned
        except (ProviderError, Exception) as exc:
            logger.warning("HyDE generation failed: %s", exc)

        return None
