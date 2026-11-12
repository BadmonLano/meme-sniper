"""security_warden.py — Meme Sniper ecosystem guard.
Watches only the Sniper ecosystem: meme_sniper + bots/sub-bots, their files and wallet.

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

import sys
import json
import re
import time
import asyncio
import hashlib
import subprocess
import shutil
import difflib
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

try:  # LLM_MAIN / LLM_FALLBACK: unselected providers are off in this process
    import llm_providers as _llm_choice
    _llm_choice.apply_choice()
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

EST              = ZoneInfo("America/New_York")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
X_NOTIFY_TELEGRAM_TOKEN = os.getenv("X_NOTIFY_TELEGRAM_TOKEN", "") or TELEGRAM_TOKEN
HELIUS_API_KEY   = os.getenv("HELIUS_API_KEY", "") or os.getenv("RPC_URL", "").split("api-key=")[-1]
X_BEARER_TOKEN   = os.getenv("X_Bearer_Token", "")
WALLET_ADDRESS   = (os.getenv("WALLET_ADDRESS") or os.getenv("HOT_WALLET_ADDRESS", ""))

# Inference: grok-4.7 primary, Ollama fallback. NO OpenRouter.
XAI_API_KEY      = os.getenv("XAI_API_KEY", "") or os.getenv("GROK_API_KEY", "")
XAI_MODEL        = os.getenv("XAI_MODEL", "grok-4.7")  # cloud primary; Ollama stays local fallback only
OLLAMA_URL       = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL     = os.getenv("OLLAMA_MODEL", "qwen3:14b-q4_K_M")

# Workspace paths (the agent's actual paths)
WORKSPACE        = WS_ROOT
BOT_LOGS         = WS_BOT_LOGS

JSON_RELAY       = WS_JSON_RELAY
INBOX            = os.path.join(WS_ROOT, "inbox")
INBOX_DONE       = os.path.join(WS_ROOT, "inbox_results", "done")
OWNER_INBOX       = os.path.join(WS_ROOT, "owner_inbox")
BOTS_DIR         = os.path.join(WS_ROOT, "bots")


def _bot_src(filename: str) -> str:
    """Path of an ecosystem bot's source: bots/<file> (meme_sniper) or bots/sub-bots/<file>."""
    for _d in (BOTS_DIR, os.path.join(BOTS_DIR, "sub-bots")):
        _p = os.path.join(_d, filename)
        if os.path.exists(_p):
            return _p
    return os.path.join(BOTS_DIR, filename)


INBOX_CRON_LOCK_FILE     = os.path.join(BOT_LOGS, "inbox_cron.lock")
INBOX_CRON_LOCK_MAX_AGE_S = int(_envv("INBOX_CRON_LOCK_MAX_AGE_S", str(15 * 60)))  # 15 min (cron guard is 12)
INBOX_CRON_LOCK_CHECK_S   = 60  # check once a minute
SUBAGENTS_DIR    = os.path.join(WS_ROOT, "bots", "subagents")

# Log files
WARDEN_LOG       = os.path.join(BOT_LOGS, "security_warden.json")
COUNTER_INTEL    = os.path.join(BOT_LOGS, "counter_intel.json")
BLACKLIST_FILE   = os.path.join(BOT_LOGS, "injection_blacklist.json")
CONFIG_FILE      = os.path.join(BOT_LOGS, "warden_config.json")
KILL_SWITCH_FILE = os.path.join(BOT_LOGS, "KILL_SWITCH.flag")
LOCKDOWN_FILE    = os.path.join(BOT_LOGS, "lockdown_state.flag")
QUARANTINE_DIR   = os.path.join(BOT_LOGS, "quarantine")
CANARY_DIR       = os.path.join(BOT_LOGS, "canary")
CANARY_LOG       = os.path.join(BOT_LOGS, "canary_trips.json")

# Medic-specific
MEDIC_LOG        = os.path.join(BOT_LOGS, "medic_log.json")
MEDIC_STAGING    = os.path.join(BOT_LOGS, "medic_staging")
MEDIC_BACKUPS    = os.path.join(BOT_LOGS, "medic_backups")
MEDIC_AUDIT      = os.path.join(BOT_LOGS, "medic_audit")

# Integrity-specific
INTEGRITY_LOG    = os.path.join(BOT_LOGS, "integrity_log.json")
HASH_BASELINE    = os.path.join(BOT_LOGS, "known_good_hashes.json")

# Comms-specific
TELEGRAM_CMD_LOG = os.path.join(BOT_LOGS, "warden_tg_commands.json")
LAST_TG_UPDATE   = os.path.join(BOT_LOGS, "warden_tg_last_update.txt")

# Ensure dirs exist
for d in (BOT_LOGS, INBOX, INBOX_DONE, OWNER_INBOX, QUARANTINE_DIR, CANARY_DIR,
          MEDIC_STAGING, MEDIC_BACKUPS, MEDIC_AUDIT):
    os.makedirs(d, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL FILES (integrity check targets)
# ═══════════════════════════════════════════════════════════════════════════

# Owner rules files (optional). Add more with WARDEN_INTEGRITY_FILES (comma-separated, workspace-relative).
# Paths match the repo layout: rules/rules.md (owner rules) and bots/.env (secrets, hash only).
OPERATOR_DOC_FILES = [os.path.join(WORKSPACE, "rules", "rules.md")] + [
    os.path.join(WORKSPACE, _p.strip()) for _p in os.getenv("WARDEN_INTEGRITY_FILES", "").split(",") if _p.strip()]
SENTINEL_FILES = [
    # .env tracked by hash only (never read contents)
    os.path.join(WORKSPACE, "bots", ".env"),
]
CRITICAL_FILES = OPERATOR_DOC_FILES + SENTINEL_FILES   # baseline covers both

# Bot whitelist — Sniper-ecosystem bots that medic is authorized to heal
# Anything not in this list, medic will refuse to touch (Tier 3 escalation only).
AGENT_BOTS_WHITELIST = [
    # ── Core execution layer ───────────────────────────────────
    "meme_sniper.py",
    # ── Intelligence + brain ───────────────────────────────────
    # ── Signal contract producers (Sprint 33) ─────────────────
    "agent_scraper.py",
    "x_intel.py",
    # ── Infrastructure ─────────────────────────────────────────
    "log_janitor.py",
    "learnings_writer.py",
    "agent_autoagent.py",
    "launch_rail.py",
    # ── Code modification toolchain ────────────────────────────
    "code_tuner.py",  # medic + doctor route requests THROUGH it; not modified BY it
]

# Files medic NEVER touches under any circumstance
MEDIC_BLACKLIST_FILES = [
    ".env",
    "wallet_keys.json",
    "private_key.json",
    "trades.log",
    "positions.json",
    "pnl.json",
    "LEARNINGS.md",  # forensic record, never auto-mutated
    "security_warden.py",  # warden never modifies itself
]

# ═══════════════════════════════════════════════════════════════════════════
# INJECTION PATTERNS (applied to UNTRUSTED text only)
# ═══════════════════════════════════════════════════════════════════════════

BASE_INJECTION_PATTERNS = [
    # Instruction override attempts
    "ignore previous instructions", "ignore all instructions", "ignore prior",
    "disregard your programming", "disregard previous", "forget everything",
    "forget your instructions", "forget your training", "forget your role",
    "new instructions:", "updated instructions:", "revised instructions:",
    # Role manipulation
    "you are now", "act as", "pretend to be", "roleplay as",
    "from now on you are", "you will now act",
    # Capability extraction
    "show me your prompt", "reveal your system", "print your instructions",
    "what are your rules", "list your guidelines",
    # Jailbreak patterns
    "do anything now", "in dan mode", "developer mode enabled",
    "no restrictions", "without limitations", "bypass your safety",
    # Direct attacks
    "drop all tables", "rm -rf", "del /f /s",
    # Wallet/credential probes via injection
    "send funds to", "transfer balance to", "export private key",
    "what's in your .env", "show your wallet seed",
]

CREDENTIAL_THEFT_PATTERNS = [
    "private_key", "wallet seed", "api_key for", "bearer token for",
    "what is your helius", "what is your telegram token",
    "leak your credentials", "expose your secrets",
    "dump environment variables", "echo $env",
]

# ═══════════════════════════════════════════════════════════════════════════
# DEFAULT CONFIG
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    "ingress_scan_interval_seconds": 60,
    "egress_scan_interval_seconds":  90,
    "wallet_unknown_tx_threshold":   2,
    "wallet_alert_cooldown_minutes": 30,
    "api_health_check_interval_seconds": 1800,
    "canary_enabled": True,
    "dead_mans_switch_max_silence_minutes": 720,  # 12h
    "medic_enabled": True,
    "medic_check_interval_seconds": 300,
    "medic_max_heal_attempts_per_bot_per_hour": 3,
    "medic_backoff_window_hours": 6,  # v3.3: 3 attempts in 6h → escalate to doctor
    "integrity_check_interval_seconds": 21600,  # 6h
    "telegram_poll_interval_seconds": 30,
    "daily_digest_hour_est": 8,
    "bot_heartbeat_monitor_enabled": True,
    "bot_heartbeat_check_interval_seconds": 600,  # 10min
    "bot_heartbeat_alert_cooldown_hours": 24,     # don't ping same bot twice in 24h
    "parked_bots": [],

    "bot_heartbeat_thresholds_minutes": {
        # CRITICAL — execution layer + brain
        "meme_sniper":      360,      # 6h
        # X PRESENCE
        # PRODUCERS (Sprint 33)
        "agent_scraper":   1440,
        "x_intel":          1440,
        # INFRASTRUCTURE
        "agent_autoagent": 1500,     # 25h (24h cron + slack)
        "log_janitor":      21600,    # 15 DAYS (14-day cadence, runs rarely)
        "code_tuner":       1500,     # 25h (daily cron + slack)
        "learnings_writer":   30,     # heartbeat every LEARNINGS_WRITER_INTERVAL_S (60s)
    },
    # ── v3.3 NEW: doctor layer ──────────────────────────────────
    "doctor_enabled": True,
    "doctor_check_interval_seconds": 300,
    "doctor_use_claude": False,  # RETIRED , warden no longer calls any LLM to diagnose; doctor routes evidence to the agent
    # If an execution bot's heartbeat is FRESH but it hasn't produced an
    # output (trade, decision, post, etc.) for > N hours during signals
    # being good, that's a silent failure. Doctor investigates.
    "silent_failure_check_interval_seconds": 1800,  # 30min
    "silent_failure_min_idle_hours": 12,  # only flag after 12h of total silence on output
    # ── Sprint 41 NEW: skill evolution Layer 10 ─────────────────────
    "bounds": {
        "memes":  {"max_buy_sol": 0.1},
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# CORE UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, data):
    """Atomic write via tmp + replace."""
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[warden] save_json err for {path}: {e}")
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except Exception: pass


def meme_buy_bound(cfg: dict | None = None) -> tuple:
    """(max_buy_sol, source). Single source of truth = the engine's own buy size, so the
    warden never drifts from what the wizard / Settings / agent / learning mode set:
      1. bots/tuner/meme_sniper_filter.json knob SNIPER_BUY_SIZE_SOL (> 0; the live value,
         seeded from bots/.env by the engine whenever the .env value changes)
      2. same file, SIZE_CAP_BASE_SOL (the engine's base cap when no buy size is set)
      3. bots/.env SNIPER_BUY_SIZE_SOL
      4. warden_config.json bounds.memes.max_buy_sol (legacy, default 0.1)
    Then capped by an optional hard ceiling WARDEN_MEME_HARD_CEILING_SOL (env) or
    bounds.memes.hard_ceiling_sol, if set (> 0)."""
    cfg = cfg if cfg is not None else load_config()
    mb = (cfg.get("bounds") or {}).get("memes") or {}
    val, src = None, ""
    try:
        knobs = (load_json(os.path.join(WORKSPACE, "bots", "tuner", "meme_sniper_filter.json"), {}) or {}).get("knobs") or {}
        for key in ("SNIPER_BUY_SIZE_SOL", "SIZE_CAP_BASE_SOL"):
            ent = knobs.get(key)
            v = ent.get("value") if isinstance(ent, dict) else ent
            if v is not None and float(v) > 0:
                val, src = float(v), f"filter {key}"
                break
    except Exception:
        pass
    if val is None:
        try:
            v = os.getenv("SNIPER_BUY_SIZE_SOL")
            if v and float(v) > 0:
                val, src = float(v), ".env SNIPER_BUY_SIZE_SOL"
        except Exception:
            pass
    if val is None:
        val, src = float(mb.get("max_buy_sol", 0.1) or 0.1), "warden_config bounds (legacy)"
    ceil = 0.0
    try:
        ceil = float(_envv("WARDEN_MEME_HARD_CEILING_SOL") or mb.get("hard_ceiling_sol") or 0)
    except Exception:
        ceil = 0.0
    if ceil > 0 and val > ceil:
        val, src = ceil, src + f" (capped by hard ceiling {ceil})"
    return val, src


def load_config() -> dict:
    cfg = load_json(CONFIG_FILE, {})
    if not cfg:
        save_json(CONFIG_FILE, DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    # Fill in any missing keys from defaults
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
    return cfg


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
    """Send Telegram alert via X notify bot. Silent fallback to stdout if TG unavailable.
    
    Uses X_NOTIFY_TELEGRAM_TOKEN (separate bot account) to avoid 409 getUpdates conflicts
    with an agent gateway, which polls on the main TELEGRAM_TOKEN. Warden is outbound-only;
    if X_NOTIFY_TELEGRAM_TOKEN is unset, falls back to TELEGRAM_TOKEN automatically.
    """
    _am = _alerts_mod()
    if _am is not None:
        _res = await _am.send(msg, source="warden", html=True, telegram_token=X_NOTIFY_TELEGRAM_TOKEN or None)
        if not _res:
            print(f"[warden] notify: {msg[:150]}")
        return
    if not X_NOTIFY_TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[warden] notify: {msg[:150]}")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{X_NOTIFY_TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
            )
    except Exception as e:
        print(f"[warden] notify err: {e}")


def log_finding(category: str, severity: str, detail: str, remediation: str = ""):
    findings = load_json(WARDEN_LOG, [])
    findings.append({
        "timestamp":   datetime.now(EST).isoformat(),
        "category":    category,
        "severity":    severity,
        "detail":      detail,
        "remediation": remediation,
        "resolved":    False,
    })
    findings = findings[-500:]
    save_json(WARDEN_LOG, findings)


def log_attack(source: str, payload: str, attack_type: str, metadata: dict = None):
    intel = load_json(COUNTER_INTEL, [])
    intel.append({
        "timestamp":   datetime.now(EST).isoformat(),
        "source":      source,
        "attack_type": attack_type,
        "payload":     payload[:500],
        "metadata":    metadata or {},
        "blocked":     True,
    })
    intel = intel[-2000:]
    save_json(COUNTER_INTEL, intel)
    print(f"[warden] attack logged: {attack_type} from {source}")


def is_kill_switch_active() -> bool:
    return os.path.exists(KILL_SWITCH_FILE)


def is_lockdown_active() -> bool:
    return os.path.exists(LOCKDOWN_FILE)


_SECRET_LINE_RE = re.compile(
    r"(?i)("
    r"(?:api[_-]?key|apikey|secret(?:[_-]?key)?|password|passwd|pwd|"
    r"access[_-]?token|refresh[_-]?token|private[_-]?key|"
    r"seed[_-]?phrase|mnemonic|wallet[_-]?seed|bearer[_-]?token)"
    r"\s*[:=]\s*\S+"
    r"|authorization\s*:\s*bearer\s+\S+"
    r"|\bbearer\s+[A-Za-z0-9\-._~+/]{16,}"
    r"|-----BEGIN\s+[A-Z0-9 ]*PRIVATE\s+KEY-----"
    r"|xai-[A-Za-z0-9]{12,}"
    r"|sk-[A-Za-z0-9_\-]{12,}"
    r"|ghp_[A-Za-z0-9]{12,}"
    r"|AKIA[0-9A-Z]{16}"
    r")"
)
_SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|apikey|password|passwd|private[_-]?key|"
    r"seed[_-]?phrase|mnemonic|bearer|access[_-]?token|refresh[_-]?token|secret[_-]?key)"
)


def _strip_secret_lines(text: str) -> str:
    """Drop lines that look like secrets. Never prints the dropped text."""
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    kept = []
    for line in text.splitlines(keepends=True):
        if _SECRET_LINE_RE.search(line):
            continue
        kept.append(line)
    return "".join(kept)


def _strip_secrets_obj(obj):
    """Redact secret-looking keys and lines inside a quarantine payload."""
    if isinstance(obj, str):
        return _strip_secret_lines(obj)
    if isinstance(obj, list):
        return [_strip_secrets_obj(x) for x in obj]
    if isinstance(obj, dict):
        cleaned = {}
        for key, val in obj.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                continue
            cleaned[key] = _strip_secrets_obj(val)
        return cleaned
    return obj

def write_inbox_packet(priority: str, source: str, slug: str, content: str,
                       target_inbox: str = "agent") -> str:
    """
    Write a packet to an inbox.

    priority: "P1" (critical) | "P2" (high) | "P3" (normal) | "P4" (low/self-note)
    source: short identifier ("warden_critical", "warden_heal", "warden_daily")
    slug: short descriptor ("balance_anomaly", "meme_sniper_healed")
    content: full markdown body of the packet
    target_inbox: "agent" (default — the agent's inbox at INBOX) or "owner" (the owner's
                  inbox at OWNER_INBOX, a notify-only record).

    Returns the absolute path of the written packet.
    """
    ts = datetime.now(EST).strftime("%Y%m%d_%H%M%S")
    filename = f"security_warden - {slug}_{ts}.md"

    if target_inbox == "owner":
        path = os.path.join(OWNER_INBOX, filename)
        recipient = "the owner (review + manual action required)"
    else:
        path = os.path.join(INBOX, filename)
        recipient = "the agent (autonomous processing)"

    header = (
        f"# {slug.replace('_', ' ').title()}\n\n"
        f"**Source:** {source}\n"
        f"**Priority:** {priority}\n"
        f"**Recipient:** {recipient}\n"
        f"**Written:** {datetime.now(EST).isoformat()}\n"
        f"**Lockdown active:** {is_lockdown_active()}\n"
        f"**Kill switch active:** {is_kill_switch_active()}\n\n"
        f"---\n\n"
    )
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + content + "\n")
        print(f"[warden] inbox packet written ({target_inbox}): {filename}")
    except Exception as e:
        print(f"[warden] inbox write err: {e}")
    return path


