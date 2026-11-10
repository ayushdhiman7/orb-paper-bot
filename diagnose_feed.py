"""Read-only Angel WebSocket check. Never trades and never prints credentials.

Run only while orb-bot is stopped:  .venv/bin/python diagnose_feed.py
"""
import json
import os
import statistics
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()
from angel_websocket import AngelWebSocketFeed  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
cache = os.getenv("NIFTY50_UNIVERSE_CACHE", "/tmp/orb-nifty50-universe.json")
rows = json.load(open(cache))["instruments"]
feed = AngelWebSocketFeed([r["symbol"] for r in rows],
                          token_map={r["symbol"]: r["token"] for r in rows})
raw = {}
packets = {"n": 0}
original = feed._on_data


def capture(wsapp, packet):
    packets["n"] += 1
    sym = feed.token_to_symbol.get(str(packet.get("token", "")))
    if sym:
        raw.setdefault(sym, []).append({
            "ex": packet.get("exchange_timestamp"), "lt": packet.get("last_traded_timestamp"),
            "ltp": packet.get("last_traded_price"), "vol": packet.get("volume_trade_for_the_day"),
            "at": time.time()})
    return original(wsapp, packet)


feed._on_data = capture
print("now_utc", datetime.now(timezone.utc).isoformat(timespec="seconds"),
      "now_ist", datetime.now(IST).isoformat(timespec="seconds"))
try:
    feed.start()
except Exception as exc:
    print("START FAILED:", type(exc).__name__, str(exc)[:150])
    raise SystemExit(1)
time.sleep(25)
feed.stop()


def when(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(float(ms) / 1000, IST).strftime("%Y-%m-%d %H:%M:%S IST")


print("packets total:", packets["n"], "symbols:", len(raw))
ages = [time.time() - float(v[-1]["ex"]) / 1000 for v in raw.values() if v[-1]["ex"]]
if ages:
    print("exchange_ts age s  min/median/max:", round(min(ages)), round(statistics.median(ages)), round(max(ages)))
for sym in list(raw)[:4]:
    first, last = raw[sym][0], raw[sym][-1]
    print(sym, "packets", len(raw[sym]), "ex", when(last["ex"]), "lt", when(last["lt"]),
          "ltp", first["ltp"], "->", last["ltp"], "vol", first["vol"], "->", last["vol"])
