import json
import logging
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

logger = logging.getLogger(__name__)
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


class ModelsResponse(BaseModel):
    configured_provider: str | None = None
    configured_model: str | None = None
    base_url: str | None = None
    timeout: str = "60"
    has_api_key: bool = False
    ollama_online: bool = False
    local_models: list[str] = Field(default_factory=list)


class ModelConfigRequest(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    timeout: str = "60"


class ModelTestRequest(BaseModel):
    base_url: str
    model: str = ""
    api_key: str = ""
    timeout: float = 5.0


class ModelTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    models: list[str] = Field(default_factory=list)
    detail: str


@router.get("/models", response_model=ModelsResponse)
def list_available_models() -> ModelsResponse:
    """List configured provider and autodiscovered local Ollama models (TKT-023)."""
    from ..core.config import llm_settings, ollama_settings
    from ..services.providers import OllamaProvider, get_provider

    llm_cfg = llm_settings()
    o_cfg = ollama_settings()

    active_provider = get_provider()
    local_models = OllamaProvider.discover_models(
        base_url=o_cfg["base_url"],
        timeout=float(o_cfg["timeout"]),
    )
    is_online = OllamaProvider.is_online(
        base_url=o_cfg["base_url"],
        timeout=float(o_cfg["timeout"]),
    )

    return ModelsResponse(
        configured_provider=active_provider.name if active_provider else None,
        configured_model=active_provider.model if active_provider else (llm_cfg.get("model") or None),
        base_url=llm_cfg.get("base_url") or None,
        timeout=llm_cfg.get("timeout") or "60",
        has_api_key=bool(llm_cfg.get("api_key")),
        ollama_online=is_online,
        local_models=local_models,
    )


@router.post("/models/config", response_model=ModelsResponse)
def update_model_config(req: ModelConfigRequest) -> ModelsResponse:
    """Update LLM endpoint configuration at runtime and persist to .env."""
    from ..core.config import llm_settings, update_env_settings

    base_url = req.base_url.strip().rstrip("/")
    if base_url and not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Endpoint Base URL must start with http:// or https://",
        )

    updates: dict[str, str] = {
        "LLM_BASE_URL": base_url,
        "LLM_MODEL": req.model.strip(),
        "LLM_TIMEOUT": str(req.timeout or "60").strip(),
    }
    if req.api_key is not None:
        updates["LLM_API_KEY"] = req.api_key.strip()
    elif "LLM_API_KEY" not in updates:
        updates["LLM_API_KEY"] = llm_settings().get("api_key", "")

    update_env_settings(updates)
    return list_available_models()


@router.post("/models/test", response_model=ModelTestResponse)
def test_model_connection(req: ModelTestRequest) -> ModelTestResponse:
    """Test connectivity to an OpenAI-compatible LLM endpoint."""
    import time
    import httpx
    from ..core.config import llm_settings

    base_url = req.base_url.strip().rstrip("/")
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return ModelTestResponse(
            ok=False,
            latency_ms=0,
            detail="Endpoint Base URL must start with http:// or https://",
        )

    api_key = req.api_key.strip() or llm_settings().get("api_key", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    t0 = time.monotonic()
    models_url = f"{base_url}/models"
    logger.info("Testing LLM connection: GET %s (model=%s)", models_url, req.model.strip() or "<unset>")
    try:
        with httpx.Client(timeout=min(max(req.timeout, 1.0), 15.0)) as client:
            resp = client.get(models_url, headers=headers)
            latency_ms = int((time.monotonic() - t0) * 1000)

            if resp.status_code < 400:
                data = resp.json()
                models = [
                    m.get("id", "")
                    for m in (data.get("data") or [])
                    if isinstance(m, dict) and m.get("id")
                ]
                logger.info("LLM connection test succeeded: GET %s (%d ms, %d models)", models_url, latency_ms, len(models))
                if req.model.strip() and models and req.model.strip() not in models:
                    return ModelTestResponse(
                        ok=True,
                        latency_ms=latency_ms,
                        models=models,
                        detail=f"Connected ({latency_ms} ms). Note: '{req.model.strip()}' not in listed models ({len(models)} found).",
                    )
                return ModelTestResponse(
                    ok=True,
                    latency_ms=latency_ms,
                    models=models,
                    detail=f"Connected ({latency_ms} ms) · {len(models)} model(s) available",
                )

            # Unified routers may not expose /models (404/405/501) or may require /chat/completions
            logger.warning("GET %s returned HTTP %s; probing /chat/completions", models_url, resp.status_code)
            if req.model.strip():
                chat_url = f"{base_url}/chat/completions"
                t1 = time.monotonic()
                chat_resp = client.post(
                    chat_url,
                    headers=headers,
                    json={
                        "model": req.model.strip(),
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
                latency_ms = int((time.monotonic() - t1) * 1000)
                if chat_resp.status_code < 400:
                    logger.info("LLM chat probe succeeded: POST %s (%d ms)", chat_url, latency_ms)
                    return ModelTestResponse(
                        ok=True,
                        latency_ms=latency_ms,
                        detail=f"Connected via /chat/completions ({latency_ms} ms) · model '{req.model.strip()}' ready",
                    )
                logger.warning("POST %s returned HTTP %s: %s", chat_url, chat_resp.status_code, chat_resp.text[:200])
                return ModelTestResponse(
                    ok=False,
                    latency_ms=latency_ms,
                    detail=f"Endpoint reachable, but returned HTTP {chat_resp.status_code}"
                    + (" (check your API key)" if chat_resp.status_code in (401, 403) else ""),
                )

            return ModelTestResponse(
                ok=False,
                latency_ms=latency_ms,
                detail=f"Endpoint reachable, but GET /models returned HTTP {resp.status_code}. "
                + ("Enter a Model Name (and API key if required) to test /chat/completions."
                   if resp.status_code in (401, 403, 404, 405) else ""),
            )
    except Exception as ex:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.exception("LLM connection test error for %s: %s", models_url, ex)
        return ModelTestResponse(
            ok=False,
            latency_ms=latency_ms,
            detail=f"Connection failed: {ex}",
        )


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
