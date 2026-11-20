"""AuditService for structured operational logging, querying, and retention pruning (TKT-012)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy import and_, func, select, delete
from sqlalchemy.orm import Session
from ..models.audit import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    """Service handling audit event logging, querying, and retention cleanup."""

    @staticmethod
    def record(
        db: Session,
        event_type: str,
        summary: str,
        status: str = "success",
        trace_id: str | None = None,
        workspace_id: int | None = None,
        user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog | None:
        """Record an audit log entry.

        Safely catches exceptions so logging issues never break core business logic.
        """
        try:
            entry = AuditLog(
                trace_id=trace_id or str(uuid.uuid4()),
                user_id=user_id,
                workspace_id=workspace_id,
                event_type=event_type,
                status=status,
                summary=summary[:512],
                metadata_json=metadata or {},
                created_at=datetime.now(timezone.utc),
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            return entry
        except Exception:
            logger.warning("Failed to persist audit log entry for event '%s'", event_type, exc_info=True)
            try:
                db.rollback()
            except Exception:
                pass
            return None

    @staticmethod
    def get_logs(
        db: Session,
        workspace_id: int | None = None,
        event_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Fetch paginated audit logs with optional filtering."""
        filters = []
        if workspace_id is not None:
            filters.append(AuditLog.workspace_id == workspace_id)
        if event_type:
            filters.append(AuditLog.event_type == event_type)
        if status:
            filters.append(AuditLog.status == status)

        where_clause = and_(*filters) if filters else True

        total = db.scalar(select(func.count(AuditLog.id)).where(where_clause)) or 0
        stmt = (
            select(AuditLog)
            .where(where_clause)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list(db.scalars(stmt).all())
        return items, total

    @staticmethod
    def prune_retention(db: Session, retention_days: int = 7) -> int:
        """Purge audit logs older than the retention window (default 7 days)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        stmt = delete(AuditLog).where(AuditLog.created_at < cutoff)
        result = db.execute(stmt)
        db.commit()
        pruned_count = result.rowcount or 0
        logger.info("Pruned %d audit log entries older than %d days", pruned_count, retention_days)
        return pruned_count
