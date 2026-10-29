"""Offline regression tests for paper-trading accounting and risk controls."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import bot


IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 29, 10, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def safe_paper_config(monkeypatch):
    monkeypatch.setattr(bot, "CAPITAL", 14_000.0)
    monkeypatch.setattr(bot, "COST_PCT", 0.10)
    monkeypatch.setattr(bot, "SLIPPAGE_PCT", 0.05)
    monkeypatch.setattr(bot, "DAILY_LOSS_CAP_PCT", 3.0)
    monkeypatch.setattr(bot, "log_trade", lambda *args, **kwargs: None)


@pytest.mark.parametrize("side,direction", [("BUY", 1), ("SELL", -1)])
def test_close_position_books_round_trip_cost_once(monkeypatch, side, direction):
    qty, entry, market_exit = 10, 100.0, 105.0 if direction == 1 else 95.0
    entry_fill = bot.adverse_fill(entry, direction, is_entry=True)
    entry_fee = bot.fee_for_notional(qty * entry_fill)
    state = bot.State(
        cash=bot.CAPITAL - qty * entry_fill - entry_fee,
        day_pnl=-entry_fee,
        positions={
            "TEST": bot.Position(
                "TEST", side, qty, entry_fill,
                entry_fill * (1 - direction * 0.01),
                entry_fill * (1 + direction * 0.015),
                NOW, entry_fee=entry_fee,
            )
        },
    )
    bot.close_position(state, "TEST", market_exit, "test", NOW)
    exit_fill = bot.adverse_fill(market_exit, direction, is_entry=False)
    gross = (exit_fill - entry_fill) * qty * direction
    exit_fee = bot.fee_for_notional(qty * exit_fill)
    expected_net = gross - entry_fee - exit_fee
    assert state.day_pnl == pytest.approx(expected_net)
    assert state.cash == pytest.approx(bot.CAPITAL + expected_net)
    assert "TEST" not in state.positions


def test_daily_loss_cap_includes_open_position_loss():
    entry = 100.0
    qty = 100
    fee = bot.fee_for_notional(entry * qty)
    pos = bot.Position(
        "TEST", "BUY", qty, entry, 99.0, 102.0, NOW, entry_fee=fee
    )
    state = bot.State(
        cash=bot.CAPITAL - entry * qty - fee,
        day_pnl=-fee,
        positions={"TEST": pos},
        last_prices={"TEST": 94.0},
    )
    assert bot.marked_day_pnl(state) < -(bot.CAPITAL * 0.03)
    bot.check_daily_cap(state)
    assert state.halted is True


def test_round_trip_cost_is_split_between_sides():
    notional = 10_000
    assert bot.fee_for_notional(notional) == pytest.approx(5.0)
    assert 2 * bot.fee_for_notional(notional) == pytest.approx(10.0)


def test_daily_cap_halts_new_entries_when_open_position_has_no_mark():
    pos = bot.Position(
        "TEST", "BUY", 10, 100.0, 99.0, 102.0, NOW, entry_fee=0.5
    )
    state = bot.State(
        cash=bot.CAPITAL - 1000.5,
        day_pnl=-0.5,
        positions={"TEST": pos},
        last_prices={},
    )
    bot.check_daily_cap(state)
    assert state.halted is True
