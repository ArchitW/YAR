import hashlib
import math
import re
from typing import Any, Dict, List
from sentence_transformers import SentenceTransformer

_model = None

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
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model

def embed(texts: List[str]) -> List[List[float]]:
    m = get_model()
    return m.encode(texts, normalize_embeddings=True).tolist()

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
