"""Universal Node-and-Edge Relational Graph for Cognitive Memory & Dreaming."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from ..core.database import Base


class MemoryNode(Base):
    """Universal node representing an episodic memory, entity, preference, concept, or dream insight."""

    __tablename__ = "memory_nodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Node taxonomy: 'episodic_memory', 'entity', 'user_preference', 'concept', 'dream_insight'
    node_type = Column(String(32), index=True, nullable=False)
    name = Column(String(256), index=True, nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(String(512), nullable=True)

    # Salience & Confidence scoring
    importance_score = Column(Float, default=0.5, nullable=False)  # 0.1 to 1.0
    confidence = Column(Float, default=1.0, nullable=False)        # 0.0 to 1.0

    # Flexible key-value attributes (e.g. {"attribute_key": "coding_style", "attribute_value": "concise"})
    properties = Column(JSON, default=dict)

    # Access frequency and decay tracking
    access_count = Column(Integer, default=1, nullable=False)
    last_accessed_at = Column(DateTime, server_default=func.now(), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    invalidated_at = Column(DateTime, nullable=True)  # Soft invalidation / temporal superseding

    # Outgoing and incoming directed edges
    out_edges = relationship(
        "MemoryEdge",
        foreign_keys="MemoryEdge.source_id",
        backref="source_node",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    in_edges = relationship(
        "MemoryEdge",
        foreign_keys="MemoryEdge.target_id",
        backref="target_node",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "node_type": self.node_type,
            "name": self.name,
            "content": self.content,
            "summary": self.summary,
            "importance_score": self.importance_score,
            "confidence": self.confidence,
            "properties": self.properties or {},
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "invalidated_at": self.invalidated_at.isoformat() if self.invalidated_at else None,
        }


class MemoryEdge(Base):
    """Universal directed edge representing relationships, contradictions, preferences, or syntheses."""

    __tablename__ = "memory_edges"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True, nullable=False)
    source_id = Column(String(36), ForeignKey("memory_nodes.id", ondelete="CASCADE"), index=True, nullable=False)
    target_id = Column(String(36), ForeignKey("memory_nodes.id", ondelete="CASCADE"), index=True, nullable=False)

    # Edge taxonomy: 'prefers', 'supersedes', 'contradicts', 'depends_on', 'synthesizes', 'extracted_from', 'relates_to'
    relation_type = Column(String(64), index=True, nullable=False)
    weight = Column(Float, default=1.0, nullable=False)  # 0.0 to 1.0
    properties = Column(JSON, default=dict)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    invalidated_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "weight": self.weight,
            "properties": self.properties or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "invalidated_at": self.invalidated_at.isoformat() if self.invalidated_at else None,
        }