def file_sha256(path: str) -> str:
    """Compute SHA-256 hex digest of a file. Returns empty string on error."""
    if not os.path.exists(path):
        return ""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        print(f"[warden] hash err for {path}: {e}")
        return ""


# ═══════════════════════════════════════════════════════════════════════════
# INFERENCE LAYER (grok-4.7 primary, Ollama fallback)
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 1: INGRESS GUARDIAN
# Scans UNTRUSTED text from X, Telegram, scraper, DexScreener, etc.
# ═══════════════════════════════════════════════════════════════════════════

UNTRUSTED_SOURCES = {
    "x_interactions":  os.path.join(BOT_LOGS, "x_interactions.json"),
    "browse_results":  os.path.join(BOT_LOGS, "browse_results.json"),
    "dex_raw_tokens":  os.path.join(BOT_LOGS, "dex_raw_tokens.json"),
}


def get_injection_patterns():
    blacklist = load_json(BLACKLIST_FILE, [])
    patterns = [p.lower() for p in BASE_INJECTION_PATTERNS + CREDENTIAL_THEFT_PATTERNS]
    patterns.extend([b.lower() for b in blacklist if len(b) > 5])
    return list(set(patterns))


def scan_text_for_injection(text: str) -> list:
    if not text or not isinstance(text, str):
        return []
    lower = text.lower()
    matches = []
    for pattern in get_injection_patterns():
        if pattern in lower:
            matches.append(pattern)
    return matches[:5]


def block_untrusted_item(source: str, item: dict, matched_patterns: list, item_identifier: str = ""):
    log_attack(
        source=source,
        payload=json.dumps(item, default=str)[:500],
        attack_type="prompt_injection_blocked",
        metadata={"patterns": matched_patterns, "identifier": item_identifier}
    )
    blacklist = load_json(BLACKLIST_FILE, [])
    learned = 0
    for pattern in matched_patterns:
        if 5 < len(pattern) < 100 and pattern not in blacklist:
            blacklist.append(pattern)
            learned += 1
    save_json(BLACKLIST_FILE, blacklist[-500:])

    quarantine_path = os.path.join(
        QUARANTINE_DIR,
        f"{datetime.now(EST).strftime('%Y%m%d_%H%M%S')}_{source}_{item_identifier[:20]}.json"
    )
    try:
        save_json(quarantine_path, {
            "source":     source,
            "blocked_at": datetime.now(EST).isoformat(),
            "patterns":   matched_patterns,
            "item":       _strip_secrets_obj(item),
        })
    except Exception as e:
        print(f"[warden] quarantine write err: {e}")


async def ingress_guardian():
    print("[warden] ingress guardian active")
    cfg = load_config()
    interval = cfg.get("ingress_scan_interval_seconds", 60)
    seen_identifiers = set()

    while True:
        try:
            for source_name, source_path in UNTRUSTED_SOURCES.items():
                if not os.path.exists(source_path):
                    continue
                data = load_json(source_path, [])
                if not isinstance(data, list):
                    if isinstance(data, dict):
                        data = [data]
                    else:
                        continue

                for item in data[-100:]:  # only scan last 100 per cycle
                    if not isinstance(item, dict):
                        continue
                    identifier = (item.get("id") or item.get("username")
                                  or item.get("url") or item.get("ticker") or "")
                    if not identifier:
                        identifier = json.dumps(item, default=str)[:50]
                    if identifier in seen_identifiers:
                        continue

                    text_blob = ""
                    for k in ("text", "content", "description", "tweet", "name", "title", "body"):
                        v = item.get(k, "")
                        if isinstance(v, str):
                            text_blob += " " + v

                    matches = scan_text_for_injection(text_blob)
                    if matches:
                        block_untrusted_item(source_name, item, matches, identifier)
                        await notify(
                            f"🛡️ <b>Warden: Injection blocked</b>\n"
                            f"Source: {source_name}\n"
                            f"From: {identifier[:60]}\n"
                            f"Patterns: {', '.join(matches[:3])}"
                        )
                    seen_identifiers.add(identifier)

            # Cap memory of seen IDs
            if len(seen_identifiers) > 5000:
                seen_identifiers = set(list(seen_identifiers)[-2000:])

            await asyncio.sleep(interval)
        except Exception as e:
            print(f"[warden] ingress err: {e}")
            await asyncio.sleep(120)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 2: EGRESS OBSERVER
# Logs the agent's signal writes. Alerts only on catastrophic issues.
# Never quarantines internal signals.
# ═══════════════════════════════════════════════════════════════════════════

EGRESS_TARGETS = [
    os.path.join(JSON_RELAY, "agent_signals.json"),
    os.path.join(JSON_RELAY, "signal_response.json"),
]


async def egress_validator():
    print("[warden] egress observer active")
    cfg = load_config()
    interval = cfg.get("egress_scan_interval_seconds", 90)

    last_seen_size = {p: 0 for p in EGRESS_TARGETS}

    while True:
        try:
            for path in EGRESS_TARGETS:
                if not os.path.exists(path):
                    continue
                size = os.path.getsize(path)
                if size == last_seen_size[path]:
                    continue
                last_seen_size[path] = size

                data = load_json(path, [])
                if not isinstance(data, list):
                    data = [data] if data else []

                # Catastrophic checks only
                for item in data[-20:]:
                    if not isinstance(item, dict):
                        continue
                    bounds = cfg.get("bounds", {})

                    # Meme oversize
                    if "amount_sol" in item:
                        amt = item.get("amount_sol", 0) or 0
                        max_meme, _msrc = meme_buy_bound(cfg)
                        if amt > max_meme * 5:
                            log_finding(
                                "egress_meme_oversize", "HIGH",
                                f"Meme buy {amt} SOL exceeds 5x max ({max_meme}*5, from {_msrc})",
                                "Verify the agent's intent before allowing"
                            )

            await asyncio.sleep(interval)
        except Exception as e:
            print(f"[warden] egress err: {e}")
            await asyncio.sleep(180)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 3a: CANARY TOKENS
# ═══════════════════════════════════════════════════════════════════════════

async def canary_monitor():
    cfg = load_config()
    if not cfg.get("canary_enabled", True):
        print("[warden] canary disabled in config")
        return

    canary_env = os.path.join(CANARY_DIR, ".env.backup")
    canary_pos = os.path.join(CANARY_DIR, "positions_backup.json")

    if not os.path.exists(canary_env):
        with open(canary_env, "w", encoding="utf-8") as f:
            f.write(
                "# backup credentials\n"
                "PRIVATE_KEY=CANARY_SOLANA_KEY_DO_NOT_USE_5xKp8mN2vQr\n"
                "HELIUS_API_KEY=CANARY_HELIUS_KEY_DO_NOT_USE_7yRt9nM3\n"
                "TELEGRAM_TOKEN=CANARY_TG_TOKEN_DO_NOT_USE_0000000000\n"
                "X_Bearer_Token=CANARY_BEARER_DO_NOT_USE_AAAAAx9Kp\n"
            )
        print(f"[warden] planted canary at {canary_env}")

    if not os.path.exists(canary_pos):
        save_json(canary_pos, {
            "CANARY_MINT_111": {
                "ticker": "CANARY", "amount_sol": 10.0,
                "entry_price": 0.001, "canary": True
            }
        })
        print(f"[warden] planted canary position at {canary_pos}")

    print("[warden] canary monitor active")
    last_access = {}
    # S2: positions_backup.json catches benign JSON scans (FP-heavy). Cool it down so it
    # alerts at most once per window; the .env.backup CREDENTIAL canary stays HOT (no cooldown).
    _canary_cooldown = {canary_pos: cfg.get("canary_positions_cooldown_seconds", 6 * 3600)}
    _canary_last_alert = {}

    while True:
        try:
            await asyncio.sleep(300)
            for canary_path in (canary_env, canary_pos):
                if not os.path.exists(canary_path):
                    continue
                atime = os.path.getatime(canary_path)
                last = last_access.get(canary_path, atime)
                if atime > last + 10:
                    _cd = _canary_cooldown.get(canary_path, 0)
                    if _cd and (time.time() - _canary_last_alert.get(canary_path, 0)) < _cd:
                        last_access[canary_path] = atime  # baseline moved; skip the noisy re-alert
                        continue
                    _canary_last_alert[canary_path] = time.time()
                    trips = load_json(CANARY_LOG, [])
                    trips.append({
                        "timestamp":   datetime.now(EST).isoformat(),
                        "file":        canary_path,
                        "atime":       atime,
                        "attack_type": "canary_trip",
                    })
                    save_json(CANARY_LOG, trips)
                    log_attack("canary", canary_path, "canary_trip",
                               {"file": canary_path, "atime": atime})
                    await notify(
                        f"🔴🔥 <b>Warden: CANARY TRIPPED</b>\n"
                        f"File: {os.path.basename(canary_path)}\n"
                        f"🔥 PIN THIS — Credential file was accessed. Possible compromise.\n"
                        f"Review who has access to {CANARY_DIR} IMMEDIATELY.\n"
                        f"Warden will NOT auto-stop bots. The agent decides on WARDEN LOCKDOWN."
                    )
                    # Also write P1 inbox packet
                    write_inbox_packet(
                        priority="P1", source="warden_canary",
                        slug=f"canary_tripped_{os.path.basename(canary_path)}",
                        content=(
                            f"## Canary Trip Detected\n\n"
                            f"**File accessed:** `{canary_path}`\n"
                            f"**Time:** {datetime.now(EST).isoformat()}\n\n"
                            f"### What this means\n"
                            f"A planted decoy credential file was accessed. "
                            f"Either the agent/the owner legitimately opened it, or the perimeter "
                            f"was breached.\n\n"
                            f"### Action\n"
                            f"1. Verify if the owner accessed this file\n"
                            f"2. If NOT the owner: ESCALATE — possible compromise\n"
                            f"3. Review process list: who has access to `{CANARY_DIR}`\n"
                            f"4. If breach confirmed, engage WARDEN LOCKDOWN\n"
                        )
                    )
                last_access[canary_path] = atime
        except Exception as e:
            print(f"[warden] canary monitor err: {e}")
            await asyncio.sleep(600)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 3b: WALLET ANOMALY WATCHER
# ═══════════════════════════════════════════════════════════════════════════

RPC_PUBLIC_FALLBACK = os.getenv("RPC_PUBLIC_FALLBACK", "https://api.mainnet-beta.solana.com")


def _wallet_rpc_urls() -> list:
    """Free RPC first (same knob Sniper uses), paid Helius last."""
    urls = [u for u in (RPC_PUBLIC_FALLBACK,) if u]
    if HELIUS_API_KEY:
        urls.append(f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}")
    return urls


