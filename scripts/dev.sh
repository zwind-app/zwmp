#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.logs"
mkdir -p "$LOG_DIR"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

BACKEND_HOST="${ZWMP_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${ZWMP_BACKEND_PORT:-8000}"
FRONTEND_PORT="${ZWMP_FRONTEND_PORT:-5173}"

cleanup() {
  if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "${FRONTEND_PID:-}" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "$ROOT_DIR"

if [ ! -x "$ROOT_DIR/apps/api/.venv/bin/uvicorn" ]; then
  echo "Backend virtualenv is missing. Run:"
  echo "  cd apps/api && python -m venv .venv && source .venv/bin/activate && pip install -e ../../packages/rule-core -e '.[test,browser]'"
  exit 1
fi

if [ ! -d "$ROOT_DIR/apps/web/node_modules" ]; then
  echo "Frontend dependencies are missing. Run:"
  echo "  cd apps/web && npm install"
  exit 1
fi

echo "Starting ZWMP backend -> http://$BACKEND_HOST:$BACKEND_PORT"
"$ROOT_DIR/apps/api/.venv/bin/uvicorn" zwmp_api.main:app \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" \
  >"$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

echo "Starting ZWMP frontend -> http://127.0.0.1:$FRONTEND_PORT"
(
  cd "$ROOT_DIR/apps/web"
  npm run dev -- --port "$FRONTEND_PORT"
) >"$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

echo "Logs:"
echo "  $LOG_DIR/backend.log"
echo "  $LOG_DIR/frontend.log"
echo "Press Ctrl-C to stop both services."

wait -n "$BACKEND_PID" "$FRONTEND_PID"
