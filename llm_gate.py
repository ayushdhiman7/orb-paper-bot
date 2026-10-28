"""
Optional AI second opinion on each breakout, using Google's Gemini API.

Fails safe: if there is no key, the network fails, or the reply is unreadable, review() returns None and the
bot carries on exactly as before. The key is read from the GEMINI_API_KEY environment variable only
(a GitHub Actions secret). Never put it in a file.
"""
import json
import os
import re
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Model names change often. GEMINI_MODEL overrides; otherwise try these in order and remember the one that works.
DEFAULT_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview"]
TIMEOUT = 20
_working = None

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
    """Pull {"decision","reason"} out of the model's text. Returns None if unreadable."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0) if m else text)
    except Exception:
        return None
    decision = str(data.get("decision", "")).strip().lower()
    if decision not in allowed:
        return None
    return {"decision": decision, "reason": str(data.get("reason", ""))[:200]}


def _ask(prompt, allowed):
    """Send one prompt, try model names in turn. Returns {"decision","reason","model"} or None. Never raises."""
    global _working
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    for model in _models():
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
        for attempt in (0, 1):
            try:
                resp = _post(model, body, key)
                text = resp["candidates"][0]["content"]["parts"][0]["text"]
                out = _parse(text, allowed)
                if out:
                    _working = model
                    out["model"] = model
                    return out
                print(f"[warn] AI reply unreadable from {model}")
                return None
            except urllib.error.HTTPError as e:
                if e.code == 400 and attempt == 0 and "generationConfig" in body:
                    body = {"contents": body["contents"]}   # some models reject JSON mode: retry plain
                    continue
                print(f"[warn] AI call failed on {model}: HTTP {e.code}")
                break   # 404 (unknown model), 403 (key problem), 429 ...: try the next model name
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
