#!/usr/bin/env bash
# Double-click this file to pull the latest dashboard updates -- no typing,
# no opening a plain Terminal window yourself.
set -uo pipefail
cd "$(dirname "$0")"

echo "Checking for updates..."
echo

OUTPUT="$(git pull 2>&1)"
STATUS=$?

echo "$OUTPUT"
echo

if [ "$STATUS" -eq 0 ]; then
  if echo "$OUTPUT" | grep -q "Already up to date"; then
    echo "You're already on the latest version -- nothing to do."
  else
    echo "Updated. Restart the dashboard (close its window, then double-click"
    echo "Start Dashboard.command again) to use the new version."
  fi
else
  if echo "$OUTPUT" | grep -q "would be overwritten by merge"; then
    echo "Update blocked: a file above (under \"Your local changes...\") has"
    echo "an edit that hasn't been saved anywhere else. This usually means a"
    echo "real setting (like a password) got typed into the wrong file --"
    echo "check whether that file should really be .env instead."
    echo
    echo "If you're not sure what to do, copy this whole message and send it"
    echo "back for help."
  else
    echo "The update didn't complete. Copy this whole message and send it"
    echo "back for help."
  fi
fi

echo
read -n 1 -s -r -p "Press any key to close this window..."
echo
