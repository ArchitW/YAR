import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/yar.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", f"{BASE_DIR}/uploads")


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
