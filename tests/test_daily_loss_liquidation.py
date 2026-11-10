from types import SimpleNamespace

import nifty50_runner as runner


def _state(symbols, day_pnl):
    return SimpleNamespace(
        positions={symbol: object() for symbol in symbols},
        last_prices={},
        day_pnl=day_pnl,
        halted=False,
    )


def test_daily_loss_cap_closes_every_open_paper_position(monkeypatch):
    state = _state(["RELIANCE", "TCS"], -25.0)
    closed = []
    alerts = []

    monkeypatch.setattr(runner.core, "CAPITAL", 1000.0)
    monkeypatch.setattr(runner.core, "DAILY_LOSS_CAP_PCT", 2.0)
    monkeypatch.setattr(runner.core, "last_price", lambda symbol: 100.0)
    monkeypatch.setattr(runner.core, "marked_day_pnl", lambda current: current.day_pnl)

    def close_position(current, symbol, price, reason, now):
        assert reason == "daily_loss_cap"
        closed.append((symbol, price))
        current.positions.pop(symbol)
        return True

    monkeypatch.setattr(runner.core, "close_position", close_position)
    monkeypatch.setattr(runner.notify, "send", lambda message, **kwargs: alerts.append(message))

    assert runner._enforce_daily_loss_cap(state, None) is True
    assert state.halted is True
    assert state.positions == {}
    assert {symbol for symbol, _ in closed} == {"RELIANCE", "TCS"}
    assert any("All paper positions closed" in message for message in alerts)


def test_daily_loss_cap_waits_for_fresh_quote_and_blocks_entries(monkeypatch):
    state = _state(["RELIANCE", "TCS"], -50.0)
    closed = []

    monkeypatch.setattr(runner.core, "CAPITAL", 1000.0)
    monkeypatch.setattr(runner.core, "DAILY_LOSS_CAP_PCT", 2.0)
    monkeypatch.setattr(
        runner.core, "last_price",
        lambda symbol: 100.0 if symbol == "RELIANCE" else None,
    )
    monkeypatch.setattr(runner.core, "marked_day_pnl", lambda current: current.day_pnl)
    monkeypatch.setattr(
        runner.core, "close_position",
        lambda *args, **kwargs: closed.append(args[1]) or True,
    )
    monkeypatch.setattr(runner.notify, "send", lambda *args, **kwargs: None)

    assert runner._enforce_daily_loss_cap(state, None) is False
    assert state.risk_mark_blocked is True
    assert state.halted is False
    assert set(state.positions) == {"RELIANCE", "TCS"}
    assert closed == []


def test_daily_loss_cap_does_not_liquidate_below_threshold(monkeypatch):
    state = _state(["RELIANCE"], -10.0)
    closed = []

    monkeypatch.setattr(runner.core, "CAPITAL", 1000.0)
    monkeypatch.setattr(runner.core, "DAILY_LOSS_CAP_PCT", 2.0)
    monkeypatch.setattr(runner.core, "last_price", lambda symbol: 100.0)
    monkeypatch.setattr(runner.core, "marked_day_pnl", lambda current: current.day_pnl)
    monkeypatch.setattr(
        runner.core, "close_position",
        lambda *args, **kwargs: closed.append(args[1]) or True,
    )
    monkeypatch.setattr(runner.notify, "send", lambda *args, **kwargs: None)

    assert runner._enforce_daily_loss_cap(state, None) is False
    assert state.halted is False
    assert set(state.positions) == {"RELIANCE"}
    assert closed == []


def test_daily_loss_cap_closes_fresh_positions_while_retrying_missing_symbol(monkeypatch):
    state = _state(["RELIANCE", "TCS"], -25.0)
    state.daily_loss_cap_triggered = True
    closed = []
    monkeypatch.setattr(runner.core, "CAPITAL", 1000.0)
    monkeypatch.setattr(runner.core, "DAILY_LOSS_CAP_PCT", 2.0)
    monkeypatch.setattr(
        runner.core, "last_price",
        lambda symbol: 100.0 if symbol == "RELIANCE" else None,
    )
    monkeypatch.setattr(runner.core, "marked_day_pnl", lambda current: current.day_pnl)

    def close_position(current, symbol, price, reason, now):
        closed.append((symbol, price, reason))
        current.positions.pop(symbol)
        return True

    monkeypatch.setattr(runner.core, "close_position", close_position)
    monkeypatch.setattr(runner.notify, "send", lambda *args, **kwargs: None)

    assert runner._enforce_daily_loss_cap(state, None, cap_triggered=True) is False
    assert state.halted is True
    assert closed == [("RELIANCE", 100.0, "daily_loss_cap")]
    assert set(state.positions) == {"TCS"}


def test_square_off_uses_last_mark_flagged_estimated_when_quote_missing(monkeypatch):
    from datetime import datetime, time
    state = _state(["RELIANCE", "TCS"], 0.0)
    state.last_prices = {"RELIANCE": 101.0}
    calls = []
    monkeypatch.setattr(runner.core, "SQUARE_OFF_FALLBACK", time(15, 25))
    monkeypatch.setattr(runner.core, "last_price", lambda symbol: 100.0 if symbol == "TCS" else None)

    def close_position(current, symbol, price, reason, now, note=None, estimated=False):
        calls.append((symbol, price, estimated))
        current.positions.pop(symbol)
        return True

    monkeypatch.setattr(runner.core, "close_position", close_position)
    runner._square_off_all(state, datetime(2026, 11, 11, 15, 31))
    assert sorted(calls) == [("RELIANCE", 101.0, True), ("TCS", 100.0, False)]


def test_square_off_before_fallback_waits_for_quote(monkeypatch):
    from datetime import datetime, time
    state = _state(["RELIANCE"], 0.0)
    state.last_prices = {"RELIANCE": 101.0}
    monkeypatch.setattr(runner.core, "SQUARE_OFF_FALLBACK", time(15, 25))
    monkeypatch.setattr(runner.core, "last_price", lambda symbol: None)
    monkeypatch.setattr(runner.core, "close_position", lambda *a, **k: (_ for _ in ()).throw(AssertionError("closed")))
    runner._square_off_all(state, datetime(2026, 11, 11, 15, 10))
    assert "RELIANCE" in state.positions
