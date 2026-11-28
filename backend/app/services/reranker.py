import logging
import os
from typing import Any, Dict, List
from sentence_transformers import CrossEncoder

from ..core.config import apply_hf_offline_mode, detect_torch_device, reranker_settings

logger = logging.getLogger(__name__)
_reranker = None
_reranker_name = None


def get_reranker() -> CrossEncoder:
    global _reranker, _reranker_name
    model_name = reranker_settings()["model"]
    if _reranker is not None and _reranker_name != model_name:
        _reranker = None
        _reranker_name = None
    if _reranker is None:
        device = detect_torch_device()
        logger.info("Loading reranker %s on device=%s", model_name, device)
        offline = apply_hf_offline_mode()
        try:
            _reranker = CrossEncoder(model_name, device=device)
        except Exception:
            if offline:
                logger.warning("Local cache miss for %s; downloading from Hugging Face", model_name)
                os.environ.pop("HF_HUB_OFFLINE", None)
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
                _reranker = CrossEncoder(model_name, device=device)
            else:
                raise
        _reranker_name = model_name
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
