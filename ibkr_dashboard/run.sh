#!/usr/bin/env bash
# Start the dashboard. Creates a virtualenv on first run.
set -euo pipefail
cd "$(dirname "$0")"

MIN_MAJOR=3
MIN_MINOR=11

# Saved before PYTHON is reassigned below, so the error message can name
# the interpreter the user actually asked for.
REQUESTED_PYTHON="${PYTHON:-}"

# macOS still ships Python 3.9, and FastAPI resolves this project's type hints
# at import time -- on an old interpreter that fails somewhere deep in the
# framework. Check up front so the message names the actual problem.
version_ok() {
  command -v "$1" > /dev/null 2>&1 \
    && "$1" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_MAJOR, $MIN_MINOR) else 1)" 2>/dev/null
}

find_python() {
  # An explicitly set PYTHON is still checked -- pointing the script at the
  # wrong interpreter should say so, not fail later inside the framework.
  if [ -n "${PYTHON:-}" ]; then
    if version_ok "$PYTHON"; then
      echo "$PYTHON"
    fi
    return
  fi
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if version_ok "$candidate"; then
      echo "$candidate"
      return
    fi
  done
}

PYTHON="$(find_python)"

if [ -z "$PYTHON" ]; then
  probe="${REQUESTED_PYTHON:-python3}"
  found="no suitable interpreter was found"
  if command -v "$probe" > /dev/null 2>&1; then
    version="$("$probe" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo 'unknown')"
    found="$probe is $version"
  fi
  cat >&2 <<MSG
This dashboard needs Python ${MIN_MAJOR}.${MIN_MINOR} or newer, but ${found}.

Install a newer Python, then run this script again:

  macOS     brew install python@3.13
            (or download from https://www.python.org/downloads/)
  Ubuntu    sudo apt install python3.13 python3.13-venv
  Windows   https://www.python.org/downloads/ (tick "Add python.exe to PATH")

Already have one under a different name? Point this script at it:

  PYTHON=/usr/local/bin/python3.13 ./run.sh
MSG
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating virtualenv with $("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')..."
  "$PYTHON" -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

PORT="${IBKR_PORT:-8787}"
HOST="${IBKR_HOST:-127.0.0.1}"

echo
echo "  Dashboard: http://${HOST}:${PORT}"
echo "  Press Ctrl+C to stop."
echo
exec ./.venv/bin/python -m uvicorn backend.main:app --host "$HOST" --port "$PORT"
