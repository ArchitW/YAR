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

# Detect GPU before installing PyTorch / sentence-transformers
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)"
  echo "==> GPU detected ($GPU_NAME) — ensuring CUDA PyTorch is installed..."
  if ! python -c "import torch; assert torch.cuda.is_available()" >/dev/null 2>&1; then
    pip install torch --index-url https://download.pytorch.org/whl/cu124
  fi
elif [ "$(uname -s)" = "Darwin" ]; then
  echo "==> macOS detected — installing PyTorch (MPS/CPU)..."
  pip install torch
else
  echo "==> No NVIDIA GPU detected — installing CPU-only PyTorch..."
  if ! python -c "import torch" >/dev/null 2>&1; then
    pip install torch --index-url https://download.pytorch.org/whl/cpu
  fi
fi

pip install -r "$ROOT/backend/requirements.txt"

# Pre-download embedding and reranker models so first run is instant
echo "==> Pre-downloading embedding (BAAI/bge-m3) and reranker (BAAI/bge-reranker-base) models..."
python -c '
from sentence_transformers import SentenceTransformer, CrossEncoder
print("Downloading BAAI/bge-m3...")
SentenceTransformer("BAAI/bge-m3", device="cpu")
print("Downloading BAAI/bge-reranker-base...")
CrossEncoder("BAAI/bge-reranker-base", device="cpu")
print("Models cached successfully.")
'

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
