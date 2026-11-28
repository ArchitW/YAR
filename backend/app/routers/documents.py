import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from typing import Any, Iterator
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, UploadFile, File, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
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
from ..services.embeddings import embed, embed_late_chunks, embed_sparse, embedding_dim
from ..services.chunking import adaptive_chunk, hierarchical_chunk
from ..services.guardrails import PIISanitizer
from ..services.cleaning import clean_text
from ..services.extraction import extract_pdf_boxes, extract_text, find_chunk_bbox, is_supported

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])
os.makedirs(UPLOAD_DIR, exist_ok=True)
qdrant = get_qdrant_client()
COLLECTION = "yar_chunks"

# Local (embedded) mode has no ANN index and is not recommended above this size.
LOCAL_MODE_WARN_POINTS = 20_000


def _deterministic_point_id(document_id: int, chunk_index: int, text: str) -> str:
    """Return a stable UUIDv5 for a document chunk so upserts are idempotent."""
    content_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{document_id}:{chunk_index}:{content_hash}"))


def ensure_collection(client: Any | None = None):
    target = client or qdrant
    try:
        dim = embedding_dim()
        exists = bool(hasattr(target, "collection_exists") and target.collection_exists(COLLECTION))

        if exists:
            # Rebuild if the configured embedding dimension no longer matches.
            try:
                current = target.get_collection(COLLECTION).config.params.vectors["dense"].size
            except Exception:
                current = None
            if current is not None and current != dim:
                logger.warning(
                    "Embedding dimension changed (%s → %s); recreating Qdrant collection. Reindex required.",
                    current,
                    dim,
                )
                try:
                    target.delete_collection(COLLECTION)
                except Exception:
                    logger.warning("Failed to delete old Qdrant collection", exc_info=True)
                exists = False

        if not exists:
            target.create_collection(
                COLLECTION,
                vectors_config={"dense": VectorParams(size=dim, distance=Distance.COSINE)},
                sparse_vectors_config={"sparse": SparseVectorParams()},
            )

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
        else:
            # Payload indexes keep workspace/master filtering O(index) in server mode.
            for field, schema in (
                ("workspace_id", PayloadSchemaType.INTEGER),
                ("is_master", PayloadSchemaType.BOOL),
            ):
                try:
                    target.create_payload_index(COLLECTION, field, field_schema=schema)
                except Exception:
                    logger.debug("Payload index %s not created (already exists or unsupported)", field)
    except Exception:
        logger.warning("Failed to verify/create Qdrant collection", exc_info=True)


def _purge_document_vectors(document_id: int) -> None:
    """Remove all Qdrant points for a document.

    Embedded (local) Qdrant has a bug where a filter delete can raise a numpy
    broadcast error once its in-memory deleted-mask drifts, and a failed delete can
    leave the SQLite connection stuck mid-transaction. We recover by resetting the
    shared client (close → release the storage lock, recreate → clean reload from
    disk), refreshing the cached references in modules that captured it at import,
    then deleting by filter with a scan+delete-by-ids fallback.
    """
    import sys

    from ..core.config import reset_qdrant_client

    client = reset_qdrant_client()
    global qdrant
    qdrant = client
    for modname in ("app.services.retrieval", "app.services.dreaming.rem"):
        module = sys.modules.get(modname)
        if module is not None and hasattr(module, "qdrant"):
            setattr(module, "qdrant", client)

    flt = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])
    try:
        try:
            client.delete(COLLECTION, points_selector=flt)
            return
        except Exception:
            logger.warning(
                "Filter delete failed for document %s; falling back to id scan", document_id, exc_info=True
            )

        ids: list[Any] = []
        offset = None
        while True:
            points, offset = client.scroll(
                COLLECTION, limit=256, offset=offset, with_payload=True, with_vectors=False
            )
            for p in points:
                if (p.payload or {}).get("document_id") == document_id:
                    ids.append(p.id)
            if offset is None:
                break
        if ids:
            client.delete(COLLECTION, points_selector=ids)
    except Exception:
        logger.warning("Vector purge failed for document %s", document_id, exc_info=True)


def _find_existing_document(
    db: Session, workspace_id: int, name: str, is_master: bool
) -> Document | None:
    """Return an existing document with the same name in the same scope, if any."""
    return (
        db.query(Document)
        .filter(
            Document.workspace_id == workspace_id,
            Document.name == name,
            Document.is_master == is_master,
        )
        .first()
    )


