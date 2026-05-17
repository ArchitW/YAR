from typing import List, Dict
import os
from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector
from ..services.embeddings import embed, embed_sparse
from ..services.reranker import rerank

qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
