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
    try:
        if "text" in (content_type or "") or path.endswith(".txt"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    except Exception:
        return ""
    return ""

@router.post("/upload")
