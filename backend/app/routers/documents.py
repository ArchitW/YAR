import json
import logging
import os
import re
import shutil
import uuid
from typing import Any, Iterator
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from fastapi.responses import FileResponse, StreamingResponse
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
    PayloadSchemaType,
)
from ..core.database import get_db
from ..core.config import UPLOAD_DIR, get_qdrant_client, qdrant_mode
from ..core.middleware import get_request_trace_id
from ..models.document import Document
from ..services.audit import AuditService
from ..services.embeddings import embed, embed_late_chunks, embed_sparse
from ..services.chunking import adaptive_chunk, hierarchical_chunk
from ..services.guardrails import PIISanitizer
from ..services.extraction import extract_pdf_boxes, extract_text, find_chunk_bbox, is_supported

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])
os.makedirs(UPLOAD_DIR, exist_ok=True)
qdrant = get_qdrant_client()
COLLECTION = "yar_chunks"

# Local (embedded) mode has no ANN index and is not recommended above this size.
LOCAL_MODE_WARN_POINTS = 20_000


def ensure_collection(client: Any | None = None):
    target = client or qdrant
    try:
        if hasattr(target, "collection_exists") and not target.collection_exists(COLLECTION):
            target.create_collection(
                COLLECTION,
                vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
                sparse_vectors_config={"sparse": SparseVectorParams()},
            )

        # Payload indexes keep workspace/master filtering O(index) instead of a scan.
        for field, schema in (
            ("workspace_id", PayloadSchemaType.INTEGER),
            ("is_master", PayloadSchemaType.BOOL),
        ):
            try:
                target.create_payload_index(COLLECTION, field, field_schema=schema)
            except Exception:
                logger.debug("Payload index %s not created (already exists or unsupported)", field)

        if qdrant_mode() == "local":
            try:
                count = target.get_collection(COLLECTION).points_count or 0
            except Exception:
                count = 0
            if count > LOCAL_MODE_WARN_POINTS:
                logger.warning(
                    "Embedded Qdrant holds %s points; local mode is not recommended above %s. "
                    "Set QDRANT_URL (server mode) for scalable retrieval.",
                    count,
                    LOCAL_MODE_WARN_POINTS,
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
    index_to_master: bool = False,
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

    pdf_blocks = []
    is_pdf = (file.content_type == "application/pdf") or (file.filename and file.filename.lower().endswith(".pdf"))
    if is_pdf:
        try:
            pdf_blocks = extract_pdf_boxes(dest)
        except Exception:
            logger.warning("Failed to extract PDF bounding boxes from %s", file.filename, exc_info=True)

    pii_stats = {"total": 0}
    if text:
        text, pii_stats = PIISanitizer.sanitize(text)
        if pii_stats["total"] > 0:
            logger.info("Redacted %d sensitive PII entities from %s before indexing", pii_stats["total"], file.filename)
        status_val = "indexed"
    elif not is_supported(dest, file.content_type):
        status_val = "queued"          # unsupported format, awaiting future parser
    else:
        status_val = "error"           # parser matched but extraction produced nothing
    doc = Document(
        workspace_id=workspace_id,
        is_master=index_to_master,
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
        metadata={
            "filename": file.filename,
            "size_bytes": size,
            "status": status_val,
            "redacted_pii_count": pii_stats["total"],
        },
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
            page_num = meta.get("page_number")
            bbox_info = find_chunk_bbox(item["child_text"], page_num, pdf_blocks) if pdf_blocks else None
            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    "dense": dvec,
                    "sparse": SparseVector(indices=sp["indices"], values=sp["values"]),
                },
                payload={
                    "workspace_id": workspace_id,
                    "is_master": index_to_master,
                    "document_id": doc.id,
                    "file_name": doc.name,
                    "chunk_index": item["child_index"],
                    "total_chunks": len(hier_items),
                    "text": item["child_text"],
                    "context": ctx_chunk,
                    "parent_id": f"{doc.id}_{item['parent_id']}",
                    "parent_text": item["parent_text"],
                    "page_number": page_num,
                    "section": sec,
                    "bbox": bbox_info.get("bbox") if bbox_info else None,
                    "page_width": bbox_info.get("page_width") if bbox_info else None,
                    "page_height": bbox_info.get("page_height") if bbox_info else None,
                    "timestamp": None,
                },
            ))
        qdrant.upsert(COLLECTION, points=points)
    return doc


