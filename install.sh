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

# Pre-download embedding and reranker models so first run is instant.
# Defaults match backend/app/core/config.py (small/fast pair); override via env.
echo "==> Pre-downloading embedding and reranker models..."
EMBEDDING_MODEL="${EMBEDDING_MODEL:-BAAI/bge-small-en-v1.5}" \
RERANKER_MODEL="${RERANKER_MODEL:-cross-encoder/ettin-reranker-17m-v1}" \
python -c '
import os
from sentence_transformers import SentenceTransformer, CrossEncoder
emb = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
rr = os.environ.get("RERANKER_MODEL", "cross-encoder/ettin-reranker-17m-v1")
print(f"Downloading embedding model {emb}...")
SentenceTransformer(emb, device="cpu")
print(f"Downloading reranker model {rr}...")
CrossEncoder(rr, device="cpu")
print("Models cached successfully.")
'

# Fetch the local Qdrant server binary (self-hosted retrieval).
echo "==> Fetching local Qdrant binary..."
if ! "$ROOT/scripts/qdrant.sh" download; then
  echo "Warning: could not fetch Qdrant now. ./scripts/qdrant.sh start will retry." >&2
fi

# Local no-Docker defaults in backend/.env (only if not already configured)
if [ ! -f "$ROOT/backend/.env" ]; then
  echo "==> Creating backend/.env with local no-Docker defaults..."
  cp "$ROOT/.env.example" "$ROOT/backend/.env"
  {
    echo ""
    echo "# Local Qdrant server (auto-started by ./start.sh via scripts/qdrant.sh)"
    echo "QDRANT_URL=http://localhost:6333"
    echo "# Embedded on-disk mode is only for small dev sets (no ANN index):"
    echo "# QDRANT_PATH=./qdrant_data"
  } >> "$ROOT/backend/.env"
fi

# Frontend dependencies
echo "==> Installing frontend dependencies..."
cd "$ROOT/frontend"
npm install

echo ""
echo "Install complete. Run ./start.sh to start YAR."
