"""
Health watchdog, run every 5 minutes by a systemd timer (separate from the bot, so it still works if the bot dies).
Alerts by Telegram when, during market hours on a weekday:
  * the orb-bot service is not running, or
  * an open paper trade's last price is older than STALE_MINUTES.
Each problem is reported once, then once more when it clears. State lives in .watchdog_state.json.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
START, END = dtime(9, 10), dtime(15, 35)
STALE_MINUTES = int(os.getenv("WATCHDOG_STALE_MINUTES", "10"))
STATE_FILE = os.getenv("WATCHDOG_STATE", ".watchdog_state.json")


def in_market_hours(now):
    return now.weekday() < 5 and START <= now.time() <= END


def evaluate(now, service_active, open_rows):
    """Returns {problem_key: message} for everything wrong right now. Pure: no network, no clock."""
    if not in_market_hours(now):
        return {}
    problems = {}
    if not service_active:
        problems["service"] = "orb-bot is NOT running during market hours."
    for r in open_rows:
        ts = r.get("last_price_ts") or r.get("ts")
        try:
            age = (now - datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(IST)).total_seconds() / 60
        except Exception:
            age = None
        if age is None or age > STALE_MINUTES:
            shown = "unknown" if age is None else f"{age:.0f} min"
            problems[f"stale:{r.get('symbol')}"] = (
                f"Open trade {r.get('symbol')} has had no price update for {shown}. Check the bot.")
    return problems


def diff_alerts(previous, current):
    """Messages to send: new problems, and recoveries. previous/current are {key: message}."""
    out = [f"ALERT: {m}" for k, m in current.items() if k not in previous]
    out += [f"RESOLVED: {previous[k]}" for k in previous if k not in current]
    return out


def _service_active():
    r = subprocess.run(["systemctl", "is-active", "orb-bot"], capture_output=True, text=True)
    return r.stdout.strip() == "active"


def _open_rows():
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return (sb.table("paper_trades").select("symbol,ts,last_price_ts")
            .eq("status", "open").eq("mode", "paper").limit(20).execute().data or [])


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
    except ImportError:
        pass
    import notify
    now = datetime.now(IST)
    try:
        prev = json.load(open(STATE_FILE))
    except Exception:
        prev = {}
    if not in_market_hours(now):
        cur = {}
    else:
        try:
            rows = _open_rows()
        except Exception as e:
            rows = []
            print(f"[warn] watchdog could not read Supabase ({type(e).__name__})")
        cur = evaluate(now, _service_active(), rows)
    for msg in diff_alerts(prev, cur):
        notify.send(msg)
        print(msg)
    json.dump(cur, open(STATE_FILE, "w"))


if __name__ == "__main__":
    sys.exit(main())
