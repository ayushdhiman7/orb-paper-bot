from datetime import datetime, timezone

import pytest

from ai_manager import ManagementDecision
from nifty50_position_manager import (
    parse_management_batch, protective_stop, validate_management_batch,
)


NOW = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)


def _position():
    return {
        "symbol": "RELIANCE", "side": "BUY", "qty": 10, "entry": 100.0,
        "stop": 98.0, "target": 106.0, "opened_at": NOW,
        "peak_price": 102.0,
    }


def test_batch_parser_requires_exact_symbol_coverage():
    raw = '{"decisions":[{"symbol":"RELIANCE","action":"HOLD","reason":"setup intact","confidence":0.8,"new_stop":null,"new_target":null}]}'
    parsed = parse_management_batch(raw, {"RELIANCE"})
    assert parsed["decisions"][0]["decision"].action == "HOLD"
    with pytest.raises(ValueError):
        parse_management_batch('{"decisions":[]}', {"RELIANCE"})


def test_management_validator_rejects_stop_widening():
    positions = [_position()]
    response = {"decisions": [{
        "symbol": "RELIANCE",
        "decision": ManagementDecision("MOVE_SL", "widen", 0.9, new_stop=97.0),
    }]}
    approved, rejected = validate_management_batch(
        positions, {"RELIANCE": 101.0}, NOW, response,
    )
    assert approved == []
    assert rejected[0]["reason"] == "stop_would_widen_risk"


def test_profit_protection_at_one_r_and_one_half_r():
    pos = {"entry": 100.0, "stop": 98.0, "side": "BUY",
           "round_trip_cost_per_share": 0.1}
    stop_1r, trigger_1r = protective_stop(
        pos, 102.0, one_r=1.0, one_half_r=1.5, two_r=2.0,
    )
    assert stop_1r >= 100.1
    assert trigger_1r == "breakeven_1r"
    stop_15r, trigger_15r = protective_stop(
        {**pos, "stop": stop_1r}, 103.0,
        one_r=1.0, one_half_r=1.5, two_r=2.0,
    )
    assert stop_15r >= 101.1
    assert trigger_15r == "protect_0_5r"


def test_two_r_trailing_uses_tighter_of_atr_and_swing_support():
    pos = {"entry": 100.0, "stop": 98.0, "side": "BUY"}
    stop, trigger = protective_stop(
        pos, 104.0, one_r=1.0, one_half_r=1.5, two_r=2.0,
        atr=1.0, recent_lows=[102.0, 102.5, 103.0],
    )
    assert stop == 103.0
    assert trigger == "trail_2r"
