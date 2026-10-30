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


def test_quote_failure_invalidates_previous_mark(monkeypatch):
    pos = bot.Position(
        "TEST", "BUY", 10, 100.0, 99.0, 102.0, NOW, entry_fee=0.5
    )
    state = bot.State(
        cash=bot.CAPITAL - 1000.5,
        day_pnl=-0.5,
        positions={"TEST": pos},
        last_prices={"TEST": 100.0},
    )
    monkeypatch.setattr(bot, "last_price", lambda symbol: None)
    bot.manage_positions(state, NOW)
    assert "TEST" not in state.last_prices
    bot.check_daily_cap(state)
    assert state.halted is True


class _FakeQuery:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        if self.error:
            raise self.error
        return type("Result", (), {"data": self.rows})()


class _FakeSupabase:
    def __init__(self, rows=None, error=None):
        self.query = _FakeQuery(rows, error)

    def table(self, _name):
        return self.query


def test_startup_refuses_to_run_without_supabase(monkeypatch):
    monkeypatch.setattr(bot, "SB", None)
    with pytest.raises(RuntimeError, match="Supabase persistence is required"):
        bot.assert_safe_startup()


def test_startup_refuses_when_previous_run_left_open_paper_trade(monkeypatch):
    monkeypatch.setattr(bot, "SB", _FakeSupabase([{"id": 1, "symbol": "RELIANCE.NS"}]))
    with pytest.raises(RuntimeError, match="refusing to start"):
        bot.assert_safe_startup()


def test_startup_refuses_when_open_trade_check_fails(monkeypatch):
    monkeypatch.setattr(bot, "SB", _FakeSupabase(error=OSError("offline")))
    with pytest.raises(RuntimeError, match="Cannot verify existing open paper trades"):
        bot.assert_safe_startup()


def test_startup_allows_clean_paper_trade_table(monkeypatch):
    monkeypatch.setattr(bot, "SB", _FakeSupabase())
    bot.assert_safe_startup()



def test_entry_is_cancelled_when_supabase_persistence_fails(monkeypatch):
    state = bot.State(ranges={"TEST": (99.0, 98.0)})
    monkeypatch.setattr(bot, "last_price", lambda _symbol: 101.0)
    monkeypatch.setattr(bot, "LLM_MODE", "off")
    monkeypatch.setattr(bot, "log_entry", lambda _pos: (_ for _ in ()).throw(
        RuntimeError("Supabase insert failed")
    ))

    bot.try_entry(state, "TEST", NOW)

    assert state.halted is True
    assert state.positions == {}
    assert state.trades_today == 0
    assert state.cash == pytest.approx(bot.CAPITAL)


def test_close_persistence_failure_retains_position_and_ledger(monkeypatch):
    pos = bot.Position("TEST", "BUY", 10, 100.0, 99.0, 102.0, NOW,
                       row_id=123, entry_fee=0.5)
    state = bot.State(
        cash=bot.CAPITAL - 1000.5, day_pnl=-0.5,
        positions={"TEST": pos}, last_prices={"TEST": 100.0},
    )
    monkeypatch.setattr(bot, "log_trade", lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("Supabase close failed")
    ))

    closed = bot.close_position(state, "TEST", 98.0, "stop_loss", NOW)

    assert closed is False
    assert state.halted is True
    assert state.positions["TEST"] is pos
    assert state.cash == pytest.approx(bot.CAPITAL - 1000.5)
    assert state.day_pnl == pytest.approx(-0.5)


def test_mark_persistence_failure_halts_new_entries_but_keeps_position(monkeypatch):
    pos = bot.Position("TEST", "BUY", 10, 100.0, 90.0, 120.0, NOW,
                       row_id=123, entry_fee=0.5)
    state = bot.State(positions={"TEST": pos}, last_prices={"TEST": 100.0})
    monkeypatch.setattr(bot, "last_price", lambda _symbol: 101.0)
    monkeypatch.setattr(bot, "log_price", lambda *_a: (_ for _ in ()).throw(
        RuntimeError("Supabase update failed")
    ))

    bot.manage_positions(state, NOW)

    assert state.halted is True
    assert state.positions["TEST"] is pos
    assert state.last_prices["TEST"] == pytest.approx(101.0)


