"""Unified application settings REST API router."""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..core.config import (
    DATABASE_URL,
    QDRANT_PATH,
    QDRANT_URL,
    UPLOAD_DIR,
    auth_enabled,
    detect_torch_device,
    llm_settings,
    ollama_settings,
    query_rewriter_settings,
    searxng_settings,
    update_env_settings,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    # Models & Providers
    llm_base_url: str
    llm_model: str
    llm_timeout: str
    has_api_key: bool
    ollama_base_url: str
    ollama_autodiscover: bool
    ollama_timeout: float
    # Retrieval & Web Search
    query_rewrite_enabled: bool
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
        query_rewrite_enabled=bool(qr["rewrite_enabled"]),
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

    return _build_settings_response()
