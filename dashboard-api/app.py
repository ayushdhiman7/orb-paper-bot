import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import pandas_market_calendars as market_calendars
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

# Load the existing bot credentials without exposing them.
load_dotenv(Path.home() / "orb-paper-bot" / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

INDIA_TZ = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
PAGE_SIZE = 1000

app = FastAPI(title="ORB Dashboard API")

# Temporary local-development CORS configuration.
# Production uses same-origin Nginx proxying.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_range_utc_bounds(range_name: Literal["1D", "7D", "30D", "ALL"]) -> tuple[str | None, str | None]:
    """Return [start, end) UTC ISO timestamps for an Indian market-date range."""
    today_ist = datetime.now(INDIA_TZ).date()

    if range_name == "ALL":
        return None, None

    if range_name == "1D":
        start_date = today_ist
    else:
        session_count = 7 if range_name == "7D" else 30
        calendar = market_calendars.get_calendar("XNSE")
        lookback_days = 120 if session_count == 7 else 540
        schedule = calendar.schedule(
            start_date=(today_ist - timedelta(days=lookback_days)).isoformat(),
            end_date=today_ist.isoformat(),
        )
        session_dates = [session.date() for session in schedule.index if session.date() <= today_ist]
        if len(session_dates) < session_count:
            raise RuntimeError(f"Unable to find {session_count} recent NSE sessions")
        start_date = session_dates[-session_count]

    end_date = today_ist + timedelta(days=1)
    start_utc = datetime.combine(start_date, time.min, tzinfo=INDIA_TZ).astimezone(UTC)
    end_utc = datetime.combine(end_date, time.min, tzinfo=INDIA_TZ).astimezone(UTC)
    return start_utc.isoformat(), end_utc.isoformat()


def fetch_all_rows(client, table_name: str, timestamp_column: str, start_utc: str | None, end_utc: str | None):
    """Fetch every matching row in stable pages; ALL must not stop at 500/1000 rows."""
    rows = []
    offset = 0

    while True:
        query = (
            client.table(table_name)
            .select("*")
            .order(timestamp_column, desc=True)
        )
        if start_utc is not None:
            query = query.gte(timestamp_column, start_utc)
        if end_utc is not None:
            query = query.lt(timestamp_column, end_utc)

        page = query.range(offset, offset + PAGE_SIZE - 1).execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return rows


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard(range: Literal["1D", "7D", "30D", "ALL"] = Query(default="7D")):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(
            status_code=503,
            detail="Dashboard database configuration is missing",
        )

    try:
        start_utc, end_utc = get_range_utc_bounds(range)
        client = create_client(SUPABASE_URL, SUPABASE_KEY)

        trades = fetch_all_rows(client, "paper_trades", "ts", start_utc, end_utc)
        controls = fetch_all_rows(client, "shadow_trades", "ts", start_utc, end_utc)
        # Active positions are account state, not historical events: return all of them
        # independently of the selected journal/performance date range.
        open_positions = (
            client.table("paper_trades")
            .select("*")
            .eq("status", "open")
            .order("ts", desc=True)
            .execute()
        ).data or []

        # Backtests are historical research, not market-session trade records.
        backtests = (
            client.table("backtest_runs")
            .select("*")
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        ).data

        return {
            "range": range,
            "timezone": "Asia/Kolkata",
            "trades": trades,
            "open_positions": open_positions,
            "controls": controls,
            "backtests": backtests,
        }

    except HTTPException:
        raise
    except Exception:
        # Avoid leaking credentials, database responses, or internals.
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve dashboard data",
        )
