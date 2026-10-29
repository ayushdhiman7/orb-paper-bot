"""Offline tests for backtest portfolio risk controls."""
from datetime import datetime, timedelta

import pytest

import backtest


def test_daily_loss_cap_blocks_later_entries_after_open_loss(monkeypatch):
    monkeypatch.setattr(backtest, "CAPITAL", 14_000.0)
    monkeypatch.setattr(backtest, "RISK_PCT", 1.0)
    monkeypatch.setattr(backtest, "COST_PCT", 0.0)
    monkeypatch.setattr(backtest, "SLIPPAGE_PCT", 0.0)
    monkeypatch.setattr(backtest, "DAILY_CAP_PCT", 3.0)
    monkeypatch.setattr(backtest, "MAX_TRADES", 3)
    t0 = datetime(2026, 10, 29, 10, 0)
    signals = [
        {"symbol": "LOSS", "side": 1, "entry": 100.0, "stop": 99.0,
         "exit_fill": 96.0, "reason": "stop", "entry_time": t0,
         "exit_time": t0 + timedelta(minutes=20),
         "mark_path": [(t0 + timedelta(minutes=5), 90.0)]},
        {"symbol": "LATER", "side": 1, "entry": 100.0, "stop": 99.0,
         "exit_fill": 102.0, "reason": "target", "entry_time": t0 + timedelta(minutes=10),
         "exit_time": t0 + timedelta(minutes=15),
         "mark_path": [(t0 + timedelta(minutes=12), 102.0)]},
    ]
    trades = backtest.run_day(signals, cost_pct=0.0)
    assert [t["symbol"] for t in trades] == ["LOSS"]


def test_run_day_accepts_signal_without_mark_path(monkeypatch):
    monkeypatch.setattr(backtest, "CAPITAL", 14_000.0)
    monkeypatch.setattr(backtest, "RISK_PCT", 1.0)
    monkeypatch.setattr(backtest, "COST_PCT", 0.0)
    monkeypatch.setattr(backtest, "MAX_TRADES", 3)
    monkeypatch.setattr(backtest, "DAILY_CAP_PCT", 3.0)
    t0 = datetime(2026, 10, 29, 10, 0)
    signal = {"symbol": "TEST", "side": 1, "entry": 100.0, "stop": 99.0,
              "exit_fill": 102.0, "reason": "target", "entry_time": t0,
              "exit_time": t0 + timedelta(minutes=5)}
    assert len(backtest.run_day([signal], cost_pct=0.0)) == 1



def test_daily_loss_cap_blocks_later_entries_after_open_short_loss(monkeypatch):
    monkeypatch.setattr(backtest, "CAPITAL", 14_000.0)
    monkeypatch.setattr(backtest, "RISK_PCT", 1.0)
    monkeypatch.setattr(backtest, "COST_PCT", 0.0)
    monkeypatch.setattr(backtest, "SLIPPAGE_PCT", 0.0)
    monkeypatch.setattr(backtest, "DAILY_CAP_PCT", 3.0)
    monkeypatch.setattr(backtest, "MAX_TRADES", 3)
    t0 = datetime(2026, 10, 29, 10, 0)
    signals = [
        {"symbol": "SHORT_LOSS", "side": -1, "entry": 100.0, "stop": 101.0,
         "exit_fill": 104.0, "reason": "stop", "entry_time": t0,
         "exit_time": t0 + timedelta(minutes=20),
         "mark_path": [(t0 + timedelta(minutes=5), 110.0)]},
        {"symbol": "LATER", "side": 1, "entry": 100.0, "stop": 99.0,
         "exit_fill": 102.0, "reason": "target", "entry_time": t0 + timedelta(minutes=10),
         "exit_time": t0 + timedelta(minutes=15),
         "mark_path": [(t0 + timedelta(minutes=12), 102.0)]},
    ]
    trades = backtest.run_day(signals, cost_pct=0.0)
    assert [t["symbol"] for t in trades] == ["SHORT_LOSS"]
    assert trades[0]["net"] < -(backtest.CAPITAL * backtest.DAILY_CAP_PCT / 100.0)



