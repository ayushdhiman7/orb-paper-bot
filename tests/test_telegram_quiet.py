from datetime import datetime

import nifty50_runner as runner


def test_same_line_is_sent_once_per_day_and_again_tomorrow():
    runner._NOTICE_SEEN.clear()
    day1 = datetime(2026, 11, 11, 10, 0)
    assert runner._fresh_lines("k", ["A REJECTED", "B REJECTED"], day1) == ["A REJECTED", "B REJECTED"]
    assert runner._fresh_lines("k", ["A REJECTED", "C REJECTED"], day1) == ["C REJECTED"]
    assert runner._fresh_lines("k", ["A REJECTED"], day1) == []
    assert runner._fresh_lines("k", ["A REJECTED"], datetime(2026, 11, 12, 10, 0)) == ["A REJECTED"]


def test_kinds_do_not_share_history():
    runner._NOTICE_SEEN.clear()
    now = datetime(2026, 11, 11, 10, 0)
    assert runner._fresh_lines("x", ["same"], now) == ["same"]
    assert runner._fresh_lines("y", ["same"], now) == ["same"]


def test_detail_messages_are_off_unless_verbose(monkeypatch):
    monkeypatch.delenv("TELEGRAM_VERBOSE", raising=False)
    assert runner._chatty() is False
    monkeypatch.setenv("TELEGRAM_VERBOSE", "on")
    assert runner._chatty() is True
