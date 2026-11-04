"""Fail-closed Phase 3 Nifty 50 batch decision and paper-sizing coordinator.

This module deliberately stops at immutable execution plans. The caller must
persist approved plans through the existing paper-trade accounting path.
There are no broker/order APIs in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from batch_entry import EntryCandidate, PortfolioLimits, validate_batch
from paper_execution import PaperExecutionPlan, recompute_paper_execution


@dataclass(frozen=True)
class BatchResult:
    candidates: tuple[dict, ...]
    decisions: tuple[dict, ...]
    plans: tuple[PaperExecutionPlan, ...]
    rejections: tuple[dict, ...]
    status: str


def _candidate(row: Mapping[str, Any]) -> EntryCandidate:
    return EntryCandidate(
        symbol=str(row["symbol"]).strip().upper(),
        signal_side=str(row["side"]).strip().upper(),
        current_price=row["price"],
        opening_range_high=row["opening_range_high"],
        opening_range_low=row["opening_range_low"],
        indicators=row["indicators"],
        sentiment=row.get("sentiment"),
    )


def run_batch_cycle(
    universe: Sequence[Mapping[str, Any]],
    feed: Any,
    now: Any,
    portfolio: PortfolioLimits,
    *,
    review_batch: Callable[[list[dict], set[str]], dict | None],
    sentiment_provider: Callable[[Sequence[str], Any], Mapping[str, Any]] | None = None,
    slippage_pct: float,
    cost_pct: float,
) -> BatchResult:
    """Collect all eligible candidates, request one AI batch, validate, then re-size.

    Any universe/feed/AI/validation failure returns no plans. AI is advisory only:
    deterministic ORB direction, portfolio limits, stop geometry, costs and cash
    determine which plans survive. No partial AI response is accepted.
    """
    from candidate_collector import collect_candidates

    try:
        if not isinstance(universe, list) or len(universe) != 50:
            return BatchResult((), (), (), (), "invalid_universe")
        symbols = [str(item.get("symbol", "")).strip().upper() for item in universe]
        if len(set(symbols)) != 50 or any(not symbol for symbol in symbols):
            return BatchResult((), (), (), (), "invalid_universe")

        candidates_raw = collect_candidates(
            universe, feed, now, sentiment_by_symbol={}, excluded_symbols=set(),
        )
        if not candidates_raw:
            return BatchResult((), (), (), (), "no_candidates")

        # Sentiment is fetched only for already-qualified candidates. It cannot
        # create, remove, or reverse a deterministic ORB signal.
        sentiment: Mapping[str, Any] = {}
        if sentiment_provider is not None:
            try:
                supplied = sentiment_provider([row["symbol"] for row in candidates_raw], now)
                if isinstance(supplied, Mapping):
                    sentiment = supplied
            except Exception:
                sentiment = {}
        for row in candidates_raw:
            row["sentiment"] = sentiment.get(row["symbol"])

        # Recheck every candidate quote after external sentiment latency and
        # before the Gemini call; stale evidence invalidates the entire batch.
        if hasattr(feed, "quote"):
            for row in candidates_raw:
                if feed.quote(row["symbol"]) is None:
                    return BatchResult(tuple(candidates_raw), (), (), (), "stale_feed")

        candidates = [_candidate(row) for row in candidates_raw]
        expected = {item.symbol for item in candidates}
        response = review_batch(candidates_raw, expected)
        if not isinstance(response, dict) or not isinstance(response.get("decisions"), list):
            return BatchResult(tuple(candidates_raw), (), (), (), "ai_unavailable")

        decisions = response["decisions"]
        accepted, rejected = validate_batch(candidates, decisions, portfolio)
        candidate_by_symbol = {item.symbol: item for item in candidates}
        decision_by_symbol = {str(item.get("symbol", "")).upper(): item for item in decisions}

        plans = []
        current_cash = portfolio.available_cash
        current_open = portfolio.open_positions
        current_trades = portfolio.trades_today
        for entry in accepted:
            candidate = candidate_by_symbol[entry.symbol]
            current_limits = PortfolioLimits(
                capital=portfolio.capital,
                available_cash=current_cash,
                risk_per_trade_pct=portfolio.risk_per_trade_pct,
                max_positions=portfolio.max_positions,
                open_positions=current_open,
                max_trades_per_day=portfolio.max_trades_per_day,
                trades_today=current_trades,
                daily_loss_cap_pct=portfolio.daily_loss_cap_pct,
                day_pnl=portfolio.day_pnl,
                min_confidence=portfolio.min_confidence,
            )
            plan = recompute_paper_execution(
                entry, candidate, current_limits,
                slippage_pct=slippage_pct, cost_pct=cost_pct,
            )
            if plan is None:
                rejected.append({
                    "symbol": entry.symbol,
                    "verdict": "REJECTED",
                    "reason": "final_execution_recheck_failed",
                })
                continue
            plans.append(plan)
            current_cash -= plan.quantity * plan.entry_fill + plan.entry_fee
            current_open += 1
            current_trades += 1

        return BatchResult(
            tuple(candidates_raw),
            tuple(decision_by_symbol[s] for s in sorted(decision_by_symbol)),
            tuple(plans),
            tuple(rejected),
            "approved" if plans else "no_approved_entries",
        )
    except Exception:
        # Fail closed: caller receives no executable plans on any unexpected error.
        return BatchResult((), (), (), (), "cycle_failed")
