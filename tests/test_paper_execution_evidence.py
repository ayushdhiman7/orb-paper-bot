from batch_entry import EntryCandidate, PortfolioLimits, ValidatedEntry
from paper_execution import recompute_paper_execution


def test_execution_plan_carries_technical_and_sentiment_evidence():
    candidate = EntryCandidate(
        symbol="RELIANCE",
        signal_side="BUY",
        current_price=100.0,
        opening_range_high=99.0,
        opening_range_low=95.0,
        indicators={"trend": "bullish", "ema20": 98.5, "vwap": 99.0, "atr14": 0.8},
        sentiment={"news_score": 0.4, "news_status": "ok", "social_status": "unavailable"},
    )
    entry = ValidatedEntry(
        symbol="RELIANCE",
        side="BUY",
        confidence=0.82,
        reason="Breakout aligned with trend and VWAP",
        stop=99.0,
        target=102.0,
        rank=1,
        quantity=50,
        risk_amount=50.0,
    )
    limits = PortfolioLimits(
        capital=10000.0,
        available_cash=10000.0,
        risk_per_trade_pct=1.0,
        max_positions=2,
        open_positions=0,
        max_trades_per_day=3,
        trades_today=0,
        daily_loss_cap_pct=2.0,
        day_pnl=0.0,
    )

    plan = recompute_paper_execution(
        entry, candidate, limits, slippage_pct=0.05, cost_pct=0.10,
    )

    assert plan is not None
    assert plan.technical_evidence == candidate.indicators
    assert plan.sentiment_evidence == candidate.sentiment
