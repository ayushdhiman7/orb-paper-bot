import asyncio
import hmac
import json
import os
import time
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import pandas_market_calendars as market_calendars
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

# Load the existing bot credentials without exposing them.
load_dotenv(Path.home() / "orb-paper-bot" / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

INDIA_TZ = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
PAGE_SIZE = 1000
WEBHOOK_MAX_SKEW_SECONDS = 300
EVENT_BATCH_SIZE = 100

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


def _webhook_secret() -> str:
    return os.getenv("DASHBOARD_WEBHOOK_SECRET", "").strip()


def _verify_webhook(raw_body: bytes, timestamp: str, signature: str) -> bool:
    secret = _webhook_secret()
    if not secret or not timestamp or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - sent_at) > WEBHOOK_MAX_SKEW_SECONDS:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + raw_body,
        digestmod="sha256",
    ).hexdigest()
    supplied = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, supplied)


@app.post("/api/events")
async def ingest_event(request: Request):
    raw_body = await request.body()
    timestamp = request.headers.get("X-ORB-Timestamp", "")
    signature = request.headers.get("X-ORB-Signature", "")
    if not _verify_webhook(raw_body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Invalid event payload")

    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    occurred_at = payload.get("occurred_at")
    data = payload.get("data")
    if (
        not isinstance(event_id, str) or not event_id or len(event_id) > 128
        or not isinstance(event_type, str)
        or event_type not in {"trade.opened", "trade.closed", "bot.status_changed", "risk.alert"}
        or not isinstance(occurred_at, str)
        or not isinstance(data, dict)
    ):
        raise HTTPException(status_code=422, detail="Invalid event payload")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=503, detail="Dashboard database configuration is missing")

    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        client.table("dashboard_events").upsert(
            {
                "event_id": event_id,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "source": str(payload.get("source", "orb-paper-bot"))[:80],
                "data": data,
            },
            on_conflict="event_id",
            ignore_duplicates=True,
        ).execute()
        return {"status": "accepted", "event_id": event_id}
    except Exception:
        raise HTTPException(status_code=502, detail="Unable to persist dashboard event")


@app.get("/api/events/stream")
async def stream_events(request: Request, after: int = Query(default=0, ge=0)):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=503, detail="Dashboard database configuration is missing")
    last_event_id = request.headers.get("Last-Event-ID", "").strip()
    if last_event_id:
        try:
            after = max(after, int(last_event_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Last-Event-ID")

    async def generate():
        cursor = after
        if cursor == 0:
            # New browser sessions start at the current head; reconnects resume from Last-Event-ID.
            try:
                client = create_client(SUPABASE_URL, SUPABASE_KEY)
                latest = (
                    client.table("dashboard_events")
                    .select("id")
                    .order("id", desc=True)
                    .limit(1)
                    .execute()
                ).data or []
                if latest:
                    cursor = int(latest[0]["id"])
            except Exception:
                pass
        last_keepalive = time.monotonic()
        while not await request.is_disconnected():
            try:
                client = create_client(SUPABASE_URL, SUPABASE_KEY)
                rows = (
                    client.table("dashboard_events")
                    .select("id,event_id,event_type,occurred_at,source,data,received_at")
                    .gt("id", cursor)
                    .order("id")
                    .limit(EVENT_BATCH_SIZE)
                    .execute()
                ).data or []
                for row in rows:
                    cursor = max(cursor, int(row["id"]))
                    event_name = row["event_type"]
                    body = json.dumps(
                        {
                            "event_id": row["event_id"],
                            "event_type": event_name,
                            "occurred_at": row["occurred_at"],
                            "source": row["source"],
                            "data": row["data"],
                        },
                        separators=(",", ":"),
                    )
                    yield f"id: {cursor}\\nevent: {event_name}\\ndata: {body}\\n\\n"
                if rows:
                    continue
            except Exception:
                # A transient database error must not terminate EventSource reconnect handling.
                pass

            if time.monotonic() - last_keepalive >= 15:
                yield ": keep-alive\\n\\n"
                last_keepalive = time.monotonic()
            await asyncio.sleep(2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
