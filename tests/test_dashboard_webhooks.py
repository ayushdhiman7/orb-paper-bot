import asyncio
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard-api"))
import app as dashboard_api


def make_request(payload, secret="test-secret", signature_prefix="sha256="):
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    signature = signature_prefix + digest
    headers = [
        (b"x-orb-timestamp", timestamp.encode()),
        (b"x-orb-signature", signature.encode()),
    ]
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/api/events",
        "raw_path": b"/api/events", "query_string": b"", "headers": headers,
        "client": ("127.0.0.1", 1234), "server": ("test", 80),
    }
    return Request(scope, receive), body, timestamp, signature


class FakeQuery:
    def __init__(self):
        self.values = None
        self.options = None

    def upsert(self, values, **options):
        self.values, self.options = values, options
        return self

    def execute(self):
        return type("Response", (), {"data": []})()


class FakeClient:
    def __init__(self):
        self.query = FakeQuery()

    def table(self, name):
        assert name == "dashboard_events"
        return self.query


def test_ingest_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("DASHBOARD_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(dashboard_api, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(dashboard_api, "SUPABASE_KEY", "service-key")
    request, _, _, _ = make_request({"event_id": "evt-1"}, signature_prefix="bad=")
    with pytest.raises(HTTPException) as error:
        asyncio.run(dashboard_api.ingest_event(request))
    assert error.value.status_code == 401


def test_ingest_persists_valid_event_and_uses_idempotent_upsert(monkeypatch):
    monkeypatch.setenv("DASHBOARD_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(dashboard_api, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(dashboard_api, "SUPABASE_KEY", "service-key")
    client = FakeClient()
    monkeypatch.setattr(dashboard_api, "create_client", lambda *_: client)
    payload = {
        "event_id": "evt-unique", "event_type": "trade.opened",
        "occurred_at": "2026-10-30T09:30:00+05:30",
        "source": "orb-paper-bot", "data": {"symbol": "RELIANCE.NS"},
    }
    request, _, _, _ = make_request(payload)
    result = asyncio.run(dashboard_api.ingest_event(request))
    assert result == {"status": "accepted", "event_id": "evt-unique"}
    assert client.query.values["event_id"] == "evt-unique"
    assert client.query.options == {"on_conflict": "event_id", "ignore_duplicates": True}


def test_ingest_rejects_timezone_naive_timestamp(monkeypatch):
    monkeypatch.setenv("DASHBOARD_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(dashboard_api, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(dashboard_api, "SUPABASE_KEY", "service-key")
    request, _, _, _ = make_request({
        "event_id": "evt-naive", "event_type": "trade.opened",
        "occurred_at": "2026-10-30T09:30:00", "data": {},
    })
    with pytest.raises(HTTPException) as error:
        asyncio.run(dashboard_api.ingest_event(request))
    assert error.value.status_code == 422
    assert error.value.detail == "Invalid event timestamp"


def test_ingest_returns_service_unavailable_without_database_config(monkeypatch):
    monkeypatch.setenv("DASHBOARD_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(dashboard_api, "SUPABASE_URL", None)
    monkeypatch.setattr(dashboard_api, "SUPABASE_KEY", None)
    request, _, _, _ = make_request({
        "event_id": "evt-no-db", "event_type": "trade.opened",
        "occurred_at": "2026-10-30T09:30:00+05:30", "data": {},
    })
    with pytest.raises(HTTPException) as error:
        asyncio.run(dashboard_api.ingest_event(request))
    assert error.value.status_code == 503
