#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
NODE_BIN="/tmp/clipper-node/bin"

if [ -d "$NODE_BIN" ]; then
  export PATH="$NODE_BIN:$PATH"
fi

export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:$BACKEND_PORT}"

if [ ! -x "$BACKEND_DIR/.venv/bin/uvicorn" ]; then
  echo "Backend venv belum siap. Jalankan: cd backend && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm tidak ditemukan. Install Node.js/npm atau pastikan /tmp/clipper-node/bin tersedia." >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg tidak ditemukan. Install ffmpeg sebelum menjalankan Clipper." >&2
  exit 1
fi

cleanup() {
  trap - INT TERM EXIT
  if [ "${BACKEND_PID:-}" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ "${FRONTEND_PID:-}" ]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}

trap cleanup INT TERM EXIT

echo "Starting backend: http://localhost:$BACKEND_PORT"
(
  cd "$BACKEND_DIR"
  .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

echo "Starting frontend: http://localhost:$FRONTEND_PORT"
(
  cd "$FRONTEND_DIR"
  npm run dev -- --hostname 127.0.0.1 --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

echo "Clipper ready. Buka http://localhost:$FRONTEND_PORT"
echo "Tekan Ctrl+C untuk menghentikan backend dan frontend."

wait -n "$BACKEND_PID" "$FRONTEND_PID"
