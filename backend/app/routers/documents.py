import logging
import os
import re
import shutil
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams,
    Distance,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    FieldCondition,
    Filter,
    MatchValue,
)
from ..core.database import get_db
from ..core.config import UPLOAD_DIR
from ..core.middleware import get_request_trace_id
from ..models.document import Document
from ..services.audit import AuditService
from ..services.embeddings import embed, embed_late_chunks, embed_sparse
from ..services.chunking import adaptive_chunk, hierarchical_chunk
from ..services.extraction import extract_text, is_supported

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])
os.makedirs(UPLOAD_DIR, exist_ok=True)
qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
COLLECTION = "yar_chunks"

def ensure_collection(client: Any | None = None):
    target = client or qdrant
    try:
        if hasattr(target, "collection_exists") and not target.collection_exists(COLLECTION):
            target.create_collection(
                COLLECTION,
                vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
                sparse_vectors_config={"sparse": SparseVectorParams()},
            )
    except Exception:
        logger.warning("Failed to verify/create Qdrant collection", exc_info=True)


def parse_chunk_metadata(chunk: str) -> dict[str, Any]:
    meta: dict[str, Any] = {"page_number": None, "section": None}
    page_match = re.search(r"\[Page\s+(\d+)\]", chunk, re.IGNORECASE)
    if page_match:
        meta["page_number"] = int(page_match.group(1))
    sheet_match = re.search(r"\[Sheet:\s*([^\]]+)\]", chunk, re.IGNORECASE)
    if sheet_match:
        meta["section"] = sheet_match.group(1).strip()
    return meta


@router.post("/upload")
def upload_document(
    workspace_id: int,
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    trace_id = get_request_trace_id(request)
    dest = os.path.join(UPLOAD_DIR, file.filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    size = os.path.getsize(dest)
    try:
        text = extract_text(dest, file.content_type)
    except Exception:
        logger.exception("Failed to extract text from %s", file.filename)
        text = ""
    if text:
        status_val = "indexed"
    elif not is_supported(dest, file.content_type):
        status_val = "queued"          # unsupported format, awaiting future parser
    else:
        status_val = "error"           # parser matched but extraction produced nothing
    doc = Document(
        workspace_id=workspace_id,
        name=file.filename,
        file_type=file.content_type or "unknown",
        status=status_val,
        size_bytes=size,
        content=text,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    AuditService.record(
        db=db,
        event_type="document.upload",
        summary=f"Uploaded '{file.filename}' ({size} bytes, status: {status_val})",
        status="success" if status_val != "error" else "failure",
        trace_id=trace_id,
        workspace_id=workspace_id,
        metadata={"filename": file.filename, "size_bytes": size, "status": status_val},
    )

    if text:
        ensure_collection()
        hier_items = hierarchical_chunk(text)
        if not hier_items:
            hier_items = [
                {
                    "child_text": c,
                    "child_index": i,
                    "parent_id": f"p_{i}",
                    "parent_index": i,
                    "parent_text": c,
                    "section": None,
                }
                for i, c in enumerate(adaptive_chunk(text))
            ]

        chunks = [item["child_text"] for item in hier_items]
        ctx_chunks = [f"Document: {file.filename}\n\n{chunk}" for chunk in chunks]
        dense_vecs = embed_late_chunks(text, ctx_chunks, original_chunks=chunks)
        points = []
        for i, (item, ctx_chunk, dvec) in enumerate(zip(hier_items, ctx_chunks, dense_vecs)):
            meta = parse_chunk_metadata(item["child_text"])
            sp = embed_sparse(ctx_chunk)
            sec = item.get("section") or meta.get("section")
            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    "dense": dvec,
                    "sparse": SparseVector(indices=sp["indices"], values=sp["values"]),
                },
                payload={
                    "workspace_id": workspace_id,
                    "document_id": doc.id,
                    "file_name": doc.name,
                    "chunk_index": item["child_index"],
                    "total_chunks": len(hier_items),
                    "text": item["child_text"],
                    "context": ctx_chunk,
                    "parent_id": f"{doc.id}_{item['parent_id']}",
                    "parent_text": item["parent_text"],
                    "page_number": meta.get("page_number"),
                    "section": sec,
                    "timestamp": None,
                },
            ))
        qdrant.upsert(COLLECTION, points=points)
    return doc

@router.get("")
def list_documents(workspace_id: int, db: Session = Depends(get_db)):
    return db.query(Document).filter(Document.workspace_id == workspace_id).all()


@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Delete a document, purge vectors from Qdrant, and record an audit log."""
    trace_id = get_request_trace_id(request)
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
        )

    # Purge vectors from Qdrant
    try:
        qdrant.delete(
            COLLECTION,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )
    except Exception:
        logger.warning("Could not sync Qdrant vector deletion for document %s", document_id, exc_info=True)

    workspace_id = doc.workspace_id
    doc_name = doc.name

    db.delete(doc)
    db.commit()

    AuditService.record(
        db=db,
        event_type="document.delete",
        summary=f"Deleted document '{doc_name}' (ID: {document_id})",
        status="success",
        trace_id=trace_id,
        workspace_id=workspace_id,
        metadata={"document_id": document_id, "name": doc_name},
    )

    return {"deleted": True, "id": document_id}
