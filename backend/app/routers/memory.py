"""Memory and Dreaming REST API: Living Dossier, Right-to-Forget, and Transparency Controls."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..core.database import get_db
from ..models.memory import MemoryEdge, MemoryNode
from ..services.dreaming.nrem import NREMConsolidator
from ..services.dreaming.rem import REMDreamer
from ..services.memory import MemoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class MemoryNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: int
    user_id: int | None = None
    node_type: str
    name: str
    content: str
    summary: str | None = None
    importance_score: float
    confidence: float
    properties: dict[str, Any] = Field(default_factory=dict)
    access_count: int
    last_accessed_at: str | None = None
    created_at: str | None = None
    invalidated_at: str | None = None


class MemoryListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class EntityPatchRequest(BaseModel):
    name: str | None = None
    content: str | None = None
    properties: dict[str, Any] | None = None
    importance_score: float | None = None


class DreamTriggerRequest(BaseModel):
    workspace_id: int
    run_nrem: bool = True
    run_rem: bool = True
    max_dreams: int = 3
    prune_threshold_hours: float = 48.0


class DreamStatusResponse(BaseModel):
    workspace_id: int
    total_memories: int
    active_nodes: int
    invalidated_nodes: int
    counts_by_type: dict[str, int]
    total_edges: int


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=MemoryListResponse)
def list_memories(
    workspace_id: int = Query(...),
    node_type: str | None = Query(None),
    include_invalidated: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> MemoryListResponse:
    """List paginated memory nodes for a workspace with type filtering."""
    filters = [MemoryNode.workspace_id == workspace_id]
    if not include_invalidated:
        filters.append(MemoryNode.invalidated_at.is_(None))
    if node_type:
        filters.append(MemoryNode.node_type == node_type)

    total = db.scalar(select(func.count(MemoryNode.id)).where(and_(*filters))) or 0
    stmt = (
        select(MemoryNode)
        .where(and_(*filters))
        .order_by(MemoryNode.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    nodes = db.scalars(stmt).all()
    return MemoryListResponse(
        items=[node.to_dict() for node in nodes],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/entities")
def get_entities_dossier(
    workspace_id: int = Query(...),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve active Living Dossier entities, preferences, and concepts."""
    return MemoryService.get_active_dossier(db, workspace_id)


@router.patch("/entities/{node_id}")
def update_entity(
    node_id: str,
    patch: EntityPatchRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manually update entity attributes, content, or importance in the Living Dossier."""
    node = db.get(MemoryNode, node_id)
    if not node or node.invalidated_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active entity not found")

    if patch.name is not None:
        node.name = patch.name
    if patch.content is not None:
        node.content = patch.content
    if patch.importance_score is not None:
        node.importance_score = max(0.1, min(1.0, patch.importance_score))
    if patch.properties is not None:
        props = dict(node.properties or {})
        props.update(patch.properties)
        node.properties = props
        flag_modified(node, "properties")

    node.last_accessed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(node)
    return node.to_dict()


@router.delete("/{node_id}")
def delete_memory(
    node_id: str,
    hard_delete: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Right-to-Forget: invalidate or permanently purge memory and remove vectors."""
    node = db.get(MemoryNode, node_id)
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    _sync_qdrant_deletion(node)

    if hard_delete:
        db.delete(node)
    else:
        MemoryService.invalidate_node(db, node_id, reason="user_right_to_forget")

    db.commit()
    return {"deleted": True, "node_id": node_id, "hard_delete": hard_delete}


def _sync_qdrant_deletion(node: MemoryNode) -> None:
    """Best-effort cleanup of matching Qdrant points when deleting memory."""
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        from .documents import COLLECTION, qdrant

        qdrant.delete(
            COLLECTION,
            points_selector=Filter(
                must=[FieldCondition(key="dream_insight_id", match=MatchValue(value=node.id))]
            ),
        )
    except Exception:
        logger.warning("Could not sync Qdrant deletion for node %s", node.id, exc_info=True)


@router.post("/dream")
def trigger_dream_cycle(
    req: DreamTriggerRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Trigger an on-demand dream consolidation cycle (NREM pruning + REM dreaming)."""
    nrem_stats: dict[str, Any] = {}
    rem_stats: dict[str, Any] = {}

    if req.run_nrem:
        nrem_stats = NREMConsolidator.consolidate(
            db, req.workspace_id, threshold_hours=req.prune_threshold_hours
        )

    if req.run_rem:
        rem_stats = REMDreamer.run_dream_cycle(
            db, req.workspace_id, max_dreams=req.max_dreams
        )

    db.commit()
    return {
        "workspace_id": req.workspace_id,
        "nrem": nrem_stats,
        "rem": rem_stats,
    }


@router.get("/dream/status", response_model=DreamStatusResponse)
def get_dream_status(
    workspace_id: int = Query(...),
    db: Session = Depends(get_db),
) -> DreamStatusResponse:
    """Report memory health metrics, active nodes by type, and pruned counts."""
    total = db.scalar(select(func.count(MemoryNode.id)).where(MemoryNode.workspace_id == workspace_id)) or 0
    active = db.scalar(
        select(func.count(MemoryNode.id)).where(
            and_(MemoryNode.workspace_id == workspace_id, MemoryNode.invalidated_at.is_(None))
        )
    ) or 0
    invalidated = total - active

    type_counts = db.execute(
        select(MemoryNode.node_type, func.count(MemoryNode.id))
        .where(and_(MemoryNode.workspace_id == workspace_id, MemoryNode.invalidated_at.is_(None)))
        .group_by(MemoryNode.node_type)
    ).all()
    counts_map = {node_type: count for node_type, count in type_counts}

    total_edges = db.scalar(
        select(func.count(MemoryEdge.id)).where(MemoryEdge.workspace_id == workspace_id)
    ) or 0

    return DreamStatusResponse(
        workspace_id=workspace_id,
        total_memories=total,
        active_nodes=active,
        invalidated_nodes=invalidated,
        counts_by_type=counts_map,
        total_edges=total_edges,
    )
