"""Best-effort, durable bot-to-dashboard event delivery.

This module never raises into the trading path. Events are written to a local
JSONL outbox and delivered by a daemon worker with HMAC authentication.
"""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()
_STARTED = False
_STOP = threading.Event()
_MAX_BACKOFF = 60
_TIMEOUT_SECONDS = 3


def _outbox_path() -> Path:
    configured = os.getenv("WEBHOOK_OUTBOX_PATH", "").strip()
    return Path(configured) if configured else Path(__file__).resolve().parent / "var" / "webhook-outbox.jsonl"


def _configuration():
    url = os.getenv("DASHBOARD_WEBHOOK_URL", "").strip()
    secret = os.getenv("DASHBOARD_WEBHOOK_SECRET", "").strip()
    return url, secret


def _append(payload: dict) -> None:
    path = _outbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _first_pending():
    path = _outbox_path()
    if not path.exists():
        return None
    with _LOCK:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    return json.loads(line)
    return None


def _remove_sent(event_id: str) -> None:
    path = _outbox_path()
    if not path.exists():
        return
    with _LOCK:
        lines = path.read_text(encoding="utf-8").splitlines()
        kept = []
        removed = False
        for line in lines:
            if not removed:
                try:
                    removed = json.loads(line).get("event_id") == event_id
                except (ValueError, AttributeError):
                    pass
                if removed:
                    continue
            kept.append(line)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        os.replace(temp, path)


def _post(payload: dict, url: str, secret: str) -> bool:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-ORB-Timestamp": timestamp,
            "X-ORB-Signature": "sha256=" + signature,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _worker() -> None:
    backoff = 2
    while not _STOP.is_set():
        url, secret = _configuration()
        if not url or not secret:
            _STOP.wait(10)
            continue
        try:
            payload = _first_pending()
            if payload is None:
                _STOP.wait(1)
                continue
            if _post(payload, url, secret):
                _remove_sent(payload["event_id"])
                backoff = 2
            else:
                _STOP.wait(backoff)
                backoff = min(_MAX_BACKOFF, backoff * 2)
        except Exception as exc:
            # Do not print payloads, URLs, signatures, or secrets.
            print(f"[warn] dashboard webhook delivery deferred ({type(exc).__name__})")
            _STOP.wait(backoff)
            backoff = min(_MAX_BACKOFF, backoff * 2)


def _start_worker() -> None:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
        threading.Thread(target=_worker, name="dashboard-webhook", daemon=True).start()


def emit(event_type: str, occurred_at: datetime, data: dict) -> bool:
    """Queue a lifecycle event. Never blocks on network I/O or raises to caller."""
    url, secret = _configuration()
    if not url or not secret:
        return False
    payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat(),
        "source": "orb-paper-bot",
        "data": data,
    }
    try:
        _append(payload)
        _start_worker()
        return True
    except Exception as exc:
        print(f"[warn] dashboard webhook queue unavailable ({type(exc).__name__})")
        return False
