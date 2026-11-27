"""Test environment defaults.

Set before the app/config modules import so local `.env` values (which may enable
web search or HyDE for manual testing) never make the suite non-deterministic.
`load_dotenv` does not override already-set environment variables.
"""

import os

os.environ.setdefault("WEB_SEARCH_ENABLED", "false")
os.environ.setdefault("HYDE_ENABLED", "false")
os.environ.setdefault("QUERY_REWRITE_ENABLED", "true")
os.environ.setdefault("QDRANT_PATH", "/tmp/kilo/qdrant_test")