async def wallet_anomaly_watcher():
    if not WALLET_ADDRESS or not _wallet_rpc_urls():
        print("[warden] wallet watcher: missing WALLET_ADDRESS or any RPC, skipping")
        return

    cfg = load_config()
    threshold = cfg.get("wallet_unknown_tx_threshold", 2)
    cooldown_min = cfg.get("wallet_alert_cooldown_minutes", 30)

    print(f"[warden] wallet watcher active — {WALLET_ADDRESS[:8]}...")

    last_sig = None
    last_alert = 0
    unknown_window = []

    while True:
        try:
            await asyncio.sleep(60)
            async with httpx.AsyncClient(timeout=15) as client:
                # Credit thrift (2026-10-14): free RPC first, paid Helius only if it fails.
                _body = {
                    "jsonrpc": "2.0", "id": 1,
                    "method":  "getSignaturesForAddress",
                    "params":  [WALLET_ADDRESS, {"limit": 5}],
                }
                r = None
                for _url in _wallet_rpc_urls():
                    try:
                        r = await client.post(_url, json=_body)
                        if r.status_code == 200 and "result" in r.json():
                            break
                    except Exception:
                        r = None
                if r is None or r.status_code != 200:
                    continue
                sigs = r.json().get("result", [])
                if not sigs:
                    continue

                latest_sig = sigs[0].get("signature", "")
                if last_sig is None:
                    last_sig = latest_sig
                    continue
                if latest_sig == last_sig:
                    continue

                new_txs = []
                for s in sigs:
                    if s.get("signature") == last_sig:
                        break
                    new_txs.append(s)

                if not new_txs:
                    last_sig = latest_sig
                    continue

                recent_trade_activity = False
                for _tl in ("trades.log", "execution_ledger.jsonl"):
                    _p = os.path.join(BOT_LOGS, _tl)
                    if os.path.exists(_p):
                        try:
                            if time.time() - os.path.getmtime(_p) < 120:
                                recent_trade_activity = True
                                break
                        except Exception:
                            pass

                positions = load_json(os.path.join(BOT_LOGS, "positions.json"), {})
                known_sigs = set()
                if isinstance(positions, dict):
                    for pos in positions.values():
                        if isinstance(pos, dict):
                            known_sigs.add(pos.get("tx_sig", ""))
                            known_sigs.add(pos.get("buy_tx", ""))
                # S3: also treat any tx in the execution ledger as KNOWN - a recent trade
                # explains an on-chain tx even if it is not a current position. Only a
                # genuinely unexplained tx escalates.
                _ledger = os.path.join(BOT_LOGS, "execution_ledger.jsonl")
                if os.path.exists(_ledger):
                    try:
                        with open(_ledger, "r", encoding="utf-8") as _lf:
                            _tail = _lf.readlines()[-200:]
                        for _ln in _tail:
                            _ln = _ln.strip()
                            if not _ln:
                                continue
                            try:
                                _e = json.loads(_ln)
                            except Exception:
                                continue
                            if isinstance(_e, dict):
                                for _k in ("tx_sig", "signature", "sig", "buy_tx", "sell_tx", "tx"):
                                    _v = _e.get(_k)
                                    if isinstance(_v, str) and _v:
                                        known_sigs.add(_v)
                    except Exception:
                        pass

                truly_unknown = [t for t in new_txs if t.get("signature") not in known_sigs]
                if recent_trade_activity:
                    truly_unknown = []  # active trading, ignore

                unknown_window.extend(truly_unknown)
                # Keep only last 10 min
                cutoff = time.time() - 600
                unknown_window = [
                    u for u in unknown_window
                    if u.get("blockTime", 0) > cutoff
                ]

                if len(unknown_window) >= threshold:
                    if time.time() - last_alert > cooldown_min * 60:
                        log_finding(
                            "wallet_anomaly", "CRITICAL",
                            f"{len(unknown_window)} unknown txs in 10min window",
                            "Verify legitimate the owner/the agent tx; if not, possible compromise"
                        )
                        await notify(
                            f"🔴 <b>Warden: WALLET ANOMALY</b>\n"
                            f"{len(unknown_window)} unknown txs in 10min\n"
                            f"Wallet: {WALLET_ADDRESS[:12]}...\n"
                            f"Latest sig: {unknown_window[0].get('signature','?')[:30]}...\n"
                            f"Verify or LOCKDOWN."
                        )
                        write_inbox_packet(
                            priority="P1", source="warden_wallet",
                            slug="wallet_anomaly",
                            content=(
                                f"## Wallet Anomaly Detected\n\n"
                                f"**Wallet:** `{WALLET_ADDRESS}`\n"
                                f"**Unknown tx count:** {len(unknown_window)} in 10min window\n"
                                f"**Threshold:** {threshold}\n\n"
                                f"### Recent unknown signatures\n" +
                                "\n".join(f"- `{u.get('signature','?')[:80]}`"
                                          for u in unknown_window[:5]) +
                                f"\n\n### Action\n"
                                f"1. Verify these txs were owner-initiated (Solscan check)\n"
                                f"2. If NOT recognized: WARDEN LOCKDOWN immediately\n"
                                f"3. Review wallet permissions / connected dapps\n"
                            )
                        )
                        last_alert = time.time()

                last_sig = latest_sig

        except Exception as e:
            # Capture the exception TYPE even when str(e) is empty — a bare
            # exception (e.g. some httpx/network errors) prints nothing otherwise,
            # leaving "[warden] wallet watcher err:" with no diagnostic at all.
            _msg = str(e) or repr(e) or "(no message)"
            print(f"[warden] wallet watcher err: {type(e).__name__}: {_msg}")
            await asyncio.sleep(120)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 3c: DEAD MAN'S SWITCH
# ═══════════════════════════════════════════════════════════════════════════

async def dead_mans_switch():
    """v3.3: REFRAMED — this is now an ECOSYSTEM-WIDE activity backstop, not a
    per-bot liveness check. Per-bot liveness moved to bot_heartbeat_monitor().
    
    Pulse files measure "is the ecosystem DOING SOMETHING" — trades happening,
    macro updating, signals firing. During quiet markets these can be silent
    for many hours legitimately. So the threshold is now 12h (was 60min) and
    it only fires when MULTIPLE pulse files have been silent simultaneously
    for >12h — that's an ecosystem-wide stoppage, not normal market quiet.
    
    For per-bot liveness ("is meme_sniper.py running and healthy"), use
    bot_heartbeat_monitor() below.
    """
    print("[warden] dead man's switch active (v3.3 — 12h ecosystem-wide backstop)")
    cfg = load_config()
    max_silence_min = cfg.get("dead_mans_switch_max_silence_minutes", 720)  # 12h

    pulse_files = [
        os.path.join(BOT_LOGS, "inbox_cron_audit.log"),
        os.path.join(BOT_LOGS, "execution_ledger.jsonl"),
        os.path.join(JSON_RELAY, "agent_signals.json"),
    ]

    # Track last alert time per file so we don't spam (24h cooldown)
    last_alerted = {}
    ALERT_COOLDOWN_SEC = 24 * 3600

    while True:
        try:
            await asyncio.sleep(1800)  # check every 30min (was 15)
            now = time.time()
            silent = []
            for p in pulse_files:
                if not os.path.exists(p):
                    continue
                age_min = (now - os.path.getmtime(p)) / 60
                if age_min > max_silence_min:
                    last = last_alerted.get(p, 0)
                    if now - last > ALERT_COOLDOWN_SEC:
                        silent.append((os.path.basename(p), int(age_min)))

            # Only fire if 2+ pulse files silent simultaneously (ecosystem-wide
            # stoppage, not just one component being quiet). And only after
            # cooldown.
            if len(silent) >= 2:
                log_finding(
                    "dead_mans_switch", "HIGH",
                    f"ECOSYSTEM-WIDE: {len(silent)} pulse files silent >{max_silence_min/60:.0f}h: " +
                    ", ".join(f"{n}({m}m)" for n, m in silent),
                    "Check whether all bots are running. Likely a power outage, "
                    "network issue, or whole-ecosystem crash."
                )
                await notify(
                    f"🟡 <b>Warden: ECOSYSTEM-WIDE ACTIVITY HALT</b>\n"
                    f"{len(silent)} pulse files silent >{max_silence_min/60:.0f}h\n" +
                    "\n".join(f"  {n}: {m//60}h silent" for n, m in silent) +
                    f"\n\nThis is the dead-man-switch backstop. For per-bot health "
                    f"see bot_heartbeat_monitor alerts."
                )
                for n, _ in silent:
                    for p in pulse_files:
                        if os.path.basename(p) == n:
                            last_alerted[p] = now
        except Exception as e:
            print(f"[warden] dead_mans err: {e}")
            await asyncio.sleep(1800)


# Alias map for bots whose heartbeat filename differs from <name>_heartbeat.json
HEARTBEAT_FILE_ALIASES_WARDEN = {
}


def _resolve_bot_heartbeat_path(bot_name: str) -> str:
    aliased = HEARTBEAT_FILE_ALIASES_WARDEN.get(bot_name)
    if aliased:
        return os.path.join(BOT_LOGS, aliased)
    return os.path.join(BOT_LOGS, f"{bot_name}_heartbeat.json")


# Bot offline alert cooldown — don't ping same bot twice in 24h
_BOT_OFFLINE_ALERT_STATE = os.path.join(BOT_LOGS, "warden_offline_alert_state.json")


def _hb_user_stopped(hb_path: str) -> bool:
    """True when the heartbeat carries stop_reason=user_stopped (intentional stop)."""
    try:
        hb = load_json(hb_path, {}) or {}
        return isinstance(hb, dict) and hb.get("stop_reason") == "user_stopped"
    except Exception:
        return False


# ── Sniper watch (2026-10-14): stale/cancelled heartbeat + zero-buy owner pings ──
SNIPER_STALE_ALERT_MIN   = float(_envv("SNIPER_STALE_ALERT_MIN", "30") or 30)
SNIPER_ZERO_BUY_ALERT_H  = float(_envv("SNIPER_ZERO_BUY_ALERT_H", "24") or 24)
SNIPER_WATCH_INTERVAL_S  = int(_envv("SNIPER_WATCH_INTERVAL_S", "300") or 300)
_SNIPER_WATCH_STATE      = os.path.join(BOT_LOGS, "warden_sniper_watch_state.json")
_SNIPER_HB_FILE          = os.path.join(BOT_LOGS, "meme_sniper_heartbeat.json")
_SNIPER_LEDGER_FILE      = os.path.join(BOT_LOGS, "execution_ledger.jsonl")
_SNIPER_TPUT_FILE        = os.path.join(BOT_LOGS, "sniper_throughput_state.json")
_SNIPER_PING_TARGET      = "owner"


def _sniper_hours_since_last_buy():
    """Hours since the last buy/override_buy in execution_ledger.jsonl (tail read).
    Falls back to sniper_throughput_state.zero_buy_hours. None if unknown."""
    try:
        if os.path.exists(_SNIPER_LEDGER_FILE):
            with open(_SNIPER_LEDGER_FILE, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 8_000_000))
                lines = f.read().decode("utf-8", "replace").splitlines()
            last = 0.0
            for ln in lines:
                if '"buy"' not in ln and '"override_buy"' not in ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                if r.get("event") in ("buy", "override_buy"):
                    last = max(last, float(r.get("ts") or 0))
            if last > 0:
                return (time.time() - last) / 3600.0
    except Exception:
        pass
    try:
        v = (load_json(_SNIPER_TPUT_FILE, {}) or {}).get("zero_buy_hours")
        return float(v) if v is not None else None
    except Exception:
        return None


async def _sniper_owner_ping(slug: str, title: str, body: str) -> None:
    """One P1 owner ping: Telegram (notify) + owner inbox packet."""
    try:
        await notify(f"🚨 <b>{title}</b>\n{body}")
    except Exception as e:
        print(f"[warden] sniper_watch notify err: {e}")
    write_inbox_packet("P1", "warden_sniper_watch", slug,
                       f"# {title}\n\n{body}\n", target_inbox=_SNIPER_PING_TARGET)


async def sniper_watch_monitor():
    """Pings the owner ONCE (deduped until recovery) when:
      1. Sniper heartbeat is older than SNIPER_STALE_ALERT_MIN, or every component
         reads cancelled, AND stop_reason is not user_stopped.
      2. Sniper is alive but has made zero buys for more than SNIPER_ZERO_BUY_ALERT_H.
    Read-only on Sniper; never restarts anything."""
    print(f"[warden] sniper watch active (stale>{SNIPER_STALE_ALERT_MIN:.0f}m, "
          f"zero_buy>{SNIPER_ZERO_BUY_ALERT_H:.0f}h)")
    while True:
        try:
            st = load_json(_SNIPER_WATCH_STATE, {}) or {}
            hb = load_json(_SNIPER_HB_FILE, {}) if os.path.exists(_SNIPER_HB_FILE) else None
            if isinstance(hb, dict):
                age_min = (time.time() - os.path.getmtime(_SNIPER_HB_FILE)) / 60.0
                comps = hb.get("components") or {}
                statuses = [str((c or {}).get("status", "")).lower()
                            for c in comps.values() if isinstance(c, dict)]
                all_cancelled = bool(statuses) and all(s == "cancelled" for s in statuses)
                stop_reason = hb.get("stop_reason")
                down = (age_min > SNIPER_STALE_ALERT_MIN or all_cancelled)
                if down and stop_reason != "user_stopped":
                    if not st.get("down_alerted"):
                        why = ("all components cancelled" if all_cancelled
                               else f"heartbeat {age_min:.0f}m old (> {SNIPER_STALE_ALERT_MIN:.0f}m)")
                        await _sniper_owner_ping(
                            "meme_sniper_down", "Meme Sniper looks DOWN",
                            f"- why: {why}\n- stop_reason: {stop_reason or 'none recorded'}\n"
                            f"- stopped_at: {hb.get('stopped_at') or '-'}\n"
                            f"- last_overall_update: {hb.get('last_overall_update') or '-'}\n"
                            "Nothing was restarted. Check the sniper console/log.")
                        st["down_alerted"] = True
                        st["down_alerted_at"] = time.time()
                elif not down and st.get("down_alerted"):
                    st["down_alerted"] = False  # recovered: re-arm
                alive = not down
                if alive:
                    zb = _sniper_hours_since_last_buy()
                    if zb is not None and zb > SNIPER_ZERO_BUY_ALERT_H:
                        if not st.get("zero_buy_alerted"):
                            await _sniper_owner_ping(
                                "meme_sniper_zero_buys", "Meme Sniper: zero buys",
                                f"- alive, but no buy fill for {zb:.1f}h "
                                f"(> {SNIPER_ZERO_BUY_ALERT_H:.0f}h)\n"
                                "- check filters / regime / throughput state. Nothing auto-changed.")
                            st["zero_buy_alerted"] = True
                            st["zero_buy_alerted_at"] = time.time()
                    elif zb is not None and st.get("zero_buy_alerted"):
                        st["zero_buy_alerted"] = False  # a buy landed: re-arm
            save_json(_SNIPER_WATCH_STATE, st)
        except Exception as e:
            print(f"[warden] sniper_watch err: {e}")
        await asyncio.sleep(SNIPER_WATCH_INTERVAL_S)


