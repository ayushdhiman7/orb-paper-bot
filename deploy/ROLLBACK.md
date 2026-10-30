# ORB EC2 rollback procedure

This procedure is for the EC2 checkout at `~/orb-paper-bot`. It is deliberately manual: do not roll back while a paper-trading session is active or while open paper positions need reconciliation.

## 1. Stop automatic code updates before changing code

```bash
sudo systemctl stop orb-update.timer
sudo systemctl stop orb-update.service
```

This prevents the five-minute updater from changing the checkout during recovery. It does not stop the bot.

## 2. Check the bot and paper-trade state

```bash
systemctl status orb-bot.service --no-pager
pgrep -af 'python.*bot.py' || true
```

If the bot is active, do not kill it as a routine rollback step. Wait until its session has completed, or follow the project's manual paper-position reconciliation procedure first. Confirm there are no unresolved open paper trades in Supabase before starting an older version.

## 3. Record the current deployment and identify the known-good commit

```bash
cd ~/orb-paper-bot
git status --short
git rev-parse HEAD
git log -10 --oneline --decorate
```

Preserve local/untracked files. Do not use `git clean`. Select a known-good commit that has already been tested; do not guess a SHA.

## 4. Roll back the code

Only after confirming the working tree is clean or all local changes are safely backed up:

```bash
git switch --detach <KNOWN_GOOD_COMMIT>
```

A detached checkout avoids silently moving a deployment branch. If the updater expects a branch checkout, leave the updater timer stopped until the deployment branch has been deliberately restored.

## 5. Reconcile dependencies and validate

The automatic updater's rollback only resets the Git commit after a failed install/compile. It does **not** restore the prior virtualenv packages or automatically revert copied dashboard files. If the rollback crosses a dependency change, restore dependencies from the selected commit:

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m py_compile *.py
```

If dashboard files changed, republish the matching dashboard build using the repository's documented deployment procedure. Do not assume a Git rollback alone restores the Nginx document root.

## 6. Reinstall the bot unit only if it changed

Do not run the full `deploy/install.sh` for a bot-unit-only rollback: it also installs dependencies and enables all three timers. Render and install only the bot unit:

```bash
sed -e "s|__DIR__|$PWD|g" -e "s|__USER__|$(id -un)|g" deploy/orb-bot.service | sudo tee /etc/systemd/system/orb-bot.service >/dev/null
sudo systemctl daemon-reload
systemctl cat orb-bot.service
```

If the update also intentionally changed timer or watchdog units, review those files and install only the specific approved units. Do not enable or start timers as an incidental rollback side effect.

## 7. Resume updates only after verification

Confirm the selected commit, Python compile check, service configuration, and absence of unresolved open paper trades. Then:

```bash
sudo systemctl start orb-update.timer
systemctl list-timers orb-bot.timer orb-update.timer orb-watchdog.timer --no-pager
```

Do not manually start a second bot if the scheduled service is active. The process lock is a final guard, not a replacement for checking service state.

## Important limitations

- The bot remains paper-only; this procedure does not authorize live trading.
- Do not change Supabase schema/data as part of a code rollback.
- Do not delete `.env`, watchdog state, or untracked files.
- The updater does not restart the bot. New bot code is used on the next scheduled start.
- A rollback of Python code, dependencies, systemd units, and dashboard assets are separate operations; verify each independently.
