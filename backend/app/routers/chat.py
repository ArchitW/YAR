from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.chat import ChatMessage
from ..services.chat import answer_query
from ..services.memory import MemoryService

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    workspace_id: int
    message: str = Field(min_length=1)
    mode: str = "auto"


class ChatResponse(BaseModel):
    answer: str
    citations: list[dict[str, Any]]
    provider: str
    model: str
    degraded: bool = False


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    # 1. Persist user message to chat history
    user_msg = ChatMessage(
        workspace_id=req.workspace_id,
        role="user",
        content=req.message,
    )
    db.add(user_msg)

    # 2. Record interaction in cognitive memory stream
    try:
        MemoryService.record_interaction(db, req.workspace_id, "user", req.message)
    except Exception:
        # Memory logging failure should never crash the chat session
        pass

    # 3. Answer query with document retrieval + memory context
    result = answer_query(req.workspace_id, req.message, req.mode, db=db)

    # 4. Persist assistant response to chat history
    assistant_msg = ChatMessage(
        workspace_id=req.workspace_id,
        role="assistant",
        content=result["answer"],
        citations=result["citations"],
        provider=result["provider"],
        model=result["model"],
        degraded=result["degraded"],
    )
    db.add(assistant_msg)

    # 5. Record assistant response in cognitive memory stream
    try:
        MemoryService.record_interaction(db, req.workspace_id, "assistant", result["answer"])
    except Exception:
        pass

    db.commit()

    return ChatResponse(**result)


class HistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    citations: list[dict[str, Any]]
    provider: str
    model: str
    degraded: bool
    created_at: str


@router.get("/history")
def chat_history(
    workspace_id: int,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
) -> list[HistoryItem]:
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.workspace_id == workspace_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
        .all()
    )
    return [
        HistoryItem(
            id=r.id,
            role=r.role,
            content=r.content,
            citations=r.citations or [],
            provider=r.provider or "",
            model=r.model or "",
            degraded=r.degraded or False,
            created_at=str(r.created_at),
        )
        for r in rows
    ]
