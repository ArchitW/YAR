"""Unified application settings REST API router."""

from __future__ import annotations

import logging
import os
import secrets
import shutil
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import Base, engine, get_db
from ..models.llm_provider import LLMProvider

from ..core.config import (
    DATABASE_URL,
    QDRANT_PATH,
    QDRANT_URL,
    UPLOAD_DIR,
    auth_enabled,
    detect_torch_device,
    embedding_settings,
    hf_offline_settings,
    async_ingest_settings,
    llm_settings,
    ollama_settings,
    query_rewriter_settings,
    reranker_settings,
    router_settings,
    searxng_settings,
    update_env_settings,
)

router = APIRouter(prefix="/settings", tags=["settings"])

logger = logging.getLogger(__name__)

_reindex_job: dict[str, Any] = {"running": False, "done": 0, "total": 0}


class SettingsResponse(BaseModel):
    # Models & Providers
    llm_base_url: str
    llm_model: str
    llm_timeout: str
    has_api_key: bool
    ollama_base_url: str
    ollama_autodiscover: bool
    ollama_timeout: float
    embedding_model: str
    reranker_model: str
    rerank_enabled: bool
    rerank_top_k: int
    query_rewrite_enabled: bool
    hf_offline: bool
    async_ingest: bool
    router_enabled: bool
    router_base_url: str
    router_model: str
    router_timeout: float
    # Retrieval & Web Search
    hyde_enabled: bool
    web_search_enabled: bool
    web_search_confidence_threshold: float
    searxng_base_url: str
    # Security
    auth_enabled: bool
    has_jwt_secret: bool
    # System & Storage
    compute_device: str
    gpu_name: str | None = None
    database_type: str
    qdrant_mode: str
    qdrant_location: str
    upload_dir: str
    upload_file_count: int
    upload_total_bytes: int


class SettingsPatchRequest(BaseModel):
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_timeout: str | None = None
    ollama_base_url: str | None = None
    ollama_autodiscover: bool | None = None
    ollama_timeout: float | None = None
    embedding_model: str | None = None
    reranker_model: str | None = None
    rerank_enabled: bool | None = None
    rerank_top_k: int | None = None
    hf_offline: bool | None = None
    async_ingest: bool | None = None
    router_enabled: bool | None = None
    router_base_url: str | None = None
    router_model: str | None = None
    router_timeout: float | None = None
    query_rewrite_enabled: bool | None = None
    hyde_enabled: bool | None = None
    web_search_enabled: bool | None = None
    web_search_confidence_threshold: float | None = None
    searxng_base_url: str | None = None
    auth_enabled: bool | None = None
    jwt_secret: str | None = None
    generate_jwt_secret: bool = False


def _gpu_name() -> str | None:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
    except Exception:
        pass
    return None


def _upload_stats() -> tuple[int, int]:
    if not os.path.isdir(UPLOAD_DIR):
        return 0, 0
    count = 0
    total = 0
    try:
        for entry in os.scandir(UPLOAD_DIR):
            if entry.is_file():
                count += 1
                total += entry.stat().st_size
    except OSError:
        pass
    return count, total


def _build_settings_response() -> SettingsResponse:
    llm = llm_settings()
    ollama = ollama_settings()
    qr = query_rewriter_settings()
    sx = searxng_settings()
    emb = embedding_settings()
    rr = reranker_settings()
    router = router_settings()
    file_count, total_bytes = _upload_stats()
    db_type = "sqlite" if DATABASE_URL.startswith("sqlite") else "postgresql"
    qdrant_mode = "local" if QDRANT_PATH else "server"
    qdrant_location = QDRANT_PATH if QDRANT_PATH else QDRANT_URL

    return SettingsResponse(
        llm_base_url=llm["base_url"],
        llm_model=llm["model"],
        llm_timeout=llm["timeout"] or "60",
        has_api_key=bool(llm["api_key"]),
        ollama_base_url=ollama["base_url"],
        ollama_autodiscover=bool(ollama["autodiscover"]),
        ollama_timeout=float(ollama["timeout"]),
        embedding_model=emb["model"],
        reranker_model=rr["model"],
        rerank_enabled=bool(rr["enabled"]),
        rerank_top_k=int(rr["top_k"]),
        query_rewrite_enabled=bool(qr["rewrite_enabled"]),
        hf_offline=bool(hf_offline_settings()["enabled"]),
        async_ingest=bool(async_ingest_settings()["enabled"]),
        router_enabled=bool(router["enabled"]),
        router_base_url=router["base_url"],
        router_model=router["model"],
        router_timeout=float(router["timeout"]),
        hyde_enabled=bool(qr["hyde_enabled"]),
        web_search_enabled=bool(sx["enabled"]),
        web_search_confidence_threshold=float(sx["confidence_threshold"]),
        searxng_base_url=sx["base_url"],
        auth_enabled=auth_enabled(),
        has_jwt_secret=bool(os.getenv("JWT_SECRET", "").strip()),
        compute_device=detect_torch_device(),
        gpu_name=_gpu_name(),
        database_type=db_type,
        qdrant_mode=qdrant_mode,
        qdrant_location=qdrant_location,
        upload_dir=UPLOAD_DIR,
        upload_file_count=file_count,
        upload_total_bytes=total_bytes,
    )