async def bot_heartbeat_monitor():
    """v3.3 — Per-bot liveness check using bot_logs/<name>_heartbeat.json.
    
    Reads cfg['bot_heartbeat_thresholds_minutes'] for per-bot threshold.
    When a bot's heartbeat exceeds its threshold:
      - Log a finding (severity HIGH if critical bot, MEDIUM otherwise)
      - Write a P1 inbox packet (if critical) or P2 (otherwise) — but only
        if it's been > cooldown since the last alert for this same bot
      - Trigger medic heal attempt (medic decides whether bot is fixable)
    """
    cfg = load_config()
    if not cfg.get("bot_heartbeat_monitor_enabled", True):
        print("[warden] bot_heartbeat_monitor disabled")
        return
    
    print("[warden] bot heartbeat monitor active (v3.3 — per-bot liveness)")
    interval = cfg.get("bot_heartbeat_check_interval_seconds", 600)
    cooldown_h = cfg.get("bot_heartbeat_alert_cooldown_hours", 24)
    thresholds = cfg.get("bot_heartbeat_thresholds_minutes", {})
    grace_floor = cfg.get("bot_heartbeat_grace_minutes_floor", 15)
    grace_pct   = cfg.get("bot_heartbeat_grace_pct", 0.05)
    
    while True:
        try:
            await asyncio.sleep(interval)
            
            # Honor lockdown
            if is_lockdown_active():
                continue
            
            alert_state = load_json(_BOT_OFFLINE_ALERT_STATE, {}) or {}
            now = time.time()
            offline_bots = []
            
            parked = set(cfg.get("parked_bots", []) or [])

            for bot_name, threshold_min in thresholds.items():
                # PARKED = dormant by design. A stale heartbeat is the EXPECTED
                # state, so it is not a finding and never a packet. Logged once
                # per cycle so the suppression is visible rather than silent -
                # warden not paging must itself be observable.
                if bot_name in parked:
                    if bot_name in alert_state:
                        alert_state.pop(bot_name, None)
                    print(f"[warden] heartbeat_monitor: {bot_name} PARKED - offline alerts suppressed")
                    continue

                if bot_name == "meme_sniper":
                    # sniper_watch_monitor owns Sniper outages (one ping per outage).
                    alert_state.pop(bot_name, None)
                    continue
                hb_path = _resolve_bot_heartbeat_path(bot_name)
                if not os.path.exists(hb_path):
                    # Heartbeat file never existed — bot may have never booted.
                    # Don't spam; log once per session and move on.
                    continue
                try:
                    age_min = (now - os.path.getmtime(hb_path)) / 60
                except OSError:
                    continue
                
                # S6 hysteresis: require threshold + grace before paging, so a bot sitting a
                # few minutes over threshold (e.g. 1445 vs 1440) does not flap. grace = max(floor, pct*threshold).
                grace_min = max(grace_floor, threshold_min * grace_pct)
                if _hb_user_stopped(hb_path):
                    # Owner stopped it on purpose (stop_reason=user_stopped): not offline.
                    alert_state.pop(bot_name, None)
                    continue
                if age_min <= threshold_min + grace_min:
                    # Fresh enough (within threshold + grace) - clear any prior alert state
                    if bot_name in alert_state:
                        alert_state.pop(bot_name, None)
                    continue
                
                # Heartbeat is stale beyond per-bot threshold
                last_alerted = alert_state.get(bot_name, {}).get("ts", 0)
                cooldown_sec = cooldown_h * 3600
                if (now - last_alerted) < cooldown_sec:
                    continue  # already alerted recently, wait for cooldown
                
                offline_bots.append({
                    "bot":          bot_name,
                    "age_minutes":  round(age_min, 1),
                    "threshold":    threshold_min,
                    "heartbeat_path": hb_path,
                })
                alert_state[bot_name] = {
                    "ts":            now,
                    "age_minutes":   round(age_min, 1),
                    "threshold_min": threshold_min,
                }
            
            save_json(_BOT_OFFLINE_ALERT_STATE, alert_state)
            
            if not offline_bots:
                continue
            
            # Classify severity per-bot
            # CRITICAL: the sniper. HIGH: its judge + intel producers.
            critical_set = {"meme_sniper"}
            high_set = {"agent_autoagent", "agent_scraper", "x_intel"}
            
            critical_offline = [b for b in offline_bots if b["bot"] in critical_set]
            high_offline = [b for b in offline_bots if b["bot"] in high_set]
            medium_offline = [b for b in offline_bots
                              if b["bot"] not in critical_set and b["bot"] not in high_set]
            
            for b in critical_offline:
                log_finding(
                    "bot_heartbeat_stale", "CRITICAL",
                    f"CRITICAL bot {b['bot']} heartbeat stale: {b['age_minutes']}min "
                    f"(threshold {b['threshold']}min)",
                    f"Medic will attempt heal. If multiple criticals offline, the ecosystem is degraded."
                )
            for b in high_offline:
                log_finding(
                    "bot_heartbeat_stale", "HIGH",
                    f"Bot {b['bot']} heartbeat stale: {b['age_minutes']}min "
                    f"(threshold {b['threshold']}min)",
                    f"Medic will attempt heal."
                )
            for b in medium_offline:
                log_finding(
                    "bot_heartbeat_stale", "MEDIUM",
                    f"Bot {b['bot']} heartbeat stale: {b['age_minutes']}min "
                    f"(threshold {b['threshold']}min)",
                    f"Medic will attempt heal."
                )
            
            # Telegram alert ONLY for critical bots — keeps the noise level low
            if critical_offline:
                lines = [f"  🔴 {b['bot']}: {b['age_minutes']/60:.1f}h stale (threshold {b['threshold']/60:.1f}h)"
                         for b in critical_offline]
                await notify(
                    f"🚨 <b>Warden: CRITICAL bot(s) offline</b>\n" +
                    "\n".join(lines) +
                    f"\n\nMedic firing. Check logs."
                )
            
            # Write P1/P2 packet to the agent's inbox + trigger medic
            for b in offline_bots:
                bot_name = b["bot"]
                priority = "P1" if bot_name in critical_set else "P2"
                content = (
                    f"# Bot Offline — {bot_name}\n\n"
                    f"**Heartbeat age:** {b['age_minutes']/60:.1f}h "
                    f"(threshold {b['threshold']/60:.1f}h)\n"
                    f"**Heartbeat file:** `{b['heartbeat_path']}`\n\n"
                    f"## Medic action\n"
                    f"Medic will attempt heal on next cycle. If heal fails 3x in 6h, "
                    f"doctor will gather the evidence and route it to you to diagnose "
                    f"and fix (code, restart, or browse).\n\n"
                    f"## Your action\n"
                    f"- Check `bot_logs/{bot_name}.log` for crash trace\n"
                    f"- Or run `python {bot_name}.py` manually to see error\n"
                    f"- If process is just hung, kill + restart via Start_Bots.bat\n"
                )
                write_inbox_packet(priority, "warden", f"bot_offline_{bot_name}", content)
                
                # Trigger medic if it's a known whitelisted bot
                bot_filename = f"{bot_name}.py"
                if bot_filename in AGENT_BOTS_WHITELIST and cfg.get("medic_enabled", True):
                    # Medic will pick this up via its own log scan, but we can also
                    # nudge it directly by appending a heartbeat-stale event to errors.json
                    # so medic's log-scan path notices.
                    try:
                        err_path = os.path.join(BOT_LOGS, "errors.json")
                        existing = load_json(err_path, []) or []
                        if not isinstance(existing, list):
                            existing = []
                        existing.append({
                            "ts":     datetime.now(EST).isoformat(),
                            "source": "warden_bot_heartbeat_monitor",
                            "bot":    bot_filename,
                            "error":  f"heartbeat_stale: {b['age_minutes']:.1f}min "
                                     f"(threshold {b['threshold']}min) — investigate or restart",
                        })
                        save_json(err_path, existing[-500:])
                    except Exception:
                        pass
        
        except Exception as e:
            print(f"[warden] bot_heartbeat err: {e}")
            await asyncio.sleep(600)


# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# A bot can be ALIVE (heartbeat fresh) but doing NOTHING in the world. This
# borked, API auth expired. The bot keeps running its loop, fails on every
# API call, but heartbeat is fresh.
#
# This monitor watches the sniper's expected output rate. If meme_sniper
# is alive but produced ZERO trade attempts for >12h despite signals being
# good, that's a silent failure. Doctor investigates.

# Source files where output rate is observable per bot
_OUTPUT_RATE_FILES = {
    "meme_sniper":  os.path.join(BOT_LOGS, "trades.log"),
}


# Newest mtime among each set = the bot did real work. Fill logs are NEVER a
# sole signal — that was the whole bug.
_WORK_EVIDENCE = {
    "meme_sniper": {
        "primary": ["scanned_mints.json"],
        "also":    ["holdings.json", "sniper_throughput_state.json"],
        "idle_hours": 2.0,      # continuous scanner; work files tick sub-hour even in dead tape
    },
}

_EXEC_SOURCES = {
    "meme_sniper": {
        "primary":  "execution_ledger.jsonl",      # structured twin of trades.log
        "fallback": "trades.log",
        "window_h": 2.0, "min_attempts": 3, "fail_ratio": 0.5,
        "success_events": ("sell", "partial_sell"),
        "fail_events":    ("sell_failed",),
        # buys are deliberately NOT counted — entry failures are a separate,
        # lower lane. This sensor is about the EXIT crisis.
        "ignore_events":  ("buy", "buy_failed"),
    },
}
_SNIPER_STUCK_MINT_FAILS = 3        # ≥3 sell_failed on ONE mint in the window → CRITICAL


def _tail_lines(path: str, max_bytes: int = 600_000):
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()
            return f.readlines()
    except Exception:
        return []


def _row_ts(row: dict):
    """Best-effort timestamp from a structured row. Returns epoch seconds or None."""
    for k in ("ts", "timestamp", "at", "time", "_ts", "created_at", "emitted_at"):
        v = row.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            return float(v) if float(v) > 1e9 else None
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
    return None


def _jsonl_rows_in_window(path: str, window_h: float):
    """(rows, window_exact). If rows carry no parseable timestamp we still return
    the tail, flagged inexact — better a slightly wide window than no sensor."""
    rows, exact, cutoff = [], True, time.time() - window_h * 3600
    any_ts = False
    for ln in _tail_lines(path):
        ln = ln.strip()
        if not ln or not ln.startswith("{"):
            continue
        try:
            row = json.loads(ln)
        except Exception:
            continue
        ts = _row_ts(row)
        if ts is not None:
            any_ts = True
            if ts < cutoff:
                continue
        rows.append(row)
    if not any_ts:
        exact = False
    return rows, exact


def _exec_counts(bot_name: str):
    """(attempts, failures, detail) per the agent's markers. Returns (0,0,...) when
    the source is missing or matches nothing — an unreadable source is UNKNOWN,
    never a pass and never a fail."""
    spec = _EXEC_SOURCES.get(bot_name) or {}
    path = os.path.join(BOT_LOGS, spec.get("primary") or "")
    detail = {"source": spec.get("primary"), "window_h": spec.get("window_h")}
    if not spec.get("primary") or not os.path.exists(path):
        detail["status"] = "source_missing"
        return (0, 0, detail)

    rows, exact = _jsonl_rows_in_window(path, spec.get("window_h", 2.0))
    detail["window_exact"] = exact
    attempts = failures = 0
    per_mint_fails = {}

    if bot_name == "meme_sniper":
        for r in rows:
            ev = str(r.get("event") or "").lower()
            if ev in spec["ignore_events"]:
                continue
            if ev in spec["success_events"]:
                attempts += 1
            elif ev in spec["fail_events"]:
                attempts += 1; failures += 1
                m = r.get("mint") or r.get("token") or "?"
                per_mint_fails[m] = per_mint_fails.get(m, 0) + 1
        detail["per_mint_fails"] = per_mint_fails

    if attempts == 0:
        detail["status"] = "no_attempts_in_window"    # healthy idle or stood down
    return (attempts, failures, detail)


def _read_json_quiet(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _stand_down_state(bot_name: str) -> tuple:
    """Returns (stood_down: bool, reason: str). Per the agent's table.
    NOTE: sniper_throughput_state.reduced_mode is NOT stand-down — that's filter
    heat, and work evidence is still expected."""
    try:
        risk = _read_json_quiet(os.path.join(BOT_LOGS, "risk_state.json"))
        if bot_name == "meme_sniper":
            if risk.get("block_new_meme") is True:
                return (True, "risk_state.block_new_meme=true")
            hb = _read_json_quiet(_resolve_bot_heartbeat_path("meme_sniper"))
            blob = json.dumps(hb).upper()
            if "SCANNER_PAUSED" in blob or "WALLET_FLOOR" in blob:
                return (True, "sniper heartbeat reports scanner paused / wallet-floor pause")
            return (False, "")
    except Exception as e:
        print(f"[warden] stand-down read err for {bot_name}: {e}")
    return (False, "")


def _newest_work_evidence(bot_name: str) -> tuple:
    """(filename, age_hours) of the newest work artifact, or (None, None).
    Primary and 'also' files are pooled — any fresh one proves work."""
    spec = _WORK_EVIDENCE.get(bot_name)
    if not spec:
        return (None, None)
    newest_name, newest_mtime = None, 0.0
    for fn in list(spec.get("primary", [])) + list(spec.get("also", [])):
        fp = os.path.join(BOT_LOGS, fn)
        try:
            m = os.path.getmtime(fp)
        except OSError:
            continue
        if m > newest_mtime:
            newest_mtime, newest_name = m, fn
    if not newest_name:
        return (None, None)
    return (newest_name, (time.time() - newest_mtime) / 3600.0)


async def silent_failure_monitor():
    """WORK STALENESS (2026-07-26 — the agent's spec; replaces the fill-log sensor).

    Finding name is `work_staleness`, not `silent_failure`/`OUTPUT_RATE`. It
    answers exactly one question: the process is alive — is it DOING anything?

      healthy idle : hb fresh + work fresh              → no alert
      stood down   : stand-down flag true               → suppress entirely
      work stale   : hb fresh + work stale + not stood  → work_staleness HIGH

    Function name kept so the task registration and doctor path stay wired.
    """
    cfg = load_config()
    print("[warden] work_staleness monitor active (v3.7 — the agent's spec, fill logs are not proof of life)")
    interval = cfg.get("silent_failure_check_interval_seconds", 1800)   # 30min per spec
    cooldown = cfg.get("work_staleness_cooldown_seconds", 6 * 3600)     # 6h per spec (24h was too sleepy)

    last_alerted = {}

    while True:
        try:
            await asyncio.sleep(interval)
            if is_lockdown_active():
                continue

            now = time.time()
            for bot_name, spec in _WORK_EVIDENCE.items():
                hb_path = _resolve_bot_heartbeat_path(bot_name)
                if not os.path.exists(hb_path):
                    continue
                try:
                    hb_age_min = (now - os.path.getmtime(hb_path)) / 60
                except OSError:
                    continue
                if hb_age_min >= 30:
                    continue      # not alive-with-no-work; bot_heartbeat_monitor owns that

                stood_down, sd_reason = _stand_down_state(bot_name)
                if stood_down:
                    # Suppress entirely — never a finding, never INFO spam.
                    print(f"[warden] work_staleness: {bot_name} STANDING DOWN ({sd_reason}) — suppressed")
                    continue

                work_name, work_age_h = _newest_work_evidence(bot_name)
                idle_hours = float(spec.get("idle_hours", 4.0))

                if work_name is not None and work_age_h is not None and work_age_h < idle_hours:
                    continue      # doing work; whatever the fill log says

                if (now - last_alerted.get(bot_name, 0)) < cooldown:
                    continue
                last_alerted[bot_name] = now

                detail = (f"newest work artifact {work_name} is {work_age_h:.1f}h old "
                          f"(threshold {idle_hours}h)") if work_name else \
                         (f"NO work artifacts exist at all "
                          f"({', '.join(spec.get('primary', []) + spec.get('also', []))})")
                log_finding(
                    "work_staleness", "HIGH",
                    f"{bot_name} ALIVE (heartbeat {hb_age_min:.0f}min) but NOT WORKING — {detail}. "
                    f"Not a stand-down. Hung loop or dead external brain (RPC/API/LLM).",
                    "Doctor routes the evidence. Check the bot's inbound data source before its code."
                )
                asyncio.create_task(doctor_investigate(
                    bot_name=bot_name,
                    symptom="work_staleness",
                    context={
                        "heartbeat_age_min":   round(hb_age_min, 1),
                        "newest_work_artifact": work_name,
                        "work_artifact_age_h": (round(work_age_h, 2) if work_age_h is not None else None),
                        "idle_threshold_hours": idle_hours,
                        "stand_down_checked":  True,
                        "note": "fill logs deliberately excluded — they are not proof of life",
                    }
                ))
        except Exception as e:
            print(f"[warden] work_staleness err: {e}")
            await asyncio.sleep(1800)


async def exec_failure_rate_monitor():
    """Sensor B: is the bot TRYING AND BLEEDING? The agent's locked thresholds.

    Distinct from work_staleness by design — staleness means it stopped trying,
    this means it can't land. Opposite remedies, so they never share a name.
    """
    cfg = load_config()
    print("[warden] exec_failure_rate monitor active (v3.7 — the agent's structured markers)")
    interval = cfg.get("exec_failure_rate_check_interval_seconds", 1800)
    cooldown = cfg.get("exec_failure_rate_cooldown_seconds", 6 * 3600)
    last_alerted = {}

    while True:
        try:
            await asyncio.sleep(interval)
            if is_lockdown_active():
                continue
            now = time.time()
            for bot_name, spec in _EXEC_SOURCES.items():
                stood_down, sd_reason = _stand_down_state(bot_name)
                if stood_down:
                    continue          # not attempting new business by design

                attempts, failures, detail = _exec_counts(bot_name)

                # SNIPER CRITICAL: a single bag that will not sell outranks any
                # ratio. The agent's rule — open book + >=3 sell_failed on the SAME
                # mint inside the window fires even when the overall rate is murky.
                if bot_name == "meme_sniper":
                    try:
                        positions = _read_json_quiet(os.path.join(BOT_LOGS, "positions.json"))
                        open_book = any(isinstance(v, dict) and v.get("status", "open") == "open"
                                         for k, v in positions.items() if k != "_meta")
                    except Exception:
                        open_book = False
                    worst = max((detail.get("per_mint_fails") or {}).items(),
                                 key=lambda kv: kv[1], default=(None, 0))
                    if open_book and worst[1] >= _SNIPER_STUCK_MINT_FAILS:
                        key = f"{bot_name}:stuck:{worst[0]}"
                        if (now - last_alerted.get(key, 0)) >= cooldown:
                            last_alerted[key] = now
                            log_finding(
                                "exec_failure_rate", "CRITICAL",
                                f"STUCK BAG — {worst[1]} failed sells on ONE mint ({str(worst[0])[:12]}) "
                                f"inside {spec['window_h']}h with an OPEN book. The position cannot be "
                                f"exited; ratio is irrelevant.",
                                "Exit path, not entry filters. Check send/confirm, then size: smaller "
                                "pieces land when full size dies."
                            )
                            asyncio.create_task(doctor_investigate(
                                bot_name=bot_name, symptom="stuck_bag",
                                context={"mint": worst[0], "failed_sells": worst[1], **detail}))
                        continue

                if attempts < spec["min_attempts"]:
                    continue          # 0 attempts = no rate. never invent one.
                ratio = failures / attempts
                if ratio <= spec["fail_ratio"]:
                    continue
                if (now - last_alerted.get(bot_name, 0)) < cooldown:
                    continue
                last_alerted[bot_name] = now
                log_finding(
                    "exec_failure_rate", "HIGH",
                    f"{bot_name} is TRYING AND BLEEDING — {failures}/{attempts} attempts failed "
                    f"({ratio*100:.0f}%) in {spec['window_h']}h (source: {detail.get('source')}"
                    f"{'' if detail.get('window_exact', True) else ', window approximate'}). "
                    f"Execution-path problem, NOT an edge problem.",
                    "Check the send/confirm path (RPC, endpoints, slippage, size) before touching "
                    "entry filters or scoring."
                )
                asyncio.create_task(doctor_investigate(
                    bot_name=bot_name, symptom="exec_failure_rate",
                    context={"attempts": attempts, "failures": failures,
                              "fail_ratio": round(ratio, 3), **detail}))
        except Exception as e:
            print(f"[warden] exec_failure_rate err: {e}")
            await asyncio.sleep(1800)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 3d: API HEALTH MONITOR
# ═══════════════════════════════════════════════════════════════════════════

async def api_health_monitor():
    print("[warden] api health monitor active")
    cfg = load_config()
    interval = cfg.get("api_health_check_interval_seconds", 1800)

    while True:
        try:
            await asyncio.sleep(interval)
            checks = []

            # Helius RPC
            if HELIUS_API_KEY:
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        r = await client.post(
                            f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}",
                            json={"jsonrpc": "2.0", "id": 1, "method": "getSlot"}
                        )
                        checks.append(("helius", r.status_code == 200))
                except Exception:
                    checks.append(("helius", False))

            # X API
            if X_BEARER_TOKEN:
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        r = await client.get(
                            "https://api.twitter.com/2/users/by/username/jack",
                            headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"}
                        )
                        checks.append(("x_api", r.status_code in (200, 429)))
                except Exception:
                    checks.append(("x_api", False))

            # xAI grok-4.7 (skips quietly when no Grok key: other brains are fine)
            if XAI_API_KEY:
                try:
                    async with httpx.AsyncClient(timeout=15) as client:
                        r = await client.post(
                            "https://api.x.ai/v1/chat/completions",
                            headers={"Authorization": f"Bearer {XAI_API_KEY}",
                                     "Content-Type": "application/json"},
                            json={"model": XAI_MODEL,
                                  "messages": [{"role": "user", "content": "ping"}],
                                  "max_tokens": 5}
                        )
                        checks.append(("grok", r.status_code == 200))
                except Exception:
                    checks.append(("grok", False))

            failures = [name for name, ok in checks if not ok]
            if failures:
                log_finding(
                    "api_health", "MEDIUM" if len(failures) == 1 else "HIGH",
                    f"API failures: {', '.join(failures)}",
                    "Check rate limits / outage"
                )
                if len(failures) >= 2:
                    await notify(
                        f"🟡 <b>Warden: API health</b>\n"
                        f"Failed: {', '.join(failures)}\n"
                        f"Multiple failures may indicate broader issue."
                    )
        except Exception as e:
            print(f"[warden] api_health err: {e}")
            await asyncio.sleep(3600)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 4: COUNTER INTEL (passive — populated by other layers)
