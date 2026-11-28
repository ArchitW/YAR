import hashlib
import logging
import math
import os
import re
from typing import Any, Dict, List
from sentence_transformers import SentenceTransformer

from ..core.config import apply_hf_offline_mode, detect_torch_device, embedding_settings

logger = logging.getLogger(__name__)
_model = None
_model_name = None

# Standard lightweight English stopwords to prevent high-frequency words dominating sparse search
STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "as",
    "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "could",
    "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had",
    "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how",
    "i", "if", "in", "into", "is", "it", "its", "itself", "me", "more", "most", "my", "myself", "no",
    "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves",
    "out", "over", "own", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those", "through", "to",
    "too", "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while",
    "who", "whom", "why", "with", "would", "you", "your", "yours", "yourself", "yourselves"
}

def get_model():
    global _model, _model_name
    model_name = embedding_settings()["model"]
    if _model is not None and _model_name != model_name:
        # Model changed at runtime — drop the cached instance so it reloads.
        _model = None
        _model_name = None
    if _model is None:
        device = detect_torch_device()
        logger.info("Loading embedding model %s on device=%s", model_name, device)
        offline = apply_hf_offline_mode()
        try:
            _model = SentenceTransformer(model_name, device=device)
        except Exception:
            if offline:
                logger.warning("Local cache miss for %s; downloading from Hugging Face", model_name)
                os.environ.pop("HF_HUB_OFFLINE", None)
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
                _model = SentenceTransformer(model_name, device=device)
            else:
                raise
        _model_name = model_name
        if device == "cuda":
            try:
                _model.half()
            except Exception:
                pass
    return _model


def embedding_dim() -> int:
    """Return the dense vector dimension of the configured embedding model."""
    m = get_model()
    dim = None
    if hasattr(m, "get_embedding_dimension"):
        dim = m.get_embedding_dimension()
    elif hasattr(m, "get_sentence_embedding_dimension"):
        dim = m.get_sentence_embedding_dimension()
    if not dim:
        raise RuntimeError("Could not determine embedding dimension")
    return int(dim)


def embed(texts: List[str], batch_size: int = 32) -> List[List[float]]:
    m = get_model()
    try:
        import torch

        with torch.inference_mode():
            return m.encode(
                texts,
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).tolist()
    except ImportError:
        return m.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

def embed_sparse(text: str) -> Dict[str, List[Any]]:
    """Generate a sparse lexical vector with 31-bit hashing and sublinear TF scaling.

    Features:
    - Filters common English stopwords so domain keywords dominate relevance.
    - Uses 31-bit integer hash space (2^31 - 1) to eliminate hash collisions.
    - Aggregates duplicate bucket collisions via sum-pooling.
    - Applies sublinear term-frequency saturation: 1.0 + ln(TF).
    - Sorts indices in ascending order as required by Qdrant SparseVector specification.
    """
    words = re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())
    if not words:
        return {"indices": [], "values": []}

    freq: dict[str, int] = {}
    for w in words:
        if w in STOPWORDS:
            continue
        freq[w] = freq.get(w, 0) + 1

    # Fallback if text consists entirely of stopwords
    if not freq:
        for w in words:
            freq[w] = freq.get(w, 0) + 1

    MAX_IDX = (1 << 31) - 1
    buckets: dict[int, float] = {}
    for term, count in freq.items():
        idx = int(hashlib.md5(term.encode("utf-8")).hexdigest(), 16) % MAX_IDX
        weight = 1.0 + math.log(count)
        buckets[idx] = buckets.get(idx, 0.0) + weight

    sorted_items = sorted(buckets.items())
    return {
        "indices": [k for k, _ in sorted_items],
        "values": [round(v, 4) for _, v in sorted_items],
    }


def embed_late_chunks(
    full_text: str,
    chunks: List[str],
    original_chunks: List[str] | None = None,
) -> List[List[float]]:
    """Late Chunking (Jina AI / BGE-M3 attention-span pooling architecture).

    Encodes the full document in a single forward pass through the transformer
    so every token attends across the entire document context window (up to 8,192 tokens).
    Then pools the token embeddings within each chunk's span into a normalized dense vector.

    Falls back cleanly to standard batched embed(chunks) if token slicing is unavailable.
    """
    if not chunks:
        return []
    if not full_text.strip():
        return embed(chunks)

    search_chunks = original_chunks if original_chunks is not None else chunks

    try:
        import torch

        m = get_model()
        device = getattr(m, "device", torch.device("cpu"))
        tokenizer = getattr(m, "tokenizer", None)
        transformer_module = m[0] if len(m) > 0 and hasattr(m[0], "auto_model") else None

        if tokenizer is None or transformer_module is None:
            return embed(chunks)

        # Tokenize entire document with offset mapping (cap to the model's max length).
        model_max = getattr(tokenizer, "model_max_length", 8192) or 8192
        max_len = min(8192, int(model_max))
        inputs = tokenizer(
            full_text,
            return_tensors="pt",
            return_offsets_mapping=True,
            truncation=True,
            max_length=max_len,
        )
        offsets = inputs["offset_mapping"][0].tolist()
        model_inputs = {k: v.to(device) for k, v in inputs.items() if k != "offset_mapping"}

        with torch.inference_mode():
            out = transformer_module.auto_model(**model_inputs)
            token_embeds = out.last_hidden_state[0]  # shape: (seq_len, hidden_dim)

        chunk_embeddings: list[list[float] | None] = [None] * len(chunks)
        fallback_indices: list[int] = []
        for i, chunk in enumerate(chunks):
            ref_chunk = search_chunks[i] if i < len(search_chunks) else chunk
            c_start = full_text.find(ref_chunk)
            if c_start == -1:
                fallback_indices.append(i)
                continue
            c_end = c_start + len(ref_chunk)

            # Locate token indices that overlap the chunk character span
            tok_indices = [
                idx for idx, (s, e) in enumerate(offsets) if e > c_start and s < c_end
            ]
            if tok_indices:
                span_embeds = token_embeds[tok_indices[0] : tok_indices[-1] + 1]
                pooled = span_embeds.mean(dim=0)
                norm = torch.nn.functional.normalize(pooled, p=2, dim=0)
                chunk_embeddings[i] = norm.cpu().tolist()
            else:
                fallback_indices.append(i)

        if fallback_indices:
            fallback_vecs = embed([chunks[i] for i in fallback_indices], batch_size=32)
            for idx, vec in zip(fallback_indices, fallback_vecs):
                chunk_embeddings[idx] = vec

        return [vec for vec in chunk_embeddings if vec is not None]
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Late chunking forward pass failed (%s); using standard embed()", exc
        )
        return embed(chunks)
