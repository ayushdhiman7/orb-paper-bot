# Nifty 50 universe resolver

This module resolves the live Nifty 50 membership from NSE's constituent CSV and
maps each symbol to the NSE cash-equity instrument token in Angel One's daily
OpenAPI scrip master. It does not use hardcoded constituent membership or guess
tokens.

Sources:
- NSE Nifty 50 index page / constituent CSV:
  https://www.nseindia.com/static/products-services/indices-nifty50-index
  https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv
- Angel One instrument master:
  https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json

Safety properties:
- Requires exactly 50 unique EQ constituents.
- Resolves only Angel One `nse_cm` instruments ending in `-EQ`.
- Rejects missing or ambiguous tokens and malformed source data.
- Downloads are bounded and time-limited; cache writes are atomic.
- This is a data/universe utility only. It does not start the WebSocket, submit
  orders, change the bot's watchlist, or enable trading.

Run the unit tests with `pytest -q test_nifty_universe.py`.
