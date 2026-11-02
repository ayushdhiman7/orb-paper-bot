"""Append-only, privacy-conscious local audit log for Gemini decisions.

Only structured metadata and parsed decisions are recorded. Prompts, raw model
responses, credentials, and arbitrary exception messages are never written.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()


class AuditWriteError(RuntimeError):
    """A decision could not be durably audited."""


def audit_path() -> Path:
    configured = os.getenv("AI_DECISION_AUDIT_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "state" / "orb-paper-bot" / "ai-decisions.jsonl"


def _safe_text(value, limit=200):
    text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    return text[:limit]


def append_decision(event: dict, path=None) -> None:
    """Append one validated event with fsync, restrictive permissions and process lock."""
    target = Path(path) if path is not None else audit_path()
    record = {
        "event_id": str(uuid.uuid4()),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "event_type": _safe_text(event.get("event_type"), 32),
        "symbol": _safe_text(event.get("symbol"), 32).upper(),
        "model": _safe_text(event.get("model"), 80),
        "attempt": int(event.get("attempt", 0)),
        "status": _safe_text(event.get("status"), 40),
        "http_status": event.get("http_status") if isinstance(event.get("http_status"), int) else None,
        "decision": _safe_text(event.get("decision"), 16).lower() or None,
        "reason": _safe_text(event.get("reason"), 200) or None,
        "error_type": _safe_text(event.get("error_type"), 80) or None,
        "quota_reason": _safe_text(event.get("quota_reason"), 80) or None,
        "duration_ms": max(0, int(event.get("duration_ms", 0))),
    }
    if record["event_type"] not in {"entry_review", "position_review"}:
        raise AuditWriteError("unsupported audit event type")
    if record["status"] not in {"approved", "rejected", "unavailable", "quota_blocked", "invalid_response"}:
        raise AuditWriteError("unsupported audit status")
    if not record["symbol"]:
        record["symbol"] = "UNKNOWN"

    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        line = json.dumps(record, separators=(",", ":"), sort_keys=True, ensure_ascii=True) + "\n"
        with _LOCK:
            with target.open("a", encoding="utf-8") as handle:
                os.chmod(target, 0o600)
                try:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except ImportError as exc:
                    raise AuditWriteError("file locking unavailable") from exc
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
    except AuditWriteError:
        raise
    except Exception as exc:
        raise AuditWriteError("AI decision audit could not be persisted") from exc
