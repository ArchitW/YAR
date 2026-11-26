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
}
trap cleanup INT TERM

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