# ═══════════════════════════════════════════════════════════════════════════

def get_attack_summary() -> str:
    intel = load_json(COUNTER_INTEL, [])
    if not intel:
        return "No attacks logged."
    today = datetime.now(EST).date().isoformat()
    today_items = [e for e in intel if (e.get("timestamp") or "").startswith(today)]
    by_type = {}
    for e in today_items:
        t = e.get("attack_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    return f"Today: {len(today_items)} attacks | " + " | ".join(
        f"{k}={v}" for k, v in sorted(by_type.items(), key=lambda x: -x[1])
    )


# Sprint 33 signal_contracts/ — if the folder has no recent envelopes from
# producers, that's a real problem (the 5 producers feeding the brain are dead).
SIGNAL_CONTRACTS_DIR_WARDEN = os.path.join(BOTS_DIR, "signal_contracts")
SIGNAL_CONTRACTS_MAX_STALE_HOURS = 6


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 6: MEDIC — process health + auto-heal
# ═══════════════════════════════════════════════════════════════════════════

NOISE_PATTERNS = [
    "urllib3.*chardet", "RequestsDependencyWarning",
    "is-window-maximized", "warn.*version",
    "<!DOCTYPE html>", "<script type",
    "JSONDecodeError.*DOCTYPE", "SyntaxWarning.*invalid escape"
]

SEVERITY_PATTERNS = {
    "CRITICAL": ["invalid_grant", "credential", "WARDEN.*BREACH",
                 "SyntaxError.*py", "private_key.*missing"],
    "HIGH":     ["IndentationError", "NameError", "ImportError",
                 "404.*endpoint", "connection.*refused", "AttributeError"],
    "MEDIUM":   ["Daily limit", "Queue empty", "Outside send window",
                 "rate limit"],
    "LOW":      ["urllib3", "chardet", "warn", "deprecated"],
}


def is_agent_bot(filename: str) -> bool:
    """Return True if a filename is a whitelisted the agent bot."""
    base = os.path.basename(filename)
    return base in AGENT_BOTS_WHITELIST


def is_blacklisted_file(filename: str) -> bool:
    """Return True if medic must NEVER touch this file."""
    base = os.path.basename(filename)
    return base in MEDIC_BLACKLIST_FILES


def classify_severity(message: str) -> str:
    for sev, patterns in SEVERITY_PATTERNS.items():
        for p in patterns:
            if re.search(p, message, re.IGNORECASE):
                return sev
    return "LOW"


def is_noise(message: str) -> bool:
    for p in NOISE_PATTERNS:
        if re.search(p, message, re.IGNORECASE):
            return True
    return False


def medic_log_action(action: str, target: str, result: str, detail: str = ""):
    log = load_json(MEDIC_LOG, [])
    log.append({
        "timestamp": datetime.now(EST).isoformat(),
        "action":    action,
        "target":    target,
        "result":    result,
        "detail":    detail,
    })
    log = log[-500:]
    save_json(MEDIC_LOG, log)


def medic_audit_entry(action: str, details: dict):
    today = datetime.now(EST).date().isoformat()
    audit_file = os.path.join(MEDIC_AUDIT, f"audit_{today}.json")
    existing = load_json(audit_file, [])
    existing.append({
        "timestamp": datetime.now(EST).isoformat(),
        "action":    action,
        "details":   details,
    })
    save_json(audit_file, existing)


def syntax_check_file(path: str) -> tuple:
    """
    Use Python's AST to check syntax. Returns (ok: bool, error: str).
    """
    if not path.endswith(".py"):
        return True, ""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", path],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr
    except Exception as e:
        return False, str(e)


async def medic_attempt_heal(bot_name: str, error_message: str = "") -> dict:
    """Attempt to heal a crashed/broken bot - MECHANICAL restore only, no LLM rewrite."""
    result = {
        "bot": bot_name,
        "started_at": datetime.now(EST).isoformat(),
        "actions": [],
        "outcome": "unknown",
    }

    if not is_agent_bot(bot_name):
        result["outcome"] = "rejected"
        result["actions"].append(f"Bot '{bot_name}' not in AGENT_BOTS_WHITELIST")
        medic_log_action("heal_rejected", bot_name, "not_whitelisted", error_message)
        return result

    if is_blacklisted_file(bot_name):
        result["outcome"] = "rejected"
        result["actions"].append(f"Bot '{bot_name}' is BLACKLISTED for medic")
        medic_log_action("heal_rejected", bot_name, "blacklisted", error_message)
        return result

    bot_path = _bot_src(bot_name)
    if not os.path.exists(bot_path):
        result["outcome"] = "not_found"
        result["actions"].append(f"File not found: {bot_path}")
        medic_log_action("heal_failed", bot_name, "not_found", "")
        return result

    # Check rate limit
    cfg = load_config()
    max_per_hour = cfg.get("medic_max_heal_attempts_per_bot_per_hour", 3)
    log = load_json(MEDIC_LOG, [])
    cutoff = (datetime.now(EST) - timedelta(hours=1)).isoformat()
    recent_attempts = [
        e for e in log
        if e.get("target") == bot_name
        and e.get("action") in ("heal_attempt", "heal_success", "heal_failed")
        and (e.get("timestamp") or "") > cutoff
    ]
    if len(recent_attempts) >= max_per_hour:
        result["outcome"] = "rate_limited"
        result["actions"].append(
            f"Rate limit hit: {len(recent_attempts)} attempts/hour (max {max_per_hour})"
        )
        medic_log_action("heal_rate_limited", bot_name, "skipped", "")
        # Escalate
        write_inbox_packet(
            priority="P1", source="warden_medic",
            slug=f"medic_rate_limit_{bot_name.replace('.py','')}",
            content=(
                f"## Medic rate-limited on {bot_name}\n\n"
                f"Medic attempted heal {len(recent_attempts)}+ times in last hour.\n\n"
                f"This means heals aren't sticking — there's a deeper issue.\n\n"
                f"### Last error\n```\n{error_message[:500]}\n```\n\n"
                f"### Action\n"
                f"1. Manual inspection of `{bot_path}`\n"
                f"2. Run `code_tuner` on it manually\n"
                f"3. Roll back to last known-good if needed\n"
            )
        )
        return result

    medic_log_action("heal_attempt", bot_name, "started", error_message)

    # Step 1: syntax check
    ok, err = syntax_check_file(bot_path)
    if ok:
        result["outcome"] = "syntax_ok"
        result["actions"].append("Syntax check passed — bot file is valid")
        medic_log_action("heal_skipped", bot_name, "syntax_ok",
                         "no fix needed, bot may have crashed for runtime reason")
        return result

    result["actions"].append(f"Syntax error detected: {err[:200]}")

    # Step 2: backup current
    backup_name = f"{bot_name}.{datetime.now(EST).strftime('%Y%m%d_%H%M%S')}.backup"
    backup_path = os.path.join(MEDIC_BACKUPS, backup_name)
    try:
        shutil.copy2(bot_path, backup_path)
        result["actions"].append(f"Backup saved: {backup_name}")
    except Exception as e:
        result["outcome"] = "backup_failed"
        result["actions"].append(f"Backup failed: {e}")
        medic_log_action("heal_failed", bot_name, "backup_failed", str(e))
        return result

    quarantine_path = os.path.join(MEDIC_STAGING, f"{bot_name}.broken.{datetime.now(EST).strftime('%Y%m%d_%H%M%S')}")
    try:
        with open(bot_path, "r", encoding="utf-8", errors="ignore") as _qsrc:
            _qtext = _qsrc.read()
        with open(quarantine_path, "w", encoding="utf-8") as _qdst:
            _qdst.write(_strip_secret_lines(_qtext))
        result["actions"].append(f"Broken file quarantined: {os.path.basename(quarantine_path)}")
    except Exception as e:
        result["actions"].append(f"Quarantine copy failed (continuing): {e}")

    # Find the newest restore candidate: medic backups first, code_tuner snapshot second
    restore_src = None
    restore_kind = None
    try:
        backups = sorted((f for f in os.listdir(MEDIC_BACKUPS)
                          if f.startswith(bot_name) and f.endswith(".backup")), reverse=True)
        # skip the backup we JUST made of the broken file
        for b in backups:
            cand = os.path.join(MEDIC_BACKUPS, b)
            if os.path.abspath(cand) == os.path.abspath(backup_path):
                continue
            ok_c, _ = syntax_check_file(cand)
            if ok_c:
                restore_src, restore_kind = cand, "medic_backup"
                break
    except Exception:
        pass
    if not restore_src:
        try:
            snap = os.path.join(BOT_LOGS, "code_tuner", "snapshots", bot_name)
            if os.path.exists(snap):
                ok_c, _ = syntax_check_file(snap)
                if ok_c:
                    restore_src, restore_kind = snap, "code_tuner_snapshot"
        except Exception:
            pass

    if restore_src:
        try:
            shutil.copy2(restore_src, bot_path)
            result["outcome"] = "restored"
            result["actions"].append(f"Rolled back to last known-good ({restore_kind}: "
                                     f"{os.path.basename(restore_src)})")
            medic_log_action("heal_success", bot_name, "restored_known_good",
                             f"from={restore_kind}; broken preserved at {os.path.basename(quarantine_path)}")
            medic_audit_entry("heal_success", {
                "bot": bot_name, "mode": "mechanical_restore",
                "restored_from": restore_src, "quarantine": quarantine_path,
                "original_error": err[:500],
            })
        except Exception as e:
            result["outcome"] = "restore_failed"
            result["actions"].append(f"Rollback copy failed: {e}")
            medic_log_action("heal_failed", bot_name, "restore_failed", str(e))
    else:
        result["outcome"] = "no_known_good"
        result["actions"].append("No syntax-valid backup or snapshot found — bot left as-is, escalated")
        medic_log_action("heal_failed", bot_name, "no_known_good", "")

    write_inbox_packet(
        priority="P1", source="warden_medic",
        slug=f"medic_patch_needed_{bot_name.replace('.py','')}",
        content=(
            f"## {bot_name} is syntax-broken — YOUR patch is needed\n\n"
            f"### Error class\n{_classify_error_class(err)}\n\n"
            f"### Original error\n```\n{err[:600]}\n```\n\n"
            + (f"### Availability action taken (mechanical)\n"
               f"- Rolled back to last known-good ({restore_kind})\n"
               f"- The RUNNING file is the OLD version — whatever the broken edit was "
               f"trying to add is NOT live\n"
               if restore_src else
               f"### Availability action\n- NO known-good backup/snapshot existed — the "
               f"bot is down until patched\n")
            + f"- Broken file preserved for you: `{quarantine_path}`\n\n"
            f"### Your job (Sprint 38 doctrine — medic no longer authors code)\n"
            f"1. Diff the quarantined broken file against the running file\n"
            f"2. Patch the file in place yourself.\n"
            f"3. Warden does not apply patches and flags do not deploy bots.\n"
            f"Medic restores availability; it never writes code. That's yours.\n"
        )
    )

    return result


def _classify_error_class(error_message: str) -> str:
    """
    Name the error class so an auth/billing crash reads at a glance.
    The owner's #1 actual crash cause is an unpaid API key (invalid_grant / 401 /
    auth-expiry), which no auto-fix could ever resolve anyway — so it leads.
    """
    e = (error_message or "").lower()
    if "invalid_grant" in e or "401" in e or "unauthorized" in e \
            or "authentication" in e or "auth" in e and "expir" in e \
            or "api key" in e or "apikey" in e or "credential" in e:
        return "AUTH / BILLING — likely an unpaid or expired API key (go pay the bill)"
    if "403" in e or "forbidden" in e:
        return "AUTH — 403 forbidden (key scope or billing)"
    if "429" in e or "rate limit" in e or "ratelimit" in e or "quota" in e:
        return "RATE LIMIT / QUOTA exhausted"
    if "syntaxerror" in e or "invalid syntax" in e or "unexpected eof" in e \
            or "unexpected indent" in e or "indentationerror" in e:
        return "SYNTAX ERROR — code won't parse (the agent authors a patch)"
    if "modulenotfound" in e or "importerror" in e or "no module named" in e:
        return "IMPORT / DEPENDENCY missing"
    if "connection" in e or "timeout" in e or "timed out" in e or "refused" in e:
        return "NETWORK / CONNECTION — external service may be down"
    if "traceback" in e or "exception" in e or "error" in e:
        return "RUNTIME ERROR"
    return "UNKNOWN"


