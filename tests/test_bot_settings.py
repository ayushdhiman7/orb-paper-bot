import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard-api"))
import app as dashboard_api


def test_defaults_are_paper_only_and_match_balanced_strategy():
    assert dashboard_api.DEFAULT_BOT_SETTINGS["paper_only"] is True
    assert dashboard_api.DEFAULT_BOT_SETTINGS["scan_interval_seconds"] == 180
    assert dashboard_api.DEFAULT_BOT_SETTINGS["position_review_seconds"] == 300
    assert dashboard_api.DEFAULT_BOT_SETTINGS["max_open_positions"] == 2
    assert dashboard_api.DEFAULT_BOT_SETTINGS["daily_loss_cap_pct"] == 2.0


def test_rejects_attempt_to_disable_paper_only():
    with pytest.raises(HTTPException) as error:
        dashboard_api._validate_bot_settings({"paper_only": False})
    assert error.value.status_code == 422


def test_rejects_fractional_integer_settings():
    with pytest.raises(HTTPException) as error:
        dashboard_api._validate_bot_settings({"max_open_positions": 1.5})
    assert error.value.status_code == 422


def test_rejects_risk_above_approved_maximum():
    with pytest.raises(HTTPException) as error:
        dashboard_api._validate_bot_settings({"risk_per_trade_pct": 1.5})
    assert error.value.status_code == 422


def test_accepts_valid_partial_update():
    result = dashboard_api._validate_bot_settings({
        "scan_interval_seconds": 240,
        "emergency_stop": True,
        "square_off_time": "15:20",
    })
    assert result == {
        "scan_interval_seconds": 240,
        "emergency_stop": True,
        "square_off_time": "15:20",
    }


def test_rejects_inconsistent_profit_protection_thresholds():
    with pytest.raises(HTTPException) as error:
        dashboard_api._validate_setting_relationships({
            "breakeven_r": 1.5,
            "profit_protection_r": 1.2,
            "protected_profit_r": 0.5,
            "trailing_start_r": 2.0,
        })
    assert error.value.status_code == 422


def test_accepts_balanced_profit_protection_thresholds():
    dashboard_api._validate_setting_relationships({
        "breakeven_r": 1.0,
        "profit_protection_r": 1.5,
        "protected_profit_r": 0.5,
        "trailing_start_r": 2.0,
    })


def test_under_25_report_endpoint_serves_only_valid_research_report(tmp_path, monkeypatch):
    report_path = tmp_path / "report.json"
    report_path.write_text('{"mode":"research_only","paper_only":true,"orders_submitted":0,"candidates":[]}')
    monkeypatch.setenv("LOW_PRICE_REPORT_PATH", str(report_path))
    assert dashboard_api.under_25_research_report()["orders_submitted"] == 0


def test_under_25_report_endpoint_rejects_non_research_payload(tmp_path, monkeypatch):
    report_path = tmp_path / "report.json"
    report_path.write_text('{"mode":"live","paper_only":false}')
    monkeypatch.setenv("LOW_PRICE_REPORT_PATH", str(report_path))
    with pytest.raises(HTTPException) as error:
        dashboard_api.under_25_research_report()
    assert error.value.status_code == 503


def test_under_25_report_endpoint_returns_not_found_before_first_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("LOW_PRICE_REPORT_PATH", str(tmp_path / "missing.json"))
    with pytest.raises(HTTPException) as error:
        dashboard_api.under_25_research_report()
    assert error.value.status_code == 404
