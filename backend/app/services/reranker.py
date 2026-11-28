import logging
from typing import Any, Dict, List
from sentence_transformers import CrossEncoder

from ..core.config import detect_torch_device

logger = logging.getLogger(__name__)
_reranker = None


def get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        device = detect_torch_device()
        logger.info("Loading reranker BAAI/bge-reranker-base on device=%s", device)
        _reranker = CrossEncoder("BAAI/bge-reranker-base", device=device)
        if device == "cuda":
            try:
                _reranker.model.half()
            except Exception:
                pass
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
        try:
            import torch

            with torch.inference_mode():
                scores = r.predict(pairs, batch_size=32, show_progress_bar=False)
        except ImportError:
            scores = r.predict(pairs, batch_size=32, show_progress_bar=False)
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
