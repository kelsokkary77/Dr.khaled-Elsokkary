#!/usr/bin/env bash
# Double-click this file in Finder to start the dashboard and open it in
# your browser. Closing this Terminal window stops the server.
set -uo pipefail
cd "$(dirname "$0")"

PORT="${IBKR_PORT:-8787}"
URL="http://127.0.0.1:${PORT}"

# Waits for the server to come up, then opens it in the browser. Runs beside
# run.sh (which occupies this terminal) rather than before it.
wait_and_open() {
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "${URL}/api/health"; then
      open "$URL"
      return
    fi
    sleep 1
  done
}

wait_and_open &
./run.sh
