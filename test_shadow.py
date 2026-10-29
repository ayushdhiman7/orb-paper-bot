"""Offline tests for the shadow ledger (alternative exit rules replayed beside the frozen baseline)."""
from datetime import datetime

import pytest

import bot
from shadow import ShadowLedger

NOW = datetime(2026, 10, 29, 10, 0)


def mk(side="BUY"):
    L = ShadowLedger(lambda n: 0.0, lambda p, d, e: p)       # zero costs: isolate the rules
    if side == "BUY":
        pos = bot.Position("T", "BUY", 10, 100.0, 99.0, 101.5, NOW, row_id=7)
    else:
        pos = bot.Position("T", "SELL", 10, 100.0, 101.0, 98.5, NOW, row_id=7)
    L.open("T", pos)
    return L


def run(L, prices, baseline_exit, baseline_pnl):
    for p in prices:
        L.tick("T", p, NOW)
    return {r["variant"]: r for r in L.close("T", baseline_exit, baseline_pnl, NOW)}


def test_giveback_saves_profit_that_baseline_loses():
    r = run(mk(), (100.5, 101.0, 101.2, 100.4, 99.0), 99.0, -10.0)
    assert r["giveback_50"]["exit_reason"] == "giveback" and r["giveback_50"]["pnl"] == pytest.approx(4.0)
    assert r["breakeven_1R"]["pnl"] == pytest.approx(-10.0)      # price gapped through breakeven to the stop
    assert all(x["baseline_pnl"] == -10.0 and x["trade_id"] == 7 for x in r.values())


def test_breakeven_exit_and_sell_side_mirror():
    r = run(mk(), (101.0, 100.0), 99.5, -5.0)
    assert r["breakeven_1R"]["exit_reason"] == "breakeven" and r["breakeven_1R"]["pnl"] == pytest.approx(0.0)
    s = run(mk("SELL"), (99.0, 98.7, 99.4), 100.5, -5.0)          # SELL: 1R at 99, fades back
    assert s["giveback_50"]["exit_reason"] == "giveback" and s["giveback_50"]["pnl"] > 0


def test_unfinished_variants_follow_baseline_exit_and_ai_exit_is_recorded():
    L = mk()
    L.tick("T", 100.2, NOW)
    L.ai_exit("T", 100.2, NOW)
    r = {x["variant"]: x for x in L.close("T", 101.5, 15.0, NOW)}
    assert r["ai_exit"]["exit_price"] == 100.2 and r["ai_exit"]["pnl"] == pytest.approx(2.0)
    assert r["trail_1R"]["exit_reason"] == "baseline_exit" and r["trail_1R"]["pnl"] == pytest.approx(15.0)


def test_close_of_unknown_symbol_is_harmless():
    assert ShadowLedger(lambda n: 0.0, lambda p, d, e: p).close("X", 1.0, 0.0, NOW) == []


def test_shadow_write_failure_never_affects_baseline_close(monkeypatch):
    class Boom:
        def table(self, _):
            raise RuntimeError("down")
    monkeypatch.setattr(bot, "SB", Boom())
    monkeypatch.setattr(bot, "log_trade", lambda *a, **k: None)
    fee = bot.fee_for_notional(1000.0)
    st = bot.State(cash=bot.CAPITAL - 1000.0 - fee, day_pnl=-fee)
    pos = bot.Position("T", "BUY", 10, 100.0, 99.0, 101.5, NOW, entry_fee=fee)
    st.positions["T"] = pos
    bot.LEDGER.open("T", pos)
    assert bot.close_position(st, "T", 101.0, "test", NOW) is True
    assert "T" not in st.positions and "T" not in bot.LEDGER.tracks


def test_ai_exit_reason_is_kept_for_review():
    L = mk()
    L.ai_exit("T", 100.2, NOW, "momentum fading on falling volume")
    r = {x["variant"]: x for x in L.close("T", 101.0, 8.0, NOW)}
    assert r["ai_exit"]["exit_reason"] == "ai_exit: momentum fading on falling volume"
