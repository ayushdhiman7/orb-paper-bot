"""Opt-in Nifty 50 batch paper runner.

Run with ORB_RUNTIME_MODE=nifty50_batch python nifty50_runner.py.
This process uses the existing paper-trade database and accounting functions.
It never imports or calls broker order APIs.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import bot as core
import llm_gate
import notify
import webhook
from batch_entry import PortfolioLimits
from nifty50_bot_runtime import scan_batch, start_feed

IST = ZoneInfo("Asia/Kolkata")


def _persist_ai_plan(plan, now):
    result = core.SB.table("paper_trades").insert({
        "ts": now.isoformat(),
        "symbol": plan.symbol,
        "side": plan.side,
        "qty": plan.quantity,
        "entry": round(plan.entry_fill, 4),
        "last_price": round(plan.market_price, 4),
        "last_price_ts": now.isoformat(),
        "reason": "open",
        "llm_decision": "take",
        "llm_reason": f"AI {plan.confidence:.0%}: {plan.reason}",
        "stop": round(plan.stop, 4),
        "target": round(plan.target, 4),
        "ai_confidence": plan.confidence,
        "ai_rank": plan.rank,
        "status": "open",
        "mode": "paper",
    }).select("id").execute()
    rows = getattr(result, "data", None) or []
    if not rows or rows[0].get("id") is None:
        raise RuntimeError("Supabase did not confirm AI paper entry persistence")
    return rows[0]["id"]


def _restore_ai_levels(state):
    """Override reconstructed levels with persisted AI-approved levels."""
    rows = (core.SB.table("paper_trades")
            .select("id,symbol,stop,target,ai_confidence,ai_rank")
            .eq("status", "open").eq("mode", "paper").execute().data or [])
    by_id = {str(row["id"]): row for row in rows}
    for position in state.positions.values():
        row = by_id.get(str(position.row_id))
        if row and row.get("stop") is not None and row.get("target") is not None:
            position.stop = float(row["stop"])
            position.target = float(row["target"])
            position.ai_confidence = row.get("ai_confidence")
            position.ai_rank = row.get("ai_rank")


def _apply_plans(state, result, now):
    for plan in result.plans:
        if plan.symbol in state.positions or plan.symbol in state.done_symbols or state.halted:
            continue
        position = core.Position(
            plan.symbol, plan.side, plan.quantity, plan.entry_fill,
            plan.stop, plan.target, now,
            llm_decision="take",
            llm_reason=f"AI {plan.confidence:.0%}: {plan.reason}",
            entry_fee=plan.entry_fee,
            ai_confidence=plan.confidence,
            ai_rank=plan.rank,
        )
        try:
            position.row_id = _persist_ai_plan(plan, now)
        except Exception as exc:
            state.halted = True
            print(f"[HALT] AI paper entry persistence failed ({type(exc).__name__})")
            notify.send("🛑 HALT: AI paper entry persistence failed; no further entries")
            return
        state.positions[plan.symbol] = position
        core.LEDGER.open(plan.symbol, position)
        state.cash -= plan.quantity * plan.entry_fill + plan.entry_fee
        state.trades_today += 1
        state.day_pnl -= plan.entry_fee
        state.last_prices[plan.symbol] = plan.market_price
        state.done_symbols.add(plan.symbol)
        notify.send(
            f"🤖 NIFTY50 PAPER ENTRY {plan.side} {plan.quantity} {plan.symbol} "
            f"@ {plan.entry_fill:.2f} | SL {plan.stop:.2f} TP {plan.target:.2f} "
            f"| AI {plan.confidence:.0%} rank #{plan.rank} | Risk verdict: APPROVED | {plan.reason}"
        )
        webhook.emit("trade.opened", now, {
            "trade_id": position.row_id, "symbol": plan.symbol, "side": plan.side,
            "qty": plan.quantity, "entry": round(plan.entry_fill, 4),
            "stop": round(plan.stop, 4), "target": round(plan.target, 4),
            "ai_confidence": plan.confidence, "ai_rank": plan.rank,
            "ai_reason": plan.reason, "risk_verdict": "APPROVED",
            "status": "open", "mode": "paper",
        })


def run():
    if os.getenv("ORB_RUNTIME_MODE", "").strip().lower() != "nifty50_batch":
        raise RuntimeError("Set ORB_RUNTIME_MODE=nifty50_batch explicitly to run this entry point")
    if not core.acquire_instance_lock():
        return
    core.SB = core.get_supabase()
    core.assert_safe_startup()
    webhook.start()
    state = core.restore_state(datetime.now(IST))
    _restore_ai_levels(state)
    universe, feed = start_feed()
    core.FEED = feed
    # This runner deliberately prevents every legacy Yahoo fallback.
    core.last_price = lambda symbol: feed.last(symbol, datetime.now(IST))
    notify.send("🚀 NIFTY50 batch paper runner started | Angel WebSocket | paper-only")
    last_scan = None
    print(f"[NIFTY50] connected; {len(universe)} constituents; paper-only")
    try:
        while True:
            now = datetime.now(IST)
            clock = now.time()
            if now.weekday() >= 5 or clock < core.MARKET_OPEN or clock > core.MARKET_CLOSE:
                if clock > core.MARKET_CLOSE and state.positions:
                    for symbol in list(state.positions):
                        price = core.last_price(symbol)
                        if price is not None:
                            core.close_position(state, symbol, price, "square_off", now)
                if clock > core.MARKET_CLOSE and not state.positions:
                    time.sleep(300)
                else:
                    time.sleep(30)
                continue

            core.process_manual_exit_requests(state, now)
            if clock >= core.SQUARE_OFF:
                for symbol in list(state.positions):
                    price = core.last_price(symbol)
                    if price is not None:
                        core.close_position(state, symbol, price, "square_off", now)
            elif clock >= core.RANGE_END:
                core.manage_positions(state, now)
                core.check_daily_cap(state)
                due = last_scan is None or (now - last_scan).total_seconds() >= int(os.getenv("NIFTY50_SCAN_SECONDS", "180"))
                if due and clock < core.NO_NEW_TRADES_AFTER and not state.halted:
                    last_scan = now
                    result, info = scan_batch(
                        universe, feed, now, state, review_batch=llm_gate.review_batch,
                        capital=core.CAPITAL, risk_pct=core.RISK_PER_TRADE_PCT,
                        daily_loss_pct=core.DAILY_LOSS_CAP_PCT,
                        max_trades=core.MAX_TRADES_PER_DAY,
                        slippage_pct=core.SLIPPAGE_PCT, cost_pct=core.COST_PCT,
                    )
                    print(f"[NIFTY50] {info}")
                    if result is not None and result.status in {"approved", "no_approved_entries"}:
                        _apply_plans(state, result, now)
                    elif result is not None:
                        notify.send(f"⚠️ NIFTY50 batch blocked: {result.status}; no entries")
            time.sleep(5)
    finally:
        feed.stop()


if __name__ == "__main__":
    run()
