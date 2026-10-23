"""Pluggable alert dispatcher (2026-10-15). One place every bot sends alerts through.

ALERT_CHANNELS = comma list of: telegram, discord, email, ntfy   (or "off")
  unset  -> "telegram" when TELEGRAM_TOKEN + TELEGRAM_CHAT_ID are set, else off
  imessage is reserved for the later Mac version and is ignored here (logged once).

Telegram behaviour is unchanged: same Bot API call and payload per caller, and the
warden's backup alert bot (X_NOTIFY_TELEGRAM_TOKEN, falls back to TELEGRAM_TOKEN).

Every attempt is logged to bot_logs/alerts.log as
  time | source | channel | sent/failed/throttled | detail | preview
Never a token, password, webhook URL or chat id.
"""
from __future__ import annotations

import asyncio
import html as _html
import json
import os
import re
import smtplib
import ssl
import threading
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path

CHANNELS = {
    #  name       Title Case label         required keys                               optional keys (default)
    "telegram": ("Telegram",            ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"),     {"X_NOTIFY_TELEGRAM_TOKEN": ""}),
    "discord":  ("Discord Webhook",     ("DISCORD_WEBHOOK_URL",),                    {}),
    "email":    ("Email (SMTP)",        ("SMTP_HOST", "ALERT_EMAIL_TO"),             {"SMTP_PORT": "587", "SMTP_USER": "", "SMTP_PASS": "",
                                                                                      "SMTP_FROM": "", "SMTP_STARTTLS": "1",
                                                                                      "ALERT_EMAIL_MIN_INTERVAL_S": "60"}),
    "ntfy":     ("Ntfy",                ("NTFY_TOPIC",),                             {"NTFY_URL": "https://ntfy.sh", "NTFY_TOKEN": ""}),
}
SECRET_KEYS = {"TELEGRAM_TOKEN", "X_NOTIFY_TELEGRAM_TOKEN", "DISCORD_WEBHOOK_URL", "SMTP_PASS", "NTFY_TOKEN"}
PLANNED = {"imessage": "iMessage - planned for the Mac version, not available yet"}

_ROOT = Path(os.environ.get("WORKSPACE_DIR") or Path(__file__).resolve().parents[2])
_LOCK = threading.Lock()
_EMAIL_STATE = {"last": 0.0, "suppressed": 0}
_NOTED = set()


# -- env -------------------------------------------------------------------------
def _dotenv() -> dict:
    out = {}
    for f in (_ROOT / ".env", _ROOT / "bots" / ".env"):       # bots/.env wins (the wizard writes it)
        try:
            for line in f.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = re.sub(r"\s+#.*$", "", v).strip().strip('"').strip("'")
        except Exception:
            pass
    return out


def env(overrides: dict | None = None) -> dict:
    """.env, then the process environment, then explicit overrides (tests / wizard)."""
    e = _dotenv()
    e.update({k: v for k, v in os.environ.items() if k in _all_keys() or k == "ALERT_CHANNELS"})
    if overrides is not None:
        e.update(overrides)
    return e


def _all_keys() -> set:
    s = set()
    for _, req, opt in CHANNELS.values():
        s.update(req); s.update(opt)
    return s


def channels(e: dict | None = None) -> list:
    """Selected channels, in order. Unknown names are ignored (planned ones noted once)."""
    e = env() if e is None else e
    raw = str(e.get("ALERT_CHANNELS") or "").strip().lower()
    if not raw:
        return ["telegram"] if (str(e.get("TELEGRAM_TOKEN") or "").strip()
                                and str(e.get("TELEGRAM_CHAT_ID") or "").strip()) else []
    out = []
    for c in [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]:
        if c in ("off", "none"):
            return []
        if c in CHANNELS and c not in out:
            out.append(c)
        elif c in PLANNED and c not in _NOTED:
            _NOTED.add(c)
            _log("dispatcher", c, "skipped", PLANNED[c], "")
    return out


def missing(name: str, e: dict) -> list:
    return [k for k in CHANNELS[name][1] if not str(e.get(k) or "").strip()]


def status(e: dict | None = None) -> list:
    """Status-first rows for wizard / settings. No values, only Set/Missing."""
    e = env() if e is None else e
    sel = channels(e)
    rows = []
    for name, (label, req, opt) in CHANNELS.items():
        miss = missing(name, e)
        on = name in sel
        st = ("On" if not miss else "On - Missing Keys") if on else ("Off (Configured)" if not miss else "Off")
        rows.append({"channel": name, "label": label, "on": on, "configured": not miss,
                     "missing": miss, "status": st, "keys": list(req) + list(opt)})
    for name, note in PLANNED.items():
        rows.append({"channel": name, "label": "iMessage", "on": False, "configured": False,
                     "missing": [], "status": "Later (Mac Version)", "keys": [], "note": note})
    return rows


# -- logging (no secrets) ------------------------------------------------------------
def _preview(msg: str) -> str:
    p = _strip_html(str(msg)).replace("\n", " ").strip()
    return p[:60]


def _log(source: str, channel: str, outcome: str, detail: str, msg: str) -> None:
    try:
        d = _ROOT / "bot_logs"
        d.mkdir(parents=True, exist_ok=True)
        line = (f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {source} | {channel} | {outcome} | "
                f"{detail} | {_preview(msg) if msg else ''}\n")
        with _LOCK, open(d / "alerts.log", "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _err(e: Exception) -> str:
    code = getattr(e, "code", None)
    return f"HTTP {code}" if code else type(e).__name__     # never str(e): it can carry the URL/token


def _strip_html(s: str) -> str:
    return _html.unescape(re.sub(r"</?(b|i|u|s|em|strong|code|pre|a|br|tg-spoiler)(\s[^>]*)?/?>", "", s, flags=re.I))


# -- transports (sync, injectable opener for tests) ---------------------------------------
def _post(opener, url: str, data: bytes, headers: dict, timeout: int = 15):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with opener(req, timeout=timeout) as r:
        return getattr(r, "status", 200), r.read().decode("utf-8", "replace")


def _telegram(e, msg, *, html_mode, silent, token, opener, tg_plain=False, **_) -> str:
    tok = str(token or e.get("TELEGRAM_TOKEN") or "").strip()
    payload = {"chat_id": str(e.get("TELEGRAM_CHAT_ID") or "").strip(), "text": msg}
    if tg_plain:
        pass                                   # launch_rail: bare chat_id + text, as before
    elif html_mode:
        payload["parse_mode"] = "HTML"
    else:
        payload["disable_web_page_preview"] = True
        payload["disable_notification"] = bool(silent)
    st, body = _post(opener, f"https://api.telegram.org/bot{tok}/sendMessage",
                     json.dumps(payload).encode(), {"Content-Type": "application/json"}, 10)
    j = json.loads(body or "{}")
    if not j.get("ok", st == 200):
        raise RuntimeError(f"telegram not ok: {str(j.get('description') or '')[:60]}")
    return "ok"


def _discord(e, msg, *, opener, **_) -> str:
    _post(opener, str(e["DISCORD_WEBHOOK_URL"]).strip(),
          json.dumps({"content": _strip_html(msg)[:1990]}).encode(),
          {"Content-Type": "application/json", "User-Agent": "MemeSniper-Alerts"})
    return "ok"


def _ntfy(e, msg, *, silent, opener, **_) -> str:
    base = str(e.get("NTFY_URL") or "https://ntfy.sh").strip().rstrip("/")
    h = {"Title": "Meme Sniper", "Priority": "low" if silent else "default"}
    if str(e.get("NTFY_TOKEN") or "").strip():
        h["Authorization"] = "Bearer " + str(e["NTFY_TOKEN"]).strip()
    _post(opener, f"{base}/{urllib.parse.quote(str(e['NTFY_TOPIC']).strip())}",
          _strip_html(msg).encode("utf-8"), h)
    return "ok"


def _email(e, msg, *, smtp_factory=None, **_) -> str:
    now = time.time()
    gap = float(e.get("ALERT_EMAIL_MIN_INTERVAL_S") or 60)
    if now - _EMAIL_STATE["last"] < gap:
        _EMAIL_STATE["suppressed"] += 1
        return "throttled"
    text = _strip_html(msg)
    if _EMAIL_STATE["suppressed"]:
        text += f"\n\n(+{_EMAIL_STATE['suppressed']} more alert(s) in the last window were not emailed; see the console/logs)"
    m = EmailMessage()
    m["Subject"] = "Meme Sniper: " + (text.splitlines()[0][:70] if text.strip() else "alert")
    m["From"] = str(e.get("SMTP_FROM") or e.get("SMTP_USER") or e.get("ALERT_EMAIL_TO")).strip()
    m["To"] = str(e["ALERT_EMAIL_TO"]).strip()
    m.set_content(text)
    host, port = str(e["SMTP_HOST"]).strip(), int(e.get("SMTP_PORT") or 587)
    if smtp_factory:
        s = smtp_factory(host, port)
    elif port == 465:
        s = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
    else:
        s = smtplib.SMTP(host, port, timeout=15)
    try:
        if port != 465 and str(e.get("SMTP_STARTTLS") or "1").strip().lower() not in ("0", "false", "no", "off"):
            s.starttls(context=ssl.create_default_context())
        if str(e.get("SMTP_USER") or "").strip():
            s.login(str(e["SMTP_USER"]).strip(), str(e.get("SMTP_PASS") or ""))
        s.send_message(m)
    finally:
        try:
            s.quit()
        except Exception:
            pass
    _EMAIL_STATE["last"], _EMAIL_STATE["suppressed"] = now, 0
    return "ok"


_TRANSPORT = {"telegram": _telegram, "discord": _discord, "email": _email, "ntfy": _ntfy}


# -- public API ------------------------------------------------------------------
def send_sync(msg: str, *, source: str = "bot", html: bool = False, silent: bool = False,
              telegram_token: str | None = None, only: list | None = None, tg_plain: bool = False,
              env_override: dict | None = None, opener=None, smtp_factory=None) -> dict:
    """Send to every selected channel (or `only`). Returns {channel: 'sent'|'throttled'|'failed: ...'}."""
    e = env(env_override)
    out = {}
    for ch in (only or channels(e)):
        if ch not in CHANNELS:
            continue
        miss = missing(ch, e)
        if miss:
            out[ch] = "failed: missing " + ",".join(miss)
            _log(source, ch, "failed", out[ch], msg)
            continue
        try:
            r = _TRANSPORT[ch](e, msg, html_mode=html, silent=silent, token=telegram_token,
                               opener=opener or urllib.request.urlopen, smtp_factory=smtp_factory,
                               tg_plain=tg_plain)
            out[ch] = "throttled" if r == "throttled" else "sent"
            _log(source, ch, out[ch], "ok" if r == "ok" else "email min interval", msg)
        except Exception as ex:
            out[ch] = "failed: " + _err(ex)
            _log(source, ch, "failed", _err(ex), msg)
    return out


async def send(msg: str, **kw) -> dict:
    """Async wrapper; never raises."""
    try:
        return await asyncio.to_thread(send_sync, msg, **kw)
    except Exception as ex:
        _log(kw.get("source", "bot"), "dispatcher", "failed", _err(ex), msg)
        return {}


def test(channel: str, env_override: dict | None = None, opener=None, smtp_factory=None) -> dict:
    """One test message on one channel. Telegram also tests the backup alert bot when set."""
    e = env(env_override)
    label = CHANNELS.get(channel, (channel,))[0]
    text = f"Meme Sniper test message ({label}). If you see this, alerts reach you."
    if channel == "email":
        _EMAIL_STATE["last"] = 0.0
    res = send_sync(text, source="test", only=[channel], env_override=env_override,
                    opener=opener, smtp_factory=smtp_factory)
    if channel == "telegram" and str(e.get("X_NOTIFY_TELEGRAM_TOKEN") or "").strip() and not missing("telegram", e):
        b = send_sync(text.replace("(Telegram)", "(Telegram, Backup Alert Bot)"), source="test", only=["telegram"],
                      telegram_token=e["X_NOTIFY_TELEGRAM_TOKEN"], env_override=env_override, opener=opener)
        res["telegram_backup"] = b.get("telegram", "failed")
    return res


HINTS = {
    "HTTP 401": "401 = token/credentials wrong",
    "HTTP 403": "403 = not allowed (bot not in chat, webhook revoked, or topic protected)",
    "HTTP 404": "404 = wrong webhook URL / topic / endpoint",
    "HTTP 400": "400 = bad request (Telegram: wrong chat ID, or you have not messaged the bot yet)",
    "SMTPAuthenticationError": "SMTP login refused - check SMTP_USER / SMTP_PASS (Gmail needs an app password)",
}
