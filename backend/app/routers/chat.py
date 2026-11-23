import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.middleware import get_request_trace_id
from ..models.chat import ChatMessage
from ..services.audit import AuditService
from ..services.chat import answer_query, stream_answer_query
from ..services.export import ExportService
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
    faithfulness_score: float | None = None
    hallucination_detected: bool = False


@router.post("", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    request: Request = None,
    db: Session = Depends(get_db),
) -> ChatResponse:
    trace_id = get_request_trace_id(request)

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

    # 6. Record audit log for chat query
    AuditService.record(
        db=db,
        event_type="chat.query",
        summary=f"Processed query in workspace {req.workspace_id}",
        status="warning" if result.get("degraded") or result.get("hallucination_detected") else "success",
        trace_id=trace_id,
        workspace_id=req.workspace_id,
        metadata={
            "provider": result.get("provider"),
            "model": result.get("model"),
            "citations_count": len(result.get("citations", [])),
            "degraded": result.get("degraded", False),
            "faithfulness_score": result.get("faithfulness_score"),
            "hallucination_detected": result.get("hallucination_detected", False),
            "unsupported_claims": result.get("unsupported_claims", []),
        },
    )

    db.commit()

    return ChatResponse(**result)


@router.post("/stream")
def chat_stream(
    req: ChatRequest,
    request: Request = None,
    db: Session = Depends(get_db),
):
    trace_id = get_request_trace_id(request)

    # 1. Persist user message to chat history immediately
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
        pass

    db.commit()

    def event_generator():
        final_result = None
        try:
            for event in stream_answer_query(req.workspace_id, req.message, req.mode, db=db):
                if event.get("type") == "done":
                    final_result = event
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            err_event = {
                "type": "error",
                "error": str(exc),
            }
            yield f"data: {json.dumps(err_event)}\n\n"

        # 3. Persist assistant message and audit log upon stream completion
        if final_result:
            try:
                assistant_msg = ChatMessage(
                    workspace_id=req.workspace_id,
                    role="assistant",
                    content=final_result.get("answer", ""),
                    citations=final_result.get("citations", []),
                    provider=final_result.get("provider", "unknown"),
                    model=final_result.get("model", "unknown"),
                    degraded=final_result.get("degraded", False),
                )
                db.add(assistant_msg)
                try:
                    MemoryService.record_interaction(db, req.workspace_id, "assistant", final_result.get("answer", ""))
                except Exception:
                    pass

                AuditService.record(
                    db=db,
                    event_type="chat.query",
                    summary=f"Processed streaming query in workspace {req.workspace_id}",
                    status="warning" if final_result.get("degraded") or final_result.get("hallucination_detected") else "success",
                    trace_id=trace_id,
                    workspace_id=req.workspace_id,
                    metadata={
                        "provider": final_result.get("provider"),
                        "model": final_result.get("model"),
                        "citations_count": len(final_result.get("citations", [])),
                        "degraded": final_result.get("degraded", False),
                        "faithfulness_score": final_result.get("faithfulness_score"),
                        "hallucination_detected": final_result.get("hallucination_detected", False),
                        "unsupported_claims": final_result.get("unsupported_claims", []),
                        "streaming": True,
                    },
                )
                db.commit()
            except Exception:
                db.rollback()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


@router.get("/export")
@router.post("/export")
def export_chat(
    workspace_id: int = Query(...),
    export_format: str = Query("markdown", alias="format"),
    request: Request = None,
    db: Session = Depends(get_db),
) -> Response:
    """Export workspace conversation history to Markdown, JSON, or Plaintext format."""
    trace_id = get_request_trace_id(request)
    fmt = export_format.lower().strip()

    if fmt in ("md", "markdown"):
        content, filename = ExportService.export_markdown(db, workspace_id)
        media_type = "text/markdown; charset=utf-8"
    elif fmt == "json":
        content, filename = ExportService.export_json(db, workspace_id)
        media_type = "application/json; charset=utf-8"
    elif fmt in ("txt", "text"):
        content, filename = ExportService.export_txt(db, workspace_id)
        media_type = "text/plain; charset=utf-8"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format '{export_format}'. Supported formats: markdown, json, txt",
        )

    AuditService.record(
        db=db,
        event_type="export.chat",
        summary=f"Exported workspace {workspace_id} conversation as {fmt}",
        status="success",
        trace_id=trace_id,
        workspace_id=workspace_id,
        metadata={"format": fmt, "filename": filename},
    )

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