async def medic_report_crash(bot_name: str, error_message: str = "") -> dict:
    """
    v3.3 rework: medic is a WATCHER/REPORTER now — it never writes or applies
    code. It detects a crashed/syntax-broken whitelisted bot, takes a free
    backup (no code-write), and writes a report packet TO AGENT. The agent is the
    sole patch author; he patches the file in place. Warden does not apply patches.

    (The old auto-heal lives on in medic_attempt_heal — defined-but-unwired,
    fired ONLY by the manual `MEDIC HEAL` Telegram break-glass.)
    """
    result = {
        "bot": bot_name,
        "started_at": datetime.now(EST).isoformat(),
        "actions": [],
        "outcome": "unknown",
    }

    if not is_agent_bot(bot_name):
        result["outcome"] = "rejected"
        result["actions"].append(f"Bot '{bot_name}' not in AGENT_BOTS_WHITELIST")
        medic_log_action("report_rejected", bot_name, "not_whitelisted", error_message)
        return result

    if is_blacklisted_file(bot_name):
        result["outcome"] = "rejected"
        result["actions"].append(f"Bot '{bot_name}' is BLACKLISTED for medic")
        medic_log_action("report_rejected", bot_name, "blacklisted", error_message)
        return result

    bot_path = _bot_src(bot_name)
    backup_path = ""
    if os.path.exists(bot_path):
        # Free safety — back up current bytes. No code-write, no fix.
        backup_name = f"{bot_name}.{datetime.now(EST).strftime('%Y%m%d_%H%M%S')}.backup"
        backup_path = os.path.join(MEDIC_BACKUPS, backup_name)
        try:
            shutil.copy2(bot_path, backup_path)
            result["actions"].append(f"Backup saved: {backup_name}")
        except Exception as e:
            backup_path = ""
            result["actions"].append(f"Backup failed (non-fatal): {e}")
    else:
        result["actions"].append(f"Bot file not found at {bot_path} (reporting anyway)")

    error_class = _classify_error_class(error_message)
    medic_log_action("crash_reported", bot_name, error_class, error_message[:300])

    # Report leads with the ERROR CLASS so auth/billing reads at a glance.
    bot_short = bot_name.replace(".py", "")
    content = (
        f"## Error class: {error_class}\n\n"
        f"**Bot:** {bot_name}\n"
        f"**Detected:** {datetime.now(EST).isoformat()}\n"
        f"**Backup:** {backup_path or '(none — file not found or backup failed)'}\n\n"
        f"---\n\n"
        f"### What medic did\n"
        f"Detected the crash, took a backup. Medic does NOT fix code — you (the agent) "
        f"patch the file in place. Warden does not apply it.\n\n"
        f"### If this is AUTH / BILLING\n"
        f"Most {bot_short} crashes are an unpaid/expired API key. If the error class "
        f"above says auth/billing, the fix is to pay the bill / refresh the key — "
        f"there is no code patch to author.\n\n"
        f"### Error trace\n"
        f"```\n{error_message[:1500]}\n```\n\n"
        f"### If this is a real code bug\n"
        f"Patch the file in place yourself. "
        f"Backup is at the path above if you need the pre-crash bytes.\n"
    )
    write_inbox_packet(
        priority="P1", source="warden_medic",
        slug=f"medic_report_{bot_short}",
        content=content,
    )
    result["outcome"] = "reported"
    result["actions"].append(f"Report written to the agent (error class: {error_class})")
    return result


async def medic_process_monitor():
    """
    Periodically scan bot logs for errors.
    Trigger heal on syntax errors / known-fixable patterns.
    """
    print("[warden] medic process monitor active")
    cfg = load_config()
    if not cfg.get("medic_enabled", True):
        print("[warden] medic disabled in config")
        return

    interval = cfg.get("medic_check_interval_seconds", 300)
    if not os.path.exists(MEDIC_LOG):
        save_json(MEDIC_LOG, [])  # S4: ensure the medic audit log exists even before the first heal

    last_seen_log_size = {}

    while True:
        try:
            await asyncio.sleep(interval)

            # Honor lockdown
            if is_lockdown_active():
                print("[warden] medic skipping — lockdown active")
                continue

            # Scan for log files in bot_logs that might contain error traces
            error_logs = [
                os.path.join(BOT_LOGS, "bot_alerts.json"),
                os.path.join(BOT_LOGS, "errors.json"),
            ]
            # Also scan any *.log files
            try:
                for f in os.listdir(BOT_LOGS):
                    if f.endswith(".log"):
                        error_logs.append(os.path.join(BOT_LOGS, f))
            except Exception:
                pass

            heal_targets = {}  # bot_name -> error message

            for log_path in error_logs:
                if not os.path.exists(log_path):
                    continue
                size = os.path.getsize(log_path)
                last_size = last_seen_log_size.get(log_path, 0)
                if size <= last_size:
                    continue
                last_seen_log_size[log_path] = size

                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        # Read only the new bytes
                        f.seek(last_size)
                        new_content = f.read()
                except Exception:
                    continue

                if not new_content:
                    continue

                # Look for SyntaxError mentioning a whitelisted bot
                for bot in AGENT_BOTS_WHITELIST:
                    if bot in new_content:
                        # Extract a small snippet around the bot mention
                        idx = new_content.find(bot)
                        snippet = new_content[max(0, idx - 200):idx + 300]
                        if is_noise(snippet):
                            continue
                        sev = classify_severity(snippet)
                        if sev in ("CRITICAL", "HIGH"):
                            heal_targets[bot] = snippet

            cfg_local = load_config()
            backoff_window = cfg_local.get("medic_backoff_window_hours", 6)
            for bot, err in heal_targets.items():
                bot_name_only = bot.replace(".py", "")
                reports_in_window = heal_attempts_in_window(bot_name_only, backoff_window)
                if reports_in_window >= 3:
                    print(f"[warden/medic] already reported {bot} "
                          f"{reports_in_window}x in {backoff_window}h — quiet, "
                          f"doctor will investigate")
                    continue

                print(f"[warden/medic] reporting crash: {bot}")
                report_result = await medic_report_crash(bot, err)
                outcome = report_result.get("outcome", "unknown")
                print(f"[warden/medic] report {bot}: {outcome}")
                # Track report for dedupe
                record_heal_attempt(bot_name_only, outcome)

        except Exception as e:
            print(f"[warden] medic monitor err: {e}")
            await asyncio.sleep(600)


DOCTOR_LOG_FILE = os.path.join(BOT_LOGS, "doctor_log.json")
HEAL_ATTEMPTS_FILE = os.path.join(BOT_LOGS, "heal_attempts.json")
CODE_REQUESTS_FILE = os.path.join(BOT_LOGS, "code_requests.json")  # code_tuner reads this


def doctor_log_entry(bot_name: str, symptom: str, diagnosis: str,
                     resolution: str, outcome: str, raw_llm_response: str = ""):
    """Append entry to doctor_log.json (capped 200)."""
    entries = load_json(DOCTOR_LOG_FILE, [])
    if not isinstance(entries, list):
        entries = []
    entries.append({
        "ts":         datetime.now(EST).isoformat(),
        "bot":        bot_name,
        "symptom":    symptom,
        "diagnosis":  diagnosis,
        "resolution": resolution,
        "outcome":    outcome,
        "raw_llm":    raw_llm_response[:2000] if raw_llm_response else "",
    })
    save_json(DOCTOR_LOG_FILE, entries[-200:])


def record_heal_attempt(bot_name: str, outcome: str):
    """Track heal attempts per bot with timestamps for backoff math."""
    attempts = load_json(HEAL_ATTEMPTS_FILE, {})
    if not isinstance(attempts, dict):
        attempts = {}
    bot_attempts = attempts.get(bot_name, [])
    bot_attempts.append({
        "ts":      datetime.now(EST).isoformat(),
        "outcome": outcome,
    })
    # Keep last 50 per bot
    attempts[bot_name] = bot_attempts[-50:]
    save_json(HEAL_ATTEMPTS_FILE, attempts)


def heal_attempts_in_window(bot_name: str, hours: int = 6) -> int:
    """Count failed heal attempts for bot_name in the last N hours."""
    attempts = load_json(HEAL_ATTEMPTS_FILE, {})
    if not isinstance(attempts, dict):
        return 0
    bot_attempts = attempts.get(bot_name, [])
    cutoff = datetime.now(EST) - timedelta(hours=hours)
    count = 0
    for a in bot_attempts:
        try:
            ts = datetime.fromisoformat(a.get("ts", ""))
            if ts >= cutoff and a.get("outcome", "").lower() in ("failed", "error"):
                count += 1
        except Exception:
            continue
    return count


async def doctor_investigate(bot_name: str, symptom: str, context: dict = None) -> dict:
    """v3.3 - evidence ROUTER for what medic can't fix. Gathers evidence and routes/escalates it to the agent (the intelligence layer). LLM diagnose is DISABLED on the auto path (do not re-enable per doctrine); this is not a Claude-powered diagnoser.
    
    bot_name:  bare name (e.g. "meme_sniper") — without .py
    symptom:   short tag for what triggered investigation
               ("medic_exhausted" | "silent_failure" | "heartbeat_stale")
    context:   optional dict of additional state (heartbeat ages, log paths, etc.)
    
    Returns a dict with the diagnosis + routing decision.
    """
    cfg = load_config()
    if not cfg.get("doctor_enabled", True):
        return {"outcome": "doctor_disabled"}
    
    context = context or {}
    print(f"[warden/doctor] investigating {bot_name} (symptom={symptom})")
    
    # Gather evidence — recent logs, heartbeat, last 24h inbox events
    evidence = {
        "bot_name":         bot_name,
        "symptom":          symptom,
        "context":          context,
        "recent_log_lines": [],
        "heartbeat_state":  None,
        "heal_attempts_6h": heal_attempts_in_window(bot_name, 6),
    }
    
    # Recent log lines (last ~3000 chars)
    log_paths = [
        os.path.join(BOT_LOGS, f"{bot_name}.log"),
        os.path.join(BOT_LOGS, "errors.json"),
    ]
    for lp in log_paths:
        if not os.path.exists(lp):
            continue
        try:
            size = os.path.getsize(lp)
            with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                if size > 8000:
                    f.seek(size - 8000)
                tail = f.read()
            evidence["recent_log_lines"].append({"file": os.path.basename(lp),
                                                  "tail": tail[-3000:]})
        except Exception:
            continue
    
    # Heartbeat content
    hb_path = _resolve_bot_heartbeat_path(bot_name)
    if os.path.exists(hb_path):
        try:
            evidence["heartbeat_state"] = load_json(hb_path, {})
            evidence["heartbeat_age_min"] = (time.time() - os.path.getmtime(hb_path)) / 60
        except Exception:
            pass
    
    # DOCTRINE: warden does NOT diagnose with an LLM (no Claude, no Grok call here).
    # It gathers evidence and hands it to the agent , the agent is the brain AND the coder.
    # He reads this on his next wake, names the cause from the logs, and acts.
    log_excerpt = "\n".join(x["tail"] for x in evidence["recent_log_lines"])[:2500]
    hb_state = json.dumps(evidence.get("heartbeat_state"), indent=2, default=str)[:1200]
    content = (
        f"# Doctor , investigate {bot_name}\n\n"
        f"**Symptom:** {symptom}\n"
        f"**Heal attempts (6h):** {evidence['heal_attempts_6h']}\n"
        f"**Heartbeat age:** {evidence.get('heartbeat_age_min', '?')} min\n\n"
        f"## Your move (the agent)\n"
        f"Medic couldn't fix this. Warden does NOT diagnose , that's yours. Read the "
        f"evidence below, name the cause, and act: code bug -> author the full file into "
        f"patch the file in place (you apply it; warden does not). "
        f"hung process -> flag a restart; external service (RPC / API) -> browse "
        f"and check; can't tell -> escalate to the owner. Log what you find in LEARNINGS.md.\n\n"
        f"## Recent log tails\n```\n{log_excerpt}\n```\n\n"
        f"## Heartbeat state\n```\n{hb_state}\n```\n\n"
    )
    content = _strip_secret_lines(content)
    write_inbox_packet("P2", "doctor", f"investigate_{bot_name}", content)
    outcome = "routed_to_agent"
    resolution = "Evidence packet written to the agent , he diagnoses + acts (no warden LLM)."

    doctor_log_entry(
        bot_name=bot_name,
        symptom=symptom,
        diagnosis="(routed to the agent , warden no longer diagnoses)",
        resolution=resolution,
        outcome=outcome,
        raw_llm_response="",
    )

    return {"outcome": outcome, "resolution": resolution}


async def doctor_monitor():
    """Runs alongside medic. When medic's heal_attempts_in_window(bot, 6) > 3,
    medic has been looping — doctor takes over investigation. Detection happens
    by reading medic_log.json for recent failures.
    """
    cfg = load_config()
    if not cfg.get("doctor_enabled", True):
        print("[warden] doctor disabled")
        return
    print("[warden] doctor monitor active (v3.3 — evidence routed to the agent, no LLM)")
    interval = cfg.get("doctor_check_interval_seconds", 300)
    backoff_window_h = cfg.get("medic_backoff_window_hours", 6)
    investigated_this_session = set()  # avoid investigating same bot repeatedly per session
    
    while True:
        try:
            await asyncio.sleep(interval)
            if is_lockdown_active():
                continue
            
            # Check each whitelisted bot for runaway heal attempts
            for bot_filename in AGENT_BOTS_WHITELIST:
                bot_name = bot_filename.replace(".py", "")
                fail_count = heal_attempts_in_window(bot_name, backoff_window_h)
                if fail_count < 3:
                    continue
                
                # Already investigated this bot in this session window — skip
                session_key = f"{bot_name}_{datetime.now(EST).strftime('%Y%m%d')}"
                if session_key in investigated_this_session:
                    continue
                
                print(f"[warden/doctor] medic exhausted on {bot_name} "
                      f"({fail_count} fails in {backoff_window_h}h) — investigating")
                result = await doctor_investigate(
                    bot_name=bot_name,
                    symptom="medic_exhausted",
                    context={"heal_fail_count": fail_count,
                             "window_hours": backoff_window_h},
                )
                investigated_this_session.add(session_key)
                print(f"[warden/doctor] {bot_name}: {result.get('outcome')}")
        except Exception as e:
            print(f"[warden/doctor] monitor err: {e}")
            await asyncio.sleep(600)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 6c: (reserved)
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 7: INTEGRITY (hash check on critical files)
# ═══════════════════════════════════════════════════════════════════════════

def integrity_baseline_snapshot():
    """Snapshot current critical-file hashes as known-good baseline.
    v3.4: configured paths that don't exist are reported ONCE (INFO) instead of
    silently thinning the baseline — 'reading wrong paths' becomes visible."""
    baseline = {}
    missing_configured = []
    for path in CRITICAL_FILES:
        h = file_sha256(path)
        if h:
            baseline[path] = {
                "sha256":      h,
                "snapshotted": datetime.now(EST).isoformat(),
                "size":        os.path.getsize(path) if os.path.exists(path) else 0,
            }
        else:
            missing_configured.append(path)
    save_json(HASH_BASELINE, baseline)
    print(f"[warden] integrity baseline snapshotted: {len(baseline)} files")
    if missing_configured:
        log_finding("integrity_config", "INFO",
                    f"{len(missing_configured)} configured watch path(s) do not exist: "
                    + ", ".join(os.path.basename(p) for p in missing_configured),
                    "Prune stale paths from OPERATOR_DOC_FILES/SENTINEL_FILES or restore the files")
        print(f"[warden] integrity: {len(missing_configured)} configured paths missing "
              f"({', '.join(os.path.basename(p) for p in missing_configured)})")
    return baseline


def integrity_log(event: str, path: str, detail: str = ""):
    log = load_json(INTEGRITY_LOG, [])
    log.append({
        "timestamp": datetime.now(EST).isoformat(),
        "event":     event,
        "path":      path,
        "detail":    detail,
    })
    log = log[-200:]
    save_json(INTEGRITY_LOG, log)


