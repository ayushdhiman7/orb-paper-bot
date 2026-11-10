"""Read-only Angel WebSocket check. Never trades and never prints credentials.

Run only while orb-bot is stopped:  .venv/bin/python diagnose_feed.py
"""
import json
import os
import time

from dotenv import load_dotenv

load_dotenv()
from angel_websocket import AngelWebSocketFeed  # noqa: E402

cache = os.getenv("NIFTY50_UNIVERSE_CACHE", "/tmp/orb-nifty50-universe.json")
rows = json.load(open(cache))["instruments"]
feed = AngelWebSocketFeed([r["symbol"] for r in rows],
                          token_map={r["symbol"]: r["token"] for r in rows})
print("starting feed for", len(rows), "symbols; local epoch", int(time.time()))
try:
    feed.start()
except Exception as exc:  # message is already truncated and free of secrets
    print("START FAILED:", type(exc).__name__, str(exc)[:150])
    raise SystemExit(1)
for second in range(1, 26):
    time.sleep(1)
    if second % 5 == 0:
        sample = next(iter(feed.latest.values()), None)
        age = None if not sample else round(time.time() - sample["event_time"].timestamp(), 1)
        print(f"t={second}s connected={feed.connected} symbols_with_packets={len(feed.latest)} "
              f"thread_alive={feed._thread.is_alive()} sample_exchange_age_s={age} last_error={feed.last_error!r}")
feed.stop()
