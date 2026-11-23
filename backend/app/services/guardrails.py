"""Automated Faithfulness & Hallucination Guardrails, and PII Sanitization (TKT-022)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII Sanitizer
# ---------------------------------------------------------------------------

class PIISanitizer:
    """Detects and redacts sensitive Personally Identifiable Information (PII)."""

    EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    PHONE_PATTERN = re.compile(
        r"(?:(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b)"
    )
    SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")

    @classmethod
    def sanitize(cls, text: str) -> tuple[str, dict[str, int]]:
        """Mask PII entities with clean redaction placeholders.

        Returns:
            (sanitized_text, counts_dict)
        """
        if not text:
            return "", {"emails": 0, "phones": 0, "ssn": 0, "credit_cards": 0, "total": 0}

        counts = {"emails": 0, "phones": 0, "ssn": 0, "credit_cards": 0, "total": 0}

        def _sub_email(m: re.Match) -> str:
            counts["emails"] += 1
            return "[EMAIL_REDACTED]"

        def _sub_ssn(m: re.Match) -> str:
            counts["ssn"] += 1
            return "[SSN_REDACTED]"

        def _sub_card(m: re.Match) -> str:
            counts["credit_cards"] += 1
            return "[CREDIT_CARD_REDACTED]"

        def _sub_phone(m: re.Match) -> str:
            counts["phones"] += 1
            return "[PHONE_REDACTED]"

        # Process in sequence: Credit Cards -> SSN -> Email -> Phone
        sanitized = cls.CREDIT_CARD_PATTERN.sub(_sub_card, text)
        sanitized = cls.SSN_PATTERN.sub(_sub_ssn, sanitized)
        sanitized = cls.EMAIL_PATTERN.sub(_sub_email, sanitized)
        sanitized = cls.PHONE_PATTERN.sub(_sub_phone, sanitized)

        counts["total"] = (
            counts["emails"] + counts["phones"] + counts["ssn"] + counts["credit_cards"]
        )
        return sanitized, counts

    @classmethod
    def has_pii(cls, text: str) -> bool:
        """Check if string contains any detectable PII."""
        if not text:
            return False
        return bool(
            cls.EMAIL_PATTERN.search(text)
            or cls.SSN_PATTERN.search(text)
            or cls.CREDIT_CARD_PATTERN.search(text)
            or cls.PHONE_PATTERN.search(text)
        )


# ---------------------------------------------------------------------------
# Faithfulness & Hallucination Verifier
# ---------------------------------------------------------------------------

@dataclass
class FaithfulnessResult:
    score: float
    is_faithful: bool
    claims_total: int
    claims_grounded: int
    unsupported_claims: list[str]
    flagged: bool = False


STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "in", "on", "at",
    "to", "for", "with", "by", "of", "it", "this", "that", "these", "those",
    "from", "as", "be", "has", "have", "had", "not", "but", "so", "can", "could",
    "will", "would", "shall", "should", "our", "their", "its", "your", "we", "they",
    "he", "she", "you", "which", "what", "where", "when", "why", "how", "all",
    "any", "both", "each", "few", "more", "most", "other", "some", "such", "than",
    "too", "very", "about", "also", "into", "just", "after", "before", "over",
    "here", "there", "based", "according", "document", "documents", "answer",
    "answers", "question", "questions", "context", "information", "summary",
}

CONVERSATIONAL_PREFIXES = (
    "based on", "according to", "in summary", "here is", "i found",
    "as mentioned", "the documents indicate", "as described", "to summarize",
)


class FaithfulnessVerifier:
    """Verifies that generated answers are grounded in retrieved source context."""

    @classmethod
    def extract_claims(cls, text: str) -> list[str]:
        """Extract substantive factual claim sentences from an assistant answer."""
        if not text:
            return []

        # Remove markdown code blocks and citation indices [1], [2]
        clean_text = re.sub(r"```[\s\S]*?```", "", text)
        clean_text = re.sub(r"\[\d+\]", "", clean_text)
        clean_text = re.sub(r"\[web:\d+\]", "", clean_text)

        # Split on sentence boundaries
        raw_sentences = [
            s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", clean_text) if s.strip()
        ]

        claims: list[str] = []
        for s in raw_sentences:
            # Strip markdown list markers and quotes
            line = re.sub(r"^(\*|-|\d+\.|>)\s*", "", s).strip()
            if not line or len(line.split()) < 4:
                continue

            lower = line.lower()
            if any(lower.startswith(pfx) for pfx in CONVERSATIONAL_PREFIXES) and len(line.split()) <= 10:
                words = re.findall(r"\b[A-Za-z0-9_-]+\b", lower)
                substantive = [w for w in words if len(w) >= 3 and w not in STOPWORDS]
                if not substantive:
                    continue

            claims.append(line)

        return claims

    @classmethod
    def evaluate_claim(cls, claim: str, context: str, min_overlap: float = 0.50) -> bool:
        """Check if an individual claim sentence is supported by context."""
        words = re.findall(r"\b[A-Za-z0-9_-]+\b", claim.lower())
        content_tokens = [w for w in words if len(w) >= 3 and w not in STOPWORDS]

        if not content_tokens:
            return True

        context_words = set(re.findall(r"\b[A-Za-z0-9_-]+\b", context.lower()))
        matched = sum(1 for w in content_tokens if w in context_words)
        overlap = matched / len(content_tokens)

        return overlap >= min_overlap

    @classmethod
    def verify(
        cls,
        answer: str,
        context: str,
        citations: list[dict[str, Any]] | None = None,
        threshold: float = 0.65,
    ) -> FaithfulnessResult:
        """Evaluate generated answer against source context and compute Groundedness Score.

        Threshold defaults to 0.65. Scores below threshold flag hallucination risk.
        """
        if not answer or not answer.strip():
            return FaithfulnessResult(
                score=1.0,
                is_faithful=True,
                claims_total=0,
                claims_grounded=0,
                unsupported_claims=[],
                flagged=False,
            )

        # If extractive answer fallback or refusal, treat as inherently grounded
        if "Based on your documents:\n-" in answer or not citations:
            return FaithfulnessResult(
                score=1.0,
                is_faithful=True,
                claims_total=1,
                claims_grounded=1,
                unsupported_claims=[],
                flagged=False,
            )

        # Combine text across context and citation chunks
        combined_context = context or ""
        if citations:
            chunk_texts = [
                str(c.get("text") or c.get("chunk_text") or c.get("parent_text") or "")
                for c in citations
            ]
            combined_context = f"{combined_context} {' '.join(chunk_texts)}"

        claims = cls.extract_claims(answer)
        if not claims:
            return FaithfulnessResult(
                score=1.0,
                is_faithful=True,
                claims_total=0,
                claims_grounded=0,
                unsupported_claims=[],
                flagged=False,
            )

        grounded = 0
        unsupported = []
        for claim in claims:
            if cls.evaluate_claim(claim, combined_context):
                grounded += 1
            else:
                unsupported.append(claim)

        score = round(grounded / len(claims), 2)
        is_faithful = score >= threshold

        return FaithfulnessResult(
            score=score,
            is_faithful=is_faithful,
            claims_total=len(claims),
            claims_grounded=grounded,
            unsupported_claims=unsupported,
            flagged=not is_faithful,
        )
