import logging
import os
import re
import shutil
import uuid
from typing import Any
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct, SparseVector, SparseVectorParams
from ..core.database import get_db
from ..core.config import UPLOAD_DIR
from ..models.document import Document
from ..services.embeddings import embed, embed_late_chunks, embed_sparse
from ..services.chunking import adaptive_chunk
from ..services.extraction import extract_text, is_supported

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])
os.makedirs(UPLOAD_DIR, exist_ok=True)
qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
COLLECTION = "yar_chunks"

def ensure_collection():
    if not qdrant.collection_exists(COLLECTION):
        qdrant.create_collection(
            COLLECTION,
            vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams()},
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


@router.post("/upload")
def upload_document(workspace_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
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
        status = "indexed"
    elif not is_supported(dest, file.content_type):
        status = "queued"          # unsupported format, awaiting future parser
    else:
        status = "error"           # parser matched but extraction produced nothing
    doc = Document(workspace_id=workspace_id, name=file.filename, file_type=file.content_type or "unknown", status=status, size_bytes=size, content=text)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    if text:
        ensure_collection()
        chunks = adaptive_chunk(text)
        ctx_chunks = [f"Document: {file.filename}\n\n{chunk}" for chunk in chunks]
        dense_vecs = embed_late_chunks(text, ctx_chunks, original_chunks=chunks)
        points = []
        for i, (chunk, ctx_chunk, dvec) in enumerate(zip(chunks, ctx_chunks, dense_vecs)):
            meta = parse_chunk_metadata(chunk)
            sp = embed_sparse(ctx_chunk)
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
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "text": chunk,
                    "context": ctx_chunk,
                    "page_number": meta.get("page_number"),
                    "section": meta.get("section"),
                    "timestamp": None,
                },
            ))
        qdrant.upsert(COLLECTION, points=points)
    return doc

@router.get("")
def list_documents(workspace_id: int, db: Session = Depends(get_db)):
    return db.query(Document).filter(Document.workspace_id == workspace_id).all()
