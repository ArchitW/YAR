import os
from typing import Any

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/yar.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", f"{BASE_DIR}/uploads")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_PATH = os.getenv("QDRANT_PATH", "").strip()

_qdrant_client: Any = None


def get_qdrant_client() -> Any:
    """Return a shared QdrantClient (local disk path when QDRANT_PATH is set, else HTTP URL)."""
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient

        if QDRANT_PATH:
            os.makedirs(QDRANT_PATH, exist_ok=True)
            _qdrant_client = QdrantClient(path=QDRANT_PATH)
        else:
            _qdrant_client = QdrantClient(url=QDRANT_URL)
    return _qdrant_client


def reset_qdrant_client() -> Any:
    """Close and recreate the cached Qdrant client.

    Embedded (local) Qdrant can drift into an inconsistent state (stale deleted
    mask, stuck SQLite transaction) after a failed delete. Closing releases the
    storage lock and recreating reloads a clean view from disk. Callers that cache
    the client at import time must refresh their reference to the returned value.
    """
    global _qdrant_client
    try:
        if _qdrant_client is not None:
            _qdrant_client.close()
    except Exception:
        pass
    _qdrant_client = None
    return get_qdrant_client()


def apply_hf_offline_mode() -> bool:
    """Force Hugging Face hub offline so cached models load without network calls.

    Controlled by ``HF_OFFLINE`` (default true). When enabled, sets
    ``HF_HUB_OFFLINE``/``TRANSFORMERS_OFFLINE`` so SentenceTransformer/CrossEncoder
    resolve from the local cache. Callers should retry online if the cache is empty.
    Returns whether offline mode is active.
    """
    enabled = os.getenv("HF_OFFLINE", "true").strip().lower() in ("1", "true", "yes", "on")
    if enabled:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    return enabled


def qdrant_mode() -> str:
    """Return 'local' for embedded on-disk Qdrant, otherwise 'server'."""
    return "local" if QDRANT_PATH else "server"


def reranker_settings() -> dict[str, Any]:
    """Cross-encoder reranker settings read at call time."""
    raw_enabled = os.getenv("RERANK_ENABLED", "false").strip().lower()
    try:
        top_k = max(1, int(os.getenv("RERANK_TOP_K", "10").strip() or "10"))
    except ValueError:
        top_k = 10
    return {
        "enabled": raw_enabled in ("1", "true", "yes", "on"),
        "top_k": top_k,
        "model": os.getenv("RERANKER_MODEL", "cross-encoder/ettin-reranker-17m-v1").strip()
        or "cross-encoder/ettin-reranker-17m-v1",
    }


def embedding_settings() -> dict[str, Any]:
    """Embedding model settings read at call time.

    Defaults to a small, fast model (384-dim). Changing the model changes the
    vector dimension, so the Qdrant collection must be rebuilt and documents
    reindexed (handled by the settings router).
    """
    return {
        "model": os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip()
        or "BAAI/bge-small-en-v1.5",
    }


def detect_torch_device() -> str:
    """Return the best available PyTorch compute device ('cuda', 'mps', or 'cpu')."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def llm_settings() -> dict[str, str]:
    """LLM gateway settings, read at call time so .env and tests take effect."""
    return {
        "base_url": os.getenv("LLM_BASE_URL", "").strip(),
        "model": os.getenv("LLM_MODEL", "").strip(),
        "api_key": os.getenv("LLM_API_KEY", "").strip(),
        "timeout": os.getenv("LLM_TIMEOUT", "60").strip(),
    }


def update_env_settings(updates: dict[str, str]) -> None:
    """Update runtime environment variables and persist them to backend/.env."""
    for key, val in updates.items():
        os.environ[key] = val

    env_path = os.path.join(BASE_DIR, ".env")
    lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    remaining = dict(updates)
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in remaining:
                new_lines.append(f"{k}={remaining.pop(k)}")
                continue
        new_lines.append(line)

    for k, v in remaining.items():
        new_lines.append(f"{k}={v}")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")


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
        "enabled": os.getenv("WEB_SEARCH_ENABLED", "false").strip().lower() in ("true", "1", "yes"),
        "confidence_threshold": float(os.getenv("WEB_SEARCH_CONFIDENCE_THRESHOLD", "0.25")),
    }


def ollama_settings() -> dict[str, Any]:
    """Settings for native Ollama local model integration and autodiscovery (TKT-023)."""
    return {
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        "autodiscover": os.getenv("OLLAMA_AUTODISCOVER", "true").strip().lower() in ("true", "1", "yes"),
        "timeout": float(os.getenv("OLLAMA_TIMEOUT", "3.0")),
    }


def router_settings() -> dict[str, Any]:
    """Settings for the small decision router (e.g. Kev-0.8B via System One API).

    The router only classifies the query into a route; it never generates text.
    Disabled by default and falls back to the built-in heuristics when unset or
    unreachable, so a missing router server never breaks chat.
    """
    return {
        "enabled": os.getenv("DECISION_ROUTER_ENABLED", "false").strip().lower() in ("true", "1", "yes"),
        "base_url": os.getenv("DECISION_ROUTER_BASE_URL", "http://127.0.0.1:8008").rstrip("/"),
        "model": os.getenv("DECISION_ROUTER_MODEL", "kev-latest").strip(),
        "timeout": float(os.getenv("DECISION_ROUTER_TIMEOUT", "5.0")),
    }
