"""Offline tests for Telegram alerts and the watchdog rules."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import notify
import watchdog

IST = ZoneInfo("Asia/Kolkata")
OPEN_T = datetime(2026, 10, 30, 11, 0, tzinfo=IST)       # a Friday, market hours


def test_send_is_noop_without_credentials(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify.send("hi") is False


def test_send_posts_and_never_leaks_token_on_failure(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRET-TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    seen = {}

    def ok(req, timeout):
        seen["url"], seen["timeout"] = req.full_url, timeout
        return type("R", (), {"read": lambda self: b"{}"})()
    monkeypatch.setattr(notify.urllib.request, "urlopen", ok)
    assert notify.send("hello") is True and seen["timeout"] <= 5

    def boom(req, timeout):
        raise OSError("failed for " + req.full_url)
    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    assert notify.send("again") is False
    assert "SECRET-TOKEN" not in capsys.readouterr().out


def test_once_key_prevents_repeat_messages(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(notify.urllib.request, "urlopen",
                        lambda req, timeout: type("R", (), {"read": lambda self: b"{}"})())
    notify._SENT.clear()
    assert notify.send("x", once_key="k") is True
    assert notify.send("x", once_key="k") is False


def test_watchdog_flags_stopped_service_and_stale_price():
    stale = {"symbol": "TCS.NS", "last_price_ts": (OPEN_T - timedelta(minutes=25)).isoformat()}
    fresh = {"symbol": "INFY.NS", "last_price_ts": (OPEN_T - timedelta(minutes=2)).isoformat()}
    p = watchdog.evaluate(OPEN_T, False, [stale, fresh])
    assert set(p) == {"service", "stale:TCS.NS"}
    assert watchdog.evaluate(OPEN_T, True, [fresh]) == {}


def test_watchdog_quiet_outside_market_hours_and_weekends():
    assert watchdog.evaluate(datetime(2026, 10, 30, 20, 0, tzinfo=IST), False, []) == {}
    assert watchdog.evaluate(datetime(2026, 10, 31, 11, 0, tzinfo=IST), False, []) == {}   # Saturday


def test_watchdog_alerts_once_then_reports_recovery():
    cur = {"service": "orb-bot is NOT running during market hours."}
    assert len(watchdog.diff_alerts({}, cur)) == 1
    assert watchdog.diff_alerts(cur, cur) == []
    assert watchdog.diff_alerts(cur, {})[0].startswith("RESOLVED")