def _sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/upload/stream")
def upload_document_stream(
    workspace_id: int,
    file: UploadFile = File(...),
    index_to_master: bool = False,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Upload and index a document while streaming stage-by-stage SSE progress."""
    trace_id = get_request_trace_id(request)
    filename = file.filename or "untitled"
    content_type = file.content_type
    dest = os.path.join(UPLOAD_DIR, filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    size = os.path.getsize(dest)

    def generate() -> Iterator[str]:
        try:
            yield _sse_event({
                "stage": "upload",
                "progress": 15,
                "detail": f"Received {filename} ({size:,} bytes)",
            })

            try:
                text = extract_text(dest, content_type)
            except Exception:
                logger.exception("Failed to extract text from %s", filename)
                text = ""

            pdf_blocks = []
            is_pdf = (content_type == "application/pdf") or filename.lower().endswith(".pdf")
            if is_pdf:
                try:
                    pdf_blocks = extract_pdf_boxes(dest)
                except Exception:
                    logger.warning("Failed to extract PDF bounding boxes from %s", filename, exc_info=True)

            extract_detail = f"Extracted {len(text):,} characters" if text else "No text extracted"
            if pdf_blocks:
                pages = len({b.get("page") for b in pdf_blocks if b.get("page")})
                extract_detail += f" ({pages} PDF page{'s' if pages != 1 else ''})"
            yield _sse_event({
                "stage": "extract",
                "progress": 35,
                "detail": extract_detail,
            })

            pii_stats = {"total": 0}
            if text:
                text, pii_stats = PIISanitizer.sanitize(text)
                status_val = "indexed"
            elif not is_supported(dest, content_type):
                status_val = "queued"
            else:
                status_val = "error"

            yield _sse_event({
                "stage": "sanitize",
                "progress": 50,
                "detail": f"{pii_stats['total']} sensitive PII entities redacted",
            })

            doc = Document(
                workspace_id=workspace_id,
                is_master=index_to_master,
                name=filename,
                file_type=content_type or "unknown",
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
                summary=f"Uploaded '{filename}' ({size} bytes, status: {status_val})",
                status="success" if status_val != "error" else "failure",
                trace_id=trace_id,
                workspace_id=workspace_id,
                metadata={
                    "filename": filename,
                    "size_bytes": size,
                    "status": status_val,
                    "redacted_pii_count": pii_stats["total"],
                },
            )

            total_chunks = 0
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

                total_chunks = len(hier_items)
                yield _sse_event({
                    "stage": "chunk",
                    "progress": 65,
                    "detail": f"Created {total_chunks} parent-child chunks",
                })

                yield _sse_event({
                    "stage": "vectorize",
                    "progress": 80,
                    "detail": f"Embedding {total_chunks} chunks & indexing in Qdrant...",
                })

                chunks = [item["child_text"] for item in hier_items]
                ctx_chunks = [f"Document: {filename}\n\n{chunk}" for chunk in chunks]
                dense_vecs = embed_late_chunks(text, ctx_chunks, original_chunks=chunks)
                points = []
                for item, ctx_chunk, dvec in zip(hier_items, ctx_chunks, dense_vecs):
                    meta = parse_chunk_metadata(item["child_text"])
                    sp = embed_sparse(ctx_chunk)
                    sec = item.get("section") or meta.get("section")
                    page_num = meta.get("page_number")
                    bbox_info = find_chunk_bbox(item["child_text"], page_num, pdf_blocks) if pdf_blocks else None
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
                            "total_chunks": total_chunks,
                            "text": item["child_text"],
                            "context": ctx_chunk,
                            "parent_id": f"{doc.id}_{item['parent_id']}",
                            "parent_text": item["parent_text"],
                            "page_number": page_num,
                            "section": sec,
                            "bbox": bbox_info.get("bbox") if bbox_info else None,
                            "page_width": bbox_info.get("page_width") if bbox_info else None,
                            "page_height": bbox_info.get("page_height") if bbox_info else None,
                            "timestamp": None,
                        },
                    ))
                qdrant.upsert(COLLECTION, points=points)
            else:
                yield _sse_event({
                    "stage": "chunk",
                    "progress": 65,
                    "detail": "Skipped chunking (no text extracted)",
                })
                yield _sse_event({
                    "stage": "vectorize",
                    "progress": 85,
                    "detail": "Skipped vectorization",
                })

            yield _sse_event({
                "stage": "complete",
                "progress": 100,
                "detail": f"Indexed {total_chunks} chunks · {pii_stats['total']} PII redacted" if text else f"Saved with status: {status_val}",
                "document": {
                    "id": doc.id,
                    "workspace_id": doc.workspace_id,
                    "name": doc.name,
                    "status": doc.status,
                    "size_bytes": doc.size_bytes,
                },
            })
        except Exception as ex:
            logger.exception("Streaming upload failed for %s", filename)
            yield _sse_event({
                "stage": "error",
                "progress": 100,
                "detail": str(ex),
            })

    return StreamingResponse(generate(), media_type="text/event-stream")

@router.get("")
def list_documents(
    workspace_id: int | None = None,
    master: bool = False,
    db: Session = Depends(get_db),
):
    q = db.query(Document)
    if master:
        q = q.filter(Document.is_master.is_(True))
    elif workspace_id is not None:
        q = q.filter(Document.workspace_id == workspace_id)
    return q.order_by(Document.id.desc()).all()


@router.get("/{document_id}/file")
def get_document_file(
    document_id: int,
    db: Session = Depends(get_db),
):
    """Serve original document file for visual PDF viewing with range request support (TKT-017)."""
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
        )
    file_path = os.path.join(UPLOAD_DIR, doc.name)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File for document {document_id} not found on disk",
        )
    return FileResponse(
        file_path,
        media_type=doc.file_type or "application/pdf",
        filename=doc.name,
    )


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
