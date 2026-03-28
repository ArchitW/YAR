from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from jose import jwt
from datetime import datetime, timedelta
from ..core.database import get_db
from ..models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
SECRET = "dev-secret-change-me"
ALGO = "HS256"

class AuthReq(BaseModel):
    email: str
    password: str

