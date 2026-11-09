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


def test_daily_loss_cap_waits_for_fresh_quote_and_keeps_entries_halted(monkeypatch):
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
    assert state.halted is True
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
