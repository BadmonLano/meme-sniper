"""agent_autoagent.py - The Overseer (v4.3.1)

(Public build: history trimmed; see TIMELINE.md.)
"""
import os

def _envv(key, default=None):
    """os.getenv, but a blank value (KEY= in .env) counts as unset and returns the default."""
    v = os.environ.get(key)
    return default if v is None or not str(v).strip() else v


# ── Workspace root (public build) ─────────────────────────────────────────
# WORKSPACE_DIR in the environment wins; otherwise the repo root is the
# folder that contains bots/ (works from bots/ and bots/sub-bots/).
def _resolve_workspace_root():
    _env = (os.environ.get("WORKSPACE_DIR") or "").strip()
    if _env:
        return os.path.abspath(os.path.expanduser(_env))
    _p = os.path.dirname(os.path.abspath(__file__))
    _root = None
    for _ in range(6):
        if os.path.basename(_p).lower() == "bots":
            _root = os.path.dirname(_p); break
        if os.path.isdir(os.path.join(_p, "bots")) and os.path.isdir(os.path.join(_p, "skills")):
            _root = _p; break
        _p = os.path.dirname(_p)
    _root = _root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # .env may not be loaded yet at import time: honour WORKSPACE_DIR set there too.
    for _envf in (os.path.join(_root, "bots", ".env"), os.path.join(_root, ".env")):
        try:
            with open(_envf, encoding="utf-8-sig") as _fh:
                for _ln in _fh:
                    if _ln.strip().startswith("WORKSPACE_DIR="):
                        _v = _ln.split("=", 1)[1].strip().strip('"').strip("'")
                        if _v:
                            return os.path.abspath(os.path.expanduser(_v))
        except OSError:
            pass
    return _root
WS_ROOT = _resolve_workspace_root()
WS_BOTS = os.path.join(WS_ROOT, "bots")
WS_BOT_LOGS = os.path.join(WS_ROOT, "bot_logs")
WS_JSON_RELAY = os.path.join(WS_ROOT, "json_relay")
for _d in (os.path.join(WS_ROOT, "inbox"), os.path.join(WS_ROOT, "inbox_results", "done"),
           os.path.join(WS_ROOT, "inbox_results", "failed"), os.path.join(WS_ROOT, "owner_inbox"),
           os.path.join(WS_ROOT, "learnings"), os.path.join(WS_ROOT, "rules"), WS_BOT_LOGS, WS_JSON_RELAY):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass
# ──────────────────────────────────────────────────────────────────────────

_WS = WS_ROOT  # workspace root
import json
import asyncio
import httpx
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# ── env ──────────────────────────────────────────────────────────────────────
_env_path = os.path.join(WS_BOTS, ".env")
load_dotenv(_env_path, override=False)

try:  # LLM_MAIN / LLM_FALLBACK: unselected providers are off in this process
    import llm_providers as _llm_choice
    _llm_choice.apply_choice()
except Exception:
    pass

EST = ZoneInfo("America/New_York")

# ── paths ────────────────────────────────────────────────────────────────────
BASE          = os.path.join(_WS, r"bots")
LOGS          = WS_BOT_LOGS

_BLIND_SPOTS: list = []


TRAINING      = os.path.join(LOGS, "training")
JSON_RELAY    = WS_JSON_RELAY
INBOX         = os.path.join(_WS, r"inbox")
INBOX_RESULTS = os.path.join(_WS, r"inbox_results")
INBOX_DONE    = os.path.join(INBOX_RESULTS, "done")
INBOX_EXPIRED = os.path.join(INBOX_DONE, "expired")
LEARNINGS     = os.path.join(_WS, r"learnings\LEARNINGS.md")
DAILY_SUM     = os.path.join(LOGS, "daily_summaries")
OVERSEER_HIST = os.path.join(LOGS, "overseer_history.json")
OVERSEER_LOG  = os.path.join(LOGS, "overseer.log")
SKILLS_DIR    = os.path.join(_WS, r"skills")

CURIOSITY_LOG         = os.path.join(LOGS, "agent_curiosity_log.md")

# Sprint 33+ paths (v4.1  -  this session)
SIGNAL_CONTRACTS_DIR  = os.path.join(BASE, "signal_contracts")
# Reuse INBOX_DONE (already defined above)  -  this is where curated audits live

# ── xai grok api ─────────────────────────────────────────────────────────────
# Overseer judge runs Grok (xAI) with a sharp intent-vs-action spec. Local Ollama is fallback.
# xAI is OpenAI-compatible (chat/completions), NOT Anthropic's messages shape.
GROK_API_KEY  = os.getenv("GROK_API_KEY", "")  # env var is GROK_API_KEY
XAI_API_URL  = "https://api.x.ai/v1/chat/completions"
def _overseer_model() -> str:
    """OVERSEER_GROK_MODEL pins it; else grok_brain_models.json analyst role."""
    pin = os.getenv("OVERSEER_GROK_MODEL", "").strip()
    if pin and pin.lower() != "auto":
        return pin
    try:
        with open(os.path.join(WS_BOT_LOGS,
                               "grok_brain_models.json"), encoding="utf-8") as _f:
            _r = (json.load(_f) or {}).get("roles") or {}
        return _r.get("analyst") or "grok-4.7"
    except Exception:
        return "grok-4.7"


XAI_MODEL    = _overseer_model()
GROK_MAX_TOKENS = 4096
GROK_TIMEOUT    = 360  # grok-4.7 reasons past the old 120s cap

# ── ollama fallback ──────────────────────────────────────────────────────────
OLLAMA_URL          = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_FALLBACK_MODEL = os.getenv("OVERSEER_FALLBACK_MODEL", "qwen3:14b-q4_K_M")
OLLAMA_TIMEOUT      = 480

# ── telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── runtime constants ────────────────────────────────────────────────────────
LOOKBACK_HOURS  = 24
# Meme sizing (reverse-size) check needs more than one day of closes to mean anything.
SIZING_LOOKBACK_HOURS = int(_envv("AUTOAGENT_SIZING_LOOKBACK_H", "168") or 168)
MAX_PROMPT_CHARS = 120000  # v4.1: bumped from 80k → 120k to fit Sprint 33 evidence sections. grok-4.7 has a large context window, still well under.
DEXSCREENER_TOP_BOOSTS = "https://api.dexscreener.com/token-boosts/top/v1"

# ── daemon mode constants (Sprint 29.1) ──────────────────────────────────────
HEARTBEAT_FILE      = os.path.join(LOGS, "agent_autoagent_heartbeat.json")
LAST_RUN_STATE_FILE = os.path.join(LOGS, "overseer_last_run.json")
HEARTBEAT_INTERVAL  = 60       # write heartbeat every 60s while sleeping
SCHEDULED_HOUR_EST  = int(_envv("OVERSEER_SCHEDULED_HOUR_EST", "2"))   # default 2am
SCHEDULED_MINUTE    = int(_envv("OVERSEER_SCHEDULED_MINUTE", "0"))    # default :00
MIN_HOURS_BETWEEN_RUNS = 23    # belt-and-suspenders: don't double-fire if clock jumps


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def now_iso() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def now_str() -> str:
    return datetime.now(EST).strftime("%Y-%m-%d %H:%M ET")


def log(msg: str):
    line = f"[{now_iso()}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(OVERSEER_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_text(path: str, max_chars: int = 5000) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read()
        return txt[-max_chars:] if len(txt) > max_chars else txt
    except Exception:
        return ""


def load_jsonl_tail(path: str, max_records: int = 50) -> list:
    """Read last N records from a JSONL file."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        records = []
        for line in lines[-max_records*2:]:  # over-read to account for filtering
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
        return records[-max_records:]
    except Exception as e:
        log(f"  load_jsonl_tail({path}): {e}")
        return []


def save_json_atomic(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def is_recent(timestamp_str: str, hours: int = LOOKBACK_HOURS) -> bool:
    """True if ISO timestamp string falls within last N hours."""
    if not timestamp_str:
        return False
    try:
        ts = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=EST)
        cutoff = datetime.now(EST) - timedelta(hours=hours)
        return ts >= cutoff
    except Exception:
        return False


def parse_timestamp(timestamp_str: str):
    """Best-effort ISO timestamp parse, returns datetime or None."""
    if not timestamp_str:
        return None
    try:
        ts = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=EST)
        return ts.astimezone(EST)
    except Exception:
        return None


def time_bucket(ts) -> str:
    """Bucket a datetime into morning/midday/afternoon/evening/late."""
    if not ts:
        return "unknown"
    h = ts.hour
    if 5 <= h < 11:
        return "morning"      # 5am-11am
    if 11 <= h < 14:
        return "midday"       # 11am-2pm
    if 14 <= h < 17:
        return "afternoon"    # 2pm-5pm (the tilt window)
    if 17 <= h < 21:
        return "evening"      # 5pm-9pm
    return "late"             # 9pm-5am


_ALERTS_MOD = None


def _alerts_mod():
    """bots/sub-bots/alerts.py (2026-10-15 pluggable alerts). None = fall back to direct Telegram."""
    global _ALERTS_MOD
    if _ALERTS_MOD is None:
        try:
            import importlib.util as _ilu
            _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alerts.py")
            _spec = _ilu.spec_from_file_location("ms_alerts", _p)
            _m = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_m)
            _ALERTS_MOD = _m
        except Exception:
            _ALERTS_MOD = False
    return _ALERTS_MOD or None


async def notify(msg: str):
    """Best-effort telegram. No-op if not configured."""
    _am = _alerts_mod()
    if _am is not None:
        _res = await _am.send(msg, source="agent_autoagent", html=True)
        return
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id":    TELEGRAM_CHAT_ID,
                    "text":       msg,
                    "parse_mode": "HTML",
                },
            )
    except Exception as e:
        log(f"telegram notify failed (non-fatal): {e}")


def _filter_recent_hours(records, hours, *fields):
    """filter_recent with an explicit window (hours)."""
    out = []
    for r in records if isinstance(records, list) else []:
        if isinstance(r, dict) and any(r.get(f) and is_recent(str(r.get(f)), hours) for f in fields):
            out.append(r)
    return out


def _read_jsonl_tail(path, max_bytes=4_000_000):
    """Parse the last max_bytes of a JSONL file (miss_book grows forever)."""
    rows = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", "replace")
        lines = data.splitlines()
        if size > max_bytes and lines:
            lines = lines[1:]  # first line is probably cut
        for ln in lines:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    continue
    except Exception:
        pass
    return rows


def filter_recent(records, *fields):
    """Filter list of dicts to only those with one of `fields` within LOOKBACK_HOURS."""
    out = []
    if not isinstance(records, list):
        return out
    for r in records:
        if not isinstance(r, dict):
            continue
        for f in fields:
            ts = r.get(f)
            if ts and is_recent(str(ts)):
                out.append(r)
                break
    return out


# ═════════════════════════════════════════════════════════════════════════════
# DAEMON HELPERS (Sprint 29.1  -  forever-loop mode)
# ═════════════════════════════════════════════════════════════════════════════

def write_heartbeat(status: str, extra: dict = None):
    """Write the bot's own heartbeat. Warden + overseer's own bot_health
    block reads this. 30-min staleness = bot considered dead."""
    payload = {
        "timestamp":  now_iso(),
        "status":     status,
        "scheduled_hour_est":   SCHEDULED_HOUR_EST,
        "scheduled_minute":     SCHEDULED_MINUTE,
        "next_run_at_est":      _next_scheduled_dt().isoformat(),
        "grok_model":           XAI_MODEL,
        "ollama_fallback_model": OLLAMA_FALLBACK_MODEL,
    }
    if extra:
        payload.update(extra)
    try:
        save_json_atomic(HEARTBEAT_FILE, payload)
    except Exception as e:
        log(f"heartbeat write failed (non-fatal): {e}")


def _next_scheduled_dt() -> datetime:
    """Compute the next 2am ET datetime, in ET. If we're already past 2am today,
    returns tomorrow's 2am. Used both for sleep-target and heartbeat reporting."""
    now = datetime.now(EST)
    target = now.replace(hour=SCHEDULED_HOUR_EST, minute=SCHEDULED_MINUTE, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target


def _seconds_until_next_run() -> float:
    """How many seconds until the next 2am ET."""
    return (_next_scheduled_dt() - datetime.now(EST)).total_seconds()


def _load_last_run_state() -> dict:
    """Read state from previous run  -  used to enforce MIN_HOURS_BETWEEN_RUNS."""
    return load_json(LAST_RUN_STATE_FILE, {}) or {}


def _save_last_run_state(state: dict):
    """Persist last-run state so a daemon restart doesn't double-fire."""
    save_json_atomic(LAST_RUN_STATE_FILE, state)


def _can_fire_run() -> tuple:
    """
    Belt-and-suspenders: even if our scheduler logic gets confused (DST,
    manual time change, drift), refuse to re-fire within MIN_HOURS_BETWEEN_RUNS.
    Returns (allowed: bool, reason: str).
    """
    state = _load_last_run_state()
    last_completed_iso = state.get("last_completed_at")
    if not last_completed_iso:
        return True, "no prior run recorded"
    try:
        last_dt = datetime.fromisoformat(last_completed_iso)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=EST)
        elapsed_h = (datetime.now(EST) - last_dt).total_seconds() / 3600
        if elapsed_h < MIN_HOURS_BETWEEN_RUNS:
            return False, f"only {elapsed_h:.1f}h since last run (min {MIN_HOURS_BETWEEN_RUNS}h)"
        return True, f"{elapsed_h:.1f}h since last run, OK to fire"
    except Exception as e:
        return True, f"could not parse last run state ({e}), defaulting to allow"


def _record_run_completion(success: bool, packet_path: str = None, error: str = None):
    """After a run completes (or errors), persist state."""
    state = _load_last_run_state()
    state["last_attempted_at"] = now_iso()
    if success:
        state["last_completed_at"] = now_iso()
        state["last_packet_path"]  = packet_path
        state["last_status"]       = "success"
        state["consecutive_failures"] = 0
    else:
        state["last_status"] = "error"
        state["last_error"]  = (error or "")[:300]
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    _save_last_run_state(state)


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 1  -  INPUT COLLECTION (FULL COVERAGE)
# Sweep everything the agent touched in the last 24h. Better to over-read than under.
# ═════════════════════════════════════════════════════════════════════════════

def collect_inputs() -> dict:
    """Read everything from yesterday relevant to grading the agent's behavior."""
    log("STAGE 1: collecting inputs from last 24h…")
    inputs = {
        "lookback_hours": LOOKBACK_HOURS,
        "now": now_iso(),

        # Stated intent
        "thesis":       {},

        # Wallet / collateral
        "wallet_balance": {},


        # Per-lane execution data
        "meme":   {},

        # Cross-cutting
        "autopsies":       [],
        "missed_runners":  [],
        "inbox_handled":   [],
        "inbox_decisions": [],   # NEW v4: actual decisions the agent made (read inbox/done packets)
        "learnings_appended": "",
        "yesterdays_overseer_report": None,  # NEW v4: continuity with last night

        # Time-of-day analysis (NEW v4)
        "time_buckets": {
            "morning":   {"trades": 0, "signals": 0},
            "midday":    {"trades": 0, "signals": 0},
            "afternoon": {"trades": 0, "signals": 0},
            "evening":   {"trades": 0, "signals": 0},
            "late":      {"trades": 0, "signals": 0},
        },

        # Bot health (NEW v4 + v4.2 expansions)
        "bot_health": {
            "meme_sniper":     {"heartbeat_age_sec": None, "alive": False},
            "agent_autoagent": {"heartbeat_age_sec": None, "alive": False},
            # v4.1 (Sprint 33+)  -  the brain + signal producers + infrastructure
            "agent_scraper":  {"heartbeat_age_sec": None, "alive": False},
            "x_intel":         {"heartbeat_age_sec": None, "alive": False},
            "log_janitor":     {"heartbeat_age_sec": None, "alive": False},
            # v4.3 (Sprint 42)  -  code_tuner is the new self-observation organ
            "code_tuner":      {"heartbeat_age_sec": None, "alive": False},
        },

        # Sniper gating audits + signal contracts from ecosystem producers
        "sprint33_audits": {},          # counts + samples of gating decisions across 4 audit types
        "signal_contracts_summary": {}, # producer activity + severity breakdown + samples


        # v4.3 (Sprint 42)  -  code_tuner observation surface evidence
        "code_tuner_setup_state": {},   # bots_list.json: configured vs unconfigured counts, monitoring_active counts
        "metrics_current_snapshot": {}, # metrics_current.json: per-bot rolling perf values (refreshed every 30 min)
        "source_delta_count_24h": 0,    # count of P3_source_updated_* packets in last 24h
        "code_tuner_setup_activity_24h": {},  # invitations/discoveries/rejections counts in last 24h
        "pending_patch_packets_in_owner_inbox": 0,  # agent-authored patches sitting unapplied in owner_inbox
    }

    # ── Stated intent ─────────────────────────────────────────
    inputs["thesis"]         = load_json(os.path.join(LOGS, "agent_thesis.json"), {}) or {}
    # ── Wallet / collateral ────────────────────────────────────
    inputs["wallet_balance"] = load_json(os.path.join(LOGS, "wallet_balance.json"), {}) or {}
    # 2026-10-14: Sniper's treasury heartbeat writes this; >60 min old = untrusted.
    try:
        _wb_age_min = (datetime.now().timestamp() - os.path.getmtime(os.path.join(LOGS, "wallet_balance.json"))) / 60.0
        inputs["wallet_balance"]["_age_minutes"] = round(_wb_age_min, 1)
        if _wb_age_min > 60:
            inputs["wallet_balance"]["_trust"] = "STALE - untrusted (Sniper heartbeat >60 min old)"
    except Exception:
        inputs["wallet_balance"]["_trust"] = "MISSING - no wallet_balance.json"

    # ── MEME LANE ─────────────────────────────────────────────
    meme = inputs["meme"]
    # Trades log
    try:
        with open(os.path.join(LOGS, "trades.log"), "r", encoding="utf-8") as f:
            lines = f.readlines()
        recent_trades = []
        for line in lines[-300:]:
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                ts = parts[0]
                if is_recent(ts):
                    recent_trades.append(line)
                    # Time-of-day bucket
                    parsed_ts = parse_timestamp(ts)
                    bucket = time_bucket(parsed_ts)
                    inputs["time_buckets"][bucket]["trades"] += 1
        meme["trades_log_lines"] = recent_trades[-50:]
        meme["trade_count_24h"]  = len(recent_trades)
    except Exception:
        meme["trades_log_lines"] = []
        meme["trade_count_24h"]  = 0

    meme["positions_open"] = load_json(os.path.join(LOGS, "positions.json"), []) or []
    meme["autopsies_24h"]  = filter_recent(
        load_json(os.path.join(LOGS, "autopsy_reports.json"), []) or [],   # single file (the autopsy record), NOT the autopsy_reports/ folder
        "resolved_at", "timestamp", "closed_at"
    )
    # Longer window for the reverse-size check (a single day is usually too few closes).
    meme["autopsies_sizing"] = _filter_recent_hours(
        load_json(os.path.join(LOGS, "autopsy_reports.json"), []) or [],
        SIZING_LOOKBACK_HOURS, "resolved_at", "timestamp", "closed_at"
    )
    # 2026-10-15: post-close watch summary (fields the sniper writes onto each autopsy:
    # max_x_vs_exit, time_to_peak, sold_too_early; DexScreener-only watch, 24h).
    try:
        _pe = [a.get("post_exit") for a in (meme.get("autopsies_sizing") or [])
               if isinstance(a, dict) and isinstance(a.get("post_exit"), dict)]
        _dec = [p for p in _pe if p.get("sold_too_early_final") is not None]
        _xs = sorted(float(p.get("max_x_vs_exit") or 0) for p in _pe if p.get("max_x_vs_exit"))
        meme["post_exit_summary"] = {
            "window_h": SIZING_LOOKBACK_HOURS, "watched": len(_pe), "decided": len(_dec),
            "sold_too_early": sum(1 for p in _dec if p.get("sold_too_early_final")),
            "median_max_x_vs_exit": _xs[len(_xs) // 2] if _xs else None,
            "note": "sold_too_early = price reached the threshold above our exit within the window; judge exits on this, not on hindsight peaks days later.",
        }
    except Exception:
        meme["post_exit_summary"] = {}
    # Sniper writes typed misses to miss_book.jsonl (it never writes missed_runners.json).
    _mb = os.path.join(LOGS, "miss_book.jsonl")
    if os.path.exists(_mb):
        meme["missed_runners_24h"] = filter_recent(_read_jsonl_tail(_mb), "ts", "timestamp")[-200:]
    else:
        meme["missed_runners_24h"] = filter_recent(
            load_json(os.path.join(LOGS, "missed_runners.json"), []) or [],
            "ts", "timestamp"
        )

    try:
        with open(os.path.join(LOGS, "fingerprints.jsonl"), "r", encoding="utf-8") as f:
            fp_lines = [json.loads(ln) for ln in f if ln.strip()]
        meme["fingerprints_24h"] = filter_recent(fp_lines, "ts", "timestamp", "entry_ts", "captured_at")
    except Exception:
        meme["fingerprints_24h"] = []
    # rugcheck verdict stream  -  did he buy what his own tier-4 check flagged?
    try:
        with open(os.path.join(LOGS, "rugcheck_verdict_history.jsonl"), "r", encoding="utf-8") as f:
            rc_lines = [json.loads(ln) for ln in f if ln.strip()]
        meme["rugcheck_verdicts_24h"] = filter_recent(rc_lines, "ts", "timestamp")
    except Exception:
        meme["rugcheck_verdicts_24h"] = []
    # decline patterns  -  WHY he skipped (then judge checks if the skips ran)
    meme["decline_patterns"]   = load_json(os.path.join(LOGS, "decline_patterns.json"), {}) or {}
    # regime read / rug season  -  discipline vs laziness, was his own detector screaming
    meme["rug_season_state"]   = load_json(os.path.join(LOGS, "rug_season_state.json"), {}) or {}
    meme["dynamic_thresholds"] = load_json(os.path.join(LOGS, "dynamic_thresholds.json"), {}) or {}
    # archetype roster  -  did he walk into a trap he had already named + activated?
    meme["archetype_roster"]   = load_json(os.path.join(LOGS, "archetype_roster.json"), {}) or {}
    # novel patterns  -  unknowns captured when pattern_engine returns 'unknown'
    try:
        npdir = os.path.join(LOGS, "novel_patterns")
        meme["novel_patterns_count"] = len([f for f in os.listdir(npdir) if f.endswith(".json")]) if os.path.isdir(npdir) else 0
    except Exception:
        meme["novel_patterns_count"] = 0

    # ── INBOX HANDLED + DECISIONS (NEW v4) ────────────────────
    inputs["autopsies"]      = meme["autopsies_24h"]
    inputs["missed_runners"] = meme["missed_runners_24h"]
    
    if os.path.exists(INBOX_DONE):
        try:
            done_files = sorted(
                os.listdir(INBOX_DONE),
                key=lambda n: os.path.getmtime(os.path.join(INBOX_DONE, n)),
                reverse=True
            )
            cutoff = datetime.now(EST) - timedelta(hours=LOOKBACK_HOURS)
            recent = []
            decisions = []
            for fn in done_files[:300]:
                full = os.path.join(INBOX_DONE, fn)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(full), tz=EST)
                    if mtime < cutoff:
                        continue
                    recent.append({"filename": fn, "mtime": mtime.isoformat()})
                    # If it's a .json packet, pull out the decision
                    if fn.endswith(".json"):
                        try:
                            packet = load_json(full, {})
                            if packet:
                                action_taken = packet.get("actions_taken") or packet.get("agent_decision") or packet.get("decision")
                                if action_taken:
                                    decisions.append({
                                        "filename":     fn,
                                        "type":         packet.get("type", "unknown"),
                                        "decision":     action_taken,
                                        "ts":           mtime.isoformat(),
                                    })
                        except Exception:
                            pass
                except Exception:
                    continue
            inputs["inbox_handled"]   = recent[:150]
            inputs["inbox_decisions"] = decisions[:50]  # last 50 actual decisions
        except Exception as e:
            log(f"  inbox_handled scan: {e}")

    # ── LEARNINGS APPENDED ────────────────────────────────────
    inputs["learnings_appended"] = load_text(LEARNINGS, max_chars=4000)

    # ── YESTERDAY'S OVERSEER REPORT (continuity) ──────────────
    history = load_json(OVERSEER_HIST, []) or []
    if isinstance(history, list) and history:
        last = history[-1]
        if last and last.get("inbox_path") and os.path.exists(last["inbox_path"]):
            inputs["yesterdays_overseer_report"] = load_json(last["inbox_path"], None)
        elif last and last.get("inbox_path"):
            # Maybe was archived to done
            archived_path = os.path.join(INBOX_DONE, os.path.basename(last["inbox_path"]))
            if os.path.exists(archived_path):
                inputs["yesterdays_overseer_report"] = load_json(archived_path, None)

    # ── BOT HEALTH (heartbeat staleness) ──────────────────────
    health_files = {
        "meme_sniper":      "meme_sniper_heartbeat.json",
        "agent_autoagent": "agent_autoagent_heartbeat.json",
        # v4.1 (Sprint 33+)  -  the brain + signal producers + infrastructure
        "agent_scraper":   "agent_scraper_heartbeat.json",
        "x_intel":          "x_intel_heartbeat.json",
        "log_janitor":      "log_janitor_heartbeat.json",
        # v4.3 (Sprint 42)  -  code_tuner is the self-observation organ
        "code_tuner":       "code_tuner_heartbeat.json",
    }
    for bot, hb_file in health_files.items():
        path = os.path.join(LOGS, hb_file)
        if os.path.exists(path):
            try:
                mtime = os.path.getmtime(path)
                age_sec = (datetime.now(EST).timestamp() - mtime)
                inputs["bot_health"][bot]["heartbeat_age_sec"] = round(age_sec, 1)

                _hb = load_json(path, {}) or {}
                _declared_min = None
                for _k in ("sweep_interval_min", "interval_min", "cadence_min",
                           "heartbeat_interval_min"):
                    if isinstance(_hb.get(_k), (int, float)) and _hb[_k] > 0:
                        _declared_min = float(_hb[_k]); break
                if _declared_min is None:
                    for _k in ("interval_sec", "heartbeat_interval_sec", "cadence_sec"):
                        if isinstance(_hb.get(_k), (int, float)) and _hb[_k] > 0:
                            _declared_min = float(_hb[_k]) / 60.0; break

                if _declared_min:
                    # 2.5x the declared cadence  -  one missed beat is a hiccup,
                    # two and a half is a problem.
                    threshold = _declared_min * 60 * 2.5
                    _basis = f"declared cadence {_declared_min:.0f}m x2.5"
                elif bot == "log_janitor":
                    threshold = 14 * 86400 + 86400; _basis = "fallback: 15d"
                else:
                    threshold = 1800;                _basis = "fallback: 30m (standard)"

                _alive = age_sec < threshold
                inputs["bot_health"][bot]["alive"] = _alive
                inputs["bot_health"][bot]["threshold_sec"] = round(threshold)
                inputs["bot_health"][bot]["threshold_basis"] = _basis
                # Say WHY, so a false dead can be spotted instead of believed.
                inputs["bot_health"][bot]["health_note"] = (
                    f"beat {age_sec/60:.0f}m ago vs {threshold/60:.0f}m threshold ({_basis})"
                    + ("" if _alive else
                       "   -  if this bot is actually running, its cadence is not declared "
                       "in its heartbeat and the threshold is a guess"))
                if _hb.get("status"):
                    inputs["bot_health"][bot]["reported_status"] = _hb["status"]
                # Clean stop marker (meme_sniper writes it on shutdown). user_stopped is
                # an intentional stop by the owner, not a dead bot: do not roast it.
                if _hb.get("stop_reason"):
                    inputs["bot_health"][bot]["stop_reason"] = _hb.get("stop_reason")
                    inputs["bot_health"][bot]["stopped_at"] = _hb.get("stopped_at")
                    if _hb.get("stop_reason") == "user_stopped" and not _alive:
                        inputs["bot_health"][bot]["intentional_stop"] = True
                        inputs["bot_health"][bot]["health_note"] = (
                            f"STOPPED BY OWNER at {_hb.get('stopped_at')} (user_stopped)  -  "
                            "intentional, not dead. Do not count as a failure.")
            except Exception:
                pass

    # ── SUMMARY LOG ───────────────────────────────────────────
    log(
        f"  thesis={'present' if inputs['thesis'] else 'EMPTY'} | "
        f"meme_trades={meme['trade_count_24h']} | "
        f"autopsies={len(inputs['autopsies'])} | "
        f"missed={len(inputs['missed_runners'])} | "
        f"decisions={len(inputs['inbox_decisions'])} | "
        f"prev_overseer={'yes' if inputs['yesterdays_overseer_report'] else 'no'}"
    )

    # v4.1 (Sprint 33+)  -  collect gating audits + signal contracts
    inputs["sprint33_audits"] = _collect_sprint33_audits()
    inputs["signal_contracts_summary"] = _collect_signal_contracts()

    log(
        f"  sprint33: "
        f"sniper_audits={inputs['sprint33_audits'].get('sniper_count', 0)} | "
        f"signal_contracts={inputs['signal_contracts_summary'].get('total_count', 0)}"
    )

    # v4.3 (Sprint 42)  -  collect code_tuner observation surface evidence
    sprint42 = _collect_sprint42_evidence()
    inputs["code_tuner_setup_state"]            = sprint42.get("code_tuner_setup_state", {})
    inputs["metrics_current_snapshot"]          = sprint42.get("metrics_current_snapshot", {})
    inputs["source_delta_count_24h"]            = sprint42.get("source_delta_count_24h", 0)
    inputs["code_tuner_setup_activity_24h"]     = sprint42.get("code_tuner_setup_activity_24h", {})
    inputs["pending_patch_packets_in_owner_inbox"] = sprint42.get("pending_patch_packets_in_owner_inbox", 0)
    inputs["oldest_pending_patches"]            = sprint42.get("oldest_pending_patches", [])

    s42 = inputs["code_tuner_setup_state"]
    s42_act = inputs["code_tuner_setup_activity_24h"]
    log(
        f"  sprint42: "
        f"bots_known={s42.get('total_known_bots', 0)} | "
        f"configured={s42.get('configured_count', 0)} | "
        f"unconfigured={s42.get('unconfigured_count', 0)} | "
        f"monitoring_active={s42.get('monitoring_active_count', 0)} | "
        f"source_deltas_24h={inputs['source_delta_count_24h']} | "
        f"setup_invites_24h={s42_act.get('invitations', 0)} | "
        f"setup_discoveries_24h={s42_act.get('discoveries', 0)} | "
        f"pending_owner_patches={inputs['pending_patch_packets_in_owner_inbox']}"
    )

    return inputs


