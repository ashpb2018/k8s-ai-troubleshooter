#!/usr/bin/env bash
# Launch the KubeMedic web UI.
#
#   bash web/start.sh        # dev:  FastAPI + Vite dev server (hot reload)
#   bash web/start.sh prod   # prod: build the UI and serve it from FastAPI
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/web/frontend"
BACKEND_PORT=8000
FRONTEND_PORT=5173
APP="kubemedic.web.app:app"

free_port() {
  local port=$1 pids
  pids=$(lsof -ti "tcp:$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "  freeing port $port ($pids)"
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 0.3
  fi
}

if [ ! -d "$ROOT/.venv" ]; then
  echo "No virtualenv found. Create one and install with:"
  echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[all]'"
  exit 1
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "Installing frontend dependencies…"
  (cd "$FRONTEND" && npm install)
fi

cd "$ROOT"

if [ "${1:-dev}" = "prod" ]; then
  echo "Building the UI…"
  (cd "$FRONTEND" && npm run build)
  free_port "$BACKEND_PORT"
  echo "Serving on http://localhost:$BACKEND_PORT"
  exec uvicorn "$APP" --host 0.0.0.0 --port "$BACKEND_PORT"
fi

free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"

echo "Backend  → http://localhost:$BACKEND_PORT"
echo "Frontend → http://localhost:$FRONTEND_PORT"

uvicorn "$APP" --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
  free_port "$BACKEND_PORT"
  free_port "$FRONTEND_PORT"
}
trap cleanup INT TERM EXIT

(cd "$FRONTEND" && npm run dev)
