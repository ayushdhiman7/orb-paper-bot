# Phase 2 — Gemini quota transport

## Request accounting

- Limits default to 100 requests per IST calendar day and 5 requests per rolling 60-second window.
- Override with `GEMINI_MAX_REQUESTS_PER_DAY` and `GEMINI_MAX_REQUESTS_PER_MINUTE`.
- A request is counted immediately before each actual Gemini HTTP attempt. HTTP failures, JSON-mode retries, and model fallback attempts all consume quota.
- Missing API credentials do not consume quota.
- The quota is shared by all callers in the bot process and protected across processes with an OS file lock.

## Durable state and failure behaviour

- State is stored at `GEMINI_QUOTA_STATE_FILE` when configured; otherwise at `~/.local/state/orb-paper-bot/gemini-quota.json`.
- The state file and lock file are created with mode 0600; state writes use a temporary file, fsync, and atomic replacement.
- Daily reset uses the Asia/Kolkata calendar date, not the EC2 host timezone.
- If state is corrupt, unreadable, or cannot be written, Gemini calls are blocked. The existing bot receives no AI opinion and retains its existing deterministic paper strategy behaviour.
- Quota state is local to the EC2 host. It is not synchronized across multiple machines; the bot's single-instance lock remains important.

## Scope and rollout

- This slice applies the quota to the existing Gemini second-opinion transport. It does not yet enable AI BUY/SELL authority or AI position-management actions.
- No Supabase schema or data is changed.
- No live broker order API is introduced.
- No EC2 deployment or environment change is included. The state path and permissions must be checked during a separately approved deployment.
- Offline tests cover restart persistence, daily rollover, rolling-minute limits, private file permissions, HTTP retry accounting, model fallback accounting, and fail-closed behaviour.
