from nifty50_bot_runtime import fresh_quote_coverage, scan_batch
from batch_entry import PortfolioLimits


class FakeFeed:
    connected = True

    def __init__(self, missing=()):
        self.missing = set(missing)

    def quote(self, symbol):
        return None if symbol in self.missing else {"symbol": symbol, "price": 100.0}


def _universe():
    return [{"symbol": f"SYMBOL{i:02d}", "token": str(i + 1)} for i in range(50)]


def test_fresh_quote_coverage_requires_every_constituent():
    universe = _universe()
    feed = FakeFeed({"SYMBOL17"})

    covered, missing = fresh_quote_coverage(universe, feed)

    assert covered == 49
    assert missing == ["SYMBOL17"]


def test_scan_batch_fails_closed_when_any_constituent_quote_is_stale(monkeypatch):
    universe = _universe()
    feed = FakeFeed({"SYMBOL17"})
    portfolio = PortfolioLimits(
        capital=14000.0,
        available_cash=14000.0,
        risk_per_trade_pct=1.0,
        max_positions=2,
        open_positions=0,
        max_trades_per_day=3,
        trades_today=0,
        daily_loss_cap_pct=2.0,
        day_pnl=0.0,
    )

    def unexpected_cycle(*args, **kwargs):
        raise AssertionError("batch cycle must not run with incomplete feed coverage")

    monkeypatch.setattr("nifty50_bot_runtime.run_batch_cycle", unexpected_cycle)

    result, info = scan_batch(
        universe, feed, None, type("State", (), {"cash": 14000.0, "positions": {},
                                                 "trades_today": 0, "day_pnl": 0.0})(),
        review_batch=lambda *_: None,
        capital=14000.0,
        risk_pct=1.0,
        daily_loss_pct=2.0,
        max_trades=3,
        slippage_pct=0.05,
        cost_pct=0.10,
    )

    assert result is None
    assert info["status"] == "incomplete_feed_coverage"
    assert info["fresh_symbols"] == 49
    assert info["required_symbols"] == 50
    assert info["missing_symbols"] == ["SYMBOL17"]