def parse_chunk_metadata(chunk: str) -> dict[str, Any]:
    meta: dict[str, Any] = {"page_number": None, "section": None}
    page_match = re.search(r"\[Page\s+(\d+)\]", chunk, re.IGNORECASE)
    if page_match:
        meta["page_number"] = int(page_match.group(1))
    sheet_match = re.search(r"\[Sheet:\s*([^\]]+)\]", chunk, re.IGNORECASE)
    if sheet_match:
        meta["section"] = sheet_match.group(1).strip()
    return meta


def index_document_file(
    db: Session,
    doc: Document,
    file_path: str,
    content_type: str | None = None,
    index_to_master: bool = False,
    trace_id: str | None = None,
) -> int:
    """Extract, sanitize, chunk, embed, and upsert an uploaded document into Qdrant."""
    try:
        text = extract_text(file_path, content_type)
    except Exception:
        logger.exception("Failed to extract text from %s", doc.name)
        text = ""

    pdf_blocks = []
    is_pdf = (content_type == "application/pdf") or (doc.name and doc.name.lower().endswith(".pdf"))
    if is_pdf:
        try:
            pdf_blocks = extract_pdf_boxes(file_path)
        except Exception:
            logger.warning("Failed to extract PDF bounding boxes from %s", doc.name, exc_info=True)

    pii_stats = {"total": 0}
    if text:
        text, pii_stats = PIISanitizer.sanitize(text)
        status_val = "indexed"
    elif not is_supported(file_path, content_type):
        status_val = "queued"
    else:
        status_val = "error"

    doc.content = text
    doc.status = status_val
    db.commit()
    db.refresh(doc)

    AuditService.record(
        db=db,
        event_type="document.upload",
        summary=f"Indexed '{doc.name}' ({doc.size_bytes} bytes, status: {status_val})",
        status="success" if status_val != "error" else "failure",
        trace_id=trace_id,
        workspace_id=doc.workspace_id,
        metadata={
            "filename": doc.name,
            "size_bytes": doc.size_bytes,
            "status": status_val,
            "redacted_pii_count": pii_stats["total"],
        },
    )

    if not text:
        return 0

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
    ctx_chunks = [f"Document: {doc.name}\n\n{chunk}" for chunk in chunks]
    dense_vecs = embed_late_chunks(text, ctx_chunks, original_chunks=chunks)
    points = []
    for item, ctx_chunk, dvec in zip(hier_items, ctx_chunks, dense_vecs):
        meta = parse_chunk_metadata(item["child_text"])
        sp = embed_sparse(ctx_chunk)
        sec = item.get("section") or meta.get("section")
        page_num = meta.get("page_number")
        bbox_info = find_chunk_bbox(item["child_text"], page_num, pdf_blocks) if pdf_blocks else None
        points.append(PointStruct(
            id=_deterministic_point_id(doc.id, item["child_index"], item["child_text"]),
            vector={
                "dense": dvec,
                "sparse": SparseVector(indices=sp["indices"], values=sp["values"]),
            },
            payload={
                "workspace_id": doc.workspace_id,
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
    return len(points)


def reindex_document(db: Session, doc: Document, trace_id: str | None = None) -> int:
    """Re-chunk, embed, and upsert a document from its stored (possibly edited) content.

    Purges any existing vectors for the document first so edits do not leave stale
    chunks behind. Returns the number of chunks indexed.
    """
    try:
        _purge_document_vectors(doc.id)
    except Exception:
        logger.warning("Could not purge vectors before reindex for document %s", doc.id, exc_info=True)

    text = doc.content or ""
    if not text.strip():
        doc.status = "error"
        db.commit()
        return 0

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
    ctx_chunks = [f"Document: {doc.name}\n\n{chunk}" for chunk in chunks]
    dense_vecs = embed_late_chunks(text, ctx_chunks, original_chunks=chunks)
    points = []
    for item, ctx_chunk, dvec in zip(hier_items, ctx_chunks, dense_vecs):
        meta = parse_chunk_metadata(item["child_text"])
        sp = embed_sparse(ctx_chunk)
        sec = item.get("section") or meta.get("section")
        page_num = meta.get("page_number")
        points.append(PointStruct(
            id=_deterministic_point_id(doc.id, item["child_index"], item["child_text"]),
            vector={
                "dense": dvec,
                "sparse": SparseVector(indices=sp["indices"], values=sp["values"]),
            },
            payload={
                "workspace_id": doc.workspace_id,
                "is_master": bool(doc.is_master),
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
                "bbox": None,
                "page_width": None,
                "page_height": None,
                "timestamp": None,
            },
        ))
    qdrant.upsert(COLLECTION, points=points)
    doc.status = "indexed"
    db.commit()
    return len(points)


@router.post("/upload")
def upload_document(
    workspace_id: int,
    file: UploadFile = File(...),
    index_to_master: bool = False,
    async_ingest: bool = False,
    response: Response = None,
    request: Request = None,
    db: Session = Depends(get_db),
):
    trace_id = get_request_trace_id(request)
    filename = file.filename or "untitled"
    if _find_existing_document(db, workspace_id, filename, index_to_master):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A document named '{filename}' already exists in this workspace.",
        )
    dest = os.path.join(UPLOAD_DIR, filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    size = os.path.getsize(dest)

    use_async = async_ingest or os.getenv("ASYNC_INGEST_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if use_async:
        from ..tasks import index_document_task

        doc = Document(
            workspace_id=workspace_id,
            is_master=index_to_master,
            name=file.filename,
            file_type=file.content_type or "unknown",
            status="queued",
            size_bytes=size,
            content="",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        index_document_task.delay(doc.id, dest, file.content_type, index_to_master, trace_id)
        if response is not None:
            response.status_code = status.HTTP_202_ACCEPTED
        return doc
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
                id=_deterministic_point_id(doc.id, item["child_index"], item["child_text"]),
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
    if _find_existing_document(db, workspace_id, filename, index_to_master):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A document named '{filename}' already exists in this workspace.",
        )
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
                        id=_deterministic_point_id(doc.id, item["child_index"], item["child_text"]),
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
            db.rollback()
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


class DocumentPatchRequest(BaseModel):
    name: str | None = None
    content: str | None = None


@router.patch("/{document_id}")
def update_document(document_id: int, req: DocumentPatchRequest, db: Session = Depends(get_db)):
    """Edit a document's name and/or extracted text. Edited content is re-cleaned.

    Saving does not re-index automatically — call POST /documents/{id}/reindex to
    rebuild vectors from the updated content.
    """
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")

    if req.name is not None:
        new_name = req.name.strip()
        if not new_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name cannot be empty")
        doc.name = new_name
    if req.content is not None:
        doc.content = clean_text(req.content)
        doc.status = "indexed" if doc.content.strip() else "error"
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/{document_id}/reindex")
def reindex_document_endpoint(
    document_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Rebuild Qdrant vectors for a document from its stored (possibly edited) content."""
    trace_id = get_request_trace_id(request)
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")

    chunks = reindex_document(db, doc, trace_id)
    AuditService.record(
        db=db,
        event_type="document.reindex",
        summary=f"Reindexed '{doc.name}' (ID: {document_id}) into {chunks} chunks",
        status="success" if chunks > 0 else "failure",
        trace_id=trace_id,
        workspace_id=doc.workspace_id,
        metadata={"document_id": document_id, "chunks": chunks},
    )
    return {"document_id": document_id, "chunks": chunks, "status": doc.status}


def _delete_document_impl(db: Session, doc: Document, trace_id: str | None) -> None:
    """Purge vectors, delete the row, and audit. Caller owns the session lifecycle."""
    document_id = doc.id
    try:
        _purge_document_vectors(document_id)
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


def _delete_document_background(document_id: int) -> None:
    """Background deletion: opens its own session (the request session is closed)."""
    from ..core.database import SessionLocal

    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is not None:
            _delete_document_impl(db, doc, None)
    except Exception:
        logger.exception("Background deletion failed for document %s", document_id)
    finally:
        db.close()


@router.get("/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db)):
    """Return a single document (used by the UI to poll async deletion)."""
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found")
    return doc


@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    background: bool = False,
    request: Request = None,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """Delete a document, purge vectors, and audit.

    When ``background=true`` the work runs via FastAPI BackgroundTasks (same
    process, after the response is sent) so the client is not blocked; the UI polls
    GET /documents/{id} until it 404s to show a completion notification.
    """
    trace_id = get_request_trace_id(request)
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
        )

    if background and background_tasks is not None:
        background_tasks.add_task(_delete_document_background, document_id)
        return {"status": "queued", "id": document_id}

    _delete_document_impl(db, doc, trace_id)
    return {"deleted": True, "id": document_id}
