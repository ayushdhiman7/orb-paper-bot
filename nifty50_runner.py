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
from nifty50_position_manager import (
    build_review_prompt, parse_management_batch, protective_stop, validate_management_batch,
)
from nifty50_bot_runtime import scan_batch, start_feed
from sentiment_client import fetch_candidate_sentiment

IST = ZoneInfo("Asia/Kolkata")



DEFAULT_SETTINGS = {
    "scan_interval_seconds": 180, "position_review_seconds": 300,
    "risk_per_trade_pct": 1.0, "daily_loss_cap_pct": 2.0,
    "max_open_positions": 2, "max_trades_per_day": 3,
    "breakeven_r": 1.0, "profit_protection_r": 1.5,
    "protected_profit_r": 0.5, "trailing_start_r": 2.0,
    "square_off_time": "15:15", "stale_quote_seconds": 45,
    "ai_position_min_confidence": 0.0, "emergency_stop": False,
    "paper_only": True,
}


def _load_runtime_settings():
    rows = (core.SB.table("orb_bot_settings").select("settings,version")
            .eq("id", 1).limit(1).execute().data or [])
    if not rows:
        raise RuntimeError("orb_bot_settings missing; apply 202611040002_orb_bot_settings.sql")
    values = {**DEFAULT_SETTINGS, **(rows[0].get("settings") or {})}
    if values.get("paper_only") is not True:
        raise RuntimeError("runtime settings violate paper-only invariant")
    return values, int(rows[0]["version"])


def _apply_runtime_settings(settings, feed):
    core.RISK_PER_TRADE_PCT = float(settings["risk_per_trade_pct"])
    core.DAILY_LOSS_CAP_PCT = float(settings["daily_loss_cap_pct"])
    core.MAX_TRADES_PER_DAY = int(settings["max_trades_per_day"])
    core.SQUARE_OFF = datetime.strptime(settings["square_off_time"], "%H:%M").time()
    feed.max_stale_seconds = int(settings["stale_quote_seconds"])


def _emergency_stop(state, now):
    state.halted = True
    unresolved = []
    for symbol in list(state.positions):
        price = core.last_price(symbol)
        if price is None:
            unresolved.append(symbol)
            continue
        core.close_position(state, symbol, price, "emergency_stop", now)
    notify.send(
        "🛑 EMERGENCY STOP active: all available paper positions closed; "
        + (f"waiting for fresh quotes: {', '.join(unresolved)}" if unresolved else "new entries disabled"),
        once_key="nifty50-emergency-stop",
    )
    return not unresolved and not state.positions


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



def feed_candles_1m(symbol):
    feed = core.FEED
    return feed.candles_1m(symbol) if feed is not None and hasattr(feed, "candles_1m") else []


def _review_open_positions(state, now, settings):
    positions = []
    prices = {}
    for symbol, pos in state.positions.items():
        price = core.last_price(symbol)
        if price is None:
            continue
        prices[symbol] = price
        positions.append({
            "symbol": symbol, "side": pos.side, "qty": pos.qty, "entry": pos.entry,
            "stop": pos.stop, "target": pos.target, "opened_at": pos.opened_at,
            "peak_price": pos.peak or price,
            "candles_1m": feed_candles_1m(symbol),
        })
    if not positions:
        return [], []
    if len(positions) != len(state.positions):
        return [], [{"reason": "one_or_more_open_positions_have_no_fresh_quote"}]
    prompt, expected = build_review_prompt(positions, prices, now)
    response = llm_gate._ask(
        prompt, (), event_type="position_review", symbol="NIFTY50_POSITIONS",
        parser=lambda raw: parse_management_batch(raw, expected),
        audit_decision="batch",
    )
    if not response:
        return [], [{"reason": "ai_unavailable"}]
    return validate_management_batch(
        positions, prices, now, response,
        min_confidence=float(settings.get("ai_position_min_confidence", 0.0)),
    )


def _apply_management_decisions(state, approved, now):
    for item in approved:
        symbol = item["symbol"]
        pos = state.positions.get(symbol)
        if pos is None:
            continue
        decision = item["decision"]
        action = decision.action
        if action == "HOLD":
            continue
        if action == "EXIT":
            price = core.last_price(symbol)
            if price is not None:
                core.close_position(state, symbol, price, "ai_exit", now, note=decision.reason)
            continue
        changes = {}
        if action in {"MOVE_SL", "LOCK_PROFIT"} and decision.new_stop is not None:
            pos.stop = float(decision.new_stop)
            changes["stop"] = round(pos.stop, 4)
        if action == "UPDATE_TARGET" and decision.new_target is not None:
            pos.target = float(decision.new_target)
            changes["target"] = round(pos.target, 4)
        if changes:
            try:
                rows = (core.SB.table("paper_trades").update(changes)
                        .eq("id", pos.row_id).eq("status", "open")
                        .select("id").execute().data or [])
                if not rows:
                    raise RuntimeError("Supabase did not confirm position-level update")
            except Exception as exc:
                state.halted = True
                notify.send("🛑 HALT: Could not persist AI position update; no new entries")
                print(f"[HALT] position update persistence failed ({type(exc).__name__})")
                continue
            notify.send(
                f"🧠 AI POSITION {action} {symbol} | confidence {decision.confidence:.0%} "
                f"| SL {pos.stop:.2f} TP {pos.target:.2f} | {decision.reason}"
            )
            webhook.emit("risk.alert", now, {
                "symbol": symbol, "action": action, "confidence": decision.confidence,
                "stop": pos.stop, "target": pos.target, "reason": decision.reason,
                "mode": "paper",
            })


