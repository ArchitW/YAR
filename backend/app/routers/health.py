"""Health and readiness probe router for Docker/Kubernetes container orchestration (TKT-006)."""

from datetime import datetime, timezone
from typing import Any
import redis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient

from ..core.config import QDRANT_URL, REDIS_URL
from ..core.database import get_db

router = APIRouter(prefix="/health", tags=["health"])


def check_database(db: Session) -> tuple[str, str | None]:
    try:
        db.execute(text("SELECT 1"))
        return "ok", None
    except Exception as ex:
        return "error", str(ex)


def check_redis() -> tuple[str, str | None]:
    try:
        client = redis.from_url(REDIS_URL, socket_timeout=2.0)
        if client.ping():
            return "ok", None
        return "error", "Ping returned False"
    except Exception as ex:
        return "error", str(ex)


def check_qdrant() -> tuple[str, str | None]:
    try:
        client = QdrantClient(url=QDRANT_URL, timeout=2.0)
        client.get_collections()
        return "ok", None
    except Exception as ex:
        return "error", str(ex)


@router.get("")
def health_check(response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Comprehensive health check probing PostgreSQL/SQLite, Redis, and Qdrant."""
    db_status, db_err = check_database(db)
    redis_status, redis_err = check_redis()
    qdrant_status, qdrant_err = check_qdrant()

    services = {
        "database": db_status if not db_err else f"error: {db_err}",
        "redis": redis_status if not redis_err else f"error: {redis_err}",
        "qdrant": qdrant_status if not qdrant_err else f"error: {qdrant_err}",
    }

    if db_status == "ok" and redis_status == "ok" and qdrant_status == "ok":
        overall = "ok"
    elif db_status == "ok":
        overall = "degraded"
    else:
        overall = "error"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": overall,
        "services": services,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/live")
def liveness_probe() -> dict[str, str]:
    """Basic liveness probe checking if the HTTP server is responsive."""
    return {"status": "ok"}
