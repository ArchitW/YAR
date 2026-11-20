from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..core.config import auth_enabled, jwt_secret
from ..core.database import get_db
from ..core.middleware import get_request_trace_id
from ..models.user import User
from ..services.audit import AuditService

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)
ALGO = "HS256"


class AuthReq(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class StatusResponse(BaseModel):
    auth_enabled: bool


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user. If auth is disabled, returns a default admin user."""
    if not auth_enabled():
        # In disabled auth mode, provide a mock admin user
        mock = db.query(User).filter(User.email == "local@yar.internal").first()
        if not mock:
            mock = User(id=1, email="local@yar.internal", role="admin")
        return mock

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[ALGO])
        email: str = payload.get("sub")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid token payload",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that requires the current user to have admin privileges."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin privileges required",
        )
    return current_user


@router.get("/status", response_model=StatusResponse)
def get_auth_status() -> StatusResponse:
    """Check if authentication is required."""
    return StatusResponse(auth_enabled=auth_enabled())


@router.post("/register", response_model=UserResponse)
def register(req: AuthReq, db: Session = Depends(get_db)) -> UserResponse:
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="email exists")

    # First user registered in the system is automatically granted admin role
    is_first_user = db.query(User).count() == 0
    role = "admin" if is_first_user else "user"

    u = User(email=req.email, role=role)
    u.set_password(req.password)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@router.post("/login", response_model=LoginResponse)
def login(
    req: AuthReq,
    request: Request = None,
    db: Session = Depends(get_db),
) -> LoginResponse:
    trace_id = get_request_trace_id(request)
    u = db.query(User).filter(User.email == req.email).first()
    if not u or not u.verify_password(req.password):
        AuditService.record(
            db=db,
            event_type="auth.login",
            summary=f"Failed login attempt for '{req.email}'",
            status="failure",
            trace_id=trace_id,
            metadata={"email": req.email},
        )
        raise HTTPException(status_code=401, detail="invalid credentials")

    token = jwt.encode(
        {"sub": u.email, "role": u.role, "exp": datetime.now(timezone.utc) + timedelta(hours=24)},
        jwt_secret(),
        algorithm=ALGO,
    )

    AuditService.record(
        db=db,
        event_type="auth.login",
        summary=f"User '{u.email}' logged in successfully",
        status="success",
        user_id=u.id,
        trace_id=trace_id,
        metadata={"email": u.email, "role": u.role},
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(id=u.id, email=u.email, role=u.role),
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the currently authenticated user profile."""
    return UserResponse(id=current_user.id, email=current_user.email, role=current_user.role)


@router.post("/logout")
def logout(
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Logout session confirmation."""
    trace_id = get_request_trace_id(request)
    AuditService.record(
        db=db,
        event_type="auth.logout",
        summary=f"User '{current_user.email}' logged out",
        status="success",
        user_id=current_user.id,
        trace_id=trace_id,
    )
    return {"message": "successfully logged out"}
