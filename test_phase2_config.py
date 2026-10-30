import pytest
from phase2_config import Phase2Settings


def test_defaults_preserve_approved_limits(monkeypatch):
    for key in ("AI_ENTRY_SCAN_SECONDS","AI_POSITION_REVIEW_SECONDS","MAX_OPEN_POSITIONS",
                "RISK_PER_TRADE_PCT","GEMINI_MAX_REQUESTS_PER_DAY","GEMINI_MAX_REQUESTS_PER_MINUTE",
                "AI_MIN_CONFIDENCE","MAX_TRADES_PER_DAY","DAILY_LOSS_CAP_PCT","SQUARE_OFF_TIME"):
        monkeypatch.delenv(key, raising=False)
    settings = Phase2Settings.from_env()
    assert settings.entry_scan_seconds == 180
    assert settings.position_review_seconds == 300
    assert settings.max_positions == 2
    assert settings.risk_per_trade_pct == 1.0
    assert settings.max_gemini_requests_per_day == 100
    assert settings.max_gemini_requests_per_minute == 5
    assert settings.min_ai_confidence == 0.0
    assert settings.square_off_time == "15:15"
    assert settings.paper_only is True


def test_rejects_risk_above_one_percent(monkeypatch):
    monkeypatch.setenv("RISK_PER_TRADE_PCT", "1.1")
    with pytest.raises(ValueError):
        Phase2Settings.from_env()


def test_rejects_invalid_confidence(monkeypatch):
    monkeypatch.setenv("AI_MIN_CONFIDENCE", "1.5")
    with pytest.raises(ValueError):
        Phase2Settings.from_env()
