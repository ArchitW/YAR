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

@router.post("/register")
def register(req: AuthReq, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="email exists")
    u = User(email=req.email, role="user")
    u.set_password(req.password)
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"id": u.id, "email": u.email, "role": u.role}

@router.post("/login")
def login(req: AuthReq, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.email == req.email).first()
    if not u or not u.verify_password(req.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = jwt.encode({"sub": u.email, "exp": datetime.utcnow() + timedelta(hours=24)}, SECRET, algorithm=ALGO)
    return {"access_token": token, "token_type": "bearer"}
