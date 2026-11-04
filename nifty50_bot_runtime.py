"""Nifty 50 batch paper runtime adapter.

The bot entry point may opt into this adapter with ORB_RUNTIME_MODE=nifty50_batch.
This module never calls broker order APIs; it persists only through the bot's
existing paper-trade callbacks.
"""
from __future__ import annotations

import os
import time
from typing import Any

from angel_websocket import AngelWebSocketFeed
from batch_entry import PortfolioLimits
from nifty_universe import fetch_nifty50_universe, write_universe_cache
from phase3_runtime import run_batch_cycle


def start_feed():
    universe = fetch_nifty50_universe()
    write_universe_cache(
        universe,
        os.getenv("NIFTY50_UNIVERSE_CACHE", "/tmp/orb-nifty50-universe.json"),
    )
    feed = AngelWebSocketFeed(
        [row["symbol"] for row in universe],
        max_stale_seconds=int(os.getenv("ANGEL_MAX_STALE_SECONDS", "45")),
        token_map={row["symbol"]: row["token"] for row in universe},
    )
    feed.start()
    deadline = time.monotonic() + int(os.getenv("ANGEL_WS_CONNECT_TIMEOUT", "20"))
    while not feed.connected and time.monotonic() < deadline:
        time.sleep(0.2)
    if not feed.connected:
        feed.stop()
        raise RuntimeError("Angel One WebSocket connection failed; refusing data fallback")
    return universe, feed


def scan_batch(universe, feed, now, state, *, review_batch, capital, risk_pct,
               daily_loss_pct, max_trades, slippage_pct, cost_pct):
    if not isinstance(universe, list) or len(universe) != 50:
        raise RuntimeError("Nifty 50 universe must contain exactly 50 instruments")
    missing = [row["symbol"] for row in universe if feed.quote(row["symbol"], now) is None]
    if missing:
        return None, {"status": "stale_feed", "missing_quotes": len(missing)}
    limits = PortfolioLimits(
        capital=capital,
        available_cash=state.cash,
        risk_per_trade_pct=risk_pct,
        max_positions=int(os.getenv("MAX_OPEN_POSITIONS", "3")),
        open_positions=len(state.positions),
        max_trades_per_day=max_trades,
        trades_today=state.trades_today,
        daily_loss_cap_pct=daily_loss_pct,
        day_pnl=state.day_pnl,
        min_confidence=float(os.getenv("AI_MIN_ENTRY_CONFIDENCE", "0.65")),
    )
    result = run_batch_cycle(
        universe, feed, now, limits, review_batch=review_batch,
        slippage_pct=slippage_pct, cost_pct=cost_pct,
    )
    return result, {"status": result.status, "candidates": len(result.candidates),
                    "plans": len(result.plans), "rejections": len(result.rejections)}
