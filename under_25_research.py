"""One-shot, research-only under-₹25 NSE scanner orchestration.

This command never places orders and is not imported by either trading runner.
It requires fresh SNAP_QUOTE evidence and 20 completed daily sessions; incomplete
coverage is reported as a failed/partial research run, never as an eligible list.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from angel_data import AngelBlocked, AngelClient
from angel_websocket import AngelWebSocketFeed
from liquidity_history import SQLiteDailyCandleCache, load_average_daily_values
from low_price_universe import LowPriceConfig, parse_nse_cash_equities, select_under_25_candidates

IST = ZoneInfo("Asia/Kolkata")
SCRIP_MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"


def fetch_scrip_master(*, timeout=20, opener=urlopen):
    request = Request(SCRIP_MASTER_URL, headers={"User-Agent": "ORB-paper-research/1.0"})
    with opener(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("Angel One scrip master response is not a list")
    return payload


def wait_for_quotes(feed, instruments, *, timeout_seconds=90, poll_seconds=1, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout_seconds
    latest = {}
    while clock() < deadline:
        now = datetime.now(IST)
        for instrument in instruments:
            symbol = instrument["symbol"]
            evidence = feed.quote(symbol, now)
            if evidence is not None:
                latest[symbol] = evidence
        if len(latest) == len(instruments):
            break
        sleep(poll_seconds)
    return latest


def build_research_report(*, instruments, quotes, average_values, history_errors,
                          as_of, generated_at, config=LowPriceConfig()):
    candidates = select_under_25_candidates(
        instruments, quotes, average_values, now_epoch=generated_at.timestamp(), config=config
    )
    report = {
        "mode": "research_only",
        "paper_only": True,
        "orders_submitted": 0,
        "generated_at": generated_at.isoformat(),
        "as_of": as_of.isoformat(),
        "criteria": {
            "max_price_inr": str(config.max_price),
            "min_avg_daily_traded_value_inr": str(config.min_avg_daily_value),
            "max_spread_pct": str(config.max_spread_pct),
            "max_quote_age_seconds": config.max_quote_age_seconds,
            "min_completed_sessions": 20,
        },
        "coverage": {
            "instruments": len(instruments),
            "fresh_quotes": len(quotes),
            "liquidity_values": len(average_values),
            "history_errors": len(history_errors),
            "full_coverage": len(quotes) == len(instruments) and len(average_values) == len(instruments),
        },
        "candidates": candidates,
        "history_errors": {str(k): str(v)[:180] for k, v in history_errors.items()},
    }
    report["status"] = "complete" if report["coverage"]["full_coverage"] else "partial"
    return report


def run_research_scan(*, master, feed, angel_client, as_of=None, generated_at=None,
                      cache=None, quote_timeout_seconds=90, config=LowPriceConfig()):
    as_of = as_of or datetime.now(IST).date()
    generated_at = generated_at or datetime.now(IST)
    instruments = parse_nse_cash_equities(master)
    if not instruments:
        raise RuntimeError("No valid NSE cash EQ instruments found in scrip master")
    # The SmartAPI V2 session quota is 1,000 tokens. Keep this separate scan below it.
    if len(instruments) > 1000:
        raise RuntimeError("NSE cash universe exceeds the 1,000-token WebSocket session quota")
    feed.start()
    try:
        quotes = wait_for_quotes(feed, instruments, timeout_seconds=quote_timeout_seconds)
    finally:
        feed.stop()
    values, errors = load_average_daily_values(
        instruments, angel_client=angel_client, as_of=as_of, cache=cache,
        now_epoch=generated_at.timestamp(),
    )
    return build_research_report(
        instruments=instruments, quotes=quotes, average_values=values,
        history_errors=errors, as_of=as_of, generated_at=generated_at, config=config,
    )


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    if os.getenv("ORB_ALLOW_UNDER25_RESEARCH_SCAN", "").strip().lower() not in {"1", "true", "yes"}:
        raise SystemExit("Set ORB_ALLOW_UNDER25_RESEARCH_SCAN=1 to explicitly run this research-only scan.")
    now = datetime.now(IST)
    if now.weekday() >= 5 or not (now.replace(hour=9, minute=15, second=0, microsecond=0)
                                  <= now <= now.replace(hour=15, minute=30, second=0, microsecond=0)):
        raise SystemExit("Run during NSE market hours on a trading day; no live quote is inferred off-session.")
    master = fetch_scrip_master()
    instruments = parse_nse_cash_equities(master)
    if not instruments:
        raise SystemExit("No NSE cash EQ instruments found.")
    # Keep WebSocket subscriptions within the SmartAPI 1,000-token limit.
    token_map = {row["symbol"]: row["token"] for row in instruments}
    feed = AngelWebSocketFeed([row["symbol"] for row in instruments], token_map=token_map)
    client = AngelClient()
    report = run_research_scan(master=master, feed=feed, angel_client=client)
    output = Path(os.getenv("LOW_PRICE_REPORT_PATH", "reports/under-25-research-latest.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({
        "status": report["status"], "coverage": report["coverage"],
        "candidate_count": len(report["candidates"]), "report_path": str(output),
        "orders_submitted": 0, "paper_only": True,
    }, indent=2))
    if report["status"] != "complete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
