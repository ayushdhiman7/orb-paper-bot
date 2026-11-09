from types import SimpleNamespace

import nifty50_runner as runner


def _state():
    return SimpleNamespace(
        positions={"RELIANCE.NS": object()},
        last_prices={},
        halted=False,
        daily_loss_cap_triggered=False,
        risk_mark_blocked=False,
    )


def test_temporary_missing_mark_blocks_entries_without_permanent_halt(monkeypatch):
    state = _state()
    prices = {"RELIANCE.NS": None}
    monkeypatch.setattr(runner.core, "last_price", lambda symbol: prices[symbol])
    monkeypatch.setattr(runner.core, "CAPITAL", 10000.0)
    monkeypatch.setattr(runner.core, "DAILY_LOSS_CAP_PCT", 2.0)
    monkeypatch.setattr(runner.core, "marked_day_pnl", lambda _state: -10.0)

    assert runner._enforce_daily_loss_cap(state, object()) is False
    assert state.risk_mark_blocked is True
    assert state.halted is False

    # A fresh mark restores risk evaluation and clears only the temporary block.
    prices["RELIANCE.NS"] = 101.0
    assert runner._enforce_daily_loss_cap(state, object()) is False
    assert state.risk_mark_blocked is False
    assert state.halted is False


def test_missing_mark_after_daily_cap_trigger_stays_latched(monkeypatch):
    state = _state()
    state.daily_loss_cap_triggered = True
    monkeypatch.setattr(runner.core, "last_price", lambda _symbol: None)
    monkeypatch.setattr(runner.core, "CAPITAL", 10000.0)
    monkeypatch.setattr(runner.core, "DAILY_LOSS_CAP_PCT", 2.0)
    monkeypatch.setattr(runner.core, "marked_day_pnl", lambda _state: -250.0)

    assert runner._enforce_daily_loss_cap(state, object()) is False
    assert state.daily_loss_cap_triggered is True
    assert state.halted is True
