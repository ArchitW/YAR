#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Run backend
cd "$ROOT/backend"
. .venv/bin/activate
uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!

# Run frontend
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

wait $BACKEND_PID $FRONTEND_PID
