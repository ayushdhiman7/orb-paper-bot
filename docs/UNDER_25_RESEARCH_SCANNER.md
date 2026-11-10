# Under-₹25 NSE research scanner

## Safety and scope

This is a standalone, research-only command. It is not imported by the legacy bot or the Nifty 50 runner, has no broker order placement path, and always reports `paper_only=true` and `orders_submitted=0`. Do not connect its output directly to execution.

## Screening rules

- NSE cash `-EQ` instruments from the Angel One scrip master only.
- Fresh Angel One SNAP_QUOTE evidence; both exchange and receive timestamps must be within 45 seconds.
- Last traded price at or below ₹25.
- Best bid and ask must both be present and positive; crossed/invalid books are rejected.
- Midpoint spread must be at most 0.50%.
- Average daily traded value must be at least ₹5 crore, calculated as daily close (₹) × volume over at least 20 completed sessions strictly before the `as_of` date.
- Liquidity history is fetched only for instruments with a fresh quote at or below ₹25. Missing/blocked/insufficient history fails closed.
- Candidates are ranked by average daily traded value and capped at 100.

## Data acquisition and limits

The command batches WebSocket subscriptions at 900 tokens per session, below the SmartAPI 1,000-token session quota. Each batch gets a separate WebSocket session. It requires a fresh quote for every instrument to mark the universe coverage complete.

Daily history uses the persistent SQLite cache described in `NIFTY50_PAPER_RUNBOOK.md`. A cache miss/expiry requests ONE_DAY candles with the lower-level raw cache bypassed. Angel One access-rate blocking stops the history batch immediately. Do not retry repeatedly or increase concurrency to force completion.

The public scrip-master JSON is downloaded from Angel One at run time. No credentials or market data are committed to the repository.

## Run manually during NSE market hours

Use the existing project virtual environment and private `.env` credentials. Do not paste credentials into chat or commit them.

```bash
ORB_ALLOW_UNDER25_RESEARCH_SCAN=1 python under_25_research.py
```

Optional environment variables:

- `LOW_PRICE_LIQUIDITY_CACHE`: SQLite cache path (default `.low_price_cache/liquidity.sqlite3`).
- `LOW_PRICE_REPORT_PATH`: sanitized JSON report path (default `reports/under-25-research-latest.json`).

The command refuses to run unless explicitly enabled and within NSE market hours. It exits non-zero if the report has partial quote/history coverage. Review the report's `coverage`, `history_errors`, and `candidates`; do not treat a partial report as a complete market scan.

## Acceptance gates still requiring the operator

1. Verify the actual Angel One account can login and receive SNAP_QUOTE for the full batched NSE cash universe.
2. Verify symbol-level quote coverage, reconnect behavior and stale-quote rejection during a normal session.
3. Confirm historical ONE_DAY access for selected low-price candidates without triggering account rate limits.
4. Build a point-in-time historical dataset and cost-inclusive chronological out-of-sample backtest. Today's constituents must not be used as historical constituents.
5. Compare the research strategy with the Nifty 50 baseline using the same costs, risk limits, and dates.
6. Run several paper-only sessions and reconcile fills, fees, and daily limits before any release decision.

The scanner is not a profitability claim, and the under-₹25 universe is not a replacement for the existing Nifty 50 strategy. Keep PR review and deployment separate from these research acceptance gates.
