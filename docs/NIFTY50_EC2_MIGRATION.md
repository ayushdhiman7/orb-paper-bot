# Nifty 50 runner — EC2 migration and rollback

## Purpose and safety

This procedure replaces the legacy bot.py systemd command with the dedicated nifty50_runner.py paper runtime. It does not place broker orders, change Supabase data/schema, or enable live trading.

**Do not perform the switch during NSE market hours or while any paper position is open.** The runner refuses unsafe startup when it finds unreconciled prior-day open trades. The service is deliberately configured with Restart=no. Automatic process restart must remain disabled until restart/position-restoration acceptance has been completed and documented.

## Readiness gates — all required

- [ ] Exact main commit to deploy is recorded and its PR CI checks are green.
- [ ] Connected Supabase project has the five Nifty 50 migrations applied and required tables/columns verified.
- [ ] Actual Angel One account has passed SNAP_QUOTE login, subscription, and fresh exchange-timestamped packet acceptance during NSE market hours.
- [ ] Full-universe symbol/token coverage and disconnect/reconnect behavior have been operator-verified.
- [ ] Operator confirms market is closed and Supabase has zero unresolved open paper trades.
- [ ] No legacy bot process is active and no other process holds the shared instance lock.
- [ ] Private environment variables are present in the EC2 repository .env; do not paste or commit secrets.
- [ ] Selected rollback commit and current unit contents are recorded.

If any gate is not satisfied, stop here. Do not start the Nifty 50 service.

## 1. Capture current state

Run on EC2 from ~/orb-paper-bot:

~~~bash
cd ~/orb-paper-bot
date -Is
git status --short
git rev-parse HEAD
git log -5 --oneline --decorate
systemctl status orb-bot.service --no-pager || true
systemctl list-timers orb-bot.timer orb-update.timer orb-watchdog.timer --no-pager
pgrep -af 'python.*(bot.py|nifty50_runner.py)' || true
systemctl cat orb-bot.service
~~~

Check the Supabase paper ledger independently. This query must return zero rows before the switch:

~~~sql
select id, symbol, side, qty, entry, ts
from public.paper_trades
where status = 'open' and mode = 'paper'
order by ts;
~~~

Do not kill a process, delete the lock file, or infer that no positions exist from an empty process list. Reconcile database and service state.

## 2. Pause scheduled starts and automatic checkout updates

Only after market close and open paper trades are reconciled:

~~~bash
sudo systemctl stop orb-bot.timer
sudo systemctl stop orb-update.timer
sudo systemctl stop orb-update.service
~~~

If the legacy service is still active, inspect its logs and confirm its paper positions are closed before stopping it:

~~~bash
sudo systemctl stop orb-bot.service
systemctl is-active orb-bot.service || true
pgrep -af 'python.*(bot.py|nifty50_runner.py)' || true
~~~

Do not proceed if any bot process remains active.

## 3. Update checkout and dependencies

Preserve local files. Do not use git clean or overwrite .env.

~~~bash
git status --short
git fetch origin main
git merge --ff-only origin/main
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m py_compile *.py
~~~

If the working tree is not clean, stop and inspect changes rather than forcing the update.

## 4. Install and inspect the Nifty 50 systemd unit

Render only the bot service unit. Do not run deploy/install.sh for this migration; it installs dependencies and enables all three timers.

~~~bash
sed -e "s|__DIR__|$PWD|g" -e "s|__USER__|$(id -un)|g" deploy/orb-bot.service | sudo tee /etc/systemd/system/orb-bot.service >/dev/null
sudo systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/orb-bot.service
systemctl cat orb-bot.service
~~~

Verify the rendered unit contains ORB_RUNTIME_MODE=nifty50_batch, ExecStart ending in nifty50_runner.py, the private .env EnvironmentFile, Restart=no, and the shared ORB_LOCK_FILE. The environment file must remain private and readable by the configured service user only.

## 5. Re-enable scheduling

~~~bash
sudo systemctl start orb-update.timer
sudo systemctl start orb-bot.timer
sudo systemctl start orb-watchdog.timer
systemctl list-timers orb-bot.timer orb-update.timer orb-watchdog.timer --no-pager
~~~

The weekday bot timer starts orb-bot.service at 09:05 Asia/Kolkata. If the scheduled time has passed, start the service manually only during an approved NSE paper-validation session after all readiness gates are met:

~~~bash
sudo systemctl start orb-bot.service
~~~

Do not start a second runner if the service is already active.

## 6. Validate the paper runtime

Follow logs:

~~~bash
journalctl -u orb-bot.service -f
~~~

Confirm from actual runtime logs and persisted state:

- Process command is nifty50_runner.py, not bot.py.
- Startup identifies the Nifty 50 batch paper runner and exactly 50 constituents.
- Angel One SNAP_QUOTE produces fresh exchange-timestamped packets; WebSocket open alone is not readiness.
- No Yahoo or other delayed-price fallback is used.
- Supabase paper ledger writes and dashboard/webhook connectivity work.
- Dashboard reports paper-only mode and expected limits: 1% per-trade risk, 2% daily loss cap, max 2 open positions, max 3 trades/day, 15:15 square-off.
- Telegram alerts are delivered if configured.
- No broker order endpoint is called and no live order is placed.

A successful systemd start is not proof of feed entitlement, full symbol coverage, or strategy acceptance. Stop validation and keep runtime disabled if SNAP_QUOTE is denied, stale, incomplete, or rate-limited. Do not switch to a fallback feed.

## Rollback

Rollback only after market close and after all paper positions are closed/reconciled.

1. Stop orb-bot.timer, orb-update.timer, and orb-update.service.
2. Stop orb-bot.service and confirm no bot process remains.
3. Restore the known-good code commit using deploy/ROLLBACK.md. Do not use git clean.
4. Render the legacy unit from the selected known-good commit, which must contain the legacy service template:

~~~bash
git show <KNOWN_GOOD_COMMIT>:deploy/orb-bot.service | sed -e "s|__DIR__|$PWD|g" -e "s|__USER__|$(id -un)|g" | sudo tee /etc/systemd/system/orb-bot.service >/dev/null
sudo systemctl daemon-reload
systemctl cat orb-bot.service
~~~

5. Re-enable timers only after confirming the legacy unit and code match:

~~~bash
sudo systemctl start orb-update.timer
sudo systemctl start orb-bot.timer
sudo systemctl start orb-watchdog.timer
~~~

Do not start the service manually if the timer or service is already active. Do not restart either runtime while open paper positions need reconciliation.

## Explicit exclusions

- No live broker order placement.
- No secrets in Git, pull requests, or chat.
- No Supabase data deletion or schema reset.
- No forced process kill or lock-file deletion.
- No automatic systemd restart until restart restoration is separately accepted.
- No deployment claim until EC2 service state, runner logs, and paper ledger have been checked.