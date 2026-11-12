"""x_session.py: ONE resolved X browser profile + an honest session status.

Used by agent_scraper (scrapes and --login), the launcher (Sign in to X) and the console status,
so all three always look at the same profile.

Profile: bots/scraper_profile (inside this repo) by default. BROWSER_USER_DATA_DIR (+ optional
BROWSER_PROFILE_NAME) is an explicit opt-in to use another Chrome user-data dir instead.

Status (never reads cookie values, only names and expiry; the DB is opened read-only):
  verified    auth_token + ct0 unexpired AND the scraper saw a logged-in X page (account switcher
              visible) in this profile within X_VERIFY_MAX_AGE_H (default 24h), with no logged-out
              page seen since.                                       -> "Connected (verified)"
  unverified  auth_token + ct0 present and unexpired, but no recent logged-in page seen.
                                                                     -> "Cookie present, unverified"
  expired     cookies past expiry, or the scraper last saw a login wall.  -> "Expired"
  missing     no X session cookies in this profile.                   -> "Missing"
The marker is bot_logs/x_session.json (handle, profile, verified_at / logged_out_at), written by
agent_scraper after each X page it loads and by --login.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

BOTS = Path(__file__).resolve().parent.parent


def _root() -> Path:
    ws = os.environ.get("WORKSPACE_DIR")
    return Path(ws) if ws else BOTS.parent


def bot_logs() -> Path:
    return _root() / "bot_logs"


def marker_path() -> Path:
    return bot_logs() / "x_session.json"


def profile(env: dict | None = None):
    """(user_data_dir, sub_profile_name or None). Default: <repo>/bots/scraper_profile, no sub-profile."""
    env = os.environ if env is None else env
    ud = str(env.get("BROWSER_USER_DATA_DIR") or "").strip()
    if ud:
        return str(Path(ud)), (str(env.get("BROWSER_PROFILE_NAME") or "").strip() or "Default")
    return str(_root() / "bots" / "scraper_profile"), None


def cookie_dir(env: dict | None = None) -> Path:
    ud, name = profile(env)
    return Path(ud) / (name or "Default")


def cookie_meta(env: dict | None = None):
    """{name: expires_epoch|0} for auth_token / ct0 / twid; None when there is no cookie DB."""
    d = cookie_dir(env)
    for db in (d / "Network" / "Cookies", d / "Cookies"):
        if not db.exists():
            continue
        con = sqlite3.connect("file:" + db.as_posix() + "?mode=ro&immutable=1", uri=True, timeout=2)
        try:
            rows = con.execute("SELECT name, expires_utc FROM cookies WHERE name IN ('auth_token','ct0','twid') "
                               "AND (host_key LIKE '%x.com' OR host_key LIKE '%twitter.com')").fetchall()
        finally:
            con.close()
        out = {}
        for n, e in rows:
            exp = (float(e) / 1e6 - 11644473600) if e else 0.0
            out[n] = max(out.get(n, 0.0), exp)
        return out
    return None


def _read_marker() -> dict:
    try:
        d = json.loads(marker_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _epoch(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def record(logged_in: bool, handle: str = "", env: dict | None = None) -> None:
    """Called by agent_scraper after it loads an X page in this profile."""
    d = _read_marker()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    d["profile"] = str(cookie_dir(env))
    if logged_in:
        d["verified_at"] = now
        d["verified_ts"] = time.time()
        if handle:
            d["handle"] = handle if handle.startswith("@") else "@" + handle
    else:
        d["logged_out_at"] = now
        d["logged_out_ts"] = time.time()
    try:
        marker_path().parent.mkdir(parents=True, exist_ok=True)
        tmp = marker_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
        os.replace(tmp, marker_path())
    except Exception:
        pass


def status(env: dict | None = None, now: float | None = None) -> dict:
    """{state, label, handle, expires, profile, detail}. Honest: verified needs a recent logged-in page."""
    now = time.time() if now is None else now
    env = os.environ if env is None else env
    prof = str(cookie_dir(env))
    out = {"state": "missing", "label": "Missing", "handle": "", "expires": None, "profile": prof, "detail": ""}
    try:
        meta = cookie_meta(env)
    except Exception as e:
        out["detail"] = f"cookie db unreadable ({type(e).__name__})"
        return out
    if not meta or "auth_token" not in meta or "ct0" not in meta:
        out["detail"] = "no X session cookies in this profile"
        return out
    exps = [meta.get(n, 0.0) for n in ("auth_token", "ct0")]
    real = [x for x in exps if x]
    out["expires"] = min(real) if real else None
    if any(x and x <= now for x in exps):
        out.update(state="expired", label="Expired", detail="auth_token/ct0 past expiry")
        return out
    m = _read_marker()
    same = str(m.get("profile") or "") == prof
    v = m.get("verified_ts") or _epoch(m.get("verified_at"))
    lo = m.get("logged_out_ts") or _epoch(m.get("logged_out_at"))
    max_age = float(env.get("X_VERIFY_MAX_AGE_H") or 24) * 3600
    out["handle"] = str(m.get("handle") or "") if same else ""
    if same and lo and (not v or lo > v):
        out.update(state="expired", label="Expired", detail="scraper last saw the X login page")
    elif same and v and now - v <= max_age:
        age = int((now - v) / 60)
        out.update(state="verified", label="Connected (verified)",
                   detail=f"logged-in X page seen {age // 60}h{age % 60:02d}m ago by the scraper")
    else:
        out.update(state="unverified", label="Cookie present, unverified",
                   detail="cookies valid, but no logged-in X page seen recently in this profile")
    return out


def describe(st: dict) -> str:
    s = st["label"]
    if st.get("handle") and st["state"] in ("verified", "unverified"):
        s += f" as {st['handle']}"
    if st.get("expires") and st["state"] != "missing":
        s += " (expires " + datetime.fromtimestamp(st["expires"]).strftime("%Y-%m-%d") + ")"
    return s


# pause / resume the scraper around a re-login (same flag the console uses)
def scraper_running(max_age_s: float = 180) -> bool:
    try:
        hb = json.loads((bot_logs() / "agent_scraper_heartbeat.json").read_text(encoding="utf-8"))
        t = _epoch(hb.get("timestamp"))
        return bool(t) and time.time() - t < max_age_s
    except Exception:
        return False


def pause_scraper(timeout_s: float = 180.0, poll_s: float = 2.0):
    f = bot_logs() / "agent_scraper_pause.flag"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"by": "launcher", "why": "x_sign_in",
                             "at": datetime.now().astimezone().isoformat(timespec="seconds")}), encoding="utf-8")
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            hb = json.loads((bot_logs() / "agent_scraper_heartbeat.json").read_text(encoding="utf-8"))
            t = _epoch(hb.get("timestamp"))
            if hb.get("status") == "paused" and t and time.time() - t < 30:
                return True, "paused"
        except Exception:
            pass
        time.sleep(poll_s)
    resume_scraper()
    return False, "scraper did not pause in time (mid-task, or its code predates the pause flag). Nothing changed."


def resume_scraper() -> None:
    try:
        (bot_logs() / "agent_scraper_pause.flag").unlink()
    except Exception:
        pass
