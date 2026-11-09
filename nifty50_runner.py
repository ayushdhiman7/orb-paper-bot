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
    "sentiment_enabled": False, "ai_position_management_enabled": True,
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


def _enforce_daily_loss_cap(state, now):
    """Liquidate every paper position after the configured marked daily loss cap is reached.

    Marks are refreshed from the runtime's fresh-quote-only price source before
    evaluating the cap. If any position cannot be marked, the runner stays
    halted and retries on the next loop; stale prices are never used to claim
    that the portfolio is flat or to fabricate an exit.
    """
    if not state.positions:
        return True

    fresh_prices = {}
    missing = []
    for symbol in list(state.positions):
        price = core.last_price(symbol)
        if price is None:
            missing.append(symbol)
        else:
            fresh_prices[symbol] = price

    if missing:
        state.halted = True
        notify.send(
            "🛑 DAILY RISK HALT: cannot verify daily loss because fresh quotes are "
            f"missing for {', '.join(missing)}. Positions remain open pending fresh quotes.",
            once_key="nifty50-daily-cap-unmarked",
        )
        return False

    state.last_prices.update(fresh_prices)
    loss_limit = float(core.CAPITAL) * float(core.DAILY_LOSS_CAP_PCT) / 100.0
    marked_pnl = core.marked_day_pnl(state)
    if marked_pnl > -loss_limit:
        return False

    state.halted = True
    unresolved = []
    for symbol, price in fresh_prices.items():
        if symbol not in state.positions:
            continue
        try:
            closed = core.close_position(state, symbol, price, "daily_loss_cap", now)
        except Exception as exc:
            print(f"[HALT] daily-loss liquidation failed for {symbol} ({type(exc).__name__})")
            closed = False
        if not closed or symbol in state.positions:
            unresolved.append(symbol)

    if unresolved or state.positions:
        remaining = sorted(set(unresolved) | set(state.positions))
        notify.send(
            "🛑 DAILY LOSS CAP HIT: entries locked; liquidation is incomplete for "
            f"{', '.join(remaining)}. Fresh-quote close will be retried.",
            once_key="nifty50-daily-cap-liquidation-pending",
        )
        return False

    notify.send(
        f"🛑 DAILY LOSS CAP HIT ({marked_pnl:+.2f}, limit -{loss_limit:.2f}). "
        "All paper positions closed and new entries locked for this session.",
        once_key="nifty50-daily-cap-liquidated",
    )
    return True


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
        "initial_stop": round(plan.stop, 4),
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
            .select("id,symbol,stop,initial_stop,target,ai_confidence,ai_rank")
            .eq("status", "open").eq("mode", "paper").execute().data or [])
    by_id = {str(row["id"]): row for row in rows}
    for position in state.positions.values():
        row = by_id.get(str(position.row_id))
        if row and row.get("stop") is not None and row.get("target") is not None:
            position.stop = float(row["stop"])
            if row.get("initial_stop") is not None:
                position.initial_stop = float(row["initial_stop"])
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
        technical = plan.technical_evidence or {}
        sentiment = plan.sentiment_evidence or {}
        notify.send(
            f"🤖 NIFTY50 PAPER ENTRY · Trade ID: {position.row_id}\\n"
            f"Recommendation: TAKE · AI confidence: {plan.confidence:.0%} · Rank: #{plan.rank}\\n"
            f"{plan.side} {plan.quantity} {plan.symbol} @ ₹{plan.entry_fill:.2f} "
            f"· SL ₹{plan.stop:.2f} · TP ₹{plan.target:.2f}\\n"
            f"Risk verdict: APPROVED · {plan.reason}\\n"
            f"Technical: trend={technical.get('trend', 'n/a')}, "
            f"EMA20={technical.get('ema20', 'n/a')}, VWAP={technical.get('vwap', 'n/a')}, "
            f"ATR14={technical.get('atr14', 'n/a')}, extension_ATR={technical.get('extension_atr', 'n/a')}\\n"
            f"Sentiment (context only): news={sentiment.get('news_score', 'n/a')} "
            f"[{sentiment.get('news_status', 'unavailable')}], "
            f"social={sentiment.get('social_score', 'n/a')} "
            f"[{sentiment.get('social_status', 'unavailable')}], "
            f"combined={sentiment.get('combined_score', 'n/a')}"
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
        proposed_stop = float(decision.new_stop) if action in {"MOVE_SL", "LOCK_PROFIT"} and decision.new_stop is not None else pos.stop
        proposed_target = float(decision.new_target) if action == "UPDATE_TARGET" and decision.new_target is not None else pos.target
        changes = {}
        if proposed_stop != pos.stop:
            changes["stop"] = round(proposed_stop, 4)
        if proposed_target != pos.target:
            changes["target"] = round(proposed_target, 4)
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
            # Mutate memory only after the database confirms the durable level change.
            pos.stop = proposed_stop
            pos.target = proposed_target
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
            {"entry": pos.entry, "stop": pos.stop, "initial_stop": pos.initial_stop, "side": pos.side,
             "round_trip_cost_per_share": round_trip_cost},
            price, one_r=float(settings["breakeven_r"]),
            one_half_r=float(settings["profit_protection_r"]),
            two_r=float(settings["trailing_start_r"]),
            protected_profit_r=float(settings["protected_profit_r"]),
            atr=atr, recent_lows=lows, recent_highs=highs,
        )
        tighter = new_stop > pos.stop if pos.side == "BUY" else new_stop < pos.stop
        if not tighter:
            continue
        try:
            rows = (core.SB.table("paper_trades").update({"stop": round(new_stop, 4)})
                    .eq("id", pos.row_id).eq("status", "open").select("id").execute().data or [])
            if not rows:
                raise RuntimeError("stop update was not confirmed")
        except Exception as exc:
            state.halted = True
            notify.send("🛑 HALT: Profit-protection stop could not be persisted")
            print(f"[HALT] deterministic stop persistence failed ({type(exc).__name__})")
            continue
        pos.stop = new_stop
        changed = True
        notify.send(f"🔒 {symbol} {trigger}: protective stop tightened to {pos.stop:.2f}")
        webhook.emit("risk.alert", now, {
            "symbol": symbol, "action": trigger, "stop": pos.stop,
            "mode": "paper", "risk_verdict": "APPROVED",
        })
    return changed



