#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$ROOT/backend/.venv" ] || [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "Dependencies not installed yet. Run ./install.sh first." >&2
  exit 1
fi

cleanup() {
  echo ""
  echo "Stopping YAR services..."
  kill "${BACKEND_PID:-}" "${FRONTEND_PID:-}" "${REDIS_PID:-}" 2>/dev/null || true
  wait "${BACKEND_PID:-}" "${FRONTEND_PID:-}" "${REDIS_PID:-}" 2>/dev/null || true
}
trap cleanup INT TERM

ensure_redis() {
  if "$ROOT/backend/.venv/bin/python" -c "import socket; s=socket.create_connection(('127.0.0.1', 6379), 1); s.close()" 2>/dev/null; then
    echo "==> Redis already running on localhost:6379"
    return 0
  fi

  if command -v redis-server >/dev/null 2>&1; then
    echo "==> Starting local redis-server on port 6379..."
    redis-server --port 6379 &
    REDIS_PID=$!
    return 0
  fi

  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "==> Starting Redis via Docker Compose..."
    (cd "$ROOT" && docker compose up -d redis) && return 0
  fi

  echo "WARNING: Redis is not running on localhost:6379 (neither redis-server nor Docker is available)." >&2
  echo "         /health will report redis as offline until Redis is started." >&2
}

ensure_redis

echo "==> Starting Backend API (http://localhost:8000)..."
cd "$ROOT/backend"
# shellcheck disable=SC1091
. .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "==> Starting Frontend UI (http://localhost:5173)..."
cd "$ROOT/frontend"
npm run dev -- --host &
FRONTEND_PID=$!

echo ""
echo "YAR is running:"
echo "  Web UI:   http://localhost:5173"
echo "  API Docs: http://localhost:8000/docs"
echo "Press Ctrl+C to stop."

wait "$BACKEND_PID" "$FRONTEND_PID"
