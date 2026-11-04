from types import SimpleNamespace

import nifty50_bot_runtime as runtime


def _universe():
    return [{"symbol": f"S{i}", "token": str(1000 + i)} for i in range(50)]


class Feed:
    def __init__(self, missing=False):
        self.missing = missing
    def quote(self, symbol, now):
        if self.missing and symbol == "S4":
            return None
        return {"symbol": symbol}


def test_scan_requires_fresh_quote_for_every_constituent(monkeypatch):
    state = SimpleNamespace(cash=10000, positions={}, trades_today=0, day_pnl=0)
    called = []
    monkeypatch.setattr(runtime, "run_batch_cycle", lambda *a, **k: called.append(True))
    result, info = runtime.scan_batch(
        _universe(), Feed(missing=True), object(), state,
        review_batch=lambda *_: None, capital=10000, risk_pct=1,
        daily_loss_pct=3, max_trades=3, slippage_pct=.05, cost_pct=.1,
    )
    assert result is None
    assert info == {"status": "stale_feed", "missing_quotes": 1}
    assert called == []


def test_scan_passes_complete_portfolio_to_coordinator(monkeypatch):
    state = SimpleNamespace(cash=9000, positions={}, trades_today=1, day_pnl=-10)
    captured = {}
    expected = SimpleNamespace(status="no_candidates", candidates=(), plans=(), rejections=())
    def cycle(universe, feed, now, limits, **kwargs):
        captured["limits"] = limits
        captured["kwargs"] = kwargs
        return expected
    monkeypatch.setattr(runtime, "run_batch_cycle", cycle)
    result, info = runtime.scan_batch(
        _universe(), Feed(), object(), state,
        review_batch=lambda *_: None, capital=10000, risk_pct=1,
        daily_loss_pct=3, max_trades=3, slippage_pct=.05, cost_pct=.1,
    )
    assert result is expected
    assert info["status"] == "no_candidates"
    assert captured["limits"].available_cash == 9000
    assert captured["limits"].trades_today == 1
    assert captured["kwargs"]["review_batch"] is not None
