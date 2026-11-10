from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import under_25_research as research

IST = ZoneInfo("Asia/Kolkata")


def instrument(symbol, token):
    return {"symbol": symbol, "token": str(token), "tradingsymbol": symbol + "-EQ",
            "exchange": "NSE", "tick_size_rupees": Decimal("0.01")}


def test_report_marks_partial_coverage_and_never_claims_orders():
    rows = [instrument("ABC", 1)]
    report = research.build_research_report(
        instruments=rows, quotes={}, average_values={}, history_errors={"ABC": "blocked"},
        as_of=date(2026, 11, 9),
        generated_at=datetime(2026, 11, 10, 10, 0, tzinfo=IST),
    )
    assert report["status"] == "partial"
    assert report["coverage"]["full_coverage"] is False
    assert report["paper_only"] is True
    assert report["orders_submitted"] == 0
    assert report["candidates"] == []


def test_scan_batches_websocket_tokens_and_loads_history_only_for_under_25(monkeypatch):
    rows = [instrument("LOW", 1), instrument("HIGH", 2), instrument("LOW2", 3)]
    created = []

    class FakeFeed:
        def __init__(self, batch):
            self.batch = batch
            self.stopped = False
        def start(self):
            return True
        def stop(self):
            self.stopped = True

    def feed_factory(batch, token_map):
        assert len(token_map) == len(batch)
        created.append(FakeFeed(batch))
        return created[-1]

    quote_by_symbol = {
        "LOW": {"price": 10.0, "bid": 9.99, "ask": 10.01, "received_at": 1_000.0},
        "HIGH": {"price": 40.0, "bid": 39.99, "ask": 40.01, "received_at": 1_000.0},
        "LOW2": {"price": 20.0, "bid": 19.99, "ask": 20.01, "received_at": 1_000.0},
    }
    monkeypatch.setattr(research, "wait_for_quotes",
                        lambda feed, batch, **kwargs: {row["symbol"]: quote_by_symbol[row["symbol"]] for row in batch})
    history_calls = []
    def load_history(batch, **kwargs):
        history_calls.append([row["symbol"] for row in batch])
        return {"LOW": Decimal("60000000"), "LOW2": Decimal("70000000")}, {}
    monkeypatch.setattr(research, "load_average_daily_values", load_history)

    report = research.run_research_scan(
        master=[{"exch_seg": "nse_cm", "symbol": row["tradingsymbol"],
                 "token": row["token"], "tick_size": "5"} for row in rows],
        feed_factory=feed_factory,
        angel_client=object(),
        as_of=date(2026, 11, 9),
        generated_at=datetime.fromtimestamp(1_000, tz=IST),
        subscription_batch_size=2,
    )
    assert len(created) == 2
    assert all(feed.stopped for feed in created)
    assert history_calls == [["LOW", "LOW2"]]
    assert report["coverage"]["instruments"] == 3
    assert report["coverage"]["fresh_quotes"] == 3
    assert report["coverage"]["liquidity_values"] == 2
    assert report["status"] == "partial"


def test_scan_rejects_subscription_batch_above_smartapi_limit():
    try:
        research.run_research_scan(
            master=[{"exch_seg": "nse_cm", "symbol": "ABC-EQ", "token": "1", "tick_size": "5"}],
            feed_factory=lambda *_: None,
            angel_client=object(),
            subscription_batch_size=1001,
        )
    except ValueError as exc:
        assert "1,000" in str(exc)
    else:
        raise AssertionError("expected batch limit validation")
