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

