import json
from datetime import datetime
import pytest

from ai_manager import (
    GeminiQuota, ManagementDecision, PositionContext,
    parse_entry_batch_response, parse_management_response,
    validate_management_decision,
)


def context(side="BUY"):
    return PositionContext(
        symbol="RELIANCE", side=side, quantity=10, entry=100,
        current_price=110 if side == "BUY" else 90,
        stop=95 if side == "BUY" else 105,
        target=115 if side == "BUY" else 85,
        opened_at=datetime(2026, 10, 30, 10, 0),
        peak_price=112 if side == "BUY" else 88,
        risk_per_share=5,
    )


@pytest.mark.parametrize("action", ["HOLD", "EXIT"])
def test_hold_and_exit_are_valid_actions(action):
    d = ManagementDecision(action, "valid", 0.9)
    assert validate_management_decision(context(), d)[0]


def test_move_stop_only_tightens_buy_and_sell():
    assert validate_management_decision(context(), ManagementDecision("MOVE_SL", "tighten", .9, new_stop=103))[0]
    assert validate_management_decision(context("SELL"), ManagementDecision("MOVE_SL", "tighten", .9, new_stop=97))[0]
    assert validate_management_decision(context(), ManagementDecision("MOVE_SL", "loosen", .9, new_stop=94))[1] == "stop_would_widen_risk"


def test_lock_profit_must_be_profitable_and_not_cross_current_price():
    assert validate_management_decision(context(), ManagementDecision("LOCK_PROFIT", "lock", .9, new_stop=102))[0]
    assert validate_management_decision(context(), ManagementDecision("LOCK_PROFIT", "bad", .9, new_stop=99))[1] == "profit_lock_must_be_above_entry"
    assert validate_management_decision(context(), ManagementDecision("LOCK_PROFIT", "bad", .9, new_stop=111))[1] == "stop_not_below_current_price"


def test_target_can_only_be_extended_in_profit_direction():
    assert validate_management_decision(context(), ManagementDecision("UPDATE_TARGET", "extend", .9, new_target=120))[0]
    assert validate_management_decision(context(), ManagementDecision("UPDATE_TARGET", "reduce", .9, new_target=114))[1] == "target_must_move_further_in_profit_direction"


def test_low_confidence_or_missing_prices_fail_closed():
    assert validate_management_decision(context(), ManagementDecision("EXIT", "low", .5))[1] == "confidence_below_threshold"
    with pytest.raises(ValueError):
        parse_management_response('{"action":"MOVE_SL","reason":"x","confidence":0.9}')


def test_parser_accepts_expected_management_schema_only():
    d = parse_management_response(json.dumps({
        "action": "LOCK_PROFIT", "reason": "protect open gain", "confidence": .88,
        "new_stop": 104, "new_target": None,
    }))
    assert d.action == "LOCK_PROFIT"
    assert d.new_stop == 104


def test_invalid_action_and_confidence_are_rejected():
    with pytest.raises(ValueError):
        parse_management_response('{"action":"BUY","reason":"x","confidence":0.9}')
    with pytest.raises(ValueError):
        parse_management_response('{"action":"HOLD","reason":"x","confidence":1.1}')


def test_gemini_quota_enforces_5_per_minute_and_100_per_day():
    epoch = [1000.0]
    quota = GeminiQuota(daily_limit=100, per_minute_limit=5, clock=lambda: epoch[0])
    now = datetime(2026, 10, 30, 10, 0)
    for _ in range(5):
        assert quota.reserve(now)[0]
    assert quota.reserve(now) == (False, "per_minute_quota_exhausted")
    epoch[0] += 61
    for _ in range(5):
        assert quota.reserve(now)[0]


def test_gemini_quota_resets_on_ist_day_change():
    epoch = [1000.0]
    quota = GeminiQuota(daily_limit=1, per_minute_limit=5, clock=lambda: epoch[0])
    assert quota.reserve(datetime(2026, 10, 30, 10, 0))[0]
    assert quota.reserve(datetime(2026, 10, 30, 10, 1))[0] is False
    assert quota.reserve(datetime(2026, 10, 31, 10, 0))[0]


def test_batch_parser_requires_exact_unique_candidate_set():
    raw = json.dumps({"decisions": [
        {"symbol":"RELIANCE.NS","decision":"BUY","confidence":.8,"reason":"breakout aligned"},
        {"symbol":"TCS.NS","decision":"SKIP","confidence":.7,"reason":"weak volume"},
    ]})
    result = parse_entry_batch_response(raw, {"RELIANCE.NS", "TCS.NS"})
    assert [x["decision"] for x in result] == ["BUY", "SKIP"]
    with pytest.raises(ValueError):
        parse_entry_batch_response(raw, {"RELIANCE.NS", "INFY.NS"})


def test_batch_parser_rejects_duplicate_symbols():
    item = {"symbol":"RELIANCE.NS","decision":"SKIP","confidence":.8,"reason":"no setup"}
    raw = json.dumps({"decisions":[item,item]})
    with pytest.raises(ValueError):
        parse_entry_batch_response(raw, {"RELIANCE.NS"})
