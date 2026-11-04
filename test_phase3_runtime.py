import phase3_runtime
from batch_entry import PortfolioLimits


def _limits(**changes):
    values = dict(
        capital=10000.0, available_cash=10000.0, risk_per_trade_pct=1.0,
        max_positions=2, open_positions=0, max_trades_per_day=3,
        trades_today=0, daily_loss_cap_pct=3.0, day_pnl=0.0,
        min_confidence=0.5,
    )
    values.update(changes)
    return PortfolioLimits(**values)


def _universe():
    return [{"symbol": f"S{i}", "token": str(1000 + i)} for i in range(50)]


def _row(symbol="S0", price=100.0):
    return {
        "symbol": symbol, "side": "BUY", "price": price,
        "opening_range_high": 99.0, "opening_range_low": 95.0,
        "indicators": {"trend": "bullish", "vwap": 98.0, "atr14": 1.0},
        "sentiment": None,
        "quote_evidence": {"event_time": "2026-11-04T10:00:00+05:30", "received_at": 1.0},
    }


def _decision(symbol="S0", rank=1):
    return {
        "symbol": symbol, "decision": "BUY", "confidence": 0.9,
        "reason": "breakout aligned with trend and VWAP",
        "stop": 99.0, "target": 103.0, "rank": rank,
    }


def test_one_batch_review_and_execution_plan_only(monkeypatch):
    # Patch the lazy-imported collector module.
    import candidate_collector
    monkeypatch.setattr(candidate_collector, "collect_candidates", lambda *a, **k: [_row()])
    calls = []
    def reviewer(rows, symbols):
        calls.append((rows, symbols))
        return {"decisions": [_decision()]}
    result = phase3_runtime.run_batch_cycle(
        _universe(), object(), object(), _limits(), review_batch=reviewer,
        slippage_pct=0.05, cost_pct=0.1,
    )
    assert len(calls) == 1
    assert calls[0][1] == {"S0"}
    assert result.status == "approved"
    assert len(result.plans) == 1
    assert result.plans[0].quantity > 0
    assert result.plans[0].entry_fill > result.plans[0].market_price


def test_no_candidates_does_not_call_ai(monkeypatch):
    import candidate_collector
    monkeypatch.setattr(candidate_collector, "collect_candidates", lambda *a, **k: [])
    def reviewer(*_):
        raise AssertionError("AI must not be called for an empty batch")
    result = phase3_runtime.run_batch_cycle(
        _universe(), object(), object(), _limits(), review_batch=reviewer,
        slippage_pct=0.05, cost_pct=0.1,
    )
    assert result.status == "no_candidates"
    assert result.plans == ()


def test_ai_unavailable_fails_closed(monkeypatch):
    import candidate_collector
    monkeypatch.setattr(candidate_collector, "collect_candidates", lambda *a, **k: [_row()])
    result = phase3_runtime.run_batch_cycle(
        _universe(), object(), object(), _limits(), review_batch=lambda *_: None,
        slippage_pct=0.05, cost_pct=0.1,
    )
    assert result.status == "ai_unavailable"
    assert result.plans == ()


def test_final_sizing_rechecks_limits_sequentially(monkeypatch):
    import candidate_collector
    rows = [_row("S0"), _row("S1")]
    monkeypatch.setattr(candidate_collector, "collect_candidates", lambda *a, **k: rows)
    decisions = [_decision("S0", 1), _decision("S1", 2)]
    result = phase3_runtime.run_batch_cycle(
        _universe(), object(), object(), _limits(max_positions=1),
        review_batch=lambda *_: {"decisions": decisions},
        slippage_pct=0.05, cost_pct=0.1,
    )
    assert len(result.plans) == 1
    assert result.plans[0].symbol == "S0"
    assert any(r["symbol"] == "S1" and r["reason"] == "max_open_positions_reached"
               for r in result.rejections)


def test_invalid_universe_never_calls_feed_or_ai():
    result = phase3_runtime.run_batch_cycle(
        _universe()[:-1], object(), object(), _limits(),
        review_batch=lambda *_: (_ for _ in ()).throw(AssertionError("must not call AI")),
        slippage_pct=0.05, cost_pct=0.1,
    )
    assert result.status == "invalid_universe"
    assert result.plans == ()