def _apply_deterministic_protection(state, now, settings):
    """Apply agreed +1R/+1.5R/+2R protections before normal stop/target checks."""
    changed = False
    from indicators import calculate_indicators
    for symbol, pos in list(state.positions.items()):
        price = core.last_price(symbol)
        if price is None:
            continue
        candles = core.FEED.candles(symbol) if core.FEED is not None else []
        snapshot = calculate_indicators(candles, ema_period=20, atr_period=14) if len(candles) >= 15 else None
        atr = snapshot.atr14 if snapshot is not None else None
        lows = [row["low"] for row in candles[-5:]]
        highs = [row["high"] for row in candles[-5:]]
        round_trip_cost = core.fee_for_notional(pos.qty * pos.entry) * 2 / max(pos.qty, 1)
        new_stop, trigger = protective_stop(
            {"entry": pos.entry, "stop": pos.stop, "side": pos.side,
             "round_trip_cost_per_share": round_trip_cost},
            price, one_r=float(settings["breakeven_r"]),\n            one_half_r=float(settings["profit_protection_r"]),\n            two_r=float(settings["trailing_start_r"]),
            protected_profit_r=float(settings["protected_profit_r"]),
            atr=atr, recent_lows=lows, recent_highs=highs,
        )
        tighter = new_stop > pos.stop if pos.side == "BUY" else new_stop < pos.stop
        if not tighter:
            continue
        pos.stop = new_stop
        changed = True
        try:
            rows = (core.SB.table("paper_trades").update({"stop": round(pos.stop, 4)})
                    .eq("id", pos.row_id).eq("status", "open").select("id").execute().data or [])
            if not rows:
                raise RuntimeError("stop update was not confirmed")
        except Exception as exc:
            state.halted = True
            notify.send("🛑 HALT: Profit-protection stop could not be persisted")
            print(f"[HALT] deterministic stop persistence failed ({type(exc).__name__})")
            continue
        notify.send(f"🔒 {symbol} {trigger}: protective stop tightened to {pos.stop:.2f}")
        webhook.emit("risk.alert", now, {
            "symbol": symbol, "action": trigger, "stop": pos.stop,
            "mode": "paper", "risk_verdict": "APPROVED",
        })
    return changed


def run():
    if os.getenv("ORB_RUNTIME_MODE", "").strip().lower() != "nifty50_batch":
        raise RuntimeError("Set ORB_RUNTIME_MODE=nifty50_batch explicitly to run this entry point")
    if not core.acquire_instance_lock():
        return
    core.SB = core.get_supabase()
    core.AI_EXITS = "off"  # all Nifty 50 position decisions go through the batch manager below
    core.assert_safe_startup()
    webhook.start()
    state = core.restore_state(datetime.now(IST))
    _restore_ai_levels(state)
    settings, settings_version = _load_runtime_settings()
    universe, feed = start_feed()
    _apply_runtime_settings(settings, feed)
    core.FEED = feed
    # This runner deliberately prevents every legacy Yahoo fallback.
    core.last_price = lambda symbol: feed.last(symbol, datetime.now(IST))
    notify.send("🚀 NIFTY50 batch paper runner started | Angel WebSocket | paper-only")
    last_scan = None
    last_position_review = None
    last_settings_refresh = time.monotonic()
    session_date = datetime.now(IST).date()
    print(f"[NIFTY50] connected; {len(universe)} constituents; paper-only")
    try:
        while True:
            now = datetime.now(IST)
            clock = now.time()
            if now.date() != session_date and not state.positions:
                state = core.restore_state(now)
                _restore_ai_levels(state)
                session_date = now.date()
                last_scan = None
                last_position_review = None
                print(f"[SESSION] restored new trading date {session_date}")
            if time.monotonic() - last_settings_refresh >= 15:
                try:
                    latest_settings, latest_version = _load_runtime_settings()
                    if latest_version != settings_version:
                        settings, settings_version = latest_settings, latest_version
                        _apply_runtime_settings(settings, feed)
                        print(f"[SETTINGS] applied version {settings_version}")
                        notify.send(f"⚙️ ORB settings updated · version {settings_version}")
                except Exception as exc:
                    state.halted = True
                    print(f"[HALT] runtime settings unavailable ({type(exc).__name__}); entries disabled")
                last_settings_refresh = time.monotonic()
            if settings.get("emergency_stop"):
                _emergency_stop(state, now)
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
                protection_event = _apply_deterministic_protection(state, now, settings)
                core.manage_positions(state, now)
                core.check_daily_cap(state)
                review_due = bool(state.positions) and (protection_event or
                    last_position_review is None or
                    (now - last_position_review).total_seconds() >= int(settings["position_review_seconds"])
                )
                if review_due and not state.halted:
                    last_position_review = now
                    approved, rejected = _review_open_positions(state, now, settings)
                    if rejected:
                        print(f"[NIFTY50][AI POSITION] rejected/unavailable: {rejected}")
                    _apply_management_decisions(state, approved, now)
                due = last_scan is None or (now - last_scan).total_seconds() >= int(settings["scan_interval_seconds"])
                if due and clock < core.NO_NEW_TRADES_AFTER and not state.halted:
                    last_scan = now
                    result, info = scan_batch(
                        universe, feed, now, state, review_batch=llm_gate.review_batch,
                        capital=core.CAPITAL, risk_pct=core.RISK_PER_TRADE_PCT,
                        daily_loss_pct=core.DAILY_LOSS_CAP_PCT,
                        max_trades=core.MAX_TRADES_PER_DAY,
                        slippage_pct=core.SLIPPAGE_PCT, cost_pct=core.COST_PCT,
                        settings=settings, day_pnl=core.marked_day_pnl(state),
                        sentiment_provider=fetch_candidate_sentiment,
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
