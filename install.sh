#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Check prerequisites
if command -v py3 >/dev/null 2>&1; then
  PY=py3
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "Error: Python 3.11+ is required but not found." >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Error: Node.js 18+ and npm are required but not found." >&2
  exit 1
fi

# Backend virtualenv + dependencies
echo "==> Setting up Python virtual environment..."
if [ ! -d "$ROOT/backend/.venv" ]; then
  "$PY" -m venv "$ROOT/backend/.venv"
fi
# shellcheck disable=SC1091
. "$ROOT/backend/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$ROOT/backend/requirements.txt"

# Local no-Docker defaults in backend/.env (only if not already configured)
if [ ! -f "$ROOT/backend/.env" ]; then
  echo "==> Creating backend/.env with local no-Docker defaults..."
  cp "$ROOT/.env.example" "$ROOT/backend/.env"
  {
    echo ""
    echo "# Embedded local-disk Qdrant (no Docker Qdrant server required)"
    echo "QDRANT_PATH=./qdrant_data"
  } >> "$ROOT/backend/.env"
fi

# Frontend dependencies
echo "==> Installing frontend dependencies..."
cd "$ROOT/frontend"
npm install

echo ""
echo "Install complete. Run ./start.sh to start YAR."
