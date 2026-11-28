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
  kill "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
  wait "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
  if [ "${QDRANT_STARTED:-0}" = "1" ]; then
    "$ROOT/scripts/qdrant.sh" stop >/dev/null 2>&1 || true
  fi
}
trap cleanup INT TERM

# Start the local Qdrant server unless the user opted into embedded mode.
QDRANT_STARTED=0
if ! grep -qE '^QDRANT_PATH=' "$ROOT/backend/.env" 2>/dev/null; then
  if ! curl -sf "http://localhost:6333/readyz" >/dev/null 2>&1; then
    echo "==> Starting local Qdrant (scripts/qdrant.sh)..."
    if "$ROOT/scripts/qdrant.sh" start; then
      QDRANT_STARTED=1
    else
      echo "Warning: Qdrant did not start; the API will report degraded health." >&2
    fi
  fi
fi

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
