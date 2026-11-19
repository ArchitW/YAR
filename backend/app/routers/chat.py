from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.chat import ChatMessage
from ..services.chat import answer_query

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
    # Persist user message
    user_msg = ChatMessage(
        workspace_id=req.workspace_id,
        role="user",
        content=req.message,
    )
    db.add(user_msg)

    result = answer_query(req.workspace_id, req.message, req.mode)

    # Persist assistant response
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
