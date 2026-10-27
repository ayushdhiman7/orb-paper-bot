#!/usr/bin/env bash
# Installs the weekday timer on this machine. Safe to re-run. Run from the repo folder:  bash deploy/install.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"
[ -x "$DIR/.venv/bin/python" ] || { echo "No .venv found in $DIR. Create it first."; exit 1; }
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
for f in orb-bot.service orb-bot.timer; do
  sed -e "s|__DIR__|$DIR|g" -e "s|__USER__|$USER_NAME|g" "$DIR/deploy/$f" | sudo tee "/etc/systemd/system/$f" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now orb-bot.timer
echo; systemctl list-timers orb-bot.timer --no-pager
echo; echo "Keys present in .env (names only):"
for k in SUPABASE_URL SUPABASE_KEY GEMINI_API_KEY; do
  if grep -q "^$k=" "$DIR/.env" 2>/dev/null; then echo "  $k: yes"; else echo "  $k: MISSING"; fi
done
