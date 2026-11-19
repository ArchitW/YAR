import logging
import os
import shutil
import uuid
import re
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct, SparseVector, SparseVectorParams
from ..core.database import get_db
from ..core.config import UPLOAD_DIR
from ..models.document import Document
from ..services.embeddings import embed, embed_sparse
from ..services.chunking import adaptive_chunk

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

def extract_text(path: str, content_type: str) -> str:
    if "text" in (content_type or "") or path.endswith(".txt"):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return ""

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
    elif file.content_type and "text" not in file.content_type and not dest.endswith(".txt"):
        status = "queued"          # unsupported format, awaiting future parser
    else:
        status = "error"           # extraction was expected to work but didn't
    doc = Document(workspace_id=workspace_id, name=file.filename, file_type=file.content_type or "unknown", status=status, size_bytes=size, content=text)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    if text:
        ensure_collection()
        chunks = adaptive_chunk(text)
        dense_vecs = embed(chunks)
        points = []
        for i, (chunk, dvec) in enumerate(zip(chunks, dense_vecs)):
            # contextual prefix
            ctx_chunk = f"Document: {file.filename}\n\n{chunk}"
            sp = embed_sparse(ctx_chunk)
            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector={"dense": embed([ctx_chunk])[0], "sparse": SparseVector(indices=sp["indices"], values=sp["values"])},
                payload={"workspace_id": workspace_id, "document_id": doc.id, "file_name": doc.name, "chunk_index": i, "total_chunks": len(chunks), "text": chunk, "context": ctx_chunk},
            ))
        qdrant.upsert(COLLECTION, points=points)
    return doc

@router.get("")
def list_documents(workspace_id: int, db: Session = Depends(get_db)):
    return db.query(Document).filter(Document.workspace_id == workspace_id).all()