def _validate_http_url(value: str, field_name: str) -> str:
    cleaned = value.strip().rstrip("/")
    if cleaned and not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must start with http:// or https://",
        )
    return cleaned


@router.get("", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    """Return current non-secret runtime settings and system diagnostics."""
    return _build_settings_response()


@router.patch("", response_model=SettingsResponse)
def update_settings(req: SettingsPatchRequest) -> SettingsResponse:
    """Update runtime settings and persist changes to backend/.env."""
    updates: dict[str, str] = {}

    if req.llm_base_url is not None:
        updates["LLM_BASE_URL"] = _validate_http_url(req.llm_base_url, "LLM Base URL")
    if req.llm_model is not None:
        updates["LLM_MODEL"] = req.llm_model.strip()
    if req.llm_api_key is not None and req.llm_api_key.strip() != "":
        updates["LLM_API_KEY"] = req.llm_api_key.strip()
    if req.llm_timeout is not None:
        updates["LLM_TIMEOUT"] = str(req.llm_timeout).strip() or "60"

    if req.ollama_base_url is not None:
        updates["OLLAMA_BASE_URL"] = _validate_http_url(req.ollama_base_url, "Ollama Base URL")
    if req.ollama_autodiscover is not None:
        updates["OLLAMA_AUTODISCOVER"] = "true" if req.ollama_autodiscover else "false"
    if req.ollama_timeout is not None:
        updates["OLLAMA_TIMEOUT"] = str(max(0.5, min(req.ollama_timeout, 30.0)))

    embedding_changed = False
    if req.embedding_model is not None:
        new_emb = req.embedding_model.strip()
        if new_emb and new_emb != embedding_settings()["model"]:
            updates["EMBEDDING_MODEL"] = new_emb
            embedding_changed = True
    if req.reranker_model is not None:
        new_rr = req.reranker_model.strip()
        if new_rr and new_rr != reranker_settings()["model"]:
            updates["RERANKER_MODEL"] = new_rr
    if req.rerank_enabled is not None:
        updates["RERANK_ENABLED"] = "true" if req.rerank_enabled else "false"
    if req.rerank_top_k is not None:
        updates["RERANK_TOP_K"] = str(max(1, int(req.rerank_top_k)))
    if req.hf_offline is not None:
        updates["HF_OFFLINE"] = "true" if req.hf_offline else "false"
    if req.async_ingest is not None:
        updates["ASYNC_INGEST_ENABLED"] = "true" if req.async_ingest else "false"
    if req.router_enabled is not None:
        updates["DECISION_ROUTER_ENABLED"] = "true" if req.router_enabled else "false"
    if req.router_base_url is not None:
        updates["DECISION_ROUTER_BASE_URL"] = _validate_http_url(req.router_base_url, "Decision Router Base URL")
    if req.router_model is not None and req.router_model.strip():
        updates["DECISION_ROUTER_MODEL"] = req.router_model.strip()
    if req.router_timeout is not None:
        updates["DECISION_ROUTER_TIMEOUT"] = str(max(0.5, min(req.router_timeout, 60.0)))

    if req.query_rewrite_enabled is not None:
        updates["QUERY_REWRITE_ENABLED"] = "true" if req.query_rewrite_enabled else "false"
    if req.hyde_enabled is not None:
        updates["HYDE_ENABLED"] = "true" if req.hyde_enabled else "false"
    if req.web_search_enabled is not None:
        updates["WEB_SEARCH_ENABLED"] = "true" if req.web_search_enabled else "false"
    if req.web_search_confidence_threshold is not None:
        clamped = max(0.0, min(1.0, float(req.web_search_confidence_threshold)))
        updates["WEB_SEARCH_CONFIDENCE_THRESHOLD"] = f"{clamped:.2f}"
    if req.searxng_base_url is not None:
        updates["SEARXNG_BASE_URL"] = _validate_http_url(req.searxng_base_url, "SearXNG Base URL")

    if req.generate_jwt_secret:
        updates["JWT_SECRET"] = secrets.token_urlsafe(32)
    elif req.jwt_secret is not None and req.jwt_secret.strip() != "":
        updates["JWT_SECRET"] = req.jwt_secret.strip()

    if req.auth_enabled is not None:
        effective_secret = updates.get("JWT_SECRET") or os.getenv("JWT_SECRET", "").strip()
        if req.auth_enabled and not effective_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JWT_SECRET must be configured before enabling AUTH_ENABLED.",
            )
        updates["AUTH_ENABLED"] = "true" if req.auth_enabled else "false"

    if updates:
        update_env_settings(updates)

    if req.hf_offline is False:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)

    if embedding_changed:
        _rebuild_for_embedding_change()

    return _build_settings_response()


