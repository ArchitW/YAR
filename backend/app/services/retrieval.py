from typing import List, Dict
import os
from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector
from ..services.embeddings import embed, embed_sparse
from ..services.reranker import rerank

qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
COLLECTION = "yar_chunks"

def rewrite_query(query: str) -> list[str]:
    # Simple query rewriting: original + keyword-focused variant
    variants = [query]
    words = [w for w in query.split() if len(w) > 3]
    if words:
        variants.append(" ".join(words))
    return variants