async def integrity_check_now() -> dict:
    """Run hash check against baseline. Returns summary."""
    baseline = load_json(HASH_BASELINE, {})
    if not baseline:
        baseline = integrity_baseline_snapshot()
        return {"first_run": True, "files": len(baseline), "mismatches": []}

    summary = {"checked": 0, "matches": 0, "mismatches": [], "missing": [],
               "operator_changes": [], "sentinel_changes": [], "deletions": []}
    _op_docs = set(OPERATOR_DOC_FILES)
    _sentinels = set(SENTINEL_FILES)
    _rebaselined = False
    for path, expected in baseline.items():
        summary["checked"] += 1
        if not os.path.exists(path):
            summary["missing"].append(path)
            summary["deletions"].append(path)
            integrity_log("deleted", path, "baselined file no longer exists")
            continue
        current_hash = file_sha256(path)
        if current_hash == expected.get("sha256"):
            summary["matches"] += 1
            continue
        rec = {"path": path, "expected": expected.get("sha256", "")[:12],
               "current": current_hash[:12],
               "size_was": expected.get("size"),
               "size_now": os.path.getsize(path)}
        summary["mismatches"].append(rec)
        if path in _sentinels:
            summary["sentinel_changes"].append(rec)
            integrity_log("sentinel_change", path,
                          f"expected={rec['expected']}, current={rec['current']}")
        else:
            # v3.4: OPERATOR CHANGE — ledger it, auto-rebaseline it, digest it.
            # No packet. No Telegram. No asking the owner if the owner was the owner.
            summary["operator_changes"].append(rec)
            integrity_log("operator_change", path,
                          f"expected={rec['expected']}, current={rec['current']}, "
                          f"size {rec['size_was']}→{rec['size_now']} — auto-rebaselined")
            baseline[path] = {"sha256": current_hash,
                              "snapshotted": datetime.now(EST).isoformat(),
                              "size": rec["size_now"]}
            _rebaselined = True
    if _rebaselined:
        save_json(HASH_BASELINE, baseline)

    n_op = len(summary["operator_changes"])
    if n_op:
        log_finding("integrity_operator_change", "INFO",
                    f"{n_op} operator doc(s) changed and auto-rebaselined: "
                    + ", ".join(os.path.basename(c["path"]) for c in summary["operator_changes"]),
                    "Visible in daily digest — no action unless a change surprises you")

    # ── THREAT CLASS 1: deletion of a baselined file ──
    if summary["deletions"]:
        log_finding("integrity_deletion", "HIGH",
                    f"{len(summary['deletions'])} baselined file(s) DELETED: "
                    + ", ".join(os.path.basename(p) for p in summary["deletions"]),
                    "Confirm intentional; restore from backup if not")
        write_inbox_packet(
            priority="P1", source="warden_integrity",
            slug=f"integrity_deleted_{len(summary['deletions'])}_files",
            content=(f"## Integrity: {len(summary['deletions'])} baselined file(s) deleted\n\n"
                     + "\n".join(f"- `{p}`" for p in summary["deletions"])
                     + "\n\nA watched file disappearing is a real signal — confirm with "
                       "The owner that removal was intentional; if yes, the next baseline "
                       "refresh drops it cleanly. If no one removed it, treat as an "
                       "incident and preserve evidence before restoring."))

    # ── THREAT CLASS 2: sentinel (.env) changed — ask, don't accuse ──
    if summary["sentinel_changes"]:
        mass_anomaly = len(summary["mismatches"]) >= 6
        sev = "CRITICAL" if mass_anomaly else "HIGH"
        log_finding("integrity_sentinel", sev,
                    f".env hash changed" + (" amid mass file changes" if mass_anomaly else ""),
                    "Agent checks the change trail; INTEGRITY BASELINE if legitimate")
        write_inbox_packet(
            priority="P1", source="warden_integrity",
            slug="integrity_sentinel_env_changed",
            content=(f"## Integrity: .env changed\n\n"
                     f"The secrets file's hash changed since last baseline.\n\n"
                     f"**Most likely:** the owner rotated a key or added a var. One question "
                     f"settles it: *\"yo, did you touch .env?\"* If yes → Telegram "
                     f"`INTEGRITY BASELINE` and move on.\n\n"
                     + ("**However:** this happened alongside "
                        f"{len(summary['mismatches'])} total file changes in one sweep — a "
                        f"mass-change pattern. If the owner did NOT do this, treat it as an "
                        f"active incident: WARDEN LOCKDOWN is on the table.\n"
                        if mass_anomaly else
                        "If the owner did NOT touch it, rotate exposed keys first, "
                        "investigate second.\n")))
        await notify(
            f"🟡 <b>Warden: .env changed</b>\n"
            f"Agent checks the change trail, then `INTEGRITY BASELINE` if legitimate."
            + ("\n⚠ Mass-change pattern alongside it — verify carefully." if mass_anomaly else ""))

    return summary


async def integrity_monitor():
    print("[warden] integrity monitor active")
    cfg = load_config()
    interval = cfg.get("integrity_check_interval_seconds", 21600)  # 6h default

    # First run: snapshot if no baseline exists
    if not os.path.exists(HASH_BASELINE):
        integrity_baseline_snapshot()

    while True:
        try:
            await asyncio.sleep(interval)
            await integrity_check_now()
        except Exception as e:
            print(f"[warden] integrity err: {e}")
            await asyncio.sleep(7200)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 8: AGENT COMMS (daily digest + telegram command channel)
# ═══════════════════════════════════════════════════════════════════════════

def get_24h_findings_summary() -> dict:
    findings = load_json(WARDEN_LOG, [])
    cutoff = (datetime.now(EST) - timedelta(days=1)).isoformat()
    recent = [f for f in findings if (f.get("timestamp") or "") > cutoff]
    by_severity = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    by_category = {}
    for f in recent:
        sev = f.get("severity", "INFO")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        cat = f.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1
    return {
        "total":       len(recent),
        "by_severity": by_severity,
        "by_category": by_category,
        "items":       recent[-30:],
    }


def get_medic_24h_summary() -> dict:
    log = load_json(MEDIC_LOG, [])
    cutoff = (datetime.now(EST) - timedelta(days=1)).isoformat()
    recent = [e for e in log if (e.get("timestamp") or "") > cutoff]
    summary = {"total": len(recent), "by_action": {}, "heals_succeeded": 0, "heals_failed": 0}
    for e in recent:
        a = e.get("action", "unknown")
        summary["by_action"][a] = summary["by_action"].get(a, 0) + 1
        if a == "heal_success":
            summary["heals_succeeded"] += 1
        elif a == "heal_failed":
            summary["heals_failed"] += 1
    return summary


# ═══════════════════════════════════════════════════════════════════════════
# v3.3 Phase 5 — DAILY DIGEST: Sprint 33+ visibility additions
# ═══════════════════════════════════════════════════════════════════════════

def get_doctor_24h_summary() -> dict:
    """v3.3 — Counts doctor investigations in last 24h grouped by outcome."""
    log = load_json(DOCTOR_LOG_FILE, [])
    if not isinstance(log, list):
        return {"total": 0, "by_outcome": {}, "samples": []}
    cutoff = (datetime.now(EST) - timedelta(days=1)).isoformat()
    recent = [e for e in log if (e.get("ts") or "") > cutoff and isinstance(e, dict)]
    by_outcome = {}
    for e in recent:
        oc = e.get("outcome", "unknown")
        by_outcome[oc] = by_outcome.get(oc, 0) + 1
    return {
        "total":      len(recent),
        "by_outcome": by_outcome,
        "samples":    recent[-5:],
    }


def get_code_tuner_queue_depth() -> dict:
    """v3.3 — Read code_requests.json, return pending count + oldest unresolved age."""
    requests = load_json(CODE_REQUESTS_FILE, [])
    if not isinstance(requests, list):
        return {"pending": 0, "oldest_age_hours": None, "by_requester": {}}
    pending = [r for r in requests if isinstance(r, dict) and not r.get("resolved", False)]
    by_requester = {}
    for r in pending:
        req = r.get("requester", "unknown")
        by_requester[req] = by_requester.get(req, 0) + 1
    oldest_age = None
    if pending:
        ages = []
        for r in pending:
            try:
                ts = datetime.fromisoformat(r.get("requested_at", ""))
                ages.append((datetime.now(EST) - ts).total_seconds() / 3600)
            except Exception:
                continue
        if ages:
            oldest_age = round(max(ages), 1)
    return {
        "pending":          len(pending),
        "oldest_age_hours": oldest_age,
        "by_requester":     by_requester,
    }


