from fastapi import APIRouter
from pydantic import BaseModel
from ..services.retrieval import retrieve

router = APIRouter(prefix="/chat", tags=["chat"])

class ChatRequest(BaseModel):
    workspace_id: int
    message: str
    mode: str = "auto"

