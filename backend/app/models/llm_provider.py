"""LLMProvider SQLAlchemy model — multiple configurable LLM endpoints.

A user can register several OpenAI-compatible endpoints (local Ollama, OpenRouter,
OpenAI, etc.) and switch the active one at runtime. Secrets (api_key) are stored
locally in the app database and never returned in full by the API.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Column, Integer, String, DateTime

from ..core.database import Base


class LLMProvider(Base):
    """A configured LLM endpoint the user can activate, edit, disable, or delete."""

    __tablename__ = "llm_providers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    base_url = Column(String(512), nullable=False)
    model = Column(String(256), nullable=False)
    api_key = Column(String(512), default="", nullable=False)
    timeout = Column(String(16), default="60", nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the API. The api_key is never exposed — only a has_api_key flag."""
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "enabled": bool(self.enabled),
            "is_active": bool(self.is_active),
            "has_api_key": bool(self.api_key),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }