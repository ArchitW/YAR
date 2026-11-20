"""Connector SQLAlchemy model for external data source connections (TKT-012)."""

from datetime import datetime, timezone
from typing import Any
from sqlalchemy import Column, Integer, String, DateTime, JSON
from ..core.database import Base


class Connector(Base):
    """External source connector (e.g., local filesystem folder, cloud sources)."""

    __tablename__ = "connectors"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    workspace_id = Column(Integer, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    type = Column(String(64), default="filesystem", nullable=False)
    config_json = Column(JSON, default=dict, nullable=False)
    status = Column(String(32), default="active", nullable=False)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "type": self.type,
            "config": self.config_json or {},
            "status": self.status,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
