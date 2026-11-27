import os
from typing import Any

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/yar.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", f"{BASE_DIR}/uploads")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")


def llm_settings() -> dict[str, str]:
    """LLM gateway settings, read at call time so .env and tests take effect."""
    return {
        "base_url": os.getenv("LLM_BASE_URL", "").strip(),
        "model": os.getenv("LLM_MODEL", "").strip(),
        "api_key": os.getenv("LLM_API_KEY", "").strip(),
        "timeout": os.getenv("LLM_TIMEOUT", "60").strip(),
    }


def auth_enabled() -> bool:
    """Whether authentication is required for endpoints."""
    return os.getenv("AUTH_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def jwt_secret() -> str:
    """JWT secret key. Raises RuntimeError if auth is enabled and secret is not set."""
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret:
        if auth_enabled():
            raise RuntimeError("JWT_SECRET environment variable is required when AUTH_ENABLED=true")
        return "yar-dev-secret-auth-disabled"
    return secret


def query_rewriter_settings() -> dict[str, bool]:
    """Settings for conversational query rewriting and HyDE expansion."""
    return {
        "rewrite_enabled": os.getenv("QUERY_REWRITE_ENABLED", "true").strip().lower() in ("true", "1", "yes"),
        "hyde_enabled": os.getenv("HYDE_ENABLED", "false").strip().lower() in ("true", "1", "yes"),
    }


def searxng_settings() -> dict[str, Any]:
    """Settings for SearXNG metasearch and autonomous web tool fallback."""
    return {
        "base_url": os.getenv("SEARXNG_BASE_URL", "").rstrip("/"),
        "enabled": os.getenv("WEB_SEARCH_ENABLED", "true").strip().lower() in ("true", "1", "yes"),
        "confidence_threshold": float(os.getenv("WEB_SEARCH_CONFIDENCE_THRESHOLD", "0.25")),
    }


def ollama_settings() -> dict[str, Any]:
    """Settings for native Ollama local model integration and autodiscovery (TKT-023)."""
    return {
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        "autodiscover": os.getenv("OLLAMA_AUTODISCOVER", "true").strip().lower() in ("true", "1", "yes"),
        "timeout": float(os.getenv("OLLAMA_TIMEOUT", "3.0")),
    }
