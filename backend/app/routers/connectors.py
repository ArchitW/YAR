"""Connectors REST API router (TKT-012)."""

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.middleware import get_request_trace_id
from ..models.connector import Connector
from ..services.connectors.filesystem import FilesystemConnectorService
from ..services.connectors.searxng import SearXNGConnectorService

router = APIRouter(prefix="/connectors", tags=["connectors"])


class ConnectorCreateRequest(BaseModel):
    workspace_id: int
    name: str = Field(min_length=1, max_length=128)
    type: str = "filesystem"
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    name: str
    type: str
    config: dict[str, Any]
    status: str
    last_sync_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@router.get("", response_model=list[ConnectorResponse])
def list_connectors(
    workspace_id: int = Query(...),
    db: Session = Depends(get_db),
) -> list[ConnectorResponse]:
    """List all configured connectors for a workspace."""
    connectors = db.query(Connector).filter(Connector.workspace_id == workspace_id).all()
    return [ConnectorResponse(**c.to_dict()) for c in connectors]


@router.post("", response_model=ConnectorResponse)
def create_connector(
    req: ConnectorCreateRequest,
    db: Session = Depends(get_db),
) -> ConnectorResponse:
    """Register a new external connector."""
    conn = Connector(
        workspace_id=req.workspace_id,
        name=req.name,
        type=req.type,
        config_json=req.config,
        status="active",
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return ConnectorResponse(**conn.to_dict())


@router.post("/{connector_id}/sync")
def sync_connector(
    connector_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Trigger synchronization for a connector."""
    trace_id = get_request_trace_id(request)
    conn = db.get(Connector, connector_id)
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )

    if conn.type == "filesystem":
        return FilesystemConnectorService.sync_connector(db, conn, trace_id=trace_id)
    elif conn.type == "searxng":
        return SearXNGConnectorService.sync_connector(db, conn, trace_id=trace_id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connector type '{conn.type}' is not currently supported for sync",
        )


@router.delete("/{connector_id}")
def delete_connector(
    connector_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a connector configuration."""
    conn = db.get(Connector, connector_id)
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )
    db.delete(conn)
    db.commit()
    return {"deleted": True, "id": connector_id}
