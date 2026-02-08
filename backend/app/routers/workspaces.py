from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..models.user import Workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

@router.get("")
def list_workspaces(db: Session = Depends(get_db)):
    return db.query(Workspace).all()

@router.post("")
def create_workspace(name: str, description: str = "", db: Session = Depends(get_db)):
    ws = Workspace(name=name, description=description)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws

@router.get("/{ws_id}")
def get_workspace(ws_id: int, db: Session = Depends(get_db)):
    ws = db.query(Workspace).filter(Workspace.id == ws_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="not found")
    return ws

@router.patch("/{ws_id}")