def test_backtest_long_and_short_net_matches_round_trip_accounting(monkeypatch):
    monkeypatch.setattr(backtest, "CAPITAL", 14_000.0)
    monkeypatch.setattr(backtest, "RISK_PCT", 1.0)
    monkeypatch.setattr(backtest, "COST_PCT", 0.10)
    monkeypatch.setattr(backtest, "SLIPPAGE_PCT", 0.0)
    monkeypatch.setattr(backtest, "DAILY_CAP_PCT", 99.0)
    monkeypatch.setattr(backtest, "MAX_TRADES", 3)
    t0 = datetime(2026, 10, 29, 10, 0)

    for side, exit_fill in ((1, 101.0), (-1, 99.0)):
        signal = {
            "symbol": f"SIDE_{side}", "side": side, "entry": 100.0,
            "stop": 99.0 if side == 1 else 101.0, "exit_fill": exit_fill,
            "reason": "fixture", "entry_time": t0,
            "exit_time": t0 + timedelta(minutes=5),
        }
        trade = backtest.run_day([signal], cost_pct=0.10)[0]
        entry_notional = trade["entry"] * trade["qty"]
        exit_notional = trade["qty"] * exit_fill
        entry_fee = entry_notional * 0.05 / 100.0
        exit_fee = exit_notional * 0.05 / 100.0
        gross = (exit_fill - trade["entry"]) * trade["qty"] * side
        assert trade["gross"] == gross
        assert trade["entry_fee"] == entry_fee
        assert trade["exit_fee"] == exit_fee
        assert trade["net"] == gross - entry_fee - exit_fee


def _bars():
    import pandas as pd
    idx = pd.DatetimeIndex([datetime(2026, 10, 29, 9, 15) + timedelta(minutes=5 * i) for i in range(7)])
    rows = [  # open, high, low, close
        (100, 101.0, 99.0, 100), (100, 101.0, 99.0, 100), (100, 101.0, 99.0, 100),   # opening range 99-101
        (101.0, 101.4, 100.9, 101.3),   # 09:30 breakout, close 0.3% above the high
        (101.3, 102.5, 101.2, 101.4),   # 1.2 up: past 1R (risk is about 1.01)
        (101.4, 101.5, 101.0, 101.2),   # pulls back through the entry
        (101.2, 101.3, 100.0, 100.3),   # later falls through the original stop
    ]
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close"])


def _no_costs(monkeypatch):
    monkeypatch.setattr(backtest, "SLIPPAGE_PCT", 0.0)
    monkeypatch.setattr(backtest, "COST_PCT", 0.0)


def test_exit_rules_beat_baseline_stop_when_trade_fades(monkeypatch):
    _no_costs(monkeypatch)
    base = backtest.find_signal("T", _bars(), 1.0, 1.5)
    assert base["reason"] == "stop" and base["exit_fill"] == pytest.approx(101.3 * 0.99)
    be = backtest.find_signal("T", _bars(), 1.0, 1.5, {"exit_rule": "breakeven_1R"})
    assert be["reason"] == "breakeven_1R" and be["exit_fill"] == pytest.approx(101.3)
    gb = backtest.find_signal("T", _bars(), 1.0, 1.5, {"exit_rule": "giveback_50"})
    assert gb["reason"] == "giveback_50" and gb["exit_fill"] == pytest.approx(101.3 + 1.2 / 2)
    assert be["stop"] == base["stop"]          # position sizing still uses the original stop


def test_effective_stop_never_loosens_original_stop():
    for rule in ("breakeven_1R", "giveback_50", "trail_1R"):
        assert backtest.effective_stop(rule, 1, 100.0, 99.0, 100.5) == 99.0       # not yet 1R: unchanged
        assert backtest.effective_stop(rule, 1, 100.0, 99.0, 102.0) >= 99.0
        assert backtest.effective_stop(rule, -1, 100.0, 101.0, 98.0) <= 101.0
    assert backtest.effective_stop(None, 1, 100.0, 99.0, 150.0) == 99.0


def test_breakout_buffer_skips_marginal_breakouts(monkeypatch):
    _no_costs(monkeypatch)
    assert backtest.find_signal("T", _bars(), 1.0, 1.5, {"min_break": 0.1}) is not None
    assert backtest.find_signal("T", _bars(), 1.0, 1.5, {"min_break": 0.5}) is None
