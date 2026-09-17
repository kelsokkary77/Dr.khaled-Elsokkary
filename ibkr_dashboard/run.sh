#!/usr/bin/env bash
# Start the dashboard. Creates a virtualenv on first run.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if [ ! -d .venv ]; then
  echo "Creating virtualenv..."
  "$PYTHON" -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

PORT="${IBKR_PORT:-8787}"
HOST="${IBKR_HOST:-127.0.0.1}"

echo "Dashboard: http://${HOST}:${PORT}"
exec ./.venv/bin/python -m uvicorn backend.main:app --host "$HOST" --port "$PORT"
