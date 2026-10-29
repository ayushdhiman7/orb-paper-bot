"""Offline tests for backtest portfolio risk controls."""
from datetime import datetime, timedelta

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