def _send_daily_report(state, now):
    """Persist and deliver an idempotent paper-session summary after all positions close."""
    session_date = now.date().isoformat()
    try:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        trades = (core.SB.table("paper_trades")
                  .select("symbol,status,pnl,llm_decision,ai_confidence")
                  .eq("mode", "paper").gte("ts", day_start).execute().data or [])
        closed = [row for row in trades if row.get("status") != "open"]
        pnls = [float(row.get("pnl") or 0.0) for row in closed]
        net_pnl = round(sum(pnls), 2)
        confidences = [float(row["ai_confidence"]) for row in closed if row.get("ai_confidence") is not None]
        summary = {
            "session_date": session_date,
            "mode": "paper",
            "trades": len(closed),
            "wins": sum(value > 0 for value in pnls),
            "losses": sum(value < 0 for value in pnls),
            "breakeven": sum(value == 0 for value in pnls),
            "net_pnl": net_pnl,
            "return_pct": round(net_pnl / core.CAPITAL * 100, 4) if core.CAPITAL else 0.0,
            "capital": round(float(core.CAPITAL), 2),
            "ai_trade_count": sum(row.get("llm_decision") == "take" for row in closed),
            "average_ai_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
            "symbols": sorted({str(row.get("symbol")) for row in closed if row.get("symbol")}),
            "open_positions": len(state.positions),
            "state_day_pnl": round(float(state.day_pnl), 2),
        }
        existing = (core.SB.table("bot_session_reports")
                    .select("summary,telegram_sent_at,webhook_queued_at")
                    .eq("session_date", session_date).limit(1).execute().data or [])
        if not existing:
            inserted = (core.SB.table("bot_session_reports").insert({
                "session_date": session_date, "summary": summary,
                "created_at": now.isoformat(), "updated_at": now.isoformat(),
            }).select("summary,telegram_sent_at,webhook_queued_at").execute().data or [])
            existing = inserted
        if not existing:
            raise RuntimeError("daily report row was not confirmed")
        report = existing[0]
        stored_summary = report.get("summary") or summary
        updates = {}
        confidence = stored_summary.get("average_ai_confidence")
        confidence_label = f"{float(confidence):.0%}" if confidence is not None else "n/a"
        message = (
            f"📊 NIFTY50 PAPER DAILY REPORT · {session_date}\n"
            f"Trades: {stored_summary.get('trades', 0)} | "
            f"W/L/BE: {stored_summary.get('wins', 0)}/{stored_summary.get('losses', 0)}/{stored_summary.get('breakeven', 0)}\n"
            f"Net P&L: ₹{float(stored_summary.get('net_pnl') or 0):+.2f} "
            f"({float(stored_summary.get('return_pct') or 0):+.2f}%)\n"
            f"AI entries: {stored_summary.get('ai_trade_count', 0)} | Avg confidence: {confidence_label}"
        )
        message += f"\nOpen positions: {stored_summary.get('open_positions', 0)} | Mode: PAPER"
        if notify.configured() and not report.get("telegram_sent_at") and notify.send(message):
            updates["telegram_sent_at"] = now.isoformat()
        if not report.get("webhook_queued_at") and webhook.emit("session.summary", now, stored_summary):
            updates["webhook_queued_at"] = now.isoformat()
        if updates:
            (core.SB.table("bot_session_reports").update({
                **updates, "updated_at": now.isoformat(),
            }).eq("session_date", session_date).execute())
        return True
    except Exception as exc:
        print(f"[NIFTY50] daily report deferred ({type(exc).__name__})")
        return False


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
    last_daily_report_attempt = None
    print(f"[NIFTY50] connected; {len(universe)} constituents; paper-only")
    try:
        while True:
            now = datetime.now(IST)
            clock = now.time()
            try:
                if feed.restart_if_stopped():
                    print("[FEED] Angel One WebSocket restart initiated; entries remain blocked until fresh quotes arrive")
                    notify.send("⚠️ Angel One WebSocket reconnect initiated; paper entries remain blocked until fresh quotes arrive")
            except Exception as exc:
                print(f"[FEED] reconnect attempt failed ({type(exc).__name__}); no fallback feed will be used")
            if now.date() != session_date and not state.positions:
                state = core.restore_state(now)
                _restore_ai_levels(state)
                session_date = now.date()
                last_scan = None
                last_position_review = None
                last_daily_report_attempt = None
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
                if now.weekday() < 5 and clock > core.MARKET_CLOSE and not state.positions:
                    if last_daily_report_attempt is None or (now - last_daily_report_attempt).total_seconds() >= 60:
                        _send_daily_report(state, now)
                        last_daily_report_attempt = now
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
                _enforce_daily_loss_cap(state, now)
                review_due = bool(settings.get("ai_position_management_enabled", True)) and bool(state.positions) and (protection_event or
                    last_position_review is None or
                    (now - last_position_review).total_seconds() >= int(settings["position_review_seconds"])
                )
                if review_due and not state.halted:
                    last_position_review = now
                    approved, rejected = _review_open_positions(state, now, settings)
                    if rejected:
                        print(f"[NIFTY50][AI POSITION] rejected/unavailable: {rejected}")
                    if approved or rejected:
                        lines = [
                            f"{row['symbol']} {row['decision'].action} {row['decision'].confidence:.0%} APPROVED"
                            for row in approved
                        ]
                        lines.extend(
                            f"{row.get('symbol', 'PORTFOLIO')} REJECTED: {row.get('reason')}"
                            for row in rejected
                        )
                        notify.send("🧠 NIFTY50 POSITION REVIEW\n" + "\n".join(lines)[:3200])
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
                        sentiment_provider=fetch_candidate_sentiment if settings.get("sentiment_enabled") else None,
                    )
                    print(f"[NIFTY50] {info}")
                    if result is not None and result.rejections:
                        lines = [
                            f"{row.get('symbol', 'unknown')} REJECTED: {row.get('reason', row.get('verdict', 'risk check failed'))}"
                            for row in result.rejections
                        ]
                        notify.send("🛡️ NIFTY50 RISK VERDICTS\n" + "\n".join(lines)[:3200])
                    if result is not None and result.status in {"approved", "no_approved_entries"}:
                        _apply_plans(state, result, now)
                    elif result is not None:
                        notify.send(f"⚠️ NIFTY50 batch blocked: {result.status}; no entries")
            time.sleep(5)
    finally:
        feed.stop()


if __name__ == "__main__":
    run()
