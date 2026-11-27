"""SearXNG web knowledge ingestion connector (TKT-021)."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.orm import Session
from qdrant_client.models import PointStruct, SparseVector

from ...models.connector import Connector
from ...models.document import Document
from ...routers.documents import COLLECTION, ensure_collection, parse_chunk_metadata, qdrant
from ...services.audit import AuditService
from ...services.chunking import adaptive_chunk, hierarchical_chunk
from ...services.embeddings import embed_late_chunks, embed_sparse
from ...services.guardrails import PIISanitizer
from ...services.tools.searxng import SearXNGSearchTool

logger = logging.getLogger(__name__)


class SearXNGConnectorService:
    """Service that searches SearXNG for topics and synchronizes web documents into workspaces."""

    @classmethod
    def sync_connector(
        cls,
        db: Session,
        connector: Connector,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute web searches for configured queries and ingest results into the workspace."""
        config = connector.config_json or {}
        raw_queries = config.get("queries") or config.get("query")
        if isinstance(raw_queries, str):
            queries = [raw_queries]
        else:
            queries = list(raw_queries or [])
        queries = [q.strip() for q in queries if q and q.strip()]

        if not queries:
            error_msg = "No search queries configured for SearXNG connector."
            connector.status = "error"
            db.commit()
            AuditService.record(
                db=db,
                event_type="connector.sync",
                summary=f"Connector '{connector.name}' failed: {error_msg}",
                status="failure",
                trace_id=trace_id,
                workspace_id=connector.workspace_id,
                metadata={"connector_id": connector.id, "error": error_msg},
            )
            return {"status": "error", "error": error_msg}

        categories = config.get("categories", "general")
        if isinstance(categories, list):
            categories = ",".join(categories)
        max_results = int(config.get("max_results", 5))
        base_url = config.get("base_url")

        connector.status = "syncing"
        db.commit()

        stats: dict[str, Any] = {
            "queries_executed": len(queries),
            "results_found": 0,
            "documents_indexed": 0,
            "documents_skipped": 0,
            "errors": 0,
            "indexed_titles": [],
        }

        # Query existing documents in this workspace to prevent duplicate indexing
        existing_docs = (
            db.query(Document)
            .filter(Document.workspace_id == connector.workspace_id)
            .all()
        )
        existing_names = {doc.name for doc in existing_docs}
        existing_urls = set()
        for doc in existing_docs:
            if doc.content:
                url_match = re.search(r"Source URL:\s*(\S+)", doc.content)
                if url_match:
                    existing_urls.add(url_match.group(1).strip())

        search_tool = SearXNGSearchTool(base_url=base_url)

        try:
            for q in queries:
                results = search_tool.search(
                    query=q,
                    num_results=max_results,
                    categories=categories,
                )
                stats["results_found"] += len(results)

                for r in results:
                    url = (r.get("url") or "").strip()
                    title = (r.get("title") or "Web Result").strip()
                    snippet = (r.get("snippet") or "").strip()

                    if not url or not snippet:
                        continue

                    if url in existing_urls:
                        stats["documents_skipped"] += 1
                        continue

                    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
                    safe_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", title)[:40].strip("_")
                    fname = f"web_{safe_slug}_{url_hash}.md"

                    if fname in existing_names:
                        stats["documents_skipped"] += 1
                        continue

                    # Construct markdown document
                    doc_content = (
                        f"# {title}\n\n"
                        f"**Source URL:** {url}\n"
                        f"**Category:** {categories}\n"
                        f"**Indexed Query:** {q}\n\n"
                        f"## Web Summary\n"
                        f"{snippet}\n"
                    )

                    # Scrub PII
                    doc_content, _ = PIISanitizer.sanitize(doc_content)
                    size_bytes = len(doc_content.encode("utf-8"))

                    doc = Document(
                        workspace_id=connector.workspace_id,
                        name=fname,
                        file_type="markdown",
                        status="indexed",
                        size_bytes=size_bytes,
                        content=doc_content,
                    )
                    db.add(doc)
                    db.commit()
                    db.refresh(doc)

                    existing_names.add(fname)
                    existing_urls.add(url)
                    stats["documents_indexed"] += 1
                    stats["indexed_titles"].append(title)

                    # Vectorize into Qdrant
                    ensure_collection()
                    hier_items = hierarchical_chunk(doc_content)
                    if not hier_items:
                        hier_items = [
                            {
                                "child_text": c,
                                "child_index": i,
                                "parent_id": f"p_{i}",
                                "parent_index": i,
                                "parent_text": c,
                                "section": "Web Summary",
                            }
                            for i, c in enumerate(adaptive_chunk(doc_content))
                        ]

                    chunks = [item["child_text"] for item in hier_items]
                    ctx_chunks = [f"Document: {fname}\nSource: {url}\n\n{chunk}" for chunk in chunks]
                    dense_vecs = embed_late_chunks(doc_content, ctx_chunks, original_chunks=chunks)
                    points = []
                    for i, (item, ctx_chunk, dvec) in enumerate(zip(hier_items, ctx_chunks, dense_vecs)):
                        meta = parse_chunk_metadata(item["child_text"])
                        sp = embed_sparse(ctx_chunk)
                        sec = item.get("section") or meta.get("section") or "Web Summary"
                        points.append(
                            PointStruct(
                                id=str(uuid.uuid4()),
                                vector={
                                    "dense": dvec,
                                    "sparse": SparseVector(indices=sp["indices"], values=sp["values"]),
                                },
                                payload={
                                    "workspace_id": connector.workspace_id,
                                    "document_id": doc.id,
                                    "file_name": doc.name,
                                    "chunk_index": item["child_index"],
                                    "total_chunks": len(hier_items),
                                    "text": item["child_text"],
                                    "context": ctx_chunk,
                                    "parent_id": f"{doc.id}_{item['parent_id']}",
                                    "parent_text": item["parent_text"],
                                    "page_number": None,
                                    "section": sec,
                                    "url": url,
                                    "is_web": True,
                                    "timestamp": None,
                                },
                            )
                        )
                    qdrant.upsert(COLLECTION, points=points)

            connector.status = "active"
            connector.last_sync_at = datetime.now(timezone.utc)
            db.commit()

            AuditService.record(
                db=db,
                event_type="connector.sync",
                summary=(
                    f"SearXNG connector '{connector.name}' indexed {stats['documents_indexed']} docs "
                    f"({stats['documents_skipped']} skipped)"
                ),
                status="success",
                trace_id=trace_id,
                workspace_id=connector.workspace_id,
                metadata={
                    "connector_id": connector.id,
                    "connector_type": "searxng",
                    **stats,
                },
            )
            return {"status": "success", "stats": stats}

        except Exception as exc:
            logger.exception("Error synchronizing SearXNG connector %d", connector.id)
            connector.status = "error"
            db.commit()
            AuditService.record(
                db=db,
                event_type="connector.sync",
                summary=f"SearXNG connector '{connector.name}' failed: {exc}",
                status="failure",
                trace_id=trace_id,
                workspace_id=connector.workspace_id,
                metadata={"connector_id": connector.id, "error": str(exc)},
            )
            return {"status": "error", "error": str(exc), "stats": stats}
