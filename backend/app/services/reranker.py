import logging
from typing import Any, Dict, List
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)
_reranker = None


def get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder("BAAI/bge-reranker-base")
    return _reranker


def rerank(query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rerank retrieval candidates using a cross-encoder model.

    Gracefully falls back to the original fusion candidate ranking if the cross-encoder
    fails (e.g., out of memory, missing weights, or model initialization error).
    """
    if not candidates:
        return candidates

    try:
        r = get_reranker()
        pairs = [(query, c.get("text", c.get("chunk_text", ""))) for c in candidates]
        scores = r.predict(pairs)
        for c, s in zip(candidates, scores):
            c["rerank_score"] = float(s)
        candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
    except Exception as exc:
        logger.warning(
            "Cross-encoder reranking failed (%s); falling back to hybrid retrieval ranking",
            exc,
        )
        for c in candidates:
            c["rerank_score"] = float(c.get("score", 0.0))

    return candidates
