from sentence_transformers import CrossEncoder

_reranker = None

def get_reranker():
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder("BAAI/bge-reranker-base")
    return _reranker

def rerank(query: str, candidates: list[dict]) -> list[dict]:
    if not candidates:
        return candidates
    r = get_reranker()
    pairs = [(query, c.get("text", c.get("chunk_text", ""))) for c in candidates]
    scores = r.predict(pairs)
    for c, s in zip(candidates, scores):
        c["rerank_score"] = float(s)
    candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
    return candidates
