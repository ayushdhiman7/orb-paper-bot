"""
Optional AI second opinion on each breakout, using Google's Gemini API.

Every actual HTTP attempt reserves a durable Gemini quota slot immediately before
network I/O. Structured decisions are durably audited without storing prompts,
raw responses, or credentials. Audit failure suppresses the AI opinion.
"""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from ai_audit import AuditWriteError, append_decision
from gemini_quota import PersistentGeminiQuota, QuotaStateError
from batch_entry import parse_batch_response

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


def _audit(event):
    try:
        append_decision(event)
        return True
    except (AuditWriteError, OSError, ValueError) as exc:
        print(f"[warn] AI opinion suppressed because audit persistence failed ({type(exc).__name__})")
        return False


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


def _ask(prompt, allowed, *, event_type="entry_review", symbol="UNKNOWN", parser=None, audit_decision=None):
    """Send Gemini request; quota and audit persistence are mandatory fail-closed gates."""
    global _working
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        _audit({"event_type": event_type, "symbol": symbol, "status": "unavailable",
                "error_type": "MissingApiKey"})
        return None
    try:
        quota = _get_quota()
    except Exception as exc:
        _audit({"event_type": event_type, "symbol": symbol, "status": "unavailable",
                "error_type": type(exc).__name__})
        print(f"[warn] Gemini request blocked by quota configuration ({type(exc).__name__})")
        return None

    for model in _models():
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
        for attempt in (0, 1):
            started = datetime.now(IST)
            try:
                try:
                    reserved, reason = quota.reserve(started)
                except (QuotaStateError, OSError, ValueError) as exc:
                    _audit({"event_type": event_type, "symbol": symbol, "model": model,
                            "attempt": attempt + 1, "status": "unavailable",
                            "error_type": type(exc).__name__})
                    print(f"[warn] Gemini request blocked by quota state ({type(exc).__name__})")
                    return None
                if not reserved:
                    _audit({"event_type": event_type, "symbol": symbol, "model": model,
                            "attempt": attempt + 1, "status": "quota_blocked",
                            "quota_reason": reason})
                    print(f"[warn] Gemini request blocked ({reason})")
                    return None

                response = _post(model, body, key)
                response_text = response["candidates"][0]["content"]["parts"][0]["text"]
                try:
                    out = parser(response_text) if parser is not None else _parse(response_text, allowed)
                except (TypeError, ValueError, KeyError):
                    out = None
                elapsed = int((datetime.now(IST) - started).total_seconds() * 1000)
                if out:
                    decision_value = audit_decision or out["decision"]
                    status = "approved" if decision_value in {"take", "hold", "batch"} else "rejected"
                    saved = _audit({"event_type": event_type, "symbol": symbol, "model": model,
                                    "attempt": attempt + 1, "status": status,
                                    "decision": decision_value,
                                    "reason": out.get("reason", f"validated batch with {len(out.get('decisions', []))} decisions"),
                                    "duration_ms": elapsed})
                    if not saved:
                        return None
                    _working = model
                    out["model"] = model
                    return out

                _audit({"event_type": event_type, "symbol": symbol, "model": model,
                        "attempt": attempt + 1, "status": "invalid_response",
                        "duration_ms": elapsed})
                print(f"[warn] AI reply unreadable from {model}")
                return None
            except urllib.error.HTTPError as exc:
                elapsed = int((datetime.now(IST) - started).total_seconds() * 1000)
                saved = _audit({"event_type": event_type, "symbol": symbol, "model": model,
                                "attempt": attempt + 1, "status": "unavailable",
                                "http_status": exc.code, "error_type": "HTTPError",
                                "duration_ms": elapsed})
                if not saved:
                    return None
                if exc.code == 400 and attempt == 0 and "generationConfig" in body:
                    body = {"contents": body["contents"]}
                    continue
                print(f"[warn] AI call failed on {model}: HTTP {exc.code}")
                break
            except Exception as exc:
                elapsed = int((datetime.now(IST) - started).total_seconds() * 1000)
                saved = _audit({"event_type": event_type, "symbol": symbol, "model": model,
                                "attempt": attempt + 1, "status": "unavailable",
                                "error_type": type(exc).__name__, "duration_ms": elapsed})
                if not saved:
                    return None
                print(f"[warn] AI call failed on {model}: {type(exc).__name__}")
                break
    return None


def review(ctx):
    """Entry opinion: take or skip this breakout. ctx is a small dict of facts. Returns dict or None."""
    symbol = ctx.get("symbol", "UNKNOWN") if isinstance(ctx, dict) else "UNKNOWN"
    return _ask(PROMPT.format(ctx=json.dumps(ctx, indent=2, default=str)),
                ("take", "skip"), event_type="entry_review", symbol=symbol)


def review_exit(ctx):
    """Exit opinion on an OPEN trade: hold or exit now. Returns dict or None (None means: keep holding)."""
    symbol = ctx.get("symbol", "UNKNOWN") if isinstance(ctx, dict) else "UNKNOWN"
    return _ask(EXIT_PROMPT.format(ctx=json.dumps(ctx, indent=2, default=str)),
                ("hold", "exit"), event_type="position_review", symbol=symbol)


BATCH_PROMPT = """You are a cautious intraday trading decision engine for a PAPER-ONLY NSE ORB system.
Review the complete candidate list together and return exactly one decision per candidate.
Do not invent facts. Never reverse the candidate's existing breakout side.
Return JSON only: {{"decisions":[{{"symbol":"...","decision":"BUY|SELL|SKIP",
"confidence":0.0,"reason":"short evidence-based reason","stop":0.0,"target":0.0,"rank":1}}]}}
For SKIP, stop and target must both be null. For BUY/SELL, provide positive stop and target
consistent with the side and current price. Rank every candidate uniquely from 1.
Candidate batch:
{ctx}"""


def review_batch(ctx, expected_symbols):
    """One Gemini request for the entire candidate batch; malformed/partial output fails closed."""
    if not isinstance(ctx, list) or not ctx or not isinstance(expected_symbols, set) or not expected_symbols:
        return None
    if not os.getenv("GEMINI_API_KEY", "").strip():
        _audit({"event_type": "entry_review", "symbol": "NIFTY50_BATCH", "status": "unavailable",
                "error_type": "MissingApiKey"})
        return None
    prompt = BATCH_PROMPT.format(ctx=json.dumps(ctx, separators=(",", ":"), default=str))
    def parse(text):
        return {"decisions": parse_batch_response(text, expected_symbols),
                "reason": f"validated complete batch of {len(expected_symbols)} candidates"}
    return _ask(prompt, (), event_type="entry_review", symbol="NIFTY50_BATCH",
                parser=parse, audit_decision="batch")
