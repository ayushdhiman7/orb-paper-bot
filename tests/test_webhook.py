import hashlib
import hmac
import json
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import webhook


def test_emit_is_noop_without_configuration(monkeypatch):
    monkeypatch.delenv("DASHBOARD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DASHBOARD_WEBHOOK_SECRET", raising=False)
    assert webhook.emit("trade.opened", datetime.now(timezone.utc), {}) is False


def test_post_sends_signature_accepted_by_api_contract():
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            received["timestamp"] = self.headers["X-ORB-Timestamp"]
            received["signature"] = self.headers["X-ORB-Signature"]
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = {"event_id": "evt-1", "event_type": "trade.opened", "data": {"symbol": "RELIANCE.NS"}}
        assert webhook._post(payload, f"http://127.0.0.1:{server.server_port}/api/events", "test-secret")
        expected = hmac.new(
            b"test-secret",
            received["timestamp"].encode("ascii") + b"." + received["body"],
            hashlib.sha256,
        ).hexdigest()
        assert received["signature"] == "sha256=" + expected
        assert json.loads(received["body"]) == payload
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_outbox_persists_event_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_WEBHOOK_URL", "https://example.invalid/api/events")
    monkeypatch.setenv("DASHBOARD_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("WEBHOOK_OUTBOX_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setattr(webhook, "start", lambda: True)
    assert webhook.emit("trade.opened", datetime.now(timezone.utc), {"symbol": "RELIANCE.NS"})
    row = json.loads((tmp_path / "events.jsonl").read_text().strip())
    assert row["event_type"] == "trade.opened"
    assert row["data"]["symbol"] == "RELIANCE.NS"
    assert row["event_id"]


def test_start_requires_webhook_configuration(monkeypatch):
    monkeypatch.delenv("DASHBOARD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DASHBOARD_WEBHOOK_SECRET", raising=False)
    assert webhook.start() is False
