"""Test environment defaults.

Set before the app/config modules import so local `.env` values (which may enable
web search or HyDE for manual testing) never make the suite non-deterministic.
`load_dotenv` does not override already-set environment variables.
"""

import os
import tempfile

# Isolate the test database so the suite is deterministic regardless of the
# developer's local backend/yar.db (which may hold real workspaces, documents,
# or an active LLM endpoint). A fresh temp file is used per session.
_tmp_db = os.path.join(tempfile.gettempdir(), f"yar_test_{os.getpid()}.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db}"

os.environ.setdefault("WEB_SEARCH_ENABLED", "false")
os.environ.setdefault("HYDE_ENABLED", "false")
os.environ.setdefault("QUERY_REWRITE_ENABLED", "true")
os.environ.setdefault("QDRANT_PATH", "/tmp/kilo/qdrant_test")
# Use the heavy models already cached in CI/dev so tests stay offline & deterministic
# (the app default is the small/fast pair).
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-m3")
os.environ.setdefault("RERANKER_MODEL", "BAAI/bge-reranker-base")