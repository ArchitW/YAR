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
