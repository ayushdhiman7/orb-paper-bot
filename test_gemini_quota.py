from datetime import datetime, timezone, timedelta
import json
import os

import pytest

from gemini_quota import PersistentGeminiQuota, QuotaStateError


def test_daily_and_rolling_minute_limits_persist_across_instances(tmp_path):
    now_epoch = [1793365200.0]
    clock = lambda: now_epoch[0]
    path = tmp_path / "quota.json"
    now = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
    quota = PersistentGeminiQuota(2, 2, path=path, clock=clock)

    assert quota.reserve(now) == (True, "reserved")
    assert quota.reserve(now) == (True, "reserved")
    assert quota.reserve(now) == (False, "daily_quota_exhausted")

    restarted = PersistentGeminiQuota(2, 2, path=path, clock=clock)
    assert restarted.snapshot()["count"] == 2
    now_epoch[0] += 61
    assert restarted.reserve(now) == (False, "daily_quota_exhausted")


def test_rolling_minute_limit_resets_after_sixty_seconds(tmp_path):
    now_epoch = [1000.0]
    quota = PersistentGeminiQuota(10, 2, path=tmp_path / "q.json", clock=lambda: now_epoch[0])
    now = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
    assert quota.reserve(now)[0]
    assert quota.reserve(now)[0]
    assert quota.reserve(now) == (False, "per_minute_quota_exhausted")
    now_epoch[0] += 60
    assert quota.reserve(now)[0]


def test_ist_calendar_day_rollover_resets_daily_count(tmp_path):
    epoch = [1000.0]
    quota = PersistentGeminiQuota(1, 5, path=tmp_path / "q.json", clock=lambda: epoch[0])
    before_midnight_ist = datetime(2026, 10, 30, 18, 29, tzinfo=timezone.utc)
    after_midnight_ist = datetime(2026, 10, 30, 18, 31, tzinfo=timezone.utc)
    assert quota.reserve(before_midnight_ist)[0]
    assert quota.reserve(after_midnight_ist)[0]
    assert quota.snapshot()["day"] == "2026-10-31"


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "q.json"
    path.write_text("{broken", encoding="utf-8")
    quota = PersistentGeminiQuota(path=path)
    with pytest.raises(QuotaStateError):
        quota.reserve(datetime.now(timezone.utc))


def test_state_file_is_private(tmp_path):
    quota = PersistentGeminiQuota(path=tmp_path / "q.json", clock=lambda: 1000.0)
    assert quota.reserve(datetime.now(timezone.utc))[0]
    assert os.stat(quota.path).st_mode & 0o777 == 0o600
