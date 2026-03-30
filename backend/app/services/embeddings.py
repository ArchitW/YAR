import hashlib
from sentence_transformers import SentenceTransformer

_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model

def embed(texts):
    m = get_model()
    return m.encode(texts, normalize_embeddings=True).tolist()

def embed_sparse(text: str):
    # Simple term-frequency sparse vector with hashed indices
    tokens = text.lower().split()
    freq = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    indices = []
    values = []
    for term, count in freq.items():
        idx = int(hashlib.md5(term.encode()).hexdigest(), 16) % (2**16)
        indices.append(idx)
        values.append(float(count))
    return {"indices": indices, "values": values}
