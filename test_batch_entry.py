import json

import pytest

from batch_entry import (
    EntryCandidate, PortfolioLimits, parse_batch_response, validate_batch,
)


def _candidate(symbol="RELIANCE.NS", side="BUY", price=100.0):
    return EntryCandidate(
        symbol=symbol, signal_side=side, current_price=price,
        opening_range_high=99.0, opening_range_low=95.0,
        indicators={"trend": "bullish", "vwap": 98.0, "atr14": 1.2},
        sentiment={"status": "unavailable"},
    )


def _decision(symbol="RELIANCE.NS", side="BUY", stop=98.0, target=104.0, rank=1):
    return {
        "symbol": symbol, "decision": side, "confidence": 0.9,
        "reason": "breakout alignment", "stop": stop, "target": target, "rank": rank,
    }


def _limits(**overrides):
    values = dict(
        capital=10000, available_cash=10000, risk_per_trade_pct=1.0,
        max_positions=2, open_positions=0, max_trades_per_day=3,
        trades_today=0, daily_loss_cap_pct=3.0, day_pnl=0.0,
        min_confidence=0.65,
    )
    values.update(overrides)
    return PortfolioLimits(**values)


def test_parser_requires_complete_exact_batch():
    raw = json.dumps({"decisions": [_decision()]})
    assert parse_batch_response(raw, {"RELIANCE.NS"})[0]["symbol"] == "RELIANCE.NS"
    with pytest.raises(ValueError, match="exactly one"):
        parse_batch_response('{"decisions":[]}', {"RELIANCE.NS"})


@pytest.mark.parametrize("bad", [
    [_decision(), _decision()],
    [{**_decision(), "symbol": "UNKNOWN"}],
    [{**_decision(), "confidence": float("nan")}],
    [{**_decision(), "rank": True}],
    [{**_decision(), "stop": None}],
    [{**_decision(), "decision": "HOLD"}],
])
def test_parser_rejects_malformed_or_ambiguous_decisions(bad):
    with pytest.raises(ValueError):
        parse_batch_response(json.dumps({"decisions": bad}), {"RELIANCE.NS"})


def test_skip_must_not_include_order_levels():
    with pytest.raises(ValueError, match="must not propose"):
        parse_batch_response(json.dumps({"decisions": [{
            **_decision(), "decision": "SKIP"
        }]}), {"RELIANCE.NS"})


def test_valid_buy_is_sized_by_risk_and_cash():
    accepted, rejected = validate_batch(
        [_candidate()], [_decision()], _limits()
    )
    assert not rejected
    assert len(accepted) == 1
    assert accepted[0].quantity == 50
    assert accepted[0].risk_amount == 100


def test_rejects_side_reversal_and_bad_stop_geometry():
    accepted, rejected = validate_batch(
        [_candidate(side="BUY")],
        [_decision(side="SELL", stop=102, target=96)],
        _limits(),
    )
    assert not accepted
    assert rejected[0]["reason"] == "side_conflicts_with_breakout_signal"

    accepted, rejected = validate_batch(
        [_candidate()], [_decision(stop=101, target=104)], _limits()
    )
    assert not accepted
    assert rejected[0]["reason"] == "invalid_buy_stop_target_geometry"


def test_hard_limits_are_enforced_across_batch_in_rank_order():
    candidates = [_candidate("A"), _candidate("B", price=100), _candidate("C", price=100)]
    decisions = [
        _decision("A", rank=1), _decision("B", rank=2), _decision("C", rank=3)
    ]
    accepted, rejected = validate_batch(
        candidates, decisions, _limits(max_positions=1, max_trades_per_day=1)
    )
    assert [x.symbol for x in accepted] == ["A"]
    assert [x["reason"] for x in rejected] == ["max_open_positions_reached"] * 2


def test_daily_loss_and_confidence_fail_closed():
    accepted, rejected = validate_batch(
        [_candidate()], [_decision()], _limits(day_pnl=-300)
    )
    assert not accepted
    assert rejected[0]["reason"] == "daily_loss_cap_reached"

    accepted, rejected = validate_batch(
        [_candidate()], [_decision()], _limits(min_confidence=0.95)
    )
    assert not accepted
    assert rejected[0]["reason"] == "confidence_below_threshold"


def test_missing_or_duplicate_decisions_rejected_as_whole_batch():
    with pytest.raises(ValueError, match="exactly once"):
        validate_batch([_candidate()], [], _limits())
    with pytest.raises(ValueError, match="exactly once"):
        validate_batch([_candidate()], [_decision(), _decision()], _limits())


def test_sell_geometry_and_sizing():
    candidate = _candidate("TCS.NS", "SELL", 100)
    decision = _decision("TCS.NS", "SELL", stop=102, target=96)
    accepted, rejected = validate_batch([candidate], [decision], _limits())
    assert not rejected
    assert accepted[0].side == "SELL"
    assert accepted[0].quantity == 50


def test_no_candidates_is_noop():
    assert validate_batch([], [], _limits()) == ([], [])



@pytest.mark.parametrize("overrides", [
    {"daily_loss_cap_pct": 0},
    {"daily_loss_cap_pct": 101},
    {"max_trades_per_day": -1},
    {"trades_today": -1},
    {"open_positions": -1},
    {"capital": float("inf")},
    {"day_pnl": float("nan")},
])
def test_invalid_portfolio_limits_fail_closed(overrides):
    with pytest.raises(ValueError):
        validate_batch([_candidate()], [_decision()], _limits(**overrides))


@pytest.mark.parametrize("bad_decision", [
    {**_decision(), "confidence": float("nan")},
    {**_decision(), "confidence": True},
    {**_decision(), "rank": True},
    {**_decision(), "rank": 0},
    {**_decision(), "decision": "HOLD"},
    {**_decision(), "reason": ""},
])
def test_validator_rejects_unparsed_or_malformed_decisions(bad_decision):
    with pytest.raises(ValueError):
        validate_batch([_candidate()], [bad_decision], _limits())


def test_parser_normalizes_expected_symbol_case():
    parsed = parse_batch_response(
        json.dumps({"decisions": [_decision(symbol="reliance.ns")]}),
        {"reliance.ns"},
    )
    assert parsed[0]["symbol"] == "RELIANCE.NS"
