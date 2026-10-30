"""Durable, fail-closed Gemini request quota for the paper bot.

Each actual HTTP attempt must reserve one request immediately before network I/O.
The state is atomically persisted across process restarts and protected by flock.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class QuotaStateError(RuntimeError):
    """Quota state cannot be safely read or persisted; requests must stop."""


def default_state_path() -> Path:
    configured = os.getenv("GEMINI_QUOTA_STATE_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "state" / "orb-paper-bot" / "gemini-quota.json"


class PersistentGeminiQuota:
    """Rolling per-minute and IST-calendar-day limiter with durable atomic state."""

    def __init__(self, daily_limit=100, per_minute_limit=5, path=None, clock=time.time):
        self.daily_limit = int(daily_limit)
        self.per_minute_limit = int(per_minute_limit)
        if self.daily_limit < 1 or self.per_minute_limit < 1:
            raise ValueError("quota limits must be positive")
        self.path = Path(path) if path is not None else default_state_path()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._clock = clock
        self._thread_lock = threading.Lock()

    def _read(self):
        if not self.path.exists():
            return {"day": None, "count": 0, "recent": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("count"), int)
                or data["count"] < 0
                or not isinstance(data.get("recent"), list)
                or any(not isinstance(x, (int, float)) for x in data["recent"])
                or (data.get("day") is not None and not isinstance(data.get("day"), str))
            ):
                raise ValueError("invalid quota state shape")
            return data
        except Exception as exc:
            raise QuotaStateError("Gemini quota state is unreadable; refusing API request") from exc

    def _write(self, state):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(state, handle, separators=(",", ":"), sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, self.path)
                os.chmod(self.path, 0o600)
                dir_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        except Exception as exc:
            raise QuotaStateError("Gemini quota state could not be persisted; refusing API request") from exc

    def reserve(self, now: datetime) -> tuple[bool, str]:
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("quota reservation time must be timezone-aware")
        ist_day = now.astimezone(IST).date().isoformat()
        epoch = float(self._clock())
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self._thread_lock:
                with self.lock_path.open("a", encoding="utf-8") as lock_file:
                    os.chmod(self.lock_path, 0o600)
                    try:
                        import fcntl
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    except ImportError as exc:
                        raise QuotaStateError("file locking unavailable; refusing API request") from exc
                    state = self._read()
                    if state.get("day") != ist_day:
                        state = {"day": ist_day, "count": 0, "recent": []}
                    recent = [float(ts) for ts in state["recent"] if epoch - float(ts) < 60]
                    if state["count"] >= self.daily_limit:
                        state["recent"] = recent
                        self._write(state)
                        return False, "daily_quota_exhausted"
                    if len(recent) >= self.per_minute_limit:
                        state["recent"] = recent
                        self._write(state)
                        return False, "per_minute_quota_exhausted"
                    recent.append(epoch)
                    state.update({"day": ist_day, "count": state["count"] + 1, "recent": recent})
                    self._write(state)
                    return True, "reserved"
        except QuotaStateError:
            raise
        except Exception as exc:
            raise QuotaStateError("Gemini quota reservation failed; refusing API request") from exc

    def snapshot(self):
        try:
            with self._thread_lock:
                return self._read()
        except QuotaStateError:
            raise
