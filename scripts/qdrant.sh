#!/usr/bin/env bash
# Run a local Qdrant server for the self-hosted (no-Docker) install path.
#
#   ./scripts/qdrant.sh start     # download if needed, start in background
#   ./scripts/qdrant.sh stop
#   ./scripts/qdrant.sh status
#   ./scripts/qdrant.sh run       # foreground
#
# Environment overrides:
#   QDRANT_VERSION   release tag to download (default: 1.20.2)
#   QDRANT_BIN       path to an existing qdrant binary (skips download)
#   QDRANT_STORAGE   storage directory (default: backend/qdrant_data)
#   QDRANT_HTTP_PORT default 6333
#   QDRANT_GRPC_PORT default 6334
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT/.qdrant"
BIN_DIR="$STATE_DIR/bin"
LOG_FILE="$STATE_DIR/qdrant.log"
PID_FILE="$STATE_DIR/qdrant.pid"

QDRANT_VERSION="${QDRANT_VERSION:-1.20.2}"
QDRANT_STORAGE="${QDRANT_STORAGE:-$ROOT/backend/qdrant_data}"
QDRANT_HTTP_PORT="${QDRANT_HTTP_PORT:-6333}"
QDRANT_GRPC_PORT="${QDRANT_GRPC_PORT:-6334}"
QDRANT_BIN="${QDRANT_BIN:-$BIN_DIR/qdrant}"

mkdir -p "$STATE_DIR" "$BIN_DIR" "$QDRANT_STORAGE"

asset_name() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os" in
    Linux)
      case "$arch" in
        # musl builds are statically linked; the gnu build needs a very new glibc.
        x86_64|amd64) echo "qdrant-x86_64-unknown-linux-musl.tar.gz" ;;
        aarch64|arm64) echo "qdrant-aarch64-unknown-linux-musl.tar.gz" ;;
        *) echo "unsupported Linux arch: $arch" >&2; return 1 ;;
      esac
      ;;
    Darwin)
      case "$arch" in
        x86_64) echo "qdrant-x86_64-apple-darwin.tar.gz" ;;
        arm64|aarch64) echo "qdrant-aarch64-apple-darwin.tar.gz" ;;
        *) echo "unsupported macOS arch: $arch" >&2; return 1 ;;
      esac
      ;;
    *)
      echo "unsupported OS: $os" >&2
      return 1
      ;;
  esac
}

download_binary() {
  if [ -x "$QDRANT_BIN" ]; then
    return 0
  fi
  if ! command -v curl >/dev/null 2>&1; then
    echo "Error: curl is required to download Qdrant." >&2
    return 1
  fi

  local asset url tmp
  asset="$(asset_name)" || return 1
  url="https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/${asset}"
  tmp="$STATE_DIR/qdrant-download.tar.gz"

  echo "==> Downloading Qdrant v${QDRANT_VERSION} (${asset})..."
  curl -fL --retry 3 -o "$tmp" "$url"
  tar -xzf "$tmp" -C "$BIN_DIR"
  rm -f "$tmp"
  chmod +x "$BIN_DIR/qdrant"
  echo "==> Qdrant binary ready at $BIN_DIR/qdrant"
}

is_running() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

wait_for_ready() {
  local i
  for i in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:${QDRANT_HTTP_PORT}/readyz" >/dev/null 2>&1; then
      return 0
    fi
    if ! is_running; then
      echo "Error: Qdrant exited during startup. See $LOG_FILE" >&2
      return 1
    fi
    sleep 0.5
  done
  echo "Error: Qdrant did not become ready. See $LOG_FILE" >&2
  return 1
}

start_qdrant() {
  if is_running; then
    echo "Qdrant already running (pid $(cat "$PID_FILE"))."
    return 0
  fi
  if curl -sf "http://127.0.0.1:${QDRANT_HTTP_PORT}/readyz" >/dev/null 2>&1; then
    echo "Port ${QDRANT_HTTP_PORT} already serves Qdrant; not starting another instance."
    return 0
  fi

  download_binary

  echo "==> Starting Qdrant on :${QDRANT_HTTP_PORT} (storage: $QDRANT_STORAGE)"
  QDRANT__STORAGE__STORAGE_PATH="$QDRANT_STORAGE" \
  QDRANT__SERVICE__HTTP_PORT="$QDRANT_HTTP_PORT" \
  QDRANT__SERVICE__GRPC_PORT="$QDRANT_GRPC_PORT" \
  QDRANT__TELEMETRY_DISABLED=true \
    nohup "$QDRANT_BIN" >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"

  if ! wait_for_ready; then
    echo "--- last Qdrant log lines ---" >&2
    tail -n 20 "$LOG_FILE" >&2 || true
    return 1
  fi
  echo "Qdrant ready: http://127.0.0.1:${QDRANT_HTTP_PORT}"
}

stop_qdrant() {
  if ! is_running; then
    echo "Qdrant is not running."
    rm -f "$PID_FILE"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  echo "==> Stopping Qdrant (pid $pid)..."
  kill "$pid" 2>/dev/null || true
  local i
  for i in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "Stopped."
}

status_qdrant() {
  if is_running; then
    echo "running (pid $(cat "$PID_FILE")) on :${QDRANT_HTTP_PORT}"
  elif curl -sf "http://127.0.0.1:${QDRANT_HTTP_PORT}/readyz" >/dev/null 2>&1; then
    echo "running (not managed by this script) on :${QDRANT_HTTP_PORT}"
  else
    echo "stopped"
    return 1
  fi
}

run_foreground() {
  download_binary
  QDRANT__STORAGE__STORAGE_PATH="$QDRANT_STORAGE" \
  QDRANT__SERVICE__HTTP_PORT="$QDRANT_HTTP_PORT" \
  QDRANT__SERVICE__GRPC_PORT="$QDRANT_GRPC_PORT" \
  QDRANT__TELEMETRY_DISABLED=true \
    exec "$QDRANT_BIN"
}

case "${1:-start}" in
  start) start_qdrant ;;
  stop) stop_qdrant ;;
  status) status_qdrant ;;
  download) download_binary ;;
  run) run_foreground ;;
  *) echo "Usage: $0 {start|stop|status|download|run}" >&2; exit 1 ;;
esac