def test_square_off_retry_and_fallback_constants():
    import bot
    assert bot.SQUARE_OFF < bot.SQUARE_OFF_FALLBACK < bot.MARKET_CLOSE


def _row(i, sym, side, qty, entry, status, pnl=None, ts="2026-10-29T04:00:00+00:00"):
    return {"id": i, "symbol": sym, "side": side, "qty": qty, "entry": entry, "status": status,
            "pnl": pnl, "ts": ts, "llm_decision": None, "llm_reason": None}


def test_restore_rebuilds_positions_cash_and_limits():
    rows = [_row(1, "INFY.NS", "SELL", 1, 1128.7, "closed", pnl=-32.6),
            _row(2, "TCS.NS", "SELL", 5, 2486.0, "open")]
    st = bot.state_from_rows(rows, NOW)
    pos = st.positions["TCS.NS"]
    fee = bot.fee_for_notional(5 * 2486.0)
    assert st.trades_today == 2 and st.done_symbols == {"INFY.NS", "TCS.NS"}
    assert pos.row_id == 2 and pos.stop == pytest.approx(2486.0 * 1.01)
    assert pos.target == pytest.approx(2486.0 - 2486.0 * 0.01 * 1.5)
    assert st.day_pnl == pytest.approx(-32.6 - fee)
    assert st.cash == pytest.approx(bot.CAPITAL - 32.6 - 5 * 2486.0 - fee)


def test_startup_allows_todays_open_row_but_refuses_older(monkeypatch):
    today = _row(1, "TCS.NS", "SELL", 5, 2486.0, "open")
    monkeypatch.setattr(bot, "SB", _FakeSupabase([today]))
    bot.assert_safe_startup(NOW)
    old = _row(2, "TCS.NS", "SELL", 5, 2486.0, "open", ts="2026-10-28T04:00:00+00:00")
    monkeypatch.setattr(bot, "SB", _FakeSupabase([old]))
    with pytest.raises(RuntimeError, match="earlier day"):
        bot.assert_safe_startup(NOW)


class _Df:
    def __init__(self, close, ts):
        import pandas as pd
        self._df = pd.DataFrame({"Close": [close]}, index=pd.DatetimeIndex([ts]))
    empty = False
    def __getattr__(self, k): return getattr(self._df, k)
    def __getitem__(self, k): return self._df[k]


def test_stale_or_invalid_yahoo_price_is_rejected(monkeypatch):
    now = datetime.now(IST)
    from datetime import timedelta
    monkeypatch.setattr(bot, "FEED", None)
    monkeypatch.setattr(bot, "fetch_candles", lambda s: _Df(100.0, now - timedelta(minutes=120)))
    assert bot.last_price("X.NS") is None
    monkeypatch.setattr(bot, "fetch_candles", lambda s: _Df(float("nan"), now))
    assert bot.last_price("X.NS") is None
    monkeypatch.setattr(bot, "fetch_candles", lambda s: _Df(100.0, now - timedelta(minutes=16)))
    assert bot.last_price("X.NS") == 100.0



def test_supabase_client_is_initialized_lazily_before_startup_check(monkeypatch):
    class StartupReached(Exception):
        pass

    fake_client = object()
    monkeypatch.setattr(bot, "SB", None)
    monkeypatch.setattr(bot, "get_supabase", lambda: fake_client)

    def startup_check():
        assert bot.SB is fake_client
        raise StartupReached

    monkeypatch.setattr(bot, "assert_safe_startup", startup_check)
    with pytest.raises(StartupReached):
        bot.run()
