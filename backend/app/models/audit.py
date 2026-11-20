"""AuditLog SQLAlchemy model for operational logging and compliance (TKT-012)."""

from datetime import datetime, timezone
from typing import Any
from sqlalchemy import Column, Integer, String, DateTime, JSON, func
from ..core.database import Base


class AuditLog(Base):
    """Audit log entry capturing system actions, actor identities, and trace context."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    trace_id = Column(String(64), index=True, nullable=False)
    user_id = Column(Integer, nullable=True)
    workspace_id = Column(Integer, index=True, nullable=True)
    event_type = Column(String(64), index=True, nullable=False)
    status = Column(String(32), default="success", nullable=False)
    summary = Column(String(512), nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "event_type": self.event_type,
            "status": self.status,
            "summary": self.summary,
            "metadata": self.metadata_json or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
