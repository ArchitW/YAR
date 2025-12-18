#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
if command -v py3 >/dev/null 2>&1; then
  PY=py3
else
  PY=python3
fi

# Backend venv + deps
if [ ! -d "$ROOT/backend/.venv" ]; then
  "$PY" -m venv "$ROOT/backend/.venv"
fi
. "$ROOT/backend/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$ROOT/backend/requirements.txt"

# Frontend bootstrap
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  if [ ! -f package.json ]; then
    npm create vite@latest . -- --template react-ts --yes
  fi
  npm install
  npx shadcn@latest init -y
fi
echo "Install complete."