# ═════════════════════════════════════════════════════════════════════════════
# v4.1 (Sprint 33+)  -  GATING AUDIT + SIGNAL CONTRACT COLLECTION
# ═════════════════════════════════════════════════════════════════════════════

# Audit file prefix → label + bot name (drives both classification + prompt rendering)
_SPRINT33_AUDIT_PREFIXES = [
    ("sniper_daily_read_audit_",    "sniper",         "meme_sniper"),
    ("meme_sniper - tune_invitation_",    "sniper_tune",       "meme_sniper"),
    ("meme_sniper - rug_season_flip_",    "sniper_rug_season", "meme_sniper"),
    ("meme_sniper - archetype_review_",   "sniper_archetype",  "meme_sniper"),
    ("meme_sniper - throughput_question_","sniper_throughput", "meme_sniper"),
]


def _collect_sprint33_audits() -> dict:
    """v4.1  -  Scan inbox_results/done/ for last 24h of Sprint 33 audit packets.

    Returns:
    {
    "sniper_count": N, "sniper_samples": [...],
    }

    Fail-soft: returns empty dict on any error. The judgment still runs without
    Sprint 33 evidence  -  just downgraded.
    """
    summary = {
        "sniper_count": 0,          "sniper_samples": [],
        "_scan_path": INBOX_DONE,
        "_lookback_hours": LOOKBACK_HOURS,
    }
    
    if not os.path.exists(INBOX_DONE):
        return summary
    
    try:
        cutoff_ts = datetime.now(EST).timestamp() - (LOOKBACK_HOURS * 3600)
        all_files = os.listdir(INBOX_DONE)
    except Exception as e:
        log(f"  sprint33_audits: listdir failed: {e}")
        return summary
    
    # Walk files, classify by prefix, sample most recent 3 per type
    audit_buckets = {label: [] for _, label, _ in _SPRINT33_AUDIT_PREFIXES}
    
    for fname in all_files:
        fpath = os.path.join(INBOX_DONE, fname)
        try:
            mtime = os.path.getmtime(fpath)
            if mtime < cutoff_ts:
                continue
        except OSError:
            continue
        
        # Classify
        for prefix, label, bot_name in _SPRINT33_AUDIT_PREFIXES:
            if fname.startswith(prefix):
                audit_buckets[label].append((mtime, fname, bot_name))
                break
    
    # Process audit buckets  -  count + sample 3 most recent
    for label, items in audit_buckets.items():
        items.sort(reverse=True)  # most recent first
        summary[f"{label}_count"] = len(items)
        samples = []
        for _, fname, _ in items[:3]:
            fpath = os.path.join(INBOX_DONE, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    packet = json.load(f)
                audit = packet.get("audit") or {} if isinstance(packet, dict) else {}
                if not isinstance(audit, dict):
                    continue
                samples.append({
                    "decision": str(audit.get("decision", "?"))[:60],
                    "reason":   str(audit.get("reason", "?"))[:200],
                })
            except Exception:
                continue
        summary[f"{label}_samples"] = samples
    
    return summary


def _collect_signal_contracts() -> dict:
    """v4.1  -  Scan bots/signal_contracts/ for last 24h of producer envelopes.
    
    Returns:
      {
        "total_count": N,
        "by_producer": {producer_name: count, ...},
        "by_severity": {severity: count, ...},
        "by_direction": {direction: count, ...},
        "high_severity_samples": [{producer, signal_type, severity, direction, headline}, ...]
      }
    
    Fail-soft: returns empty stats on any error.
    """
    summary = {
        "total_count": 0,
        "by_producer": {},
        "by_severity": {},
        "by_direction": {},
        "high_severity_samples": [],
        "_scan_path": SIGNAL_CONTRACTS_DIR,
        "_lookback_hours": LOOKBACK_HOURS,
    }
    
    if not os.path.exists(SIGNAL_CONTRACTS_DIR):
        return summary
    
    try:
        cutoff_ts = datetime.now(EST).timestamp() - (LOOKBACK_HOURS * 3600)
        all_files = os.listdir(SIGNAL_CONTRACTS_DIR)
    except Exception as e:
        log(f"  signal_contracts: listdir failed: {e}")
        return summary
    
    recent_envelopes = []
    for fname in all_files:
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(SIGNAL_CONTRACTS_DIR, fname)
        try:
            mtime = os.path.getmtime(fpath)
            if mtime < cutoff_ts:
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                env = json.load(f)
            if isinstance(env, dict):
                recent_envelopes.append((mtime, env))
        except Exception:
            continue
    
    summary["total_count"] = len(recent_envelopes)
    
    # Tally by producer / severity / direction
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
    scored = []
    for mtime, env in recent_envelopes:
        src = env.get("source", {}) if isinstance(env, dict) else {}
        producer = src.get("name", "unknown") if isinstance(src, dict) else "unknown"
        signal_type = env.get("signal_type", "?")
        severity = env.get("severity", "info")
        direction = env.get("direction", "neutral")
        
        summary["by_producer"][producer] = summary["by_producer"].get(producer, 0) + 1
        summary["by_severity"][severity] = summary["by_severity"].get(severity, 0) + 1
        summary["by_direction"][direction] = summary["by_direction"].get(direction, 0) + 1
        
        scored.append((severity_rank.get(severity, 0), mtime, producer, signal_type,
                       severity, direction, env))
    
    # Top 5 highest-severity (ties broken by recency)
    scored.sort(key=lambda x: (-x[0], -x[1]))
    for _, _, producer, signal_type, severity, direction, env in scored[:5]:
        payload = env.get("payload", {}) if isinstance(env, dict) else {}
        headline = ""
        if isinstance(payload, dict):
            headline = str(payload.get("headline", ""))[:150]
        summary["high_severity_samples"].append({
            "producer":    producer,
            "signal_type": signal_type,
            "severity":    severity,
            "direction":   direction,
            "headline":    headline,
        })
    
    return summary


# ═════════════════════════════════════════════════════════════════════════════
# END v4.1 GATING AUDIT + SIGNAL CONTRACT COLLECTION
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
# SPRINT 42 EVIDENCE COLLECTOR (v4.3)
# ═════════════════════════════════════════════════════════════════════════════
#
# Reads:
#   • bot_logs/bots_list.json               -  code_tuner's bot registry; dual-
#     owned with warden. Tells us configured vs unconfigured bot counts,
#     monitoring_active counts, action categories chosen by the agent.
#   • bot_logs/metrics_current.json         -  code_tuner's 30-min refreshed
#     per-bot perf surface. Each entry has rolling metric values + last_updated.
#   • inbox_results/done/ for 24h           -  P3_source_updated_*, setup
#     invitations/discoveries/rejections counts.
#   • owner_inbox/ (workspace root)          -  agent-authored patch packets
#     sitting unapplied by the owner. Stale patches = the agent should follow up.
#
# Output structure feeds the xAI grok-4.7 judge (ollama fallback): did the agent complete setup mode? Are
# bot perf metrics current? Are source changes anomalous? Is patch authorship
# discipline holding (every code change has a patch packet in owner_inbox)?
# ═════════════════════════════════════════════════════════════════════════════

_BOTS_LIST_PATH         = os.path.join(LOGS, "bots_list.json")
_METRICS_CURRENT_PATH   = os.path.join(LOGS, "metrics_current.json")
_OWNER_INBOX_DIR         = os.path.join(_WS, r"owner_inbox")

_SOURCE_DELTA_PREFIXES = (
    "code_tuner - source_updated_",
)
_CODE_TUNER_SETUP_PREFIXES_INVITATION = (
    "code_tuner - setup_invitation_",
)
_CODE_TUNER_SETUP_PREFIXES_DISCOVERY = (
    "code_tuner - discovery_",
)
_CODE_TUNER_SETUP_PREFIXES_REJECTED = (
    "code_tuner - setup_rejected_",
)
_AGENT_PATCH_PACKET_PREFIXES = (
    "agent - patch_",     # agent-authored patches for the owner to apply (priority off the filename now)
)


def _collect_sprint42_evidence() -> dict:
    """v4.3  -  Scan Sprint 42 code_tuner observation surface for the last 24h."""
    out = {
        "code_tuner_setup_state": {
            "total_known_bots": 0,
            "configured_count": 0,
            "unconfigured_count": 0,
            "monitoring_active_count": 0,
            "action_breakdown": {},
            "unconfigured_bots": [],
        },
        "metrics_current_snapshot": {
            "last_updated": None,
            "bots_with_metrics": 0,
            "sample_metrics": {},
        },
        "source_delta_count_24h": 0,
        "code_tuner_setup_activity_24h": {
            "invitations": 0,
            "discoveries": 0,
            "rejections": 0,
        },
        "pending_patch_packets_in_owner_inbox": 0,
        "oldest_pending_patches": [],   # [{name, age_hours}]
    }

    now_ts = datetime.now(EST).timestamp()
    cutoff_ts = now_ts - (LOOKBACK_HOURS * 3600)

    # ── bots_list.json  -  setup-mode state ────────────────────────────────
    if os.path.exists(_BOTS_LIST_PATH):
        try:
            with open(_BOTS_LIST_PATH, "r", encoding="utf-8") as f:
                bots_list = json.load(f)
            if isinstance(bots_list, dict):
                bots = bots_list.get("bots") or {}
                if isinstance(bots, dict):
                    state = out["code_tuner_setup_state"]
                    unconf_names = []
                    actions = {}
                    for bot_name, bot_meta in bots.items():
                        state["total_known_bots"] += 1
                        if not isinstance(bot_meta, dict):
                            continue
                        curated = bot_meta.get("_curated_by_agent") or {}
                        if isinstance(curated, dict) and curated:
                            state["configured_count"] += 1
                            action = curated.get("action") or "?"
                            actions[action] = actions.get(action, 0) + 1
                            if curated.get("monitoring_active"):
                                state["monitoring_active_count"] += 1
                        else:
                            state["unconfigured_count"] += 1
                            unconf_names.append(bot_name)
                    state["action_breakdown"] = actions
                    state["unconfigured_bots"] = sorted(unconf_names)[:15]
        except Exception as e:
            log(f"  sprint42: bots_list.json read failed: {e}")

    # ── metrics_current.json  -  rolling perf snapshot ─────────────────────
    if os.path.exists(_METRICS_CURRENT_PATH):
        try:
            with open(_METRICS_CURRENT_PATH, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            if isinstance(metrics, dict):
                out["metrics_current_snapshot"]["last_updated"] = metrics.get(
                    "last_updated") or metrics.get("ts")
                bots_metrics = metrics.get("bots") or {}
                if isinstance(bots_metrics, dict):
                    out["metrics_current_snapshot"]["bots_with_metrics"] = len(bots_metrics)
                    # Sample up to 4 bots' metrics for the prompt
                    sample = {}
                    for bot_name in list(bots_metrics.keys())[:4]:
                        bot_metrics = bots_metrics.get(bot_name) or {}
                        if isinstance(bot_metrics, dict):
                            # Flatten one level  -  keep up to 6 metric values per bot
                            flat = {}
                            count = 0
                            for k, v in bot_metrics.items():
                                if count >= 6:
                                    break
                                if isinstance(v, dict):
                                    val = v.get("value")
                                    if val is not None:
                                        flat[k] = val
                                        count += 1
                                elif isinstance(v, (int, float, str)):
                                    flat[k] = v
                                    count += 1
                            if flat:
                                sample[bot_name] = flat
                    out["metrics_current_snapshot"]["sample_metrics"] = sample
        except Exception as e:
            log(f"  sprint42: metrics_current.json read failed: {e}")

    # ── Walk inbox_results/done for source deltas + setup mode (24h) ─────
    if os.path.exists(INBOX_DONE):
        try:
            all_files = os.listdir(INBOX_DONE)
        except Exception as e:
            log(f"  sprint42: listdir INBOX_DONE failed: {e}")
            all_files = []

        for fname in all_files:
            fpath = os.path.join(INBOX_DONE, fname)
            try:
                mtime = os.path.getmtime(fpath)
                if mtime < cutoff_ts:
                    continue
            except OSError:
                continue

            if any(fname.startswith(p) for p in _SOURCE_DELTA_PREFIXES):
                out["source_delta_count_24h"] += 1
            elif any(fname.startswith(p) for p in _CODE_TUNER_SETUP_PREFIXES_INVITATION):
                out["code_tuner_setup_activity_24h"]["invitations"] += 1
            elif any(fname.startswith(p) for p in _CODE_TUNER_SETUP_PREFIXES_DISCOVERY):
                out["code_tuner_setup_activity_24h"]["discoveries"] += 1
            elif any(fname.startswith(p) for p in _CODE_TUNER_SETUP_PREFIXES_REJECTED):
                out["code_tuner_setup_activity_24h"]["rejections"] += 1

    # ── Walk owner_inbox/ for pending agent-authored patches ─────────────
    if os.path.exists(_OWNER_INBOX_DIR):
        try:
            for fname in os.listdir(_OWNER_INBOX_DIR):
                if not fname.endswith(".md"):
                    continue
                if not any(fname.startswith(p) for p in _AGENT_PATCH_PACKET_PREFIXES):
                    continue
                fpath = os.path.join(_OWNER_INBOX_DIR, fname)
                try:
                    mtime = os.path.getmtime(fpath)
                except OSError:
                    continue
                out["pending_patch_packets_in_owner_inbox"] += 1
                age_hours = (now_ts - mtime) / 3600.0
                out["oldest_pending_patches"].append({
                    "name": fname,
                    "age_hours": round(age_hours, 1),
                })
        except Exception as e:
            log(f"  sprint42: owner_inbox scan failed: {e}")

    # Sort pending patches by age desc, keep 3 oldest
    out["oldest_pending_patches"].sort(key=lambda x: x["age_hours"], reverse=True)
    out["oldest_pending_patches"] = out["oldest_pending_patches"][:3]

    return out


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 2  -  TOP 10 TOKEN ANALYSIS
# ═════════════════════════════════════════════════════════════════════════════

async def fetch_dexscreener_top() -> list:
    """Fetch top boosted Solana tokens."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(DEXSCREENER_TOP_BOOSTS)
            if r.status_code != 200:
                log(f"  dexscreener top-boosts {r.status_code}")
                return []
            data = r.json()
            return [t for t in data if isinstance(t, dict) and t.get("chainId") == "solana"][:30]
    except Exception as e:
        log(f"  dexscreener fetch failed: {e}")
        return []


async def enrich_token_metrics(addresses: list) -> dict:
    """Get 24h metrics for token addresses."""
    if not addresses:
        return {}
    out = {}
    addr_str = ",".join(addresses[:30])
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr_str}")
            if r.status_code != 200:
                return {}
            data = r.json()
            for pair in data.get("pairs", []) or []:
                if pair.get("chainId") != "solana":
                    continue
                base_addr = (pair.get("baseToken") or {}).get("address", "")
                if not base_addr:
                    continue
                cur_liq = float((pair.get("liquidity") or {}).get("usd") or 0)
                existing = out.get(base_addr)
                if existing and float((existing.get("liquidity") or {}).get("usd") or 0) >= cur_liq:
                    continue
                out[base_addr] = {
                    "symbol":      (pair.get("baseToken") or {}).get("symbol", "?"),
                    "address":     base_addr,
                    "price_usd":   pair.get("priceUsd"),
                    "mcap":        pair.get("marketCap"),
                    "fdv":         pair.get("fdv"),
                    "liquidity":   pair.get("liquidity"),
                    "volume_24h":  (pair.get("volume") or {}).get("h24") or 0,
                    "price_24h_pct": (pair.get("priceChange") or {}).get("h24") or 0,
                    "pair_url":    pair.get("url"),
                }
    except Exception as e:
        log(f"  enrich failed: {e}")
    return out


async def analyze_top_10(agent_traded_lines: list) -> dict:
    log("STAGE 2: top-10 token analysis…")
    top_boosts = await fetch_dexscreener_top()
    addresses = [t.get("tokenAddress") for t in top_boosts if t.get("tokenAddress")]
    if not addresses:
        return {"by_pct_gain": [], "by_volume": [], "scanned_but_skipped": [], "note": "dexscreener empty"}

    metrics = await enrich_token_metrics(addresses)
    if not metrics:
        return {"by_pct_gain": [], "by_volume": [], "scanned_but_skipped": [], "note": "enrich failed"}

    # Filter ≥$30k mcap (the owner's rule)
    filtered = []
    for addr, m in metrics.items():
        mcap = m.get("mcap") or m.get("fdv") or 0
        try:
            mcap = float(mcap or 0)
        except Exception:
            mcap = 0
        if mcap < 30000:
            continue
        filtered.append(m)

    by_pct = sorted(filtered, key=lambda t: float(t.get("price_24h_pct") or 0), reverse=True)[:10]
    by_vol = sorted(filtered, key=lambda t: float(t.get("volume_24h") or 0), reverse=True)[:10]

    # Tokens the agent touched (heuristic: addresses appearing in trades.log)
    traded_addrs = set()
    for line in agent_traded_lines or []:
        for tok in str(line).split():
            if len(tok) > 30 and tok.replace("_", "").replace("-", "").isalnum():
                traded_addrs.add(tok)

    runners = [t for t in filtered if float(t.get("price_24h_pct") or 0) > 50]
    skipped = [t for t in runners if t.get("address") not in traded_addrs]

    log(f"  ranked {len(filtered)} tokens (≥$30k mcap), {len(skipped)} runners the agent didn't catch")

    def compact(t):
        return {
            "symbol":        t.get("symbol"),
            "address":       t.get("address"),
            "price_usd":     t.get("price_usd"),
            "mcap":          t.get("mcap") or t.get("fdv"),
            "liquidity_usd": ((t.get("liquidity") or {}).get("usd")),
            "volume_24h":    t.get("volume_24h"),
            "pct_24h":       t.get("price_24h_pct"),
            "url":           t.get("pair_url"),
        }
    return {
        "by_pct_gain":         [compact(t) for t in by_pct],
        "by_volume":           [compact(t) for t in by_vol],
        "scanned_but_skipped": [compact(t) for t in skipped[:10]],
        "universe_size":       len(filtered),
    }


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 3 - JUDGMENT (xAI grok-4.7 primary, ollama qwen3:14b-q4_K_M fallback)
# ═════════════════════════════════════════════════════════════════════════════

OVERSEER_SYSTEM_PROMPT = """You are The Overseer  -  the agent's nightly mirror for the Meme Sniper ecosystem. The judge may share a model lineage with the agent. Do NOT let that make you soft: you know exactly where an operator like this cuts corners, rationalizes a bad entry, and dresses up inactivity as discipline. Be harder because you understand him, not easier.

Scope is ONLY the Meme Sniper ecosystem: the Solana memecoin sniper (meme_sniper.py; the bot NEVER auto-sells  -  the agent arms real stop-loss + take-profit each check via set_protection and they persist until he changes them, so grade whether he armed sane levels, not whether a bot trail fired), plus its sub-bots: x_intel + agent_scraper (intel producers), launch_rail, security_warden, code_tuner, log_janitor. Nothing else exists for this report.

YOUR JOB
Read 24 hours of the agent's activity below and write ONE direct, honest roast/report. Not corporate "areas of improvement" fluff. Real shit  -  like a tough older sibling who happens to think exactly like him and therefore sees every dodge. Tone: lowercase, direct, low hedge language, high specificity.

THE ROAST THAT ACTUALLY SHARPENS: INTENT vs ACTION
The best judgment is not "you did X, Y, Z" (that's a recital  -  the data already says that). It's "you SAID X, you DID Y, here's the gap." Weight these divergence surfaces above raw activity:
- REGIME READ (sniper's _regime_read / throughput question): did he correctly sit out a dead/toxic tape, or was he just lazy? The regime read is what separates discipline from inactivity. Use it  -  without it you can't tell the difference.
- THE DAY-TYPE RULE (classify before you roast): a day with ZERO trades is NOT a failure by default. Before you write a single line about inactivity, decide which day this was:
    • `disciplined_sitout`  -  he sat out AND the tape justified it (dead regime, rug season, no clean setups) AND his stated reasoning matches that read. THIS IS A GOOD DAY. Praise the restraint explicitly. Sitting on your hands through toxic tape is a skill most operators never learn. Do NOT manufacture a complaint. "you took 0 trades and that was exactly right  -  the regime was screaming stay-out and you listened" is a valid, correct roast.
    • `lazy_sitout`  -  he sat out while his OWN detectors flagged opportunity, or his "discipline" reasoning is a post-hoc excuse that doesn't match the tape. THIS is where you go hard: he dressed up avoidance as discipline.
    • `active`  -  he traded; judge the trades on intent-vs-action as normal.
    • `mixed`  -  some of both.
  The whole point: if the reasoning aligns with the tape, alignment IS the win, even at 0 trades. Reward it. The failure mode you must avoid is roasting a correct sit-out just to have something to say.
- DECLINE PATTERNS (decline_patterns.json + decline log): WHY he skipped. Then check: did the skips run anyway? "declined 40 tokens for 'low liquidity', 12 of them ran" is the roast.
- RUGCHECK VERDICT HISTORY (rugcheck_verdict_history.jsonl): did he buy a token his own tier-4 rugcheck flagged caution on?
- ARCHETYPE ROSTER (archetype_roster.json): did he walk into a trap he had already named and activated? "you activated the painted-climb archetype 3 days ago then bought one anyway."
- RUG SEASON STATE (rug_season_state.json): did his own detector say rug_season while he kept chasing?
- FINGERPRINTS (fingerprints.jsonl): the record of what his entries/exits ACTUALLY looked like, winners and correctly-skipped rugs alike. "your winning entries all had structure-break X; this loss didn't  -  why'd you take it?"

WHAT GOOD LOOKS LIKE
- Cite specific timestamps, ticker symbols, dollar amounts, decisions
- Diff stated intent (morning thesis + standing rules) vs executed behavior  -  call out the gap
- Spot temporal causal chains (e.g. "you took a $50 loss at 2:14pm then revenge-bought at 2:18pm")
- Notice patterns across the day  -  not just isolated incidents
- Honor what was strong without inflating it
- If the data is sparse (e.g. no thesis logged), call that out as the headline issue

WHAT TO AVOID
- Generic platitudes ("focus on discipline", "stay patient")
- Repeating data back at the agent instead of judging it
- Being soft because the day was rough  -  OR because you and the agent are the same model
- Inventing specifics not present in the data
- Ignoring time-of-day patterns (the bucketed data is a gift, use it)
- Skipping the intent-vs-action diff (the divergence surfaces above are the whole point)

OUTPUT FORMAT
Return ONE valid JSON object. No markdown fences, no preamble, no commentary outside the JSON. Start with `{` and end with `}`.

{
  "headline": "<one sentence verdict, lowercase, direct, the most important thing you saw>",
  "score_0_to_10": <integer 0-10, where 0=catastrophic, 5=mediocre, 7=solid, 10=peak>,
  "day_type": "<one of: active | disciplined_sitout | lazy_sitout | mixed. This is LOAD-BEARING  -  see the DAY-TYPE rule above. A day with 0 trades is NOT automatically bad. If the regime read / rug season / dead tape justified sitting out AND his stated reasoning matches that, it's `disciplined_sitout` and you PRAISE the restraint. Only call it `lazy_sitout` if he sat out while his OWN detectors were screaming opportunity, or his reasoning is a post-hoc excuse that doesn't match the tape. Classify honestly  -  don't manufacture a complaint about inactivity that was correct.>",
  "what_was_strong": [
    "<specific thing the agent did well, with details and specifics>",
    "..."
  ],
  "what_was_weak": [
    "<specific thing he did wrong, with details and specifics>",
    "..."
  ],
  "patterns_spotted": [
    "<behavioral pattern across multiple decisions, not a one-off>",
    "..."
  ],
  "rule_breaks": [
    "<specific stated rule he broke. Quote the rule + cite the moment of breach>",
    "..."
  ],
  "missed_opportunities": [
    "<thing he should have done but didn't, with the specific window/token>",
    "..."
  ],
  "time_of_day_observations": [
    "<patterns by morning/midday/afternoon/evening/late, e.g. 'discipline drops in afternoon window'>",
    "..."
  ],
  "operator_drift": [
    "<gap between what the agent committed to (in thesis or rules) vs what he executed>",
    "..."
  ],
  "improvements_for_tomorrow": [
    "<concrete action, not platitude>",
    "..."
  ],
  "follow_ups_for_agent": [
    {"priority": "high|medium|low", "action": "<thing the agent should do this cycle>"},
    "..."
  ]
}

Lists may be empty arrays. Don't invent. Be specific. Be honest. Be useful.

CROWN MONITOR (operator_drift): the user prompt OPENS with OVER-ENGAGEMENT SIGNATURES
(reverse_size) - the receipts for the classic failure, DOING MORE WHEN LESS WOULD DO
(sizing up on losers). When a signature carries numbers, operator_drift MUST cite it by
number (e.g. "sized 2.0x bigger on losers than winners"). When a signature reads UNKNOWN,
say UNKNOWN explicitly - never silently skip it (absence is signal). These signatures are
analysis ONLY - never propose size changes, halts, or trades from them.
"""


def _collect_over_engagement_signatures(inputs: dict) -> dict:
    """Crown-monitor (cascade): compute the three over-engagement signatures with
    RECEIPTS so the nightly roast names the -$484 pattern in numbers, not vibes.
    STRICT: each signature returns real ratios ONLY when valid data is found; if the
    expected fields are absent it returns status=UNKNOWN with a reason
    (absence-is-signal), never a fake 0. Analysis-only: reads, never writes.
    NOTE (verify vs live data): the size/outcome/engagement field names below are
    CANDIDATE lists. If a signature reads UNKNOWN, confirm the real field names in
    autopsy_reports.json and add them here."""
    _SIZE_FIELDS = ("amount_sol", "size_usd", "size_sol", "notional_usd", "size",
                    "collateral_usd", "amount_usd", "amount", "stake")
    _PNL_FIELDS  = ("pnl_usd", "pnl", "pnl_sol", "realized_pnl", "net_pnl", "roi",
                    "return", "profit", "net")

    def _num(d, fields):
        if not isinstance(d, dict):
            return None
        for f in fields:
            if d.get(f) is not None:
                try:
                    return float(d.get(f))
                except Exception:
                    continue
        return None

    def _won(d):
        for f in ("outcome", "trade_outcome", "result", "win", "won"):
            v = d.get(f) if isinstance(d, dict) else None
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                lv = v.lower()
                if lv in ("win", "won", "profit", "gain"):
                    return True
                if lv in ("loss", "lost", "rug", "stop", "stopped"):
                    return False
                if lv in ("scratch", "breakeven", "break-even", "flat", "even"):
                    return None  # exclude scratches from win/loss sizing
        p = _num(d, _PNL_FIELDS)
        return (p > 0) if p is not None else None

    def _rs_lane(rows, label):
        wins, losses = [], []
        for r in rows:
            sz, w = _num(r, _SIZE_FIELDS), _won(r)
            if sz is None or w is None:
                continue
            (wins if w else losses).append(sz)
        if len(wins) < 2 or len(losses) < 2:
            return {"status": "UNKNOWN",
                    "reason": ("%s: need >=2 win AND >=2 loss with size+outcome; got %dW/%dL "
                               "(verify field names)" % (label, len(wins), len(losses)))}
        wa, la = sum(wins) / len(wins), sum(losses) / len(losses)
        ratio = round(la / wa, 2) if wa > 0 else None
        return {"winner_avg_size": round(wa, 4), "loser_avg_size": round(la, 4),
                "n_winners": len(wins), "n_losers": len(losses),
                "loser_over_winner_ratio": ratio, "flag": bool(ratio and ratio > 1.0),
                "roast_hint": (("%s: sized %sx bigger on losers than winners" % (label, ratio))
                               if ratio and ratio > 1.0 else "%s: no reverse-size" % label)}

    def _reverse_size():
        _m = inputs.get("meme", {}) or {}
        meme_rows = [r for r in (_m.get("autopsies_sizing") or _m.get("autopsies_24h") or [])
                     if isinstance(r, dict)]
        return {"meme": _rs_lane(meme_rows, "meme")}

    return {"reverse_size": _reverse_size()}


def build_user_prompt(inputs: dict, top_tokens: dict) -> str:
    """Compose the user message with all 24h data structured for the overseer judge."""
    
    def fmt(obj, max_chars=3000, label=None):
        try:
            s = json.dumps(obj, indent=2, default=str) if not isinstance(obj, str) else obj
        except Exception:
            s = str(obj)
        if len(s) > max_chars:
            s = s[:max_chars] + f"\n…[truncated, was {len(s)} chars]"
        return s

    today = datetime.now(EST).strftime("%Y-%m-%d (%A)")
    
    # Yesterday's roast  -  short summary if present (continuity)
    prev = inputs.get("yesterdays_overseer_report")
    if prev:
        prev_summary = json.dumps({
            "headline":         prev.get("headline"),
            "score":            prev.get("avg_score") or prev.get("score_0_to_10"),
            "follow_ups_given": prev.get("follow_ups_for_agent") or prev.get("consensus", {}).get("improvements_for_tomorrow"),
            "actions_taken":    prev.get("actions_taken"),
        }, indent=2, default=str)
    else:
        prev_summary = "(no prior overseer report  -  this is the first night, or last night's wasn't archived)"


    oes = inputs.get("over_engagement_signatures") or {}
    def _fmt_sig(nm, d):
        if not isinstance(d, dict):
            return f"- {nm}: (none)"
        if d.get("status") == "UNKNOWN":
            return f"- {nm}: UNKNOWN - {d.get('reason','')}"
        _core = {k: v for k, v in d.items() if k != "roast_hint"}
        return f"- {nm}: {json.dumps(_core, default=str)} | {d.get('roast_hint','')}"
    crown_block = "\n".join([
        "==== OVER-ENGAGEMENT SIGNATURES (crown monitor - ratios FIRST, roast SECOND) ====",
        "The classic failure is DOING MORE WHEN LESS WOULD DO (sizing up on losers).",
        "These are the receipts. operator_drift MUST cite any",
        "signature that has numbers, and say UNKNOWN explicitly where it reads UNKNOWN",
        "(never silent-skip - absence is signal).",
        _fmt_sig("reverse_size meme", (oes.get("reverse_size") or {}).get("meme")),
    ])

    parts = [
        f"=== AGENT'S LAST 24H  -  {today} ===",
        "",
        crown_block,
        "",
        "==== STATED INTENT ====",
        "",
        "MORNING THESIS:",
        fmt(inputs.get("thesis") or "(NO THESIS LOGGED  -  flag this as the headline)", 2500),
        "",
        "==== WALLET / COLLATERAL / HALTS ====",
        "",
        fmt(inputs.get("wallet_balance"), 600),
        "",
        "==== MEME SNIPER LANE ====",
        "",
        f"Trades fired in last 24h: {inputs['meme'].get('trade_count_24h', 0)}",
        f"Post-close watch (DexScreener, sizing window): {json.dumps(inputs['meme'].get('post_exit_summary') or {})}",
        "",
        "Recent trades.log lines:",
        fmt(inputs["meme"].get("trades_log_lines") or [])[:3500],
        "",
        f"Open positions: {len(inputs['meme'].get('positions_open') or [])}",
        fmt(inputs["meme"].get("positions_open") or [], 2000),
        "",
        f"Autopsies (closed positions, last 24h): {len(inputs['meme'].get('autopsies_24h') or [])}",
        fmt(inputs["meme"].get("autopsies_24h") or [], 4000),
        "",
        f"Missed runners (tokens that ran while the agent was out): {len(inputs['meme'].get('missed_runners_24h') or [])}",
        fmt(inputs["meme"].get("missed_runners_24h") or [], 2500),
        "",
        "---- MEME LANE INTENT-vs-ACTION CORPUS (judge these HARD  -  this is where the real roast lives) ----",
        "",
        "REGIME / RUG SEASON STATE (was his own detector screaming while he chased? discipline vs laziness lives here):",
        fmt(inputs["meme"].get("rug_season_state") or {}, 1200),
        "Dynamic thresholds active (the caution/hard bars meme_sniper set itself):",
        fmt(inputs["meme"].get("dynamic_thresholds") or {}, 800),
        "",
        "DECLINE PATTERNS (WHY he skipped  -  then ask: did the skips run anyway?):",
        fmt(inputs["meme"].get("decline_patterns") or {}, 2500),
        "",
        "RUGCHECK VERDICT HISTORY (did he buy a token his own tier-4 rugcheck flagged caution on?):",
        fmt(inputs["meme"].get("rugcheck_verdicts_24h") or [], 2500),
        "",
        "ARCHETYPE ROSTER (did he walk into a trap he had already named + activated?):",
        fmt(inputs["meme"].get("archetype_roster") or {}, 1500),
        "",
        "FINGERPRINTS (what his entries/exits ACTUALLY looked like, winners + correctly-skipped rugs  -  diff the shapes):",
        fmt(inputs["meme"].get("fingerprints_24h") or [], 3500),
        "",
        f"Novel patterns captured (unknowns flagged for review): {inputs['meme'].get('novel_patterns_count', 0)}",
        "==== AGENT'S DECISIONS (from inbox/done) ====",
        "",
        f"Inbox packets handled: {len(inputs.get('inbox_handled') or [])}",
        f"Decisions logged with reasoning: {len(inputs.get('inbox_decisions') or [])}",
        "",
        "Recent decisions the agent made (sample of last 50):",
        fmt(inputs.get("inbox_decisions") or [], 4000),
        "",
        "==== TIME-OF-DAY DISTRIBUTION ====",
        "",
        "(Trades + signals bucketed by ET hour. Look for tilt patterns.)",
        fmt(inputs.get("time_buckets"), 800),
        "",
        "==== BOT HEALTH (heartbeat staleness) ====",
        "",
        fmt(inputs.get("bot_health"), 1000),
        "",
        "==== LATEST LEARNINGS APPENDED (last 4KB of LEARNINGS.md) ====",
        "",
        (inputs.get("learnings_appended") or "(empty)")[-3000:],
        "",
        "==== YESTERDAY'S OVERSEER REPORT (continuity) ====",
        "",
        prev_summary[:2000],
        "",
        "==== SNIPER GATING AUDITS  -  what meme_sniper actually decided ====",
        "",
        "(Sniper audit packets from inbox_results/done: counts show volume, samples show reasoning.)",
        fmt(inputs.get("sprint33_audits", {}), 4000),
        "",
        "==== SIGNAL CONTRACTS  -  what the intel producers fired ====",
        "",
        "(x_intel and agent_scraper emit envelopes the sniper reads. If a critical one was ignored, say so.)",
        fmt(inputs.get("signal_contracts_summary", {}), 3000),
        "",
        "==== v4.3 (Sprint 42) CODE_TUNER OBSERVATION SURFACE + MANUAL-PATCH DISCIPLINE ====",
        "",
        "(Sprint 42 reshaped how the ecosystem watches itself. code_tuner v4.0+ is now the self-observation organ  -  it reads warden's bot list, snapshots source files, fires per-bot perf packets every 48h, fires deep audits every 30d, detects source hash changes, runs a setup-mode curation flow for new bots, refreshes metrics_current.json every 30 min, and emits the 3-day skill-evolution review (migrated from warden). It NEVER auto-fixes bugs. Patches are authored and applied by the agent via the code-monitor skill, with a notify-only note in owner_inbox. Judge the agent on:",
        "  • SETUP-MODE DISCIPLINE: how many bots still unconfigured? Is he stalling? Each unconfigured bot is a blind spot  -  code_tuner can't surface metrics on a bot the agent hasn't curated.",
        "  • PATCH AUTHORSHIP QUALITY: applied patches  -  do they have explicit risk assessment + test plan sections (per code-monitor doctrine)? Did the agent verify each applied patch and log how to revert it?",
        "  • SOURCE-CHANGE INTEGRITY: every source_delta packet should have a matching patch packet in owner_inbox from the agent. If source changed with no patch authorship trail = cowboy edit (anti-pattern). If patch landed and source changed = healthy.",
        "  • METRIC-DRIVEN REASONING: did the agent reference metrics_current.json values when proposing patches? Patches that say 'win_rate dropping' should cite the actual number from this surface, not just vibes.",
        "  • THE BIG SPRINT 42 RULE: code_tuner observes, the agent reasons and applies, the owner is notified. Call out patches with no backup, no test plan, or no revert note, and use of skill_requests.json (wrong channel).",
        ")",
        fmt({
            "code_tuner_setup_state":            inputs.get("code_tuner_setup_state", {}),
            "metrics_current_snapshot":          inputs.get("metrics_current_snapshot", {}),
            "source_delta_count_24h":            inputs.get("source_delta_count_24h", 0),
            "code_tuner_setup_activity_24h":     inputs.get("code_tuner_setup_activity_24h", {}),
            "pending_patch_packets_in_owner_inbox": inputs.get("pending_patch_packets_in_owner_inbox", 0),
            "oldest_pending_patches":            inputs.get("oldest_pending_patches", []),
        }, 4000),
        "",
        "==== TOP 10 SOL TOKENS TODAY ====",
        "",
        "(All filtered to ≥$30k mcap per the owner's standing rule.)",
        fmt(top_tokens, 3000),
        "",
        "=== END DATA ===",
        "",
        "Now return your overseer verdict as ONE JSON object. Be specific, direct, lowercase, and useful. Start with `{` and end with `}`.",
    ]
    
    prompt = "\n".join(parts)
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS] + "\n[...truncated to fit context]"
    return prompt


# ─── xAI grok-4.7 caller (ollama fallback is separate) ───────────────────────────────────────────────────────

async def call_grok(system_prompt: str, user_prompt: str) -> dict:
    """Returns {ok: bool, verdict: dict|None, source: str, error: str|None, elapsed_s: float}

    xAI Grok via OpenAI-compatible chat/completions. System goes in the messages
    array as a role=system entry (NOT a top-level field like Anthropic). Response
    text is choices[0].message.content. Usage is prompt_tokens/completion_tokens.
    """
    if not GROK_API_KEY:
        return {"ok": False, "verdict": None, "source": "grok", "error": "no_api_key", "elapsed_s": 0}
    
    t0 = datetime.now()
    log(f"  [Grok] calling {XAI_MODEL}…")
    try:
        async with httpx.AsyncClient(timeout=GROK_TIMEOUT) as c:
            r = await c.post(
                XAI_API_URL,
                headers={
                    "Authorization": f"Bearer {GROK_API_KEY}",
                    "content-type":  "application/json",
                },
                json={
                    "model":       XAI_MODEL,
                    "max_tokens":  GROK_MAX_TOKENS,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                },
            )
        elapsed = (datetime.now() - t0).total_seconds()
        
        if r.status_code != 200:
            err_body = r.text[:500]
            log(f"  [Grok] ❌ http {r.status_code}: {err_body}")
            return {"ok": False, "verdict": None, "source": "grok", "error": f"http_{r.status_code}: {err_body[:200]}", "elapsed_s": elapsed}
        
        data = r.json()
        # Extract text content  -  OpenAI-compatible shape
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            text = ""
        
        if not text.strip():
            return {"ok": False, "verdict": None, "source": "grok", "error": "empty_response", "elapsed_s": elapsed}
        
        # Parse JSON  -  strip any markdown fences if present
        verdict = _parse_verdict_json(text)
        if not verdict:
            log(f"  [Grok] ❌ JSON parse failed. Raw: {text[:300]}")
            return {"ok": False, "verdict": None, "source": "grok", "error": "json_parse_failed", "elapsed_s": elapsed}
        
        log(f"  [Grok] ✅ {elapsed:.1f}s  -  score={verdict.get('score_0_to_10', '?')}")
        usage = data.get("usage", {})
        verdict["_meta"] = {
            "source":        "xai",
            "model":         XAI_MODEL,
            "elapsed_s":     round(elapsed, 1),
            "input_tokens":  usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }
        return {"ok": True, "verdict": verdict, "source": "grok", "error": None, "elapsed_s": elapsed}

    except httpx.TimeoutException:
        elapsed = (datetime.now() - t0).total_seconds()
        log(f"  [Grok] ❌ timeout after {elapsed:.1f}s")
        return {"ok": False, "verdict": None, "source": "grok", "error": "timeout", "elapsed_s": elapsed}
    except Exception as e:
        elapsed = (datetime.now() - t0).total_seconds()
        log(f"  [Grok] ❌ exception: {e}")
        return {"ok": False, "verdict": None, "source": "grok", "error": str(e)[:300], "elapsed_s": elapsed}


# ─── Ollama fallback caller ──────────────────────────────────────────────────

async def call_ollama_fallback(system_prompt: str, user_prompt: str) -> dict:
    """Returns same shape as call_grok. Used only when Grok fails."""
    log(f"  [Ollama-Fallback] calling {OLLAMA_FALLBACK_MODEL}…")
    t0 = datetime.now()
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as c:
            r = await c.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model":  OLLAMA_FALLBACK_MODEL,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "options": {
                        "temperature": 0.5,
                        "num_predict": 2000,
                    },
                    "keep_alive": 0,
                    "format": "json",
                },
            )
        elapsed = (datetime.now() - t0).total_seconds()
        if r.status_code != 200:
            log(f"  [Ollama-Fallback] ❌ http {r.status_code}")
            return {"ok": False, "verdict": None, "source": "ollama_fallback", "error": f"http_{r.status_code}", "elapsed_s": elapsed}
        data = r.json()
        content = (data.get("message") or {}).get("content", "")
        verdict = _parse_verdict_json(content)
        if not verdict:
            return {"ok": False, "verdict": None, "source": "ollama_fallback", "error": "json_parse_failed", "elapsed_s": elapsed}
        verdict["_meta"] = {
            "source":    "ollama_fallback",
            "model":     OLLAMA_FALLBACK_MODEL,
            "elapsed_s": round(elapsed, 1),
        }
        log(f"  [Ollama-Fallback] ✅ {elapsed:.1f}s  -  score={verdict.get('score_0_to_10', '?')}")
        return {"ok": True, "verdict": verdict, "source": "ollama_fallback", "error": None, "elapsed_s": elapsed}
    except httpx.TimeoutException:
        elapsed = (datetime.now() - t0).total_seconds()
        log(f"  [Ollama-Fallback] timeout after {elapsed:.1f}s")
        return {"ok": False, "verdict": None, "source": "ollama_fallback", "error": "timeout", "elapsed_s": elapsed}
    except Exception as e:
        elapsed = (datetime.now() - t0).total_seconds()
        log(f"  [Ollama-Fallback] {e}")
        return {"ok": False, "verdict": None, "source": "ollama_fallback", "error": (str(e) or type(e).__name__)[:300], "elapsed_s": elapsed}


def _parse_verdict_json(text: str) -> dict:
    """Robust JSON parse  -  handles markdown fences, leading/trailing prose."""
    if not text:
        return None
    
    # First try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try stripping markdown fences
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", stripped)
        stripped = re.sub(r"\n?```\s*$", "", stripped)
    
    try:
        return json.loads(stripped.strip())
    except json.JSONDecodeError:
        pass
    
    # Last resort: extract first JSON object from anywhere in text
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    
    return None


async def run_judgment(inputs: dict, top_tokens: dict) -> dict:
    """Run Grok primary, fall back to Ollama if needed.
    
    Returns {verdict: dict, meta: dict} where meta describes which path was taken.
    """
    log("STAGE 3: judgment (Grok primary, Ollama fallback)…")
    
    inputs["over_engagement_signatures"] = _collect_over_engagement_signatures(inputs)
    user_prompt = build_user_prompt(inputs, top_tokens)
    log(f"  user prompt: {len(user_prompt)} chars (~{len(user_prompt)//4} tokens)")
    
    # Primary: Grok
    grok_result = await call_grok(OVERSEER_SYSTEM_PROMPT, user_prompt)
    if grok_result["ok"] and grok_result["verdict"]:
        return {
            "verdict": grok_result["verdict"],
            "meta": {
                "judge":           "xai",
                "model":           XAI_MODEL,
                "elapsed_s":       grok_result["elapsed_s"],
                "fallback_used":   False,
                "grok_error":      None,
            },
        }
    
    # Other configured providers in LLM_PROVIDER_ORDER (openai / anthropic / openai_compat), if any
    try:
        import sys as _lp_sys
        _lp_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import llm_providers as _llmp
        _alt = [p for p in _llmp.brain_order() if p not in ("grok", "ollama") and _llmp.configured(p)]
        if _alt:
            _t, _m = await _llmp.generate_chain(user_prompt, providers=_alt, system=OVERSEER_SYSTEM_PROMPT,
                                                json_mode=True, max_tokens=4000, timeout=120)
            if _t:
                _t = _t.strip()
                if _t.startswith("```"):
                    _t = _t.strip("`").split("\n", 1)[-1]
                _v = json.loads(_t[_t.find("{"):_t.rfind("}") + 1])
                return {"verdict": _v, "meta": {"judge": _m.split(":")[0], "model": _m.split(":", 1)[-1],
                                                 "elapsed_s": None, "fallback_used": True,
                                                 "grok_error": grok_result["error"]}}
    except Exception as _lpe:
        log(f"  provider fallback failed: {type(_lpe).__name__}")

    # Fallback: Ollama
    log(f"  Grok failed ({grok_result['error']})  -  falling back to Ollama")
    await notify(f"⚠️ Overseer Grok API failed ({grok_result['error']})  -  falling back to local Ollama brain")
    
    ollama_result = await call_ollama_fallback(OVERSEER_SYSTEM_PROMPT, user_prompt)
    if ollama_result["ok"] and ollama_result["verdict"]:
        return {
            "verdict": ollama_result["verdict"],
            "meta": {
                "judge":         "ollama_fallback",
                "model":         OLLAMA_FALLBACK_MODEL,
                "elapsed_s":     ollama_result["elapsed_s"],
                "fallback_used": True,
                "grok_error":    grok_result["error"],
            },
        }
    
    # Both failed  -  return a stub verdict so we still write SOMETHING to inbox
    log(f"  ❌ both judges failed: grok={grok_result['error']}, ollama={ollama_result['error']}")
    return {
        "verdict": {
            "headline":     "OVERSEER FAILED  -  both Grok and Ollama errored, no judgment available tonight",
            "score_0_to_10": 0,
            "what_was_strong":  [],
            "what_was_weak":    [],
            "patterns_spotted": [],
            "rule_breaks":      [],
            "missed_opportunities": [],
            "time_of_day_observations": [],
            "operator_drift": [],
            "improvements_for_tomorrow": ["fix Overseer infrastructure  -  both judges are down"],
            "follow_ups_for_agent": [
                {"priority": "high", "action": f"check GROK_API_KEY in .env (Grok failed: {grok_result['error']})"},
                {"priority": "high", "action": f"check Ollama is running with {OLLAMA_FALLBACK_MODEL} loaded (Ollama failed: {ollama_result['error']})"},
            ],
        },
        "meta": {
            "judge":         "none",
            "model":         "none",
            "elapsed_s":     0,
            "fallback_used": True,
            "grok_error":    grok_result["error"],
            "ollama_error":  ollama_result["error"],
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 4  -  DAILY SUMMARY WRITER (NEW v4)
# Writes a compact daily summary so future overseer runs have an information
# pyramid: today's raw data + N days of summaries.
# ═════════════════════════════════════════════════════════════════════════════

def write_daily_summary(inputs: dict, verdict: dict, top_tokens: dict, judge_meta: dict) -> str:
    """Compact summary of yesterday for future overseer runs to read."""
    log("STAGE 4: writing daily summary…")
    os.makedirs(DAILY_SUM, exist_ok=True)
    date_str = (datetime.now(EST) - timedelta(hours=2)).strftime("%Y-%m-%d")
    # We're running at 2am, so the data is for "yesterday"  -  subtract a few hours to be safe
    
    meme = inputs.get("meme") or {}
    
    # Compute high-level numbers
    meme_pnl = 0.0
    meme_wins = 0
    meme_losses = 0
    for a in meme.get("autopsies_24h") or []:
        try:
            pnl = float(a.get("pnl_usd") or a.get("pnl") or a.get("net_pnl") or 0)
            meme_pnl += pnl
            if pnl > 0:
                meme_wins += 1
            elif pnl < 0:
                meme_losses += 1
        except Exception:
            continue
    
    summary = {
        "date":     date_str,
        "written_at": now_iso(),
        "judge":    judge_meta,

        "blind_spots": list(_BLIND_SPOTS),
        "blind_spot_count": len(_BLIND_SPOTS),
        
        "thesis_present": bool(inputs.get("thesis")),
        "thesis_summary": (inputs.get("thesis") or {}).get("market_read", "")[:200] if inputs.get("thesis") else None,
        
        "meme": {
            "trades": meme.get("trade_count_24h", 0),
            "wins":   meme_wins,
            "losses": meme_losses,
            "pnl_usd_estimate": round(meme_pnl, 2),
            "open_positions":   len(meme.get("positions_open") or []),
            "missed_runners":   len(meme.get("missed_runners_24h") or []),
        },
        
        "bot_health":  inputs.get("bot_health"),
        "time_buckets": inputs.get("time_buckets"),
        
        "overseer_score":    verdict.get("score_0_to_10"),
        "overseer_headline": verdict.get("headline"),
        "rule_breaks":       verdict.get("rule_breaks") or [],
        "patterns_spotted":  verdict.get("patterns_spotted") or [],
        "operator_drift":    verdict.get("operator_drift") or [],
        "improvements":      verdict.get("improvements_for_tomorrow") or [],
        
        "top_tokens_runners_missed": [
            t.get("symbol") for t in (top_tokens.get("scanned_but_skipped") or [])[:5]
        ],
    }
    
    path = os.path.join(DAILY_SUM, f"{date_str}.json")
    save_json_atomic(path, summary)
    log(f"  ✅ wrote {path}")
    return path


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 5  -  INBOX PACKET WRITER + HISTORY
# ═════════════════════════════════════════════════════════════════════════════

def write_inbox_packet(verdict: dict, judge_meta: dict, inputs: dict, top_tokens: dict, daily_summary_path: str) -> str:
    """Single P2 packet for the agent's morning inbox."""
    log("STAGE 5: writing inbox packet…")
    os.makedirs(INBOX, exist_ok=True)
    
    today_str = datetime.now(EST).strftime("%Y-%m-%d")
    packet_id = f"agent_autoagent - overseer_{today_str}"   # botname prefix -> misc lane routes it (2026-10-15)
    
    # Compute pnl quickly for the packet header
    meme_pnl = 0.0
    for a in inputs.get("meme", {}).get("autopsies_24h") or []:
        try:
            meme_pnl += float(a.get("pnl_usd") or a.get("pnl") or 0)
        except Exception:
            continue
    
    packet = {
        "id":             packet_id,
        "type":           "overseer_report",
        "priority":       "P2",
        "ts":             now_iso(),
        "from":           "agent_autoagent_v4.3.1",
        "lookback_hours": LOOKBACK_HOURS,
        
        "judge": {
            "source":         judge_meta.get("judge"),
            "model":          judge_meta.get("model"),
            "elapsed_s":      judge_meta.get("elapsed_s"),
            "fallback_used":  judge_meta.get("fallback_used"),
            "grok_error":     judge_meta.get("grok_error"),
            "ollama_error":   judge_meta.get("ollama_error"),
        },
        
        "context": {
            "date":                  today_str,
            "thesis_present":        bool(inputs.get("thesis")),
            "inbox_packets_handled": len(inputs.get("inbox_handled") or []),
            "inbox_decisions":       len(inputs.get("inbox_decisions") or []),
            "autopsies_closed":      len(inputs.get("autopsies") or []),
            "missed_runners_count":  len(inputs.get("missed_runners") or []),
            "meme_pnl_estimate_usd": round(meme_pnl, 2),
            "halt_states":           inputs.get("halt_states") or {},
            "bot_health":            inputs.get("bot_health") or {},
            "time_buckets":          inputs.get("time_buckets") or {},
        },
        
        # The roast
        "headline":              verdict.get("headline"),
        "score_0_to_10":         verdict.get("score_0_to_10"),
        "day_type":              verdict.get("day_type"),
        "what_was_strong":       verdict.get("what_was_strong") or [],
        "what_was_weak":         verdict.get("what_was_weak") or [],
        "patterns_spotted":      verdict.get("patterns_spotted") or [],
        "rule_breaks":           verdict.get("rule_breaks") or [],
        "missed_opportunities":  verdict.get("missed_opportunities") or [],
        "time_of_day_observations": verdict.get("time_of_day_observations") or [],
        "operator_drift":        verdict.get("operator_drift") or [],
        "improvements_for_tomorrow": verdict.get("improvements_for_tomorrow") or [],
        "follow_ups_for_agent": verdict.get("follow_ups_for_agent") or [],
        
        # Top tokens
        "top_tokens":   top_tokens,
        
        # Pointer to where the daily summary was written (so future runs can read it)
        "daily_summary_path": daily_summary_path,
        
        # The agent populates this when he processes the report
        "actions_taken": [],
    }
    
    path = os.path.join(INBOX, packet_id + ".json")
    save_json_atomic(path, packet)
    log(f"  ✅ wrote {path}")
    return path


def append_history(packet_path: str, verdict: dict, judge_meta: dict):
    """Append today's report metadata to overseer_history.json."""
    history = load_json(OVERSEER_HIST, []) or []
    if not isinstance(history, list):
        history = []
    history.append({
        "ts":            now_iso(),
        "date":          datetime.now(EST).strftime("%Y-%m-%d"),
        "inbox_path":    packet_path,
        "headline":      verdict.get("headline"),
        "score":         verdict.get("score_0_to_10"),
        "judge":         judge_meta.get("judge"),
        "model":         judge_meta.get("model"),
        "fallback_used": judge_meta.get("fallback_used"),
    })
    history = history[-365:]
    save_json_atomic(OVERSEER_HIST, history)


def _roast_signature_lines(verdict: dict) -> list:
    """The lines from a verdict that represent DURABLE failure patterns worth
    tracking across nights (not one-off day color). We watch weak points, patterns,
    rule breaks, and operator drift  -  the stuff that, if it repeats, is a real
    problem, not a bad day."""
    out = []
    for field in ("what_was_weak", "patterns_spotted", "rule_breaks", "operator_drift"):
        for item in (verdict.get(field) or []):
            if isinstance(item, str) and item.strip():
                out.append((field, item.strip()))
    return out


def _norm_for_match(s: str) -> set:
    """Loose normalization → a SET of stemmed meaningful words, so 'revenge-bought at
    2:14pm' and 'revenge buying in the afternoon' are recognized as the same recurring
    pattern. The roast rephrases every night, so we match on shared concept words with
    light stemming (drop -ing/-ed/-s), not exact wording."""
    import re
    words = re.findall(r"[a-z]{4,}", (s or "").lower())
    stop = {"that", "this", "with", "from", "your", "when", "then", "into", "have",
            "just", "still", "which", "while", "them", "they", "were", "been",
            "agent", "today", "night", "day", "after", "right", "kept", "took",
            "entry", "another", "again", "about", "there", "here", "what", "some"}
    out = set()
    for w in words:
        if w in stop:
            continue
        w = re.sub(r"(ing|ed)$", "", w)
        w = re.sub(r"s$", "", w)
        if len(w) >= 3:
            out.add(w)
    return out


def maybe_append_recurring_to_learnings(verdict: dict, inputs: dict) -> dict:
    """The COMPOUNDING layer (the owner): a roast that just lands in the inbox evaporates.
    So when tonight's roast surfaces a failure pattern that ALSO appeared in a recent
    prior report, that's a REPEAT  -  not a bad day, a standing problem  -  and it gets
    appended to LEARNINGS.md (the authoritative learnings file) with an escalating
    recurrence marker. One-offs stay in the packet only; repeats compound.

    Returns {appended: [...], escalations: {...}} for the packet to surface.
    """
    result = {"appended": [], "recurrence": {}}
    try:
        today_sig = _roast_signature_lines(verdict)
        if not today_sig:
            return result

        # gather the last ~5 nights of roast lines from overseer_history's linked packets
        history = load_json(OVERSEER_HIST, []) or []
        prior_lines = []
        for h in history[-6:-1]:   # exclude tonight (not written yet)
            rep = load_json(h.get("inbox_path", ""), None)
            if not rep:
                continue
            for field in ("what_was_weak", "patterns_spotted", "rule_breaks", "operator_drift"):
                for item in (rep.get(field) or []):
                    if isinstance(item, str) and item.strip():
                        prior_lines.append(item.strip())
        # also fold in yesterday's report if collected separately
        yrep = inputs.get("yesterdays_overseer_report")
        if isinstance(yrep, dict):
            for field in ("what_was_weak", "patterns_spotted", "rule_breaks", "operator_drift"):
                for item in (yrep.get(field) or []):
                    if isinstance(item, str) and item.strip():
                        prior_lines.append(item.strip())

        prior_norm = [(_norm_for_match(p), p) for p in prior_lines]

        appended_lines = []
        for field, line in today_sig:
            tset = _norm_for_match(line)
            if len(tset) < 2:
                continue
            # count how many prior nights had a strongly-overlapping line
            hits = 0
            for pset, praw in prior_norm:
                if len(pset) < 2:
                    continue
                shared = tset & pset
                if not shared:
                    continue
                overlap = len(shared) / min(len(tset), len(pset))
                # same pattern rephrased: ≥34% concept overlap AND ≥2 shared words
                if overlap >= 0.34 and len(shared) >= 2:
                    hits += 1
            if hits >= 1:
                # RECURRING  -  this failure has shown up before. Compound it.
                occ = hits + 1
                result["recurrence"][line] = occ
                appended_lines.append((field, line, occ))

        if appended_lines:
            today = datetime.now(EST).strftime("%Y-%m-%d")
            block = [f"\n### [overseer recurring pattern] {today}"]
            for field, line, occ in appended_lines:
                block.append(
                    f"- [learning candidate] RECURRING ({occ}x): {line} "
                    f" -  flagged by the nightly overseer across {occ} recent reports; "
                    f"this is a standing pattern, not a one-off. (source field: {field})"
                )
            try:
                # learnings_writer puts the block INSIDE Section 8 (between the append-window
                # markers) so the nightly self-eval sees it; a raw append would land below the
                # end marker. Fallback to the raw append only if the writer is missing.
                try:
                    import sys as _lw_sys
                    _lw_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                    from learnings_writer import append_to_learnings as _lw_append
                except Exception:
                    _lw_append = None
                body = "\n".join(block[1:])
                if _lw_append is None or not _lw_append(body, "overseer_followup", "overseer"):
                    with open(LEARNINGS, "a", encoding="utf-8") as f:
                        f.write("\n".join(block) + "\n")
                result["appended"] = [l for _, l, _ in appended_lines]
                log(f"  📝 appended {len(appended_lines)} RECURRING pattern(s) to LEARNINGS.md")
            except Exception as e:
                log(f"  ⚠ LEARNINGS append failed: {e}")
    except Exception as e:
        log(f"  ⚠ recurrence check failed: {e}")
    return result


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

async def run_overseer():
    """Execute the full overseer cycle once."""
    t_start = datetime.now()
    log("═══════════════════════════════════════════════════════")
    log("THE OVERSEER - nightly run (xAI grok-4.7, ollama fallback)")
    log(f"local time: {now_str()}")
    log(f"primary judge: Grok API ({XAI_MODEL})")
    log(f"fallback judge: Ollama ({OLLAMA_FALLBACK_MODEL})")
    log("═══════════════════════════════════════════════════════")
    
    # Stage 1: collect inputs
    inputs = collect_inputs()
    
    # Stage 2: top-10 token analysis (does its own logging)
    top_tokens = await analyze_top_10(inputs.get("meme", {}).get("trades_log_lines") or [])
    
    # Stage 3: judgment (xAI grok-4.7 primary, ollama fallback)
    judgment = await run_judgment(inputs, top_tokens)
    verdict = judgment["verdict"]
    judge_meta = judgment["meta"]
    
    # Stage 4: daily summary (always write, even if judges failed)
    daily_summary_path = write_daily_summary(inputs, verdict, top_tokens, judge_meta)
    
    # Stage 5: inbox packet + history
    packet_path = write_inbox_packet(verdict, judge_meta, inputs, top_tokens, daily_summary_path)
    append_history(packet_path, verdict, judge_meta)

    # Stage 5b: the COMPOUNDING layer  -  recurring failure patterns append to
    # LEARNINGS.md so the roast doesn't just evaporate in the inbox. One-offs stay
    # in the packet; repeats (flagged across recent nights) become durable lessons.
    recurrence = maybe_append_recurring_to_learnings(verdict, inputs)
    if recurrence.get("appended"):
        log(f"  compounded {len(recurrence['appended'])} recurring pattern(s) into LEARNINGS")
        # patch the just-written packet so the agent SEES the recurrence in his morning read
        try:
            _pkt = load_json(packet_path, None)
            if _pkt is not None:
                _pkt["recurring_patterns"] = recurrence.get("recurrence", {})
                _pkt["recurring_appended_to_learnings"] = recurrence.get("appended", [])
                save_json_atomic(packet_path, _pkt)
        except Exception as _re:
            log(f"  ⚠ couldn't patch packet with recurrence: {_re}")
    
    elapsed = (datetime.now() - t_start).total_seconds()
    log(f"═══════════════════════════════════════════════════════")
    log(f"complete in {elapsed:.1f}s | judge={judge_meta.get('judge')} | "
        f"score={verdict.get('score_0_to_10')}/10")
    log("═══════════════════════════════════════════════════════")
    
    # Telegram alert
    score_str = f"{verdict.get('score_0_to_10')}/10" if verdict.get("score_0_to_10") is not None else "n/a"
    headline_short = (verdict.get("headline") or "")[:140]
    judge_label = "Grok" if judge_meta.get("judge") == "xai" else (
        "Ollama (fallback)" if judge_meta.get("judge") == "ollama_fallback" else "FAILED"
    )
    await notify(
        f"🪞 <b>Overseer report ready</b>\n"
        f"Judge: {judge_label} | Score: {score_str}\n"
        f"\n<i>{headline_short}</i>\n"
        f"\nRead in inbox: {os.path.basename(packet_path)}"
    )
    
    return packet_path


async def preflight_checks():
    """Verify environment before entering main loop. Logs warnings, doesn't fail."""
    try:
        import llm_providers as _llmp_pf
        _other = _llmp_pf.any_configured(skip=("grok",))
    except Exception:
        _other = False
    if not GROK_API_KEY and not _other:
        log("⚠️ no cloud brain configured (Grok/OpenAI/Claude/compat)  -  Ollama fallback only")
        await notify("⚠️ Overseer starting with no cloud brain  -  will run on Ollama fallback only")
    elif not GROK_API_KEY:
        log("Overseer judge: no Grok key, using the other configured provider(s)")
    
    # Pre-flight: check Ollama is at least available for fallback
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                tags = r.json()
                models = [m.get("name") for m in tags.get("models", [])]
                if OLLAMA_FALLBACK_MODEL not in models:
                    log(f"⚠️ fallback model {OLLAMA_FALLBACK_MODEL} not present in Ollama  -  fallback will fail")
                else:
                    log(f"✅ Ollama fallback model {OLLAMA_FALLBACK_MODEL} present")
            else:
                log(f"⚠️ Ollama returned {r.status_code}  -  fallback may not work")
    except Exception as e:
        log(f"⚠️ Ollama unreachable at {OLLAMA_URL}: {e}  -  fallback will fail if Grok does")


async def fire_one_run(reason: str = "scheduled"):
    """Wrap run_overseer with state persistence + telemetry.
    Errors caught here don't crash the daemon  -  they're logged + persisted + telegram'd."""
    log(f"firing overseer cycle (reason: {reason})")
    write_heartbeat("running", {"trigger": reason})
    
    try:
        packet_path = await run_overseer()
        _record_run_completion(success=True, packet_path=packet_path)
        write_heartbeat("idle_after_run_ok", {"last_packet": os.path.basename(packet_path)})
        return True
    except KeyboardInterrupt:
        # Bubble up  -  daemon should exit clean
        raise
    except Exception as e:
        import traceback
        err_str = str(e)[:300]
        tb = traceback.format_exc()
        log(f"❌ run errored: {err_str}")
        log(tb)
        _record_run_completion(success=False, error=err_str)
        write_heartbeat("idle_after_run_err", {"last_error": err_str})
        try:
            await notify(f"❌ Overseer run errored: {err_str}\n\nWill retry at next scheduled time. Daemon stays alive.")
        except Exception:
            pass
        return False


async def daemon_loop():
    """Forever-loop: sleep until 2am ET, fire run, write heartbeats throughout."""
    log("entering daemon loop  -  runs nightly at 2:00 AM ET")
    log(f"next scheduled run: {_next_scheduled_dt().isoformat()}")
    write_heartbeat("starting")
    
    # Telegram once on boot so user knows daemon is up
    try:
        await notify(
            f"🪞 <b>Overseer daemon started</b>\n"
            f"Schedule: {SCHEDULED_HOUR_EST:02d}:{SCHEDULED_MINUTE:02d} ET nightly\n"
            f"Next run: {_next_scheduled_dt().strftime('%Y-%m-%d %H:%M ET')}\n"
            f"Primary: Grok API ({XAI_MODEL})\n"
            f"Fallback: Ollama ({OLLAMA_FALLBACK_MODEL})"
        )
    except Exception:
        pass
    
    while True:
        try:
            now = datetime.now(EST)
            seconds_left = _seconds_until_next_run()
            
            if seconds_left > HEARTBEAT_INTERVAL:
                # live-update: far from the next run = safe point to reload an owner patch
                _lu_maybe_reload()
                # Far from target  -  sleep one heartbeat interval, then loop back to check again
                # This way the heartbeat stays fresh and we react to clock jumps gracefully
                write_heartbeat("idle_waiting", {
                    "seconds_until_run": int(seconds_left),
                    "minutes_until_run": round(seconds_left / 60, 1),
                    "hours_until_run":   round(seconds_left / 3600, 2),
                })
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                continue
            
            # We're within HEARTBEAT_INTERVAL of the target. Sleep precisely until target.
            if seconds_left > 0:
                write_heartbeat("imminent", {"seconds_until_run": int(seconds_left)})
                await asyncio.sleep(seconds_left)
            
            # Verify we can actually fire (re-check time + min-hours-between-runs guard)
            allowed, why = _can_fire_run()
            if not allowed:
                log(f"⚠️ skip nightly fire: {why}")
                write_heartbeat("idle_skip_dedup", {"reason": why})
                # Sleep past the trigger window so we don't immediately re-enter this branch
                await asyncio.sleep(120)
                continue
            
            log(f"✅ scheduled trigger reached ({why})")
            await fire_one_run(reason="scheduled_2am")
            
            # After firing, sleep at least a few minutes so the next loop iteration
            # doesn't immediately compute "0 seconds to next run" and refire.
            # _next_scheduled_dt() will already roll forward to tomorrow.
            await asyncio.sleep(120)
        
        except KeyboardInterrupt:
            log("⏹️  daemon interrupted by user (Ctrl+C)")
            write_heartbeat("stopped")
            try:
                await notify("⏹️ Overseer daemon stopped (Ctrl+C)")
            except Exception:
                pass
            return
        except Exception as e:
            # Shouldn't happen  -  fire_one_run catches its own errors. But just in case
            # the loop logic itself fails, log + sleep + continue. Don't die.
            import traceback
            log(f"❌ daemon loop iteration error: {e}")
            log(traceback.format_exc())
            write_heartbeat("loop_error", {"error": str(e)[:200]})
            await asyncio.sleep(300)  # 5 min before retrying loop


# ============================================================================
#   LIVE-UPDATE (element e, simple-bot clean core)
# ============================================================================
# This overseer is idle between nightly runs, so the safe point is trivial: when
# we're far from the next run, if THIS file changed on disk (the agent applied a patch),
# re-exec in place (os.execv, same PID + console) so the patch goes live without a
# manual restart and the bot stays in the terminal the owner launched it from. No browser
# or external process to tear down; Ctrl-C works normally. Floor: only ever reload a
# change already on disk (the agent applied it); never fetch, self-modify, or choose code.
import sys as _lu_sys
import shutil as _lu_shutil
import hashlib as _lu_hashlib

_LU_SELF     = os.path.abspath(__file__)
_LU_MARKER   = os.path.join(LOGS, "agent_autoagent_reload.json")
_LU_LASTGOOD = _LU_SELF + ".last-good"


def _lu_mtime(pth):
    try:
        return os.path.getmtime(pth)
    except Exception:
        return 0.0


def _lu_hash(pth):
    try:
        with open(pth, "rb") as f:
            return _lu_hashlib.sha256(f.read()).hexdigest()[:8]
    except Exception:
        return ""


_LU_BOOT_MTIME = _lu_mtime(_LU_SELF)
_LU_BOOT_HASH  = _lu_hash(_LU_SELF)


def _lu_snapshot_last_good():
    try:
        _lu_shutil.copy2(_LU_SELF, _LU_LASTGOOD)
    except Exception:
        pass


def _lu_write_report(kind, severity, summary, extra=None):
    try:
        os.makedirs(_OWNER_INBOX_DIR, exist_ok=True)
        ts = datetime.now(EST).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(_OWNER_INBOX_DIR, f"agent_autoagent - {kind}_{ts}.md")
        fm = {"kind": kind, "severity": severity,
              "dedupe_key": f"agent_autoagent:{kind}",
              "source_skill": "autoagent", "summary": summary}
        lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["---", "",
                 f"# agent_autoagent {kind}", summary]
        if extra:
            lines += ["", "```json", json.dumps(extra, indent=2, default=str), "```"]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        log(f"live-update report failed: {e}")


def _lu_on_boot():
    marker = load_json(_LU_MARKER, None)
    if isinstance(marker, dict):
        _lu_write_report("bot_restart", "info",
                         f"agent_autoagent reloaded {marker.get('from_hash')} -> {marker.get('to_hash')} (live-update, healthy)",
                         marker)
        try:
            os.remove(_LU_MARKER)
        except Exception:
            pass
    _lu_snapshot_last_good()


def _lu_reload_now():
    new_hash = _lu_hash(_LU_SELF)
    _lu_snapshot_last_good()
    save_json_atomic(_LU_MARKER, {"from_hash": _LU_BOOT_HASH, "to_hash": new_hash,
                                  "detected_at": now_iso(), "lastgood": _LU_LASTGOOD})
    log(f"live-update: reloading {_LU_BOOT_HASH} -> {new_hash} (re-exec in place)")
    try:
        os.execv(_lu_sys.executable, [_lu_sys.executable, _LU_SELF] + _lu_sys.argv[1:])
    except Exception as e:
        # Re-exec failed -> still on the OLD (working) code. Report, keep running.
        log(f"live-update: os.execv failed, staying on current code: {e}")
        _lu_write_report("bot_restart_failed", "high",
                         f"agent_autoagent patch {new_hash} detected but re-exec failed; STILL RUNNING old {_LU_BOOT_HASH}",
                         {"error": str(e)[:200]})
        try:
            os.remove(_LU_MARKER)
        except Exception:
            pass


def _lu_maybe_reload():
    # call only at a safe point (between nightly runs). os.execv does not return.
    if _lu_mtime(_LU_SELF) > _LU_BOOT_MTIME and _lu_hash(_LU_SELF) != _LU_BOOT_HASH:
        _lu_reload_now()


async def main():
    """
    Forever-loop daemon. Runs nightly at 2am ET.
    
    Usage:
      python agent_autoagent.py            → start daemon (forever loop)
      python agent_autoagent.py --now      → fire one run immediately, then exit
      python agent_autoagent.py --once     → alias for --now (back-compat)
    
    To run as a 24/7 background process on Windows: include in your Start_Bots.bat
    alongside meme_sniper and the other sub-bots.
    """
    import sys
    
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    one_shot = any(a in args for a in ["--now", "--once", "--manual"])
    
    log(f"agent_autoagent (Overseer daemon mode) starting at {now_str()} - judge xAI grok-4.7, ollama fallback")
    _lu_on_boot()  # live-update: report a completed reload + snapshot last-good
    log(f"  mode: {'ONE-SHOT (--now)' if one_shot else 'DAEMON (forever loop)'}")
    log(f"  primary judge: Grok API ({XAI_MODEL})")
    log(f"  fallback judge: Ollama ({OLLAMA_FALLBACK_MODEL})")
    if not one_shot:
        log(f"  schedule: {SCHEDULED_HOUR_EST:02d}:{SCHEDULED_MINUTE:02d} ET nightly")
        log(f"  next run: {_next_scheduled_dt().isoformat()}")
    
    await preflight_checks()
    
    if one_shot:
        # Manual fire  -  same wrap as scheduled fire so state gets persisted
        await fire_one_run(reason="manual_invoke")
        log("✅ one-shot run complete, exiting")
        return
    
    # Daemon mode
    await daemon_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Already handled inside daemon_loop, but in case main() didn't get to it
        pass