# Nifty 50 candidate collector

The collector is a deterministic, read-only strategy layer. It consumes the
validated 50-stock universe and a feed adapter exposing `last(symbol)` and
`candles(symbol)`. It returns a complete batch of qualifying candidates.

Rules:
- Scan window: 09:30 through 14:30 IST.
- Opening range: exactly three completed 5-minute candles timestamped 09:15,
  09:20 and 09:25 IST.
- BUY: current fresh quote strictly above opening-range high.
- SELL: current fresh quote strictly below opening-range low.
- Indicators: EMA20 direction/close alignment, session VWAP agreement, and
  Wilder ATR14 as implemented in `indicators.py`. Insufficient/neutral data
  blocks the candidate.
- Optional sentiment is attached as context only; it cannot create or reverse
  a breakout candidate.
- A malformed or unavailable symbol is skipped, not guessed. The validated
  universe itself must contain exactly 50 unique symbols and tokens.

This module does not call Gemini, size positions, persist trades, or submit
broker orders. The caller remains responsible for a fresh feed health check,
risk validation, and a fail-closed AI decision stage before any paper entry.

Run tests with `pytest -q test_candidate_collector.py`.
