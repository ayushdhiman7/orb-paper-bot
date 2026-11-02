# Phase 2 — structured AI decision audit

## What is recorded

Every Gemini review outcome is appended to a local JSONL audit file:
- entry review or open-position review type
- NSE symbol, selected model, attempt number, timestamp and duration
- parsed decision and short reason when valid
- quota block, HTTP status, invalid response, or safe error class when unavailable

The audit intentionally excludes prompts, market-context payloads, raw model responses, API keys, tokens, and arbitrary exception messages.

## Durability and failure policy

- Configure `AI_DECISION_AUDIT_FILE`; default is `~/.local/state/orb-paper-bot/ai-decisions.jsonl`.
- Parent directory is created with restrictive permissions; the log is mode 0600.
- Appends are protected by a process lock and OS file lock, flushed and fsynced before an AI opinion is returned.
- If the audit record cannot be durably written, the AI opinion is suppressed. The existing paper strategy's current fallback behaviour remains in control.
- This is a local append-only log; it is not yet synchronized to Supabase or displayed in the dashboard. Log rotation/retention is a deployment follow-up before sustained production use.

## Scope

- Applies to the existing Gemini entry and exit second-opinion calls.
- Does not grant new BUY/SELL authority, alter stop/target logic, or enable the Phase 2 management action schema.
- No schema changes, live orders, or EC2 changes.
