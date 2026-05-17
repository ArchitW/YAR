from typing import List, Dict
import os
from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector
from ..services.embeddings import embed, embed_sparse
from ..services.reranker import rerank

qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
COLLECTION = "yar_chunks"

def rewrite_query(query: str) -> list[str]:
    # Simple query rewriting: original + keyword-focused variant
    variants = [query]
    words = [w for w in query.split() if len(w) > 3]
    if words:
        variants.append(" ".join(words))
    return variants

def retrieve(workspace_id: int, query: str, mode: str = "auto", top_k: int = 5) -> List[Dict]:
    variants = rewrite_query(query)
    all_scores = {}
    payload_map = {}
    for v in variants:
        dvec = embed([v])[0]
        dense_res = qdrant.search(COLLECTION, query_vector=("dense", dvec), limit=20, with_payload=True)
        sp = embed_sparse(v)
        sparse_res = qdrant.search(COLLECTION, query_vector=("sparse", SparseVector(indices=sp["indices"], values=sp["values"])), limit=20, with_payload=True)
        for rank, r in enumerate(dense_res):
            pid = r.id
            all_scores[pid] = all_scores.get(pid, 0) + 1.0 / (60 + rank)
            payload_map[pid] = r.payload
        for rank, r in enumerate(sparse_res):
            pid = r.id
            all_scores[pid] = all_scores.get(pid, 0) + 1.0 / (60 + rank)
            payload_map[pid] = r.payload
    cands = []
    for pid, sc in all_scores.items():
        pl = payload_map.get(pid) or {}
        if pl.get("workspace_id") != workspace_id:
            continue
        cands.append({"id": pid, "score": sc, "document_id": pl.get("document_id"), "file_name": pl.get("file_name"), "chunk_text": pl.get("text", ""), "text": pl.get("text", ""), "chunk_index": pl.get("chunk_index"), "total_chunks": pl.get("total_chunks")})
    cands = rerank(query, cands)
    return cands[:top_k]
