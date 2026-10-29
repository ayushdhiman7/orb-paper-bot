"""
Telegram alerts. Never raises, never blocks the bot for long, never logs the token.
Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env; without them every call is a silent no-op.
"""
import json
import os
import urllib.request

TIMEOUT_SECONDS = 4
_SENT = set()


def configured():
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip())


def send(text, once_key=None):
    """Send one message. once_key: send only the first time this key is seen in this process (halt spam guard)."""
    if not configured():
        return False
    if once_key is not None:
        if once_key in _SENT:
            return False
        _SENT.add(once_key)
    token, chat = os.environ["TELEGRAM_BOT_TOKEN"].strip(), os.environ["TELEGRAM_CHAT_ID"].strip()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": chat, "text": str(text)[:3500]}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS).read()
        return True
    except Exception as e:          # the error text can contain the URL (and so the token): print only the type
        print(f"[warn] Telegram alert failed ({type(e).__name__})")
        return False
