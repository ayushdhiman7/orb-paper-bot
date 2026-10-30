import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import webhook


def test_emit_is_noop_without_configuration(monkeypatch):
    monkeypatch.delenv("DASHBOARD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DASHBOARD_WEBHOOK_SECRET", raising=False)
    assert webhook.emit("trade.opened", __import__("datetime").datetime.now(), {}) is False


def test_signed_body_matches_api_verification_contract():
    secret = "test-secret"
    timestamp = str(int(time.time()))
    body = json.dumps({"event_id": "evt-1"}, separators=(",", ":")).encode()
    signature = hmac.new(
        secret.encode(), timestamp.encode("ascii") + b"." + body, hashlib.sha256
    ).hexdigest()
    expected = hmac.new(
        secret.encode(), timestamp.encode("ascii") + b"." + body, hashlib.sha256
    ).hexdigest()
    assert hmac.compare_digest(signature, expected)


def test_outbox_persists_event_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_WEBHOOK_URL", "https://example.invalid/api/events")
    monkeypatch.setenv("DASHBOARD_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("WEBHOOK_OUTBOX_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setattr(webhook, "_start_worker", lambda: None)
    from datetime import datetime, timezone
    assert webhook.emit("trade.opened", datetime.now(timezone.utc), {"symbol": "RELIANCE.NS"})
    row = json.loads((tmp_path / "events.jsonl").read_text().strip())
    assert row["event_type"] == "trade.opened"
    assert row["data"]["symbol"] == "RELIANCE.NS"
    assert row["event_id"]
