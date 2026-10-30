import asyncio
import hmac
import json
import logging
import os
import time as time_module
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
from starlette.concurrency import run_in_threadpool

# Load the existing bot credentials without exposing them.
load_dotenv(Path.home() / "orb-paper-bot" / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

INDIA_TZ = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
PAGE_SIZE = 1000
WEBHOOK_MAX_SKEW_SECONDS = 300
EVENT_BATCH_SIZE = 1000
logger = logging.getLogger(__name__)

# Single-process fan-out: run the API with one Uvicorn worker. Events are
# persisted before broadcast; reconnecting clients replay from their DB cursor.
_event_subscribers: set[asyncio.Queue] = set()


def _broadcast_event(event: dict) -> None:
    for subscriber in tuple(_event_subscribers):
        try:
            subscriber.put_nowait(event)
        except asyncio.QueueFull:
            # Force this client to reconnect; Last-Event-ID will replay missed rows.
            while not subscriber.empty():
                try:
                    subscriber.get_nowait()
                except asyncio.QueueEmpty:
                    break
            try:
                subscriber.put_nowait({"_overflow": True})
            except asyncio.QueueFull:
                pass

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
    if not secret or not timestamp or not signature.startswith("sha256="):
        return False
    try:
        sent_at = int(timestamp)
        timestamp_bytes = timestamp.encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        return False
    if abs(time_module.time() - sent_at) > WEBHOOK_MAX_SKEW_SECONDS:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        timestamp_bytes + b"." + raw_body,
        digestmod="sha256",
    ).hexdigest()
    supplied = signature[len("sha256="):]
    return hmac.compare_digest(expected, supplied)


def _persist_dashboard_event(payload: dict) -> dict | None:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    client.table("dashboard_events").upsert(
        {
            "event_id": payload["event_id"],
            "event_type": payload["event_type"],
            "occurred_at": payload["occurred_at"],
            "source": str(payload.get("source", "orb-paper-bot"))[:80],
            "data": payload["data"],
        },
        on_conflict="event_id",
        ignore_duplicates=True,
    ).execute()
    # Read back even on duplicate delivery: if the first request persisted but
    # crashed before broadcasting, the retry must still wake connected clients.
    result = (
        client.table("dashboard_events")
        .select("id,event_id,event_type,occurred_at,source,data")
        .eq("event_id", payload["event_id"])
        .limit(1)
        .execute()
    )
    return (result.data or [None])[0]


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
    try:
        parsed_occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        if parsed_occurred_at.tzinfo is None:
            raise ValueError("Event timestamp must include a timezone")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid event timestamp")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=503, detail="Dashboard database configuration is missing")

    try:
        stored = await run_in_threadpool(_persist_dashboard_event, payload)
        if stored:
            _broadcast_event({
                "id": int(stored["id"]),
                "event_id": stored["event_id"],
                "event_type": stored["event_type"],
                "occurred_at": stored["occurred_at"],
                "source": stored["source"],
                "data": stored["data"],
            })
        return {"status": "accepted", "event_id": event_id, "duplicate": stored is None}
    except Exception:
        logger.exception("Unable to persist dashboard webhook event_id=%s", event_id)
        raise HTTPException(status_code=502, detail="Unable to persist dashboard event")


def _latest_dashboard_event_id() -> int:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    latest = (
        client.table("dashboard_events")
        .select("id")
        .order("id", desc=True)
        .limit(1)
        .execute()
    ).data or []
    return int(latest[0]["id"]) if latest else 0


def _fetch_dashboard_events_after(cursor: int) -> list[dict]:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return (
        client.table("dashboard_events")
        .select("id,event_id,event_type,occurred_at,source,data,received_at")
        .gt("id", cursor)
        .order("id")
        .limit(EVENT_BATCH_SIZE)
        .execute()
    ).data or []


@app.get("/api/events/stream")
async def stream_events(request: Request, after: int = Query(default=0, ge=0)):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=503, detail="Dashboard database configuration is missing")
    last_event_id = request.headers.get("Last-Event-ID", "").strip()
    has_last_event_id = bool(last_event_id)
    if last_event_id:
        try:
            after = max(after, int(last_event_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Last-Event-ID")

    async def generate():
        cursor = after
        subscriber: asyncio.Queue = asyncio.Queue(maxsize=256)
        # Subscribe before reading the durable cursor/history so events arriving
        # during setup are either replayed from the DB or buffered in this queue.
        _event_subscribers.add(subscriber)
        try:
            if not has_last_event_id:
                cursor = await run_in_threadpool(_latest_dashboard_event_id)
                ready_body = json.dumps({"cursor": cursor}, separators=(",", ":"))
                yield f"id: {cursor}\nevent: ready\ndata: {ready_body}\n\n"
                # Events committed after the cursor read but before/around the
                # ready frame must be replayed; subscription buffering covers
                # events arriving after this query starts.
                missed = await run_in_threadpool(_fetch_dashboard_events_after, cursor)
            else:
                missed = await run_in_threadpool(_fetch_dashboard_events_after, cursor)

            for row in missed:
                cursor = max(cursor, int(row["id"]))
                body = json.dumps({
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "occurred_at": row["occurred_at"],
                    "source": row["source"],
                    "data": row["data"],
                }, separators=(",", ":"))
                yield f"id: {cursor}\nevent: {row['event_type']}\ndata: {body}\n\n"

            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(subscriber.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if event.get("_overflow"):
                    yield "event: resync\ndata: {}\n\n"
                    break
                event_id = int(event["id"])
                if event_id <= cursor:
                    continue
                cursor = event_id
                body = json.dumps({
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "occurred_at": event["occurred_at"],
                    "source": event["source"],
                    "data": event["data"],
                }, separators=(",", ":"))
                yield f"id: {cursor}\nevent: {event['event_type']}\ndata: {body}\n\n"
        except Exception:
            logger.exception("Dashboard SSE stream failed")
        finally:
            _event_subscribers.discard(subscriber)

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
