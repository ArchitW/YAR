import os
from typing import Any, Dict, List

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, SparseVector

from ..services.embeddings import embed, embed_sparse
from ..services.reranker import rerank

qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
COLLECTION = "yar_chunks"


def rewrite_query(query: str) -> list[str]:
    """Query expansion: original query + keyword-filtered variant."""
    variants = [query]
    words = [w for w in query.split() if len(w) > 3]
    if words:
        variants.append(" ".join(words))
    return variants


def _build_workspace_filter(workspace_id: int) -> Filter:
    """Build Qdrant filter condition to enforce workspace isolation at database level."""
    return Filter(
        must=[
            FieldCondition(
                key="workspace_id",
                match=MatchValue(value=workspace_id),
            )
        ]
    )


def _query_qdrant(
    client: QdrantClient,
    query_vec: Any,
    using: str,
    query_filter: Filter | None = None,
    limit: int = 20,
) -> list[Any]:
    """Execute search against Qdrant supporting both query_points and legacy search with filtering."""
    try:
        if hasattr(client, "query_points"):
            res = client.query_points(
                COLLECTION,
                query=query_vec,
                using=using,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            return res.points
        elif hasattr(client, "search"):
            return client.search(
                COLLECTION,
                query_vector=(using, query_vec),
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
    except Exception:
        return []
    return []


def retrieve(
    workspace_id: int,
    query: str,
    mode: str = "auto",
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Retrieve relevant chunks from Qdrant using the requested retrieval strategy.

    Supported modes:
    - 'semantic': Dense vector similarity only.
    - 'keyword': Sparse lexical vector similarity only.
    - 'hybrid': Fuses dense and sparse results with Reciprocal Rank Fusion (RRF).
    - 'auto': Defaults to hybrid strategy.
    """
    mode = mode.lower().strip()
    if mode not in ("semantic", "keyword", "hybrid", "auto"):
        mode = "auto"
    if mode == "auto":
        mode = "hybrid"

    run_dense = mode in ("semantic", "hybrid")
    run_sparse = mode in ("keyword", "hybrid")

    ws_filter = _build_workspace_filter(workspace_id)
    all_scores: dict[Any, float] = {}
    payload_map: dict[Any, dict[str, Any]] = {}

    # 1. Semantic search: encode natural language query directly
    if run_dense:
        dvec = embed([query])[0]
        dense_res = _query_qdrant(qdrant, dvec, using="dense", query_filter=ws_filter, limit=20)
        for rank, r in enumerate(dense_res):
            pid = r.id
            all_scores[pid] = all_scores.get(pid, 0.0) + 1.0 / (60 + rank)
            payload_map[pid] = r.payload or {}

    # 2. Sparse lexical search: run across keyword-expanded variants
    if run_sparse:
        variants = rewrite_query(query)
        for v in variants:
            sp = embed_sparse(v)
            if not sp["indices"]:
                continue
            sparse_res = _query_qdrant(
                qdrant,
                SparseVector(indices=sp["indices"], values=sp["values"]),
                using="sparse",
                query_filter=ws_filter,
                limit=20,
            )
            for rank, r in enumerate(sparse_res):
                pid = r.id
                all_scores[pid] = all_scores.get(pid, 0.0) + 1.0 / (60 + rank)
                payload_map[pid] = r.payload or {}

    cands: list[dict[str, Any]] = []
    for pid, sc in all_scores.items():
        pl = payload_map.get(pid) or {}
        # Defense-in-depth verification
        if pl.get("workspace_id") is not None and pl.get("workspace_id") != workspace_id:
            continue
        cands.append({
            "id": pid,
            "score": sc,
            "document_id": pl.get("document_id"),
            "file_name": pl.get("file_name"),
            "chunk_text": pl.get("text", ""),
            "text": pl.get("text", ""),
            "chunk_index": pl.get("chunk_index"),
            "total_chunks": pl.get("total_chunks"),
            "page_number": pl.get("page_number"),
            "section": pl.get("section"),
            "timestamp": pl.get("timestamp"),
        })

    cands = rerank(query, cands)
    return cands[:top_k]
