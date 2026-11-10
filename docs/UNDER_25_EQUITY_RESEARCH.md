# Under-₹25 NSE equity scanner — research specification

## Status and safety boundary

This is a separate research-only universe. It does not replace the Nifty 50 scanner, change the EC2 service, modify Supabase, or place broker orders. The existing paper-only execution boundary and risk limits remain unchanged.

A share price below ₹25 is not evidence of better expected returns. Low nominal price can coincide with poor liquidity, wide spreads, price impact, circuit limits, and elevated volatility. The scanner therefore ranks only candidates that pass independent liquidity, quote freshness, and spread gates.

## Initial research defaults

| Setting | Initial value | Meaning |
|---|---:|---|
| Maximum last price | ₹25.00 inclusive | Rechecked at selection and before a paper plan |
| Minimum average daily traded value | ₹5 crore | Must come from trusted historical data |
| Maximum quoted spread | 0.50% | Requires actual best bid and ask; missing data rejects |
| Maximum candidates | 100 | Research shortlist cap, not a WebSocket subscription promise |
| Maximum quote age | 45 seconds | Reject stale/future timestamps |

These are starting hypotheses, not validated optimal thresholds. They must be configurable and tested in sensitivity analysis.

## Pipeline design

1. Parse Angel One scrip master for unique nse_cm -EQ instruments only.
2. Exclude ambiguous/malformed tokens; preserve exchange and token identity.
3. Apply an EOD liquidity prefilter before intraday WebSocket subscriptions. Never subscribe to the entire NSE cash universe blindly.
4. Obtain fresh quote snapshots for a bounded shortlist.
5. Require price <= ₹25, historical average traded value above the floor, fresh timestamp, valid positive bid/ask, and spread below the configured maximum.
6. Apply ORB setup filters (opening range, EMA20, VWAP, ATR14) only after feed/candle coverage is proven.
7. Recheck gates before a paper plan; retain tick-size validation, fees, taxes, slippage, risk sizing, and daily loss controls.

## Known integration blockers

- Current SNAP_QUOTE adapter returns LTP and timestamps but not a verified best-bid/best-ask pair. The selector rejects missing bid/ask. Do not wire it to runtime until packet fields are confirmed against official protocol/SDK and tested with sanitized packets.
- Adapter volume fields are not a trusted daily traded-value measure. Historical turnover must be sourced independently.
- Angel One subscription limits and throughput for a broader universe have not been established. Candidate cap is not a claim about broker limits.
- Exchange tick-size metadata must be validated before price rounding.
- Current Nifty50 pipeline hard-requires exactly 50 instruments. Preserve that invariant and build a separate dynamic-universe orchestration path.

## Validation and promotion gates

- Unit tests cover ₹25 boundary, ambiguous token rejection, liquidity, missing/wide spread, stale quotes, ranking, and shortlist cap.
- Integration tests must validate instrument master, turnover source, quote packet parsing, broker subscription capacity, reconnects, and full coverage during live market hours.
- Backtest point-in-time constituents and cost-inclusive fills. Compare with Nifty50 baseline over identical periods; report OOS trades, expectancy in R, profit factor, drawdown, turnover, slippage, per-symbol results, and rejected-candidate reasons.
- No runtime integration, deployment, or live execution until evidence gates pass. Execution remains paper-only.