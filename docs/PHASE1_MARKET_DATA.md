# Phase 1 market-data and indicator contract

## Candle source and timeframe

- Primary source: Angel One SmartAPI WebSocket V2, NSE cash-market instruments.
- Subscribe in one batch for the configured stock universe using SNAP_QUOTE mode (mode 3).
- SmartAPI binary packet prices are scaled from paise to rupees (last_traded_price / 100).
- The WebSocket is the live quote transport. REST historical-candle calls are not used for the live loop.
- Build indicators from completed 5-minute candles only. Do not mix an unfinished candle into a signal.

## Indicator definitions

1. **5-minute trend:** EMA(20) of completed 5-minute closes. Bullish only when latest close is above EMA20 and latest EMA20 is above the prior completed-candle EMA20. Bearish is the inverse. Otherwise neutral. Require sufficient data; insufficient data blocks entry.
2. **VWAP:** session VWAP reset at 09:15 IST each trading day, calculated as cumulative typical price multiplied by volume divided by cumulative volume. Typical price is (high + low + close) / 3 for each completed 5-minute candle.
3. **ATR:** ATR(14) on completed 5-minute candles, using Wilder smoothing and true range. Requires 15 candles (first candle supplies the prior close).
4. **Alignment:** BUY requires bullish trend and close above VWAP. SELL requires bearish trend and close below VWAP. Neutral, missing, or insufficient indicator data blocks entry.

## ATR usage

ATR and distance-from-VWAP measured in ATR units are exposed in the indicator snapshot. No hard ATR entry threshold is enabled in this phase because a maximum extension / minimum volatility threshold has not been approved or validated. It must not silently become a hard-coded trading filter.

## Safety and rollout

- This phase adds a WebSocket V2 adapter, completed 5-minute candle builder, pure indicator calculations, and offline tests. The adapter is not wired into bot.py, so the existing strategy/feed remains unchanged and no order placement is enabled.
- Candle buckets use the exchange packet timestamp; last-trade timestamp is retained only as a fallback. Volume is derived from changes in cumulative day volume, with last-traded quantity used for the first sample of a session.
- SNAP_QUOTE access must be validated against the actual Angel One account before relying on the feed.
- The adapter uses the SDK SNAP_QUOTE subscription and configured retry policy. Real-account SNAP_QUOTE entitlement, actual packet fields, reconnect/resubscribe behaviour, and volume reconciliation still require a controlled market-hours smoke test before the new feed can become the bot's primary data source.
- Telegram AI-confidence and risk-verdict fields remain a separate validation item.
- Paper trading only. No live order API is used.