def _rebuild_for_embedding_change() -> None:
    """Reset the embedding model, recreate the Qdrant collection, and mark docs for reindex."""
    from ..core.database import SessionLocal
    from ..models.document import Document
    from ..services import embeddings as _embeddings

    _embeddings._model = None
    _embeddings._model_name = None

    try:
        from ..core.config import reset_qdrant_client
        from ..routers import documents as _documents

        client = reset_qdrant_client()
        try:
            _documents.ensure_collection(client)
        except Exception:
            logger.warning("Failed to recreate collection after embedding change", exc_info=True)
        import sys

        _documents.qdrant = client
        for modname in ("app.services.retrieval", "app.services.dreaming.rem"):
            module = sys.modules.get(modname)
            if module is not None and hasattr(module, "qdrant"):
                setattr(module, "qdrant", client)
    except Exception:
        logger.warning("Qdrant rebuild after embedding change failed", exc_info=True)

    db = SessionLocal()
    try:
        db.query(Document).update({Document.status: "queued"})
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Multiple LLM endpoints (register / edit / enable / delete / activate)
# ---------------------------------------------------------------------------


class LLMEndpointCreate(BaseModel):
    name: str
    base_url: str
    model: str
    api_key: str | None = None
    timeout: str = "60"
    enabled: bool = True


class LLMEndpointUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout: str | None = None
    enabled: bool | None = None