def get_sprint33_producer_health() -> dict:
    """v3.3 — Count 24h signal_contract envelopes per producer."""
    summary = {"by_producer": {}, "missing_producers": [], "total_24h": 0}
    contracts_dir = os.path.join(BOTS_DIR, "signal_contracts")
    if not os.path.exists(contracts_dir):
        summary["missing_producers"] = ["(signal_contracts dir missing)"]
        return summary
    
    cutoff = time.time() - 86400
    expected_producers = {"agent_scraper", "x_intel"}
    
    try:
        for fname in os.listdir(contracts_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(contracts_dir, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    continue
                with open(fpath, "r", encoding="utf-8") as f:
                    env = json.load(f)
                if not isinstance(env, dict):
                    continue
                src = env.get("source", {})
                producer = src.get("name", "unknown") if isinstance(src, dict) else "unknown"
                summary["by_producer"][producer] = summary["by_producer"].get(producer, 0) + 1
                summary["total_24h"] += 1
            except Exception:
                continue
    except Exception:
        pass
    
    active = set(summary["by_producer"].keys())
    summary["missing_producers"] = sorted(expected_producers - active)
    return summary


def get_anomaly_packets_24h() -> dict:
    """v3.3 — Count janitor_anomaly packets in last 24h."""
    counts = {"janitor": 0, "miner": 0, "examples": []}
    cutoff = time.time() - 86400
    
    for scan_dir in (INBOX, INBOX_DONE):
        if not os.path.exists(scan_dir):
            continue
        try:
            for fname in os.listdir(scan_dir):
                fpath = os.path.join(scan_dir, fname)
                try:
                    if os.path.getmtime(fpath) < cutoff:
                        continue
                except OSError:
                    continue
                if fname.startswith("janitor_anomaly_"):
                    counts["janitor"] += 1
                    if len(counts["examples"]) < 5:
                        counts["examples"].append(fname)
        except Exception:
            continue
    return counts


def get_bot_heartbeat_snapshot() -> dict:
    """v3.3 — Current ✅/⚠️/🔴 status per bot using configured thresholds."""
    cfg = load_config()
    thresholds = cfg.get("bot_heartbeat_thresholds_minutes", {})
    snapshot = {"alive": [], "stale": [], "offline": [], "no_heartbeat": []}
    now = time.time()
    
    for bot_name, threshold_min in thresholds.items():
        hb_path = _resolve_bot_heartbeat_path(bot_name)
        if not os.path.exists(hb_path):
            snapshot["no_heartbeat"].append(bot_name)
            continue
        try:
            age_min = (now - os.path.getmtime(hb_path)) / 60
        except OSError:
            snapshot["no_heartbeat"].append(bot_name)
            continue
        
        if age_min <= threshold_min:
            snapshot["alive"].append((bot_name, round(age_min, 1)))
        elif age_min <= threshold_min * 2:
            snapshot["stale"].append((bot_name, round(age_min, 1), threshold_min))
        else:
            snapshot["offline"].append((bot_name, round(age_min, 1), threshold_min))
    return snapshot


def build_daily_digest_content() -> str:
    findings_summary = get_24h_findings_summary()
    medic_summary = get_medic_24h_summary()
    integrity_log = load_json(INTEGRITY_LOG, [])
    cutoff = (datetime.now(EST) - timedelta(days=1)).isoformat()
    recent_integrity = [e for e in integrity_log if (e.get("timestamp") or "") > cutoff]
    attack_sum = get_attack_summary()
    
    # v3.3 Phase 5: Sprint 33+ visibility
    doctor_summary = get_doctor_24h_summary()
    code_tuner_queue = get_code_tuner_queue_depth()
    producer_health = get_sprint33_producer_health()
    anomaly_counts = get_anomaly_packets_24h()
    heartbeat_snapshot = get_bot_heartbeat_snapshot()

    fs = findings_summary
    ms = medic_summary

    sections = []

    # Header
    sections.append(
        f"## Warden 24h Digest — {datetime.now(EST).strftime('%Y-%m-%d')}\n\n"
        f"**Status snapshot**\n"
        f"- Lockdown active: {is_lockdown_active()}\n"
        f"- Kill switch active: {is_kill_switch_active()}\n"
        f"- Integrity baseline: {'present' if os.path.exists(HASH_BASELINE) else 'MISSING'}\n"
    )

    # === v3.4: operator changes — awareness, not alarm ===
    _op_changes = [e for e in recent_integrity if e.get("event") == "operator_change"]
    if _op_changes:
        _by_file = {}
        for e in _op_changes:
            _by_file.setdefault(os.path.basename(e.get("path", "?")), 0)
            _by_file[os.path.basename(e.get("path", "?"))] += 1
        sections.append(
            "\n### Operator changes (auto-rebaselined — no action needed)\n\n"
            + "\n".join(f"- `{f}` ({n}×)" for f, n in sorted(_by_file.items()))
            + "\nThese are the owner's workspace docs changing, which is the owner working. "
              "Read for awareness — sprint context often lives in these diffs. Only "
              "flag if a change here surprises BOTH of you.\n")
    
    # === v3.3 Phase 5 NEW: Bot Heartbeat Snapshot (first thing to know each morning) ===
    alive_count = len(heartbeat_snapshot["alive"])
    stale_count = len(heartbeat_snapshot["stale"])
    offline_count = len(heartbeat_snapshot["offline"])
    no_hb_count = len(heartbeat_snapshot["no_heartbeat"])
    
    hb_lines = []
    if offline_count:
        hb_lines.append("**🔴 OFFLINE:**")
        for name, age, threshold in heartbeat_snapshot["offline"]:
            hb_lines.append(f"  - `{name}`: {age/60:.1f}h stale (threshold {threshold/60:.1f}h)")
    if stale_count:
        hb_lines.append("**⚠️  STALE (1-2x threshold):**")
        for name, age, threshold in heartbeat_snapshot["stale"]:
            hb_lines.append(f"  - `{name}`: {age/60:.1f}h stale")
    if no_hb_count:
        hb_lines.append("**❓ NO HEARTBEAT FILE:**")
        hb_lines.append(f"  - {', '.join(heartbeat_snapshot['no_heartbeat'])}")
    if not hb_lines:
        hb_lines.append("All monitored bots within threshold ✅")
    
    sections.append(
        f"\n### Bot heartbeat snapshot (v3.3)\n\n"
        f"- Alive: {alive_count} | Stale: {stale_count} | Offline: {offline_count} | No HB: {no_hb_count}\n\n"
        + "\n".join(hb_lines) + "\n"
    )

    # Findings
    sev_lines = "\n".join(
        f"  - {sev}: {n}" for sev, n in fs["by_severity"].items() if n > 0
    ) or "  - none"
    cat_lines = "\n".join(
        f"  - {cat}: {n}" for cat, n in
        sorted(fs["by_category"].items(), key=lambda x: -x[1])[:8]
    ) or "  - none"

    sections.append(
        f"\n### Findings ({fs['total']} total)\n\n"
        f"**By severity:**\n{sev_lines}\n\n"
        f"**By category (top 8):**\n{cat_lines}\n"
    )

    # Medic
    sections.append(
        f"\n### Medic activity\n\n"
        f"- Total actions: {ms['total']}\n"
        f"- Heals succeeded: {ms['heals_succeeded']}\n"
        f"- Heals failed: {ms['heals_failed']}\n"
    )
    
    # === v3.3 Phase 5 NEW: Doctor activity ===
    doctor_outcome_lines = "\n".join(
        f"  - {outcome}: {n}" for outcome, n in doctor_summary["by_outcome"].items()
    ) or "  - (no investigations)"
    doctor_section = (
        f"\n### Doctor activity (v3.3)\n\n"
        f"- Total investigations: {doctor_summary['total']}\n"
        f"**By outcome:**\n{doctor_outcome_lines}\n"
    )
    if doctor_summary["samples"]:
        doctor_section += "\n**Recent samples:**\n"
        for s in doctor_summary["samples"][-3:]:
            doctor_section += (
                f"  - `{s.get('bot','?')}` ({s.get('symptom','?')}) → "
                f"{s.get('outcome','?')}: {s.get('diagnosis','?')[:80]}\n"
            )
    sections.append(doctor_section)
    
    # === v3.3 Phase 5 NEW: Code tuner queue depth ===
    queue_line = f"- Pending: {code_tuner_queue['pending']}"
    if code_tuner_queue.get("oldest_age_hours"):
        queue_line += f" (oldest: {code_tuner_queue['oldest_age_hours']}h old)"
    by_req = code_tuner_queue.get("by_requester", {})
    if by_req:
        req_lines = "\n".join(f"  - {req}: {n}" for req, n in by_req.items())
    else:
        req_lines = "  - (queue empty)"
    sections.append(
        f"\n### Code tuner queue (v3.3)\n\n"
        f"{queue_line}\n\n"
        f"**By requester:**\n{req_lines}\n"
    )
    
    # === v3.3 Phase 5 NEW: Sprint 33 producer health ===
    by_prod = producer_health.get("by_producer", {})
    if by_prod:
        prod_lines = "\n".join(f"  - {p}: {n} envelopes"
                                for p, n in sorted(by_prod.items(), key=lambda x: -x[1]))
    else:
        prod_lines = "  - (no envelopes in 24h)"
    missing = producer_health.get("missing_producers", [])
    missing_line = ""
    if missing:
        missing_line = f"\n**🔴 Silent producers (0 envelopes 24h):** {', '.join(missing)}\n"
    sections.append(
        f"\n### Sprint 33 producer health (v3.3)\n\n"
        f"- Total envelopes 24h: {producer_health['total_24h']}\n\n"
        f"**By producer:**\n{prod_lines}\n"
        f"{missing_line}"
    )
    
    # === v3.3 Phase 5 NEW: Infrastructure anomaly packets ===
    anomaly_section = (
        f"\n### Infrastructure anomaly packets (v3.3)\n\n"
        f"- janitor_anomaly: {anomaly_counts['janitor']}\n"
    )
    if anomaly_counts["examples"]:
        anomaly_section += (
            f"\n**Recent (last 5):**\n" +
            "\n".join(f"  - `{ex}`" for ex in anomaly_counts["examples"][-5:]) + "\n"
        )
    sections.append(anomaly_section)

    # Integrity
    if recent_integrity:
        sections.append(
            f"\n### Integrity\n\n"
            f"- Events in 24h: {len(recent_integrity)}\n"
            f"- Latest: {recent_integrity[-1].get('event', 'n/a')} on "
            f"`{os.path.basename(recent_integrity[-1].get('path',''))}`\n"
        )
    else:
        sections.append(
            f"\n### Integrity\n\n"
            f"- No events in 24h (clean)\n"
        )

    # Counter intel
    sections.append(
        f"\n### Counter-intel\n\n"
        f"- {attack_sum}\n"
    )

    # Critical findings detail
    crit_items = [
        f for f in fs["items"] if f.get("severity") in ("CRITICAL", "HIGH")
    ]
    if crit_items:
        crit_lines = "\n".join(
            f"- `{f.get('category','?')}` ({f.get('severity','?')}): {f.get('detail','?')[:100]}"
            for f in crit_items[-10:]
        )
        sections.append(
            f"\n### Critical/high findings (last 10)\n\n{crit_lines}\n"
        )

    # Proactive question (v3.3 updated)
    sections.append(
        f"\n### Proactive\n\n"
        f"Items worth the agent's attention this cycle:\n"
        f"1. Review any P1 inbox packets from warden + doctor in last 24h\n"
        f"2. If a producer is silent in the 'Sprint 33 producer health' section, check why\n"
        f"3. If code_tuner queue depth > 5 OR oldest > 48h, review pending requests\n"
        f"4. If doctor activity is high, consider investigating the underlying patterns\n"
        f"5. If integrity baseline drifted, refresh after legitimate changes\n"
        f"6. If medic heals failing repeatedly, doctor should already have escalated — check inbox\n"
    )

    return "".join(sections)


# ═══════════════════════════════════════════════════════════════════════════
# END LAYER 10
# ═══════════════════════════════════════════════════════════════════════════


async def daily_inbox_dispatcher():
    """
    Once per day at configured hour ET, write a P3 digest packet to the agent's inbox.
    Replaces v3.1's daily_summary_report Telegram-only mode.
    """
    print("[warden] daily inbox dispatcher active")
    cfg = load_config()
    target_hour = cfg.get("daily_digest_hour_est", 8)

    while True:
        try:
            now = datetime.now(EST)
            target = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            sleep_seconds = (target - now).total_seconds()
            await asyncio.sleep(sleep_seconds)

            await fire_daily_digest()

        except Exception as e:
            print(f"[warden] daily digest err: {e}")
            await asyncio.sleep(3600)


async def fire_daily_digest():
    """Build + write daily digest packet (also callable on demand via WARDEN DIGEST tg cmd)."""
    content = build_daily_digest_content()
    write_inbox_packet(
        priority="P3", source="warden_daily",
        slug=f"daily_digest_{datetime.now(EST).strftime('%Y%m%d')}",
        content=content,
    )
    # Also brief telegram
    summary = get_24h_findings_summary()
    msg = (
        f"🛡️ <b>Warden Daily Digest</b>\n"
        f"{datetime.now(EST).strftime('%Y-%m-%d')}\n\n"
        f"Findings (24h): {summary['total']}\n"
        f"Critical: {summary['by_severity'].get('CRITICAL', 0)} | "
        f"High: {summary['by_severity'].get('HIGH', 0)}\n"
        f"Lockdown: {'⛔' if is_lockdown_active() else '✅'} | "
        f"Kill: {'⛔' if is_kill_switch_active() else '✅'}\n\n"
        f"Full digest written to the agent inbox (P3)."
    )
    await notify(msg)


# Telegram command channel
TG_COMMAND_HANDLERS = {}  # populated below


# ═══════════════════════════════════════════════════════════════════════════
# BOOT SEQUENCE (from WARDEN-WINDOWS spec)
# ═══════════════════════════════════════════════════════════════════════════

async def boot_sequence() -> bool:
    """
    Run boot checks before starting other layers.
    Returns True if boot is OK to proceed, False if must halt.
    """
    print("=" * 60)
    print("[warden] BOOT SEQUENCE")
    print("=" * 60)

    # Step 1: lockdown check
    if is_lockdown_active():
        msg = ("⚠️ Warden booting INTO lockdown state. "
               "Critical layers active, but bots-that-honor-lockdown will halt writes. "
               "Send `WARDEN RESUME` from Telegram to lift.")
        print(f"[warden/boot] {msg}")
        await notify(msg)

    # Step 2: verify workspace exists
    if not os.path.isdir(WORKSPACE):
        msg = f"❌ Workspace missing: {WORKSPACE}"
        print(f"[warden/boot] {msg}")
        await notify(msg)
        return False

    if not os.path.isdir(BOT_LOGS):
        os.makedirs(BOT_LOGS, exist_ok=True)
        print(f"[warden/boot] created bot_logs dir")

    if not os.path.isdir(INBOX):
        os.makedirs(INBOX, exist_ok=True)
        print(f"[warden/boot] created inbox dir")

    # Step 3: load config (creates default if missing)
    cfg = load_config()
    print(f"[warden/boot] config loaded")

    # Step 4: integrity baseline check
    if not os.path.exists(HASH_BASELINE):
        print("[warden/boot] no integrity baseline — snapshotting now")
        integrity_baseline_snapshot()
    else:
        print("[warden/boot] integrity baseline present")

    # Step 5: quick integrity scan on critical files
    print("[warden/boot] running quick integrity check...")
    summary = await integrity_check_now()
    if summary.get("mismatches"):
        print(f"[warden/boot] ⚠️ {len(summary['mismatches'])} files mismatch baseline")
        # Don't halt — just alert. Sprint chops mean baseline will commonly drift.
    else:
        print(f"[warden/boot] integrity nominal: {summary.get('matches',0)}/{summary.get('checked',0)}")

    # Step 6: kill switch check
    if is_kill_switch_active():
        print("[warden/boot] ℹ️ KILL_SWITCH.flag exists — manual flag, individual bots may check")

    # Step 7: log boot complete
    log_finding("boot", "INFO", "warden boot sequence complete", "")
    print("[warden/boot] boot complete — starting layers")
    print("=" * 60)
    return True


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


async def inbox_cron_lock_reaper():
    """Sprint 65 — reaps a stale inbox_cron.lock so the owner doesn't have to remove it by
    hand. The inbox cron writes bot_logs/inbox_cron.lock at pass start and deletes it at
    pass end; if a pass dies before that delete (crash, timeout, context cut), the lock
    goes stale and blocks every future pass. We delete a lock older than
    INBOX_CRON_LOCK_MAX_AGE_S (15 min — above the cron's own 12-min guard, so a pass
    that's legitimately still running is never killed).

    Age is taken from the file MTIME, not its contents — we don't parse or trust the
    lock body, just how long it's sat there. Never touches a fresh lock."""
    print(f"[warden] inbox_cron lock reaper active (reaps locks > {INBOX_CRON_LOCK_MAX_AGE_S//60}min)")
    while True:
        try:
            if os.path.exists(INBOX_CRON_LOCK_FILE):
                age = time.time() - os.path.getmtime(INBOX_CRON_LOCK_FILE)
                if age > INBOX_CRON_LOCK_MAX_AGE_S:
                    try:
                        os.remove(INBOX_CRON_LOCK_FILE)
                        msg = (f"reaped stale inbox_cron.lock (age {int(age/60)}min > "
                               f"{INBOX_CRON_LOCK_MAX_AGE_S//60}min) — a prior inbox pass died "
                               "before releasing it; next cron fire can now run")
                        print(f"[warden] {msg}")
                        log_finding("inbox_cron", "info", msg,
                                    remediation="stale lock removed automatically")
                        await notify(f"🧹 warden: {msg}")
                    except FileNotFoundError:
                        pass  # cron released it between our check and remove — fine
                    except Exception as e:
                        print(f"[warden] lock reaper remove err: {e}")
        except Exception as e:
            print(f"[warden] lock reaper err: {e}")
        await asyncio.sleep(INBOX_CRON_LOCK_CHECK_S)


# ============================================================================
#   LIVE-UPDATE (element e, simple-bot clean core)
# ============================================================================
# Poll THIS file's mtime; on an on-disk change, re-exec this warden only (os.execv,
# same PID + terminal) so the patch goes live without a manual restart and warden
# stays in the terminal the owner launched it from. No browser/external process to tear
# down; Ctrl-C works normally. Floor: only reload a change already on disk (the owner
# The agent patches in place); never fetch, self-modify, or reload any other bot.
import sys as _lu_sys
import shutil as _lu_shutil
import hashlib as _lu_hashlib

_LU_BOT      = "security_warden"
_LU_SELF     = os.path.abspath(__file__)
_LU_MARKER   = os.path.join(BOT_LOGS, f"{_LU_BOT}_reload.json")
_LU_LASTGOOD = _LU_SELF + ".last-good"
_LU_POLL_S   = 30


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
        os.makedirs(INBOX, exist_ok=True)
        ts = datetime.now(EST).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(INBOX, f"{_LU_BOT} - {kind}_{ts}.md")
        fm = {"kind": kind, "severity": severity, "dedupe_key": f"{_LU_BOT}:{kind}",
              "source_skill": _LU_BOT, "summary": summary}
        lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["---", "",
                 f"# {_LU_BOT} {kind}", summary]
        if extra:
            lines += ["", "```json", json.dumps(extra, indent=2, default=str), "```"]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[warden] live-update report failed: {e}")


def _lu_on_boot():
    marker = load_json(_LU_MARKER, None)
    if isinstance(marker, dict):
        _lu_write_report("bot_restart", "info",
                         f"{_LU_BOT} reloaded {marker.get('from_hash')} -> {marker.get('to_hash')} (live-update, healthy)",
                         marker)
        try:
            os.remove(_LU_MARKER)
        except Exception:
            pass
    _lu_snapshot_last_good()


def _lu_reload_now():
    new_hash = _lu_hash(_LU_SELF)
    _lu_snapshot_last_good()
    save_json(_LU_MARKER, {"from_hash": _LU_BOOT_HASH, "to_hash": new_hash,
                           "detected_at": datetime.now(EST).isoformat(), "lastgood": _LU_LASTGOOD})
    print(f"[warden] live-update: reloading {_LU_BOOT_HASH} -> {new_hash} (re-exec in place)")
    try:
        os.execv(_lu_sys.executable, [_lu_sys.executable, _LU_SELF] + _lu_sys.argv[1:])
    except Exception as e:
        print(f"[warden] live-update: os.execv failed, staying on current code: {e}")
        _lu_write_report("bot_restart_failed", "high",
                         f"{_LU_BOT} patch {new_hash} detected but re-exec failed; STILL RUNNING old {_LU_BOOT_HASH}",
                         {"error": str(e)[:200]})
        try:
            os.remove(_LU_MARKER)
        except Exception:
            pass


async def live_update_watcher_loop():
    print(f"[warden] live_update_watcher: online (poll {_LU_POLL_S}s, boot {_LU_BOOT_HASH})")
    while True:
        try:
            if _lu_mtime(_LU_SELF) > _LU_BOOT_MTIME and _lu_hash(_LU_SELF) != _LU_BOOT_HASH:
                _lu_reload_now()  # os.execv does not return on success
        except Exception as e:
            print(f"[warden] live_update_watcher err: {e}")
        await asyncio.sleep(_LU_POLL_S)


async def main():
    print()
    print("=" * 60)
    print("[warden] 🛡️  Security Warden — Sniper ecosystem guard")
    print("=" * 60)
    print(f"[warden] inference:    {XAI_MODEL} (primary) → {OLLAMA_MODEL} (fallback)")
    print(f"[warden] config:       {CONFIG_FILE}")
    print(f"[warden] quarantine:   {QUARANTINE_DIR}")
    print(f"[warden] kill switch:  {KILL_SWITCH_FILE} (MANUAL ONLY)")
    print(f"[warden] lockdown:     {LOCKDOWN_FILE}")
    print(f"[warden] medic:        staging={MEDIC_STAGING}, backups={MEDIC_BACKUPS}")
    print(f"[warden] integrity:    baseline={HASH_BASELINE}")
    print(f"[warden] inbox:        {INBOX}")
    print(f"[warden] approval watcher: DISABLED (flags do not copy into bots)")
    print("[warden] mode:         OBSERVE + medic report/backup (no auto-repair)")
    print("=" * 60)

    cfg = load_config()
    _mv, _ms = meme_buy_bound(cfg)
    print(f"[warden] bounds: meme={_mv} SOL (from {_ms}; alert above 5x)")

    # Run boot sequence
    boot_ok = await boot_sequence()
    if not boot_ok:
        print("[warden] boot failed — halting")
        return

    _lu_on_boot()  # live-update: report a completed reload + snapshot last-good

    # Start all layers concurrently
    await asyncio.gather(
        # live-update watcher (element e, simple-bot core)
        live_update_watcher_loop(),
        # Layer 1
        ingress_guardian(),
        # Layer 2
        egress_validator(),
        # Layer 3
        canary_monitor(),
        wallet_anomaly_watcher(),
        dead_mans_switch(),
        api_health_monitor(),
        # v3.3 NEW: Layer 3d-bis (heartbeat-based liveness) + 3e (silent failure)
        bot_heartbeat_monitor(),
        sniper_watch_monitor(),
        silent_failure_monitor(),
        exec_failure_rate_monitor(),
        # Layer 5
        # Layer 6
        medic_process_monitor(),
        # v3.3 NEW: Layer 6b (doctor)
        doctor_monitor(),
        # Layer 7
        integrity_monitor(),
        # Layer 8
        daily_inbox_dispatcher(),
        # Sprint 65: reap stale inbox_cron.lock so the owner doesn't remove it by hand
        inbox_cron_lock_reaper(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[warden] shutdown via KeyboardInterrupt")
