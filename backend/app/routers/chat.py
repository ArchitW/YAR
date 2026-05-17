from fastapi import APIRouter
from pydantic import BaseModel
from ..services.retrieval import retrieve

router = APIRouter(prefix="/chat", tags=["chat"])

class ChatRequest(BaseModel):
    workspace_id: int
    message: str
    mode: str = "auto"

@router.post("")
def chat(req: ChatRequest):
    hits = retrieve(req.workspace_id, req.message, req.mode)
    if hits:
        answer = "Based on your documents:\n" + "\n".join(f"- {h['chunk_text']}" for h in hits)
    else:
        answer = "No relevant content found in your documents."
    return {
        "answer": answer,
        "citations": hits,
        "provider": "local",
        "model": "llama.cpp",
    }
