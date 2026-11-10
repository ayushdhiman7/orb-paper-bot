"""Strict Nifty 50 constituent and Angel One NSE cash-token resolver.

The NSE CSV is the source of constituent membership; Angel One's daily scrip
master is the source of broker tokens. This module deliberately refuses partial
or ambiguous mappings so the scanner cannot silently trade a smaller universe.
"""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import time

import requests
from datetime import datetime, timezone
from pathlib import Path

NSE_CONSTITUENTS_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
ANGEL_MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
EXPECTED_CONSTITUENTS = 50


class UniverseError(RuntimeError):
    """The official constituent list or broker token mapping is unsafe to use."""


def _text(value):
    return str(value or "").strip()


def parse_nse_constituents(csv_text):
    """Parse NSE's constituent CSV, tolerating its title/preamble rows."""
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))
    header_index = None
    for i, row in enumerate(rows):
        names = {cell.strip().lower() for cell in row}
        if "symbol" in names and "series" in names:
            header_index = i
            break
    if header_index is None:
        raise UniverseError("NSE CSV is missing Symbol/Series header")
    header = [cell.strip().lower() for cell in rows[header_index]]
    symbol_col, series_col = header.index("symbol"), header.index("series")
    symbols = []
    for row in rows[header_index + 1:]:
        if len(row) <= max(symbol_col, series_col):
            continue
        symbol = _text(row[symbol_col]).upper()
        series = _text(row[series_col]).upper()
        if symbol and series == "EQ":
            symbols.append(symbol)
    if len(symbols) != EXPECTED_CONSTITUENTS:
        raise UniverseError(
            f"Expected exactly {EXPECTED_CONSTITUENTS} Nifty 50 EQ constituents; received {len(symbols)}"
        )
    if len(set(symbols)) != EXPECTED_CONSTITUENTS:
        raise UniverseError("NSE constituent list contains duplicate symbols")
    return symbols


# Angel's public scrip master labels cash-market rows NSE; older fixtures used nse_cm.
NSE_CASH_SEGMENTS = {'nse', 'nse_cm'}


def parse_angel_master(payload):
    """Return unique NSE cash-equity symbol -> token mappings from Angel master JSON."""
    try:
        rows = json.loads(payload) if isinstance(payload, (str, bytes, bytearray)) else payload
    except (TypeError, ValueError) as exc:
        raise UniverseError("Angel One instrument master is not valid JSON") from exc
    if not isinstance(rows, list):
        raise UniverseError("Angel One instrument master must be a JSON array")
    found = {}
    duplicates = set()
    for row in rows:
        if not isinstance(row, dict) or _text(row.get("exch_seg")).lower() not in NSE_CASH_SEGMENTS:
            continue
        tradingsymbol = _text(row.get("symbol")).upper()
        if not tradingsymbol.endswith("-EQ"):
            continue
        symbol = tradingsymbol[:-3]
        token = _text(row.get("token"))
        if not symbol or not token or not token.isdigit():
            continue
        if symbol in found and found[symbol] != token:
            duplicates.add(symbol)
        found[symbol] = token
    for symbol in duplicates:
        found.pop(symbol, None)
    if duplicates:
        raise UniverseError("Ambiguous Angel One tokens for: " + ", ".join(sorted(duplicates)))
    return found


def build_nifty50_universe(nse_csv, angel_master):
    """Build ordered records; fail unless every current NSE constituent maps exactly once."""
    constituents = parse_nse_constituents(nse_csv)
    token_map = parse_angel_master(angel_master)
    missing = [symbol for symbol in constituents if symbol not in token_map]
    if missing:
        raise UniverseError("Missing Angel One NSE cash tokens for: " + ", ".join(missing))
    return [
        {"symbol": symbol, "tradingsymbol": f"{symbol}-EQ", "token": token_map[symbol], "exchange": "NSE"}
        for symbol in constituents
    ]


def _download(session, url, max_bytes, referer=None, attempts=3):
    """Download official source data with bounded retries and size validation."""
    headers = {"Accept": "application/json,text/csv,*/*"}
    if referer:
        headers["Referer"] = referer
    last_error = None
    for attempt in range(attempts):
        try:
            with session.get(url, headers=headers, timeout=(8, 35), stream=True) as response:
                response.raise_for_status()
                length = response.headers.get("Content-Length")
                if length and int(length) > max_bytes:
                    raise UniverseError(f"Download exceeds configured size limit: {url}")
                data = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise UniverseError(f"Download exceeds configured size limit: {url}")
                if not data:
                    raise UniverseError(f"Empty download: {url}")
                return bytes(data)
        except UniverseError:
            raise
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise UniverseError(f"Failed to download {url} after {attempts} attempts: {last_error}")


def fetch_nifty50_universe():
    """Fetch official sources using an NSE-warmed session and validate all 50."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        try:  # NSE homepage may 403 from cloud IPs; the archive CSV can still work afterwards.
            session.get("https://www.nseindia.com/", timeout=(8, 12))
        except requests.RequestException:
            pass
        nse_csv = _download(session, NSE_CONSTITUENTS_URL, 1_000_000,
                            referer="https://www.nseindia.com/").decode("utf-8-sig")
        angel_master = _download(session, ANGEL_MASTER_URL, 50_000_000)
        return build_nifty50_universe(nse_csv, angel_master)
    finally:
        session.close()


def write_universe_cache(universe, path):
    """Atomically write a validated universe cache; callers must not use stale/partial data."""
    if not isinstance(universe, list) or len(universe) != EXPECTED_CONSTITUENTS:
        raise UniverseError("Refusing to cache an incomplete Nifty 50 universe")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": {"constituents": NSE_CONSTITUENTS_URL, "instruments": ANGEL_MASTER_URL},
        "instruments": universe,
    }
    fd, temp_path = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
