import logging
import os
import time
from typing import Any, Dict, List

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, SparseVector

from ..core.config import get_qdrant_client, reranker_settings
from ..services.embeddings import embed, embed_sparse
from ..services.reranker import rerank

logger = logging.getLogger(__name__)
qdrant = get_qdrant_client()
COLLECTION = "yar_chunks"


def rewrite_query(query: str) -> list[str]:
    """Query expansion: original query + keyword-filtered variant."""
    variants = [query]
    words = [w for w in query.split() if len(w) > 3]
    if words:
        variants.append(" ".join(words))
    return variants


def _build_workspace_filter(workspace_id: int) -> Filter:
    """Build a Qdrant filter enforcing workspace isolation at the DB level.

    A workspace sees its own chunks plus any chunk flagged as master knowledge
    (``is_master == True``), which is shared across all workspaces.
    """
    return Filter(
        should=[
            FieldCondition(
                key="workspace_id",
                match=MatchValue(value=workspace_id),
            ),
            FieldCondition(
                key="is_master",
                match=MatchValue(value=True),
            ),
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
    rewritten_query: str | None = None,
    hyde_passage: str | None = None,
) -> List[Dict[str, Any]]:
    """Retrieve relevant chunks from Qdrant using the requested retrieval strategy.

    Supported modes:
    - 'semantic': Dense vector similarity only.
    - 'keyword': Sparse lexical vector similarity only.
    - 'hybrid': Fuses dense and sparse results with Reciprocal Rank Fusion (RRF).
    - 'auto': Defaults to hybrid strategy.

    Optionally incorporates `rewritten_query` (pronoun resolution) and `hyde_passage` (HyDE).
    """
    mode = mode.lower().strip()
    if mode not in ("semantic", "keyword", "hybrid", "auto"):
        mode = "auto"
    if mode == "auto":
        mode = "hybrid"

    run_dense = mode in ("semantic", "hybrid")
    run_sparse = mode in ("keyword", "hybrid")

    search_query = (rewritten_query or "").strip() or query

    ws_filter = _build_workspace_filter(workspace_id)
    all_scores: dict[Any, float] = {}
    payload_map: dict[Any, dict[str, Any]] = {}

    t_start = time.perf_counter()
    embed_ms = 0.0
    qdrant_ms = 0.0
    rerank_ms = 0.0

    # 1. Semantic search: encode natural language query (and optional HyDE passage)
    if run_dense:
        t0 = time.perf_counter()
        dvec = embed([search_query])[0]
        embed_ms += (time.perf_counter() - t0) * 1000.0
        t0 = time.perf_counter()
        dense_res = _query_qdrant(qdrant, dvec, using="dense", query_filter=ws_filter, limit=20)
        qdrant_ms += (time.perf_counter() - t0) * 1000.0
        for rank, r in enumerate(dense_res):
            pid = r.id
            all_scores[pid] = all_scores.get(pid, 0.0) + 1.0 / (60 + rank)
            payload_map[pid] = r.payload or {}

        # If HyDE hypothetical passage is provided, execute secondary dense probe
        if hyde_passage and hyde_passage.strip():
            t0 = time.perf_counter()
            hyde_vec = embed([hyde_passage.strip()])[0]
            embed_ms += (time.perf_counter() - t0) * 1000.0
            t0 = time.perf_counter()
            hyde_res = _query_qdrant(qdrant, hyde_vec, using="dense", query_filter=ws_filter, limit=20)
            qdrant_ms += (time.perf_counter() - t0) * 1000.0
            for rank, r in enumerate(hyde_res):
                pid = r.id
                all_scores[pid] = all_scores.get(pid, 0.0) + 1.0 / (60 + rank)
                payload_map[pid] = r.payload or {}

    # 2. Sparse lexical search: run across keyword-expanded variants of search_query
    if run_sparse:
        variants = rewrite_query(search_query)
        t0 = time.perf_counter()
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
        qdrant_ms += (time.perf_counter() - t0) * 1000.0

    cands: list[dict[str, Any]] = []
    for pid, sc in all_scores.items():
        pl = payload_map.get(pid) or {}
        # Defense-in-depth verification (master docs are shared across workspaces)
        is_master = bool(pl.get("is_master", False))
        if not is_master and pl.get("workspace_id") is not None and pl.get("workspace_id") != workspace_id:
            continue
        cands.append({
            "id": pid,
            "score": sc,
            "document_id": pl.get("document_id"),
            "file_name": pl.get("file_name"),
            "is_master": is_master,
            "chunk_text": pl.get("text", ""),
            "text": pl.get("text", ""),
            "chunk_index": pl.get("chunk_index"),
            "total_chunks": pl.get("total_chunks"),
            "parent_id": pl.get("parent_id"),
            "parent_text": pl.get("parent_text"),
            "page_number": pl.get("page_number"),
            "section": pl.get("section"),
            "bbox": pl.get("bbox"),
            "page_width": pl.get("page_width"),
            "page_height": pl.get("page_height"),
            "timestamp": pl.get("timestamp"),
            "is_dream": bool(pl.get("is_dream", False)),
            "dream_insight_id": pl.get("dream_insight_id"),
            "dream_title": pl.get("dream_title"),
        })

    rr = reranker_settings()
    if rr["enabled"]:
        t0 = time.perf_counter()
        cands = rerank(search_query, cands[: rr["top_k"]])
        rerank_ms = (time.perf_counter() - t0) * 1000.0
    total_ms = (time.perf_counter() - t_start) * 1000.0
    logger.info(
        "retrieve workspace=%s mode=%s hits=%d embed_ms=%.1f qdrant_ms=%.1f rerank_ms=%.1f total_ms=%.1f",
        workspace_id,
        mode,
        len(cands[:top_k]),
        embed_ms,
        qdrant_ms,
        rerank_ms,
        total_ms,
    )
    return cands[:top_k]
