"""
Optional AI second opinion on each breakout, using Google's Gemini API.

Every actual HTTP attempt reserves a durable Gemini quota slot immediately before
network I/O. Missing credentials, quota exhaustion, corrupt quota state, or network
failure fail closed and return None; existing paper strategy behaviour is unchanged.
"""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from gemini_quota import PersistentGeminiQuota, QuotaStateError

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview"]
TIMEOUT = 20
IST = ZoneInfo("Asia/Kolkata")
_working = None
_quota = None


def _get_quota():
    global _quota
    if _quota is None:
        _quota = PersistentGeminiQuota(
            daily_limit=int(os.getenv("GEMINI_MAX_REQUESTS_PER_DAY", "100")),
            per_minute_limit=int(os.getenv("GEMINI_MAX_REQUESTS_PER_MINUTE", "5")),
        )
    return _quota


PROMPT = """You are a cautious intraday-trading risk reviewer for a PAPER-trading bot on Indian (NSE) stocks.
The bot wants to enter the trade below after an opening-range breakout. Decide whether this particular breakout
looks worth taking, or looks like a likely false breakout.
Use only the data given. Do not invent news or facts. Reply with JSON only, in this exact shape:
{{"decision": "take" or "skip", "reason": "<one short sentence>"}}

Trade data:
{ctx}"""

EXIT_PROMPT = """You are a cautious intraday-trading risk manager for a PAPER-trading bot on Indian (NSE) stocks.
The bot already holds the position below. Every few minutes you decide: "hold" (keep it open, the fixed stop
and target stay in place) or "exit" (close it at the current price now).
Guidance: do not let a decent open profit turn into a loss; do not exit a position that is merely a little
down while the setup is still intact (the stop loss already protects the downside); every exit costs brokerage;
everything is closed automatically at 15:15 IST. Weigh momentum from the recent closes, how much profit has been
given back from the peak, and how much time is left. Use only the data given. Do not invent news or facts.
Reply with JSON only, in this exact shape:
{{"decision": "hold" or "exit", "reason": "<one short sentence>"}}

Position data:
{ctx}"""


def _models():
    env = os.getenv("GEMINI_MODEL", "").strip()
    models = [env] if env else list(DEFAULT_MODELS)
    if _working and _working in models:
        models.remove(_working)
        models.insert(0, _working)
    return models


def _post(model, body, key):
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _parse(text, allowed=("take", "skip")):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0) if m else text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    decision = str(data.get("decision", "")).strip().lower()
    if decision not in allowed:
        return None
    return {"decision": decision, "reason": str(data.get("reason", ""))[:200]}


def _ask(prompt, allowed):
    """Send a Gemini request. Every HTTP attempt consumes one reserved quota slot."""
    global _working
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    try:
        quota = _get_quota()
    except Exception as exc:
        print(f"[warn] Gemini request blocked by quota configuration ({type(exc).__name__})")
        return None
    for model in _models():
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
        for attempt in (0, 1):
            try:
                try:
                    reserved, reason = quota.reserve(datetime.now(IST))
                except (QuotaStateError, OSError, ValueError) as exc:
                    print(f"[warn] Gemini request blocked by quota state ({type(exc).__name__})")
                    return None
                if not reserved:
                    print(f"[warn] Gemini request blocked ({reason})")
                    return None
                resp = _post(model, body, key)
                response_text = resp["candidates"][0]["content"]["parts"][0]["text"]
                out = _parse(response_text, allowed)
                if out:
                    _working = model
                    out["model"] = model
                    return out
                print(f"[warn] AI reply unreadable from {model}")
                return None
            except urllib.error.HTTPError as e:
                if e.code == 400 and attempt == 0 and "generationConfig" in body:
                    body = {"contents": body["contents"]}
                    continue
                print(f"[warn] AI call failed on {model}: HTTP {e.code}")
                break
            except Exception as e:
                print(f"[warn] AI call failed on {model}: {type(e).__name__}")
                break
    return None


def review(ctx):
    """Entry opinion: take or skip this breakout. ctx is a small dict of facts. Returns dict or None."""
    return _ask(PROMPT.format(ctx=json.dumps(ctx, indent=2, default=str)), ("take", "skip"))


def review_exit(ctx):
    """Exit opinion on an OPEN trade: hold or exit now. Returns dict or None (None means: keep holding)."""
    return _ask(EXIT_PROMPT.format(ctx=json.dumps(ctx, indent=2, default=str)), ("hold", "exit"))
