# Under-₹25 NSE equity scanner — research specification

## Status and safety boundary

Separate research-only universe. It does not replace the Nifty 50 scanner, change EC2, modify Supabase, or place broker orders. Existing paper-only execution and risk limits remain unchanged.

A share price below ₹25 is not evidence of better expected returns. Low nominal price can coincide with poor liquidity, wide spreads, price impact, circuit limits, and elevated volatility. Candidates must pass independent liquidity, quote freshness, and spread gates.

## Initial research defaults

| Setting | Initial value | Meaning |
|---|---:|---|
| Maximum last price | ₹25.00 inclusive | Rechecked at selection and before paper plan |
| Minimum average daily traded value | ₹5 crore | 20 completed daily sessions minimum |
| Maximum quoted spread | 0.50% | Requires actual best bid and ask; missing data rejects |
| Maximum candidates | 100 | Well below documented 1,000 subscription quota for one WebSocket session |
| Maximum quote age | 45 seconds | Reject stale/future timestamps |

These are initial research hypotheses, not optimized thresholds. Test sensitivity before runtime adoption.

## Data contract and verified SmartAPI behavior

- SmartAPI SNAP_QUOTE mode provides five buy and five sell depth levels; each level contains flag, quantity, price, and order count. Binary prices are paise and must be divided by 100. The SDK parser exposes `best_5_buy_data` and `best_5_sell_data`.
- Best bid is the highest valid buy price with positive quantity; best ask is the lowest valid sell price with positive quantity. Missing depth means missing spread and must reject the candidate.
- SNAP_QUOTE also provides average traded price and volume traded for the day. Their product estimates current-session traded value, not historical average daily turnover.
- The SmartAPI docs state a 1,000 total token-subscription quota per WebSocket session. This includes subscriptions across modes; a 100-candidate SNAP_QUOTE shortlist is below the documented cap, but account-level feed acceptance still needs testing.
- Angel One daily historical candle records provide [timestamp, open, high, low, close, volume] with prices in rupees. The liquidity helper computes average close*volume from at least 20 completed sessions before the screening date. This is a proxy turnover estimate, not exchange-reported traded value.

## Pipeline

1. Parse unique Angel One `nse_cm` `-EQ` instruments; reject ambiguous tokens.
2. Build liquidity shortlist from at least 20 completed daily candles per symbol. Exclude insufficient or malformed history.
3. Subscribe only the bounded shortlist in SNAP_QUOTE mode; respect 1,000 total subscriptions per session.
4. Require LTP <= ₹25, valid fresh best bid/ask, spread <= configured maximum, and historical turnover >= configured floor.
5. Apply ORB filters only after current-session completed candle and full quote coverage are proven; recheck price and risk before a paper plan.
6. Preserve tick-size validation, costs, slippage, position limits and daily loss controls. Never infer spread from LTP or total buy/sell quantities.

## Remaining blockers

- Historical candle access previously hit Angel One rate denial for this account. The new liquidity helper is implemented and unit-tested, but a reliable bulk EOD source/cache and real-account retrieval test are still required. Do not hammer historical endpoints.
- Broker WebSocket account entitlement, actual 100-symbol quote/depth completeness, reconnect behavior, and packet-field delivery must be tested during market hours.
- The existing Nifty50 runtime still hard-requires 50 symbols. Keep it unchanged; the new dynamic scanner needs a separate orchestrator.
- Exchange tick size is supplied by scrip master in paise; normalize to rupees and validate order-price alignment before any paper order simulation.

## Validation and promotion gates

- Unit tests cover instrument filtering, ambiguous token rejection, ₹25 boundary, liquidity, missing/wide spread, stale quotes, ranking, candidate cap, SNAP_QUOTE depth parsing, and historical-turnover calculations.
- Integration tests: actual scrip master, at least 20 EOD sessions, 100-symbol quote coverage, depth completeness, subscription quota, reconnects and persistence during a live market session.
- Cost-inclusive point-in-time backtest vs Nifty50 baseline; report out-of-sample trades, expectancy in R, profit factor, drawdown, turnover, slippage, per-symbol results and rejection reasons.
- No merge-to-runtime, deployment, or live execution until gates pass. Paper-only remains mandatory.