"""Audit logs REST API router (TKT-012)."""

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..models.audit import AuditLog
from ..services.audit import AuditService

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trace_id: str
    user_id: int | None = None
    workspace_id: int | None = None
    event_type: str
    status: str
    summary: str
    metadata: dict[str, Any] = {}
    created_at: str | None = None


class AuditLogListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


@router.get("", response_model=AuditLogListResponse)
def list_audit_logs(
    workspace_id: int | None = Query(None),
    event_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    """Retrieve paginated audit logs with optional filtering by workspace, event type, or status."""
    items, total = AuditService.get_logs(
        db=db,
        workspace_id=workspace_id,
        event_type=event_type,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return AuditLogListResponse(
        items=[item.to_dict() for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{log_id}", response_model=AuditLogResponse)
def get_audit_log(
    log_id: int,
    db: Session = Depends(get_db),
) -> AuditLogResponse:
    """Retrieve details for a single audit log entry."""
    entry = db.get(AuditLog, log_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit log entry {log_id} not found",
        )
    return AuditLogResponse(**entry.to_dict())


@router.post("/prune")
def prune_audit_logs(
    retention_days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger retention cleanup for audit logs older than retention_days."""
    pruned = AuditService.prune_retention(db=db, retention_days=retention_days)
    return {"pruned_count": pruned, "retention_days": retention_days}
