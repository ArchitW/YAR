"""Local filesystem connector for automatic directory monitoring and ingestion (TKT-012)."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.orm import Session
from qdrant_client.models import PointStruct, SparseVector

from ...models.connector import Connector
from ...models.document import Document
from ...routers.documents import COLLECTION, ensure_collection, parse_chunk_metadata, qdrant
from ...services.audit import AuditService
from ...services.chunking import adaptive_chunk
from ...services.embeddings import embed_late_chunks, embed_sparse
from ...services.extraction import extract_text, is_supported

logger = logging.getLogger(__name__)


class FilesystemConnectorService:
    """Service that scans and synchronizes documents from local folders into workspaces."""

    @classmethod
    def sync_connector(
        cls,
        db: Session,
        connector: Connector,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Scan folder path and ingest new or updated documents into the target workspace."""
        config = connector.config_json or {}
        folder_path = config.get("folder_path") or config.get("path")
        recursive = config.get("recursive", True)

        if not folder_path or not os.path.exists(folder_path):
            error_msg = f"Directory not found: '{folder_path}'"
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

        connector.status = "syncing"
        db.commit()

        stats = {
            "files_scanned": 0,
            "files_indexed": 0,
            "files_skipped": 0,
            "errors": 0,
            "indexed_files": [],
        }

        # Query existing documents in this workspace to prevent duplicate indexing
        existing_docs = {
            doc.name: doc
            for doc in db.query(Document).filter(Document.workspace_id == connector.workspace_id).all()
        }

        try:
            for root, _, files in os.walk(folder_path):
                for fname in files:
                    stats["files_scanned"] += 1
                    file_path = os.path.join(root, fname)

                    if not is_supported(file_path):
                        stats["files_skipped"] += 1
                        continue

                    # If file already indexed with identical size, skip
                    file_size = os.path.getsize(file_path)
                    existing = existing_docs.get(fname)
                    if existing and existing.status == "indexed" and existing.size_bytes == file_size:
                        stats["files_skipped"] += 1
                        continue

                    try:
                        text = extract_text(file_path)
                    except Exception as ex:
                        logger.warning("Failed to extract %s during sync: %s", file_path, ex)
                        stats["errors"] += 1
                        continue

                    if not text:
                        stats["files_skipped"] += 1
                        continue

                    # Register or update Document in database
                    if existing:
                        doc = existing
                        doc.size_bytes = file_size
                        doc.content = text
                        doc.status = "indexed"
                    else:
                        doc = Document(
                            workspace_id=connector.workspace_id,
                            name=fname,
                            file_type=os.path.splitext(fname)[1].lstrip(".") or "unknown",
                            status="indexed",
                            size_bytes=file_size,
                            content=text,
                        )
                        db.add(doc)

                    db.commit()
                    db.refresh(doc)
                    existing_docs[fname] = doc

                    # Index chunks into Qdrant
                    ensure_collection()
                    chunks = adaptive_chunk(text)
                    ctx_chunks = [f"Document: {fname}\n\n{chunk}" for chunk in chunks]
                    dense_vecs = embed_late_chunks(text, ctx_chunks, original_chunks=chunks)
                    points = []
                    for i, (chunk, ctx_chunk, dvec) in enumerate(zip(chunks, ctx_chunks, dense_vecs)):
                        meta = parse_chunk_metadata(chunk)
                        sp = embed_sparse(ctx_chunk)
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
                                    "chunk_index": i,
                                    "total_chunks": len(chunks),
                                    "text": chunk,
                                    "context": ctx_chunk,
                                    "page_number": meta.get("page_number"),
                                    "section": meta.get("section"),
                                    "timestamp": None,
                                },
                            )
                        )
                    qdrant.upsert(COLLECTION, points=points)

                    stats["files_indexed"] += 1
                    stats["indexed_files"].append(fname)

                if not recursive:
                    break

            connector.status = "active"
            connector.last_sync_at = datetime.now(timezone.utc)
            db.commit()

            AuditService.record(
                db=db,
                event_type="connector.sync",
                summary=f"Connector '{connector.name}' synced: {stats['files_indexed']} indexed, {stats['files_skipped']} skipped",
                status="success",
                trace_id=trace_id,
                workspace_id=connector.workspace_id,
                metadata={"connector_id": connector.id, "stats": stats},
            )
            return {"status": "success", "connector_id": connector.id, "stats": stats}

        except Exception as ex:
            logger.exception("Error during filesystem sync for connector %s", connector.id)
            connector.status = "error"
            db.commit()
            AuditService.record(
                db=db,
                event_type="connector.sync",
                summary=f"Connector '{connector.name}' failed during sync: {ex}",
                status="failure",
                trace_id=trace_id,
                workspace_id=connector.workspace_id,
                metadata={"connector_id": connector.id, "error": str(ex)},
            )
            return {"status": "error", "error": str(ex)}
