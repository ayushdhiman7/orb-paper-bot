#!/usr/bin/env bash
# Pull-based auto deploy. Runs every 5 minutes from a systemd timer (orb-update.timer).
# - Fetches GitHub main. If nothing new, exits quietly.
# - Pulls only fast-forward changes, installs new Python packages if requirements.txt changed,
#   checks the code compiles (rolls back if not), and refreshes the Nginx dashboard files.
# - NEVER restarts the trading bot. It starts fresh each weekday 09:05 IST, so new code is used the next morning.
set -euo pipefail
DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
WEB="${WEB_DIR:-/var/www/orb-dashboard}"
PY="${PY:-$DIR/.venv/bin/python}"
BRANCH="${BRANCH:-main}"
cd "$DIR"

git fetch -q origin "$BRANCH"
OLD="$(git rev-parse HEAD)"
NEW="$(git rev-parse FETCH_HEAD)"
if [ "$OLD" = "$NEW" ]; then exit 0; fi
if git merge-base --is-ancestor "$NEW" "$OLD"; then exit 0; fi   # remote is behind us: nothing to do

echo "[deploy] updating ${OLD:0:7} -> ${NEW:0:7}"
if ! git merge --ff-only -q "$NEW"; then
  echo "[deploy] cannot fast-forward (local changes or diverged history). Skipped."; exit 1
fi

if ! git diff --quiet "$OLD" "$NEW" -- requirements.txt; then
  echo "[deploy] requirements.txt changed: installing"
  "$PY" -m pip install -q -r requirements.txt || { git reset -q --hard "$OLD"; echo "[deploy] pip failed, rolled back"; exit 1; }
fi

if ! "$PY" -m py_compile *.py; then
  git reset -q --hard "$OLD"; echo "[deploy] code did not compile, rolled back to ${OLD:0:7}"; exit 1
fi

if [ -d "$WEB" ] && [ -w "$WEB" ]; then
  cp -r docs/. "$WEB"/
  echo "[deploy] dashboard files refreshed"
fi
echo "[deploy] done: now at ${NEW:0:7}. The bot picks this up at its next start."
