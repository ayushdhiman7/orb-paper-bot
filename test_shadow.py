"""Offline tests for the shadow ledger (alternative exit rules replayed beside the frozen baseline)."""
from datetime import datetime

import pytest

import bot
from shadow import NoAIControlLedger, ShadowLedger

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

def test_no_ai_control_finishes_independently_after_real_trade_closes():
    control = NoAIControlLedger(lambda n: n * 0.0005, lambda p, d, e: p)
    pos = bot.Position("T", "BUY", 10, 100.0, 99.0, 101.5, NOW,
                       row_id=None, entry_fee=0.5)
    control.open("T", pos, "T:2026-10-29T10:00:00", "skip", "weak breakout")
    # The real AI-managed trade may close at a different time; that must not delete this control.
    real = mk()
    real.close("T", 100.2, 1.0, NOW)
    assert "T" in control.tracks
    rows = control.tick("T", 101.5, NOW)
    assert "T" not in control.tracks
    assert len(rows) == 1
    row = rows[0]
    assert row["variant"] == "no_ai_control"
    assert row["ai_decision"] == "skip"
    assert row["ai_reason"] == "weak breakout"
    assert row["exit_reason"] == "target"
    assert row["signal_id"] == "T:2026-10-29T10:00:00"
    assert row["pnl"] == pytest.approx((101.5 - 100.0) * 10 - 0.5 - 1015.0 * 0.0005)


def test_no_ai_control_supports_sell_stop_and_squareoff():
    control = NoAIControlLedger(lambda n: 0.0, lambda p, d, e: p)
    pos = bot.Position("T", "SELL", 2, 100.0, 101.0, 98.5, NOW, entry_fee=0.0)
    control.open("T", pos, "signal-2", "take", "accepted")
    assert control.tick("T", 100.5, NOW) == []
    rows = control.close_all({"T": 100.5}, NOW)
    assert rows[0]["exit_reason"] == "square_off"
    assert rows[0]["side"] == "SELL"
    assert rows[0]["pnl"] == pytest.approx(-1.0)
    assert control.tracks == {}


def test_ai_skipped_entry_still_opens_no_ai_control(monkeypatch):
    bot.CONTROL_LEDGER = NoAIControlLedger(bot.fee_for_notional, bot.adverse_fill)
    state = bot.State(ranges={"TEST": (100.0, 99.0)})
    monkeypatch.setattr(bot, "last_price", lambda _symbol: 101.0)
    monkeypatch.setattr(bot, "LLM_MODE", "gate")
    monkeypatch.setattr(bot, "ask_ai", lambda *args: {"decision": "skip", "reason": "weak volume"})
    monkeypatch.setattr(bot, "log_entry", lambda _pos: pytest.fail("AI-skipped entry must not be persisted as real"))
    bot.try_entry(state, "TEST", NOW)
    assert state.positions == {}
    assert state.trades_today == 0
    assert "TEST" in bot.CONTROL_LEDGER.tracks
    assert bot.CONTROL_LEDGER.tracks["TEST"].ai_decision == "skip"
    assert bot.CONTROL_LEDGER.tracks["TEST"].ai_reason == "weak volume"