def _require_endpoint(db: Session, endpoint_id: int) -> LLMProvider:
    ep = db.get(LLMProvider, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM endpoint not found")
    return ep


@router.get("/llm-endpoints")
def list_llm_endpoints(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return all configured LLM endpoints (api keys masked)."""
    rows = db.query(LLMProvider).order_by(LLMProvider.id.asc()).all()
    return [r.to_dict() for r in rows]


@router.post("/llm-endpoints", status_code=status.HTTP_201_CREATED)
def create_llm_endpoint(req: LLMEndpointCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Register a new LLM endpoint. The first endpoint created becomes active."""
    base_url = _validate_http_url(req.base_url, "LLM Base URL")
    if not req.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")
    if not req.model.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="model is required")

    is_first = db.query(LLMProvider).count() == 0
    ep = LLMProvider(
        name=req.name.strip(),
        base_url=base_url,
        model=req.model.strip(),
        api_key=(req.api_key or "").strip(),
        timeout=str(req.timeout or "60").strip() or "60",
        enabled=req.enabled,
        is_active=is_first,
    )
    db.add(ep)
    db.commit()
    db.refresh(ep)
    return ep.to_dict()


@router.patch("/llm-endpoints/{endpoint_id}")
def update_llm_endpoint(endpoint_id: int, req: LLMEndpointUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Edit an existing endpoint. A blank api_key keeps the stored key."""
    ep = _require_endpoint(db, endpoint_id)

    if req.name is not None:
        if not req.name.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name cannot be empty")
        ep.name = req.name.strip()
    if req.base_url is not None:
        ep.base_url = _validate_http_url(req.base_url, "LLM Base URL")
    if req.model is not None:
        if not req.model.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="model cannot be empty")
        ep.model = req.model.strip()
    if req.api_key is not None and req.api_key.strip() != "":
        ep.api_key = req.api_key.strip()
    if req.timeout is not None:
        ep.timeout = str(req.timeout).strip() or "60"
    if req.enabled is not None:
        ep.enabled = req.enabled
        if not ep.enabled and ep.is_active:
            # Disabling the active endpoint clears the active pointer.
            ep.is_active = False

    db.commit()
    db.refresh(ep)
    return ep.to_dict()


@router.delete("/llm-endpoints/{endpoint_id}")
def delete_llm_endpoint(endpoint_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Delete an endpoint. If it was active, the next enabled endpoint is promoted."""
    ep = _require_endpoint(db, endpoint_id)
    was_active = bool(ep.is_active)
    db.delete(ep)
    db.commit()

    if was_active:
        nxt = (
            db.query(LLMProvider)
            .filter(LLMProvider.enabled.is_(True))
            .order_by(LLMProvider.id.asc())
            .first()
        )
        if nxt is not None:
            nxt.is_active = True
            db.commit()

    rows = db.query(LLMProvider).order_by(LLMProvider.id.asc()).all()
    return {"deleted": endpoint_id, "endpoints": [r.to_dict() for r in rows]}


@router.post("/llm-endpoints/{endpoint_id}/activate")
def activate_llm_endpoint(endpoint_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Mark this endpoint as the active one used by the chat provider."""
    ep = _require_endpoint(db, endpoint_id)
    if not ep.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enable the endpoint before activating it")
    db.query(LLMProvider).filter(LLMProvider.id != endpoint_id).update({LLMProvider.is_active: False})
    ep.is_active = True
    db.commit()
    db.refresh(ep)
    return ep.to_dict()


@router.post("/reset")
def reset_everything() -> dict[str, Any]:
    """Wipe all data: drop/recreate DB tables, purge Qdrant vectors, clear uploads.

    Destructive and irreversible. The app recreates an empty schema immediately so
    it stays usable; the user must re-add LLM endpoints and re-upload documents.
    """
    # 1. Rebuild the relational schema from scratch.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # 2. Recreate an empty Qdrant collection (refresh cached client refs).
    from ..core.config import reset_qdrant_client

    client = reset_qdrant_client()
    try:
        import sys

        from ..routers import documents as _documents

        try:
            client.delete_collection(_documents.COLLECTION)
        except Exception:
            pass
        _documents.ensure_collection(client)
        _documents.qdrant = client
        for modname in ("app.services.retrieval", "app.services.dreaming.rem"):
            module = sys.modules.get(modname)
            if module is not None and hasattr(module, "qdrant"):
                setattr(module, "qdrant", client)
    except Exception:
        logger.warning("Qdrant reset failed", exc_info=True)

    # 3. Clear uploaded files.
    if os.path.isdir(UPLOAD_DIR):
        for entry in os.scandir(UPLOAD_DIR):
            try:
                if entry.is_dir():
                    shutil.rmtree(entry.path, ignore_errors=True)
                else:
                    os.remove(entry.path)
            except OSError:
                pass

    return {"reset": True}


def _reindex_all_background() -> None:
    from ..core.database import SessionLocal
    from ..models.document import Document
    from ..routers.documents import reindex_document

    db = SessionLocal()
    try:
        docs = db.query(Document).all()
        _reindex_job.update(running=True, done=0, total=len(docs))
        for doc in docs:
            try:
                reindex_document(db, doc)
            except Exception:
                logger.warning("Reindex failed for document %s", doc.id, exc_info=True)
            _reindex_job["done"] += 1
    except Exception:
        logger.exception("Reindex-all failed")
    finally:
        _reindex_job["running"] = False
        db.close()


@router.post("/reindex-all")
def reindex_all(background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Reindex every document in the background (e.g. after an embedding change)."""
    if _reindex_job["running"]:
        return {"status": "running", "done": _reindex_job["done"], "total": _reindex_job["total"]}
    background_tasks.add_task(_reindex_all_background)
    return {"status": "queued"}


@router.get("/reindex-status")
def reindex_status() -> dict[str, Any]:
    """Progress of the background reindex-all job."""
    return dict(_reindex_job)
