"""agent_scraper.py — Sprint 43 / Phases 1-5 + Cadence wire-in shipped
Fast deterministic Playwright scraping for known structures.

(Public build: history trimmed; see TIMELINE.md.)
"""
from __future__ import annotations

import json
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

import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# v1.1.0 live-update + boot orphan guard
import hashlib as _lu_hashlib
import shutil as _lu_shutil
import subprocess as _lu_subprocess


# ── paths ─────────────────────────────────────────────────────────────────────
_BASE = Path(WS_BOTS)
JSON_RELAY = Path(WS_JSON_RELAY)
BOT_LOGS = Path(WS_BOT_LOGS)
TASK_FILE = JSON_RELAY / "scraper_task.json"
RESPONSE_FILE = JSON_RELAY / "agent_scraper_response.json"


def _response_channel_for(task: dict):
    """Pick the response file. All scrapes go to the shared scraper channel."""
    return RESPONSE_FILE
# Sprint 44: completed scrapes are archived here for keeping (good data). Lives under
# the done folder, scrapes subfolder so it doesn't flood inbox task results.
SCRAPE_DONE_DIR = _BASE.parent / "inbox_results" / "done" / "scrapes"
HEARTBEAT_FILE = BOT_LOGS / "agent_scraper_heartbeat.json"
_PAUSE_FILE = BOT_LOGS / "agent_scraper_pause.flag"   # console X sign-in; see main_loop
SCRAPE_LOG = BOT_LOGS / "scraper.log"

JSON_RELAY.mkdir(parents=True, exist_ok=True)
BOT_LOGS.mkdir(parents=True, exist_ok=True)
SCRAPE_DONE_DIR.mkdir(parents=True, exist_ok=True)


APPEARANCE_CACHE_FILE = BOT_LOGS / "scraper_appearance_cache.json"

# Per-scrape-type minimum persistence count for envelope emission.
# Items below this floor don't emit (suppressed as noise).
# Tuned per scrape type because pump_recent is noisier than dex_solana_top
# is noisier than x_trending.
PHASE1_PERSISTENCE_MIN_EMIT = {
    "x_trending":     2,   # trends churn fast, 2-scan persistence already meaningful
    "dex_solana_top": 3,   # tokens dropping in and out is common, need 3 scans
    "pump_recent":    3,   # most pump.fun launches rug in <1 scan; survivors matter
}

# Persistence at which severity gets bumped UP one tier
# (e.g. "medium" → "high" when an item has been around 4+ scans)
PHASE1_PERSISTENCE_BUMP_SEVERITY = {
    "x_trending":     4,
    "dex_solana_top": 5,
    "pump_recent":    4,
}

# Cap appearance count — no point counting beyond this, prevents counter overflow
PHASE1_PERSISTENCE_CAP = 20

# How long an item is "missing" before its appearance count resets to 0.
# If we don't see it for this many consecutive scans, the streak breaks.
# Default 1 = strict consecutive (any miss resets). Could allow short gaps
# by setting to 2-3, but Phase 1 keeps it strict.
PHASE1_GAP_TOLERANCE = 1


def _phase1_load_appearance_cache() -> dict:
    """Load the persistence cache. Returns {} on missing/corrupt."""
    try:
        if APPEARANCE_CACHE_FILE.exists():
            with open(APPEARANCE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as e:
        print(f"[scraper][phase1] appearance cache load err: {e}")
    return {}


def _phase1_save_appearance_cache(cache: dict) -> None:
    """Atomic save."""
    try:
        APPEARANCE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(APPEARANCE_CACHE_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=str)
        os.replace(tmp, str(APPEARANCE_CACHE_FILE))
    except Exception as e:
        print(f"[scraper][phase1] appearance cache save err: {e}")


def _phase1_extract_item_key(scrape_type: str, item: dict) -> str | None:
    """Get a stable identifier for an item so we can track it across scans.
    
    x_trending uses trend_name (or "name" / "topic" fallbacks).
    dex_solana_top uses contract address (CA) primarily, falls back to symbol.
    pump_recent uses CA primarily, falls back to symbol.
    
    Returns None when we can't identify the item — those don't get tracked.
    """
    if not isinstance(item, dict):
        return None
    
    if scrape_type == "x_trending":
        for k in ("trend_name", "name", "topic", "hashtag"):
            v = item.get(k)
            if v:
                return str(v).strip().lower()
        return None
    
    if scrape_type in ("dex_solana_top", "pump_recent"):
        ca = item.get("ca") or item.get("contract") or item.get("address")
        if ca:
            return str(ca).strip().lower()
        # Symbol fallback — less reliable (collisions possible) but better than nothing
        sym = item.get("symbol") or item.get("token") or item.get("ticker")
        if sym:
            return f"sym:{str(sym).strip().lower()}"
        return None
    
    return None


def _phase1_update_appearance_cache(scrape_type: str, items: list) -> list:
    """Update the appearance cache for this scrape type with current scan's items.
    
    Items present this scan → count incremented (capped).
    Items absent this scan but had count > 0 → count decremented by 1 (gap
        tolerance). When count hits 0, entry removed.
    
    Returns the items list ANNOTATED with `_appearance_count` field on each
    item (the post-update count). Caller uses this for filtering + severity.
    
    The annotation uses underscore prefix to clearly distinguish Phase 1
    metadata from native scrape fields.
    """
    if scrape_type not in PHASE1_PERSISTENCE_MIN_EMIT:
        # Not a tracked scrape type — pass through unchanged with annotation=1
        for item in items:
            if isinstance(item, dict):
                item["_appearance_count"] = 1
        return items
    
    cache = _phase1_load_appearance_cache()
    scrape_cache = cache.setdefault(scrape_type, {})
    
    # Build set of keys present in current scan
    current_keys = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _phase1_extract_item_key(scrape_type, item)
        if key:
            current_keys.add(key)
    
    now_iso = _now_iso()
    
    # Increment counts for items present this scan
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _phase1_extract_item_key(scrape_type, item)
        if not key:
            item["_appearance_count"] = 1
            continue
        
        existing = scrape_cache.get(key, {})
        new_count = min(existing.get("count", 0) + 1, PHASE1_PERSISTENCE_CAP)
        scrape_cache[key] = {
            "count":          new_count,
            "last_seen_at":   now_iso,
            "first_seen_at":  existing.get("first_seen_at", now_iso),
        }
        item["_appearance_count"] = new_count
    
    # Decrement counts for items NOT present this scan (gap tolerance)
    missing_keys = [k for k in scrape_cache.keys() if k not in current_keys]
    for k in missing_keys:
        entry = scrape_cache[k]
        entry["count"] = entry.get("count", 0) - PHASE1_GAP_TOLERANCE
        if entry["count"] <= 0:
            del scrape_cache[k]
    
    _phase1_save_appearance_cache(cache)
    return items


def _phase1_filter_to_persistent(scrape_type: str, items: list) -> list:
    """Filter items to those meeting the minimum persistence floor for emission.
    
    Items below the floor are not removed from the scrape RESULT (the agent/UI
    still sees them) — but they are filtered out of the SIGNAL ENVELOPE
    payload so they don't pollute downstream readers. Caller uses this filtered
    list when computing severity + writing envelopes.
    """
    if scrape_type not in PHASE1_PERSISTENCE_MIN_EMIT:
        return items
    floor = PHASE1_PERSISTENCE_MIN_EMIT[scrape_type]
    return [
        item for item in items
        if isinstance(item, dict) and item.get("_appearance_count", 1) >= floor
    ]


def _phase1_compute_severity_bump(scrape_type: str, items: list) -> int:
    """Return the number of severity tiers to bump UP based on max
    persistence depth in the result set.
    
    0 = no bump (default)
    1 = bump one tier (low→medium, medium→high, high→critical)
    """
    if scrape_type not in PHASE1_PERSISTENCE_BUMP_SEVERITY:
        return 0
    threshold = PHASE1_PERSISTENCE_BUMP_SEVERITY[scrape_type]
    max_persistence = max(
        (item.get("_appearance_count", 1) for item in items if isinstance(item, dict)),
        default=1
    )
    return 1 if max_persistence >= threshold else 0


def _phase1_apply_severity_bump(severity: str, bump: int) -> str:
    """Apply persistence-based severity bump."""
    if bump <= 0:
        return severity
    tiers = ["low", "medium", "high", "critical"]
    try:
        idx = tiers.index(severity)
    except ValueError:
        return severity
    new_idx = min(idx + bump, len(tiers) - 1)
    return tiers[new_idx]


# ════════════════════════════════════════════════════════════════════════════
# END Phase 1 insertion
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
# PHASE 2: CROSS-SOURCE CONFLUENCE
# ════════════════════════════════════════════════════════════════════════════
# Track recent observations per scrape type. When a symbol is observed in
# 2+ scrape types within the recency window, emit a confluence envelope.

CONFLUENCE_CACHE_FILE = BOT_LOGS / "scraper_confluence_cache.json"
PHASE2_CONFLUENCE_WINDOW_MINUTES = 60   # observations within 60min count toward confluence
PHASE2_CONFLUENCE_MIN_SOURCES = 2       # 2+ sources = confluence emit


def _phase2_load_confluence_cache() -> dict:
    """Persistent cache: {scrape_type: {symbol: last_seen_iso}}.
    Stale entries (older than window) get pruned on each update."""
    try:
        if CONFLUENCE_CACHE_FILE.exists():
            with open(CONFLUENCE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as e:
        print(f"[scraper][phase2] confluence cache load err: {e}")
    return {}


def _phase2_save_confluence_cache(cache: dict) -> None:
    try:
        CONFLUENCE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(CONFLUENCE_CACHE_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=str)
        os.replace(tmp, str(CONFLUENCE_CACHE_FILE))
    except Exception as e:
        print(f"[scraper][phase2] confluence cache save err: {e}")


def _phase2_prune_stale(cache: dict) -> dict:
    """Remove observations older than the confluence window."""
    cutoff = datetime.now() - timedelta(minutes=PHASE2_CONFLUENCE_WINDOW_MINUTES)
    pruned = {}
    for scrape_type, symbols in cache.items():
        pruned[scrape_type] = {}
        for sym, last_seen_str in symbols.items():
            try:
                last_seen = datetime.fromisoformat(last_seen_str)
                if last_seen > cutoff:
                    pruned[scrape_type][sym] = last_seen_str
            except (ValueError, TypeError):
                # Keep entries we can't parse rather than blow them away
                pruned[scrape_type][sym] = last_seen_str
    return pruned


_SYMBOL_SHAPE_RE = re.compile(r"^[a-z0-9]{2,20}$")


def _phase2_is_valid_symbol(sym: str | None) -> bool:
    """True only when sym looks like a real ticker (alphanumeric, 2-20 chars).
    Spaces, '·', and multi-word phrases fail."""
    return bool(sym and _SYMBOL_SHAPE_RE.match(sym))


def _phase2_extract_symbol_from_item(scrape_type: str, item: dict) -> str | None:
    """Normalize symbol identifier across scrape types. Returns lowercase
    string or None when an item has no extractable symbol."""
    if not isinstance(item, dict):
        return None
    
    if scrape_type == "x_trending":
        raw = (item.get("trend_name") or item.get("name") or "").strip()
        if not raw.startswith("$"):
            return None
        sym = raw[1:].strip().lower()
        return sym if _phase2_is_valid_symbol(sym) else None
    
    if scrape_type in ("dex_solana_top", "pump_recent"):
        # DEX/pump use symbol primarily, CA as fallback
        sym = item.get("symbol") or item.get("token") or item.get("ticker")
        if sym:
            return str(sym).lstrip("$").strip().lower()
        ca = item.get("ca") or item.get("contract") or item.get("address")
        if ca:
            return str(ca).lower()
    
    return None


def _phase2_update_confluence_cache(scrape_type: str, items: list) -> dict:
    """Add this scan's symbols to the confluence cache. Returns
    {symbol: [scrape_type, ...]} — symbols seen in 2+ scrape types."""
    cache = _phase2_load_confluence_cache()
    cache = _phase2_prune_stale(cache)
    
    type_cache = cache.setdefault(scrape_type, {})
    now_iso = _now_iso()
    
    for item in items:
        sym = _phase2_extract_symbol_from_item(scrape_type, item)
        if sym:
            type_cache[sym] = now_iso
    
    _phase2_save_confluence_cache(cache)
    
    # Build symbol → sources map for confluence detection
    symbol_sources = {}
    for stype, symbols in cache.items():
        for sym in symbols:
            symbol_sources.setdefault(sym, set()).add(stype)
    
    # Filter to symbols with 2+ sources
    confluent = {
        sym: sorted(sources) for sym, sources in symbol_sources.items()
        if len(sources) >= PHASE2_CONFLUENCE_MIN_SOURCES
    }
    return confluent


def _phase2_emit_confluence_envelopes(scrape_type: str, confluent: dict) -> int:
    """Emit a `cross_source_confluence` envelope for each newly-confluent symbol.
    
    Anti-dupe: cache tracks `_last_confluence_emit` per symbol so we don't
    re-emit on every scan when the same confluence persists.
    """
    if not confluent:
        return 0
    
    emit_cache = _phase2_load_confluence_cache()
    emit_meta = emit_cache.setdefault("_emit_meta", {})
    
    emit_count = 0
    now_iso = _now_iso()
    cutoff = (datetime.now() - timedelta(minutes=PHASE2_CONFLUENCE_WINDOW_MINUTES)).isoformat()
    
    for sym, sources in confluent.items():
        # Skip re-emit if we already emitted for this symbol within the window
        last_emit = emit_meta.get(sym, "")
        if last_emit and last_emit > cutoff:
            continue
        
        try:
            SIGNAL_CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
            env_id = f"agent_scraper_confluence_{int(time.time())}_{_signal_secrets.token_hex(3)}"
            emitted_at = datetime.now(_signal_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            # Confluence envelopes live longer — 12h
            expires_at = (datetime.now(_signal_tz.utc) + _signal_timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            severity = "high" if len(sources) >= 3 else "medium"
            
            envelope = {
                "_schema":    SIGNAL_CONTRACT_SCHEMA,
                "id":         env_id,
                "emitted_at": emitted_at,
                "expires_at": expires_at,
                "source": {
                    "name":    "agent_scraper",
                    "tier":    "B",   # scraped data baseline tier (still has manipulation risk)
                    "version": "v1.0+sprint43_phase2",
                },
                "signal_type":     "cross_source_confluence",
                "severity":        severity,
                "phase_relevance": None,
                "decay": {
                    "half_life_hours": 3,
                    "shape":           "exponential",
                },
                "confluence_with": [],
                "payload": {
                    "headline": f"[scraper:confluence] '${sym}' observed in {len(sources)} sources: {', '.join(sources)}",
                    "details":  (f"Symbol '{sym}' appeared in {len(sources)} different scraper sources "
                                 f"within {PHASE2_CONFLUENCE_WINDOW_MINUTES}min window. Sources: {', '.join(sources)}. "
                                 f"Cross-source presence = real flow, not single-source noise."),
                    "raw": {
                        "symbol":           sym,
                        "sources":          sources,
                        "source_count":     len(sources),
                        "window_minutes":   PHASE2_CONFLUENCE_WINDOW_MINUTES,
                        "triggered_by_scrape": scrape_type,
                        "timestamp":        now_iso,
                    },
                },
            }
            
            final_path = SIGNAL_CONTRACTS_DIR / f"{env_id}.json"
            tmp_path = SIGNAL_CONTRACTS_DIR / f"{env_id}.json.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(envelope, f, indent=2, default=str)
            os.replace(str(tmp_path), str(final_path))
            
            emit_meta[sym] = now_iso
            emit_count += 1
            _log(f"[signal][phase2] confluence emit: ${sym} ({len(sources)} sources)")
        except Exception as e:
            _log(f"[signal][phase2] confluence emit err for ${sym}: {e}")
    
    if emit_count > 0:
        emit_cache["_emit_meta"] = emit_meta
        _phase2_save_confluence_cache(emit_cache)
    
    return emit_count


# ════════════════════════════════════════════════════════════════════════════
# END Phase 2 insertion
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
# PHASE 3: PUMP.FUN RUG FILTERING
# ════════════════════════════════════════════════════════════════════════════
PUMP_FOLLOWUP_CACHE_FILE = BOT_LOGS / "scraper_pump_followup_cache.json"
PHASE3_PUMP_FOLLOWUP_WINDOW_HOURS = 2  # launch must show in dex_solana_top within 2h


def _phase3_load_pump_cache() -> dict:
    """Cache shape: {symbol_or_ca: {first_pump_seen_at, dex_followup_at}}"""
    try:
        if PUMP_FOLLOWUP_CACHE_FILE.exists():
            with open(PUMP_FOLLOWUP_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as e:
        print(f"[scraper][phase3] pump cache load err: {e}")
    return {}


def _phase3_save_pump_cache(cache: dict) -> None:
    try:
        PUMP_FOLLOWUP_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(PUMP_FOLLOWUP_CACHE_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=str)
        os.replace(tmp, str(PUMP_FOLLOWUP_CACHE_FILE))
    except Exception as e:
        print(f"[scraper][phase3] pump cache save err: {e}")


def _phase3_record_pump_launches(items: list) -> None:
    """When pump_recent scrape happens, record each launch's symbol/CA."""
    cache = _phase3_load_pump_cache()
    now_iso = _now_iso()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _phase1_extract_item_key("pump_recent", item)
        if not key:
            continue
        if key not in cache:
            cache[key] = {"first_pump_seen_at": now_iso, "dex_followup_at": None}
    _phase3_save_pump_cache(cache)


def _phase3_record_dex_followup(items: list) -> None:
    """When dex_solana_top scrape happens, check if any of these tokens
    were previously seen in pump_recent. If so, mark dex_followup_at — 
    they cleared rug filter."""
    cache = _phase3_load_pump_cache()
    now_iso = _now_iso()
    updated = False
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _phase1_extract_item_key("dex_solana_top", item)
        if not key:
            continue
        if key in cache and not cache[key].get("dex_followup_at"):
            cache[key]["dex_followup_at"] = now_iso
            updated = True
    if updated:
        _phase3_save_pump_cache(cache)


def _phase3_should_suppress_pump_item(item: dict) -> bool:
    """For pump_recent emit: suppress if this launch hasn't received DEX
    follow-up within the rug window AND was first seen long enough ago."""
    if not isinstance(item, dict):
        return False
    key = _phase1_extract_item_key("pump_recent", item)
    if not key:
        return False
    cache = _phase3_load_pump_cache()
    entry = cache.get(key)
    if not entry:
        # Not yet recorded — record on this pass, don't suppress yet
        return False
    
    first_seen_str = entry.get("first_pump_seen_at")
    if not first_seen_str:
        return False
    try:
        first_seen = datetime.fromisoformat(first_seen_str)
    except (ValueError, TypeError):
        return False
    
    age = datetime.now() - first_seen
    # Within the window, give it a chance to get DEX follow-up
    if age < timedelta(hours=PHASE3_PUMP_FOLLOWUP_WINDOW_HOURS):
        return False
    
    # Past the window, suppress unless DEX followed up
    return not entry.get("dex_followup_at")


# ════════════════════════════════════════════════════════════════════════════
# PHASE 4: AGENT-INBOX FALLBACK FOR UNKNOWN SYMBOLS
# ════════════════════════════════════════════════════════════════════════════
# Tracked keyword list — symbols we already know about. Symbols persistent
# enough to pass Phase 1 but NOT in this list are "unknown persistent" and
# get queued for the agent.

_PHASE4_KNOWN_SYMBOLS = {
    # Major crypto
    "btc", "bitcoin", "eth", "ethereum", "sol", "solana", "doge", "shib",
    "jup", "jupiter", "wif", "bonk", "popcat", "trump", "pengu", "fartcoin",
    # Common L2 / DeFi
    "arb", "op", "matic", "uni", "aave", "link", "avax",
    # Common stables (worth tracking depeg events)
    "usdt", "usdc", "dai",
}

AGENT_SCRAPER_INBOX_DIR = os.path.join(WS_ROOT, "inbox")
AGENT_SCRAPER_REPLY_FILE = os.path.join(WS_JSON_RELAY, "agent_scraper_unknown_response.json")
PHASE4_UNKNOWN_ASKS_CACHE_FILE = str(BOT_LOGS / "scraper_unknown_asks_cache.json")
PHASE4_UNKNOWN_STALE_DAYS = 7

_PHASE4_ASK_AGENT_QUEUE = []


def _phase4_load_asks_cache() -> dict:
    try:
        if os.path.exists(PHASE4_UNKNOWN_ASKS_CACHE_FILE):
            with open(PHASE4_UNKNOWN_ASKS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as e:
        print(f"[scraper][phase4] asks cache load err: {e}")
    return {}


def _phase4_save_asks_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(PHASE4_UNKNOWN_ASKS_CACHE_FILE), exist_ok=True)
        tmp = PHASE4_UNKNOWN_ASKS_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=str)
        os.replace(tmp, PHASE4_UNKNOWN_ASKS_CACHE_FILE)
    except Exception as e:
        print(f"[scraper][phase4] asks cache save err: {e}")


def _phase4_absorb_agent_unknown_response() -> int:
    """NON-BLOCKING. Read the agent's reply, update known-symbol cache,
    delete reply file. Returns count absorbed."""
    if not os.path.exists(AGENT_SCRAPER_REPLY_FILE):
        return 0
    try:
        with open(AGENT_SCRAPER_REPLY_FILE, "r", encoding="utf-8-sig") as f:
            raw = f.read().strip()
        if not raw:
            return 0
        reply = json.loads(raw)
    except Exception as e:
        print(f"[scraper][phase4] reply read err: {e}")
        return 0
    
    interpretations = reply.get("symbols", []) or []
    if not interpretations:
        try: os.remove(AGENT_SCRAPER_REPLY_FILE)
        except Exception: pass
        return 0
    
    cache = _phase4_load_asks_cache()
    absorbed = 0
    for entry in interpretations:
        sym = (entry.get("symbol") or "").lower().strip()
        if not sym:
            continue
        cache[sym] = {
            "should_track":   bool(entry.get("should_track", False)),
            "what_is_it":     entry.get("what_is_it", ""),
            "interpreted_at": datetime.now().isoformat(),
        }
        absorbed += 1
    _phase4_save_asks_cache(cache)
    try: os.remove(AGENT_SCRAPER_REPLY_FILE)
    except Exception: pass
    if absorbed > 0:
        print(f"[scraper][phase4] absorbed {absorbed} the agent symbol interpretations")
    return absorbed


def _phase4_already_asked(symbol: str) -> bool:
    """Check if the agent already ruled on this symbol (or if asked recently)."""
    cache = _phase4_load_asks_cache()
    entry = cache.get(symbol.lower())
    if not entry:
        return False
    # Check stale
    asked_at = entry.get("interpreted_at")
    if asked_at:
        try:
            asked_dt = datetime.fromisoformat(asked_at)
            if (datetime.now() - asked_dt).days > PHASE4_UNKNOWN_STALE_DAYS:
                return False  # stale, can re-ask
        except (ValueError, TypeError):
            pass
    return True


def _phase4_queue_unknown_ask(symbol: str, scrape_type: str, appearance_count: int,
                              example_item: dict) -> None:
    """Queue an unknown persistent symbol for batched agent-ask."""
    global _PHASE4_ASK_AGENT_QUEUE
    _PHASE4_ASK_AGENT_QUEUE.append({
        "symbol":            symbol,
        "scrape_type":       scrape_type,
        "appearance_count":  appearance_count,
        "example_item":      {
            k: v for k, v in (example_item or {}).items()
            if k in ("symbol", "ca", "name", "price", "volume_24h", "mcap", "url")
        },
    })


def _phase4_flush_unknown_queue() -> int:
    """Write ONE inbox packet with all queued unknown symbols.
    Per Sprint 43 naming: `<bot> - <subject>_<ts>.<ext>`."""
    global _PHASE4_ASK_AGENT_QUEUE
    if not _PHASE4_ASK_AGENT_QUEUE:
        return 0
    
    asks = _PHASE4_ASK_AGENT_QUEUE
    _PHASE4_ASK_AGENT_QUEUE = []
    
    # Dedupe in case same symbol queued from multiple scrape types this scan
    seen_syms = set()
    deduped = []
    for ask in asks:
        if ask["symbol"] in seen_syms:
            continue
        seen_syms.add(ask["symbol"])
        # Mark as asked in cache to prevent re-asking next scan
        cache = _phase4_load_asks_cache()
        cache[ask["symbol"]] = {
            "should_track":   None,  # awaiting the agent
            "what_is_it":     "awaiting_agent",
            "interpreted_at": datetime.now().isoformat(),
        }
        _phase4_save_asks_cache(cache)
        deduped.append(ask)
    
    if not deduped:
        return 0
    
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    fname = f"agent_scraper - unknown_symbol_request_{ts}.md"
    inbox_path = os.path.join(AGENT_SCRAPER_INBOX_DIR, fname)
    
    lines = [
        "---",
        f"packet_id: unknown_symbol_request_{ts}",
        "packet_type: unknown_symbol_request",
        "emitted_by: agent_scraper",
        f"fired_at: {datetime.now().isoformat()}",
        f"symbol_count: {len(deduped)}",
        "---",
        "",
        f"# Unknown Symbol Request — {len(deduped)} persistent symbol(s)",
        "",
        "These symbols have appeared in scrapes across multiple consecutive",
        "scans (passed Phase 1 persistence floor) but are NOT in the tracked",
        "known-symbol list. Please tell me what they are and whether to track.",
        "",
        "## Symbols",
        "",
    ]
    
    for i, ask in enumerate(deduped, 1):
        lines.extend([
            f"### Symbol {i}: `${ask['symbol']}`",
            "",
            f"- **Scrape type:** {ask['scrape_type']}",
            f"- **Appearance count:** {ask['appearance_count']} consecutive scans",
            f"- **Example item:** `{json.dumps(ask['example_item'], default=str)[:200]}`",
            "",
        ])
    
    lines.extend([
        "## Response schema",
        "",
        "Write to: `bots/json_relay/agent_scraper_unknown_response.json`",
        "",
        "```json",
        "{",
        f'  \"packet_id\": \"unknown_symbol_request_{ts}\",',
        '  \"symbols\": [',
        "    {",
        '      \"symbol\": \"<lowercase symbol>\",',
        '      \"should_track\": true | false,',
        '      \"what_is_it\": \"<one-line description>\"',
        "    }",
        "  ]",
        "}",
        "```",
        "",
        "Non-blocking: scraper keeps running. Your reply lands when it lands.",
    ])
    
    body = "\\n".join(lines)
    
    try:
        os.makedirs(AGENT_SCRAPER_INBOX_DIR, exist_ok=True)
        tmp = inbox_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, inbox_path)
        _log(f"[signal][phase4] asked the agent about {len(deduped)} unknown symbol(s)")
        return len(deduped)
    except Exception as e:
        _log(f"[signal][phase4] unknown_symbol_request write err: {e}")
        return 0


# ════════════════════════════════════════════════════════════════════════════
# PHASE 5: SUSTAINED ANOMALY ENVELOPES
# ════════════════════════════════════════════════════════════════════════════
ANOMALY_HISTORY_FILE = BOT_LOGS / "scraper_anomaly_history.json"
PHASE5_ANOMALY_WINDOW_SCANS = 4
PHASE5_ANOMALY_EMIT_THRESHOLD = 4  # 4 consecutive anomaly scans = sustained
PHASE5_ANOMALY_CAP = 20


def _phase5_load_anomaly_history() -> dict:
    """Shape: {scrape_type: {anomaly_count: int, last_anomaly_at: iso,
                              first_anomaly_at: iso, emitted_at: iso}}"""
    try:
        if ANOMALY_HISTORY_FILE.exists():
            with open(ANOMALY_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as e:
        print(f"[scraper][phase5] anomaly history load err: {e}")
    return {}


def _phase5_save_anomaly_history(history: dict) -> None:
    try:
        ANOMALY_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(ANOMALY_HISTORY_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, default=str)
        os.replace(tmp, str(ANOMALY_HISTORY_FILE))
    except Exception as e:
        print(f"[scraper][phase5] anomaly history save err: {e}")


def _phase5_update_and_emit_sustained_anomaly(scrape_type: str, anomaly: bool,
                                                example_payload: dict) -> bool:
    """Update anomaly streak. Return True if sustained envelope emitted."""
    history = _phase5_load_anomaly_history()
    entry = history.get(scrape_type, {"anomaly_count": 0, "emitted_at": None})
    now_iso = _now_iso()
    
    if anomaly:
        entry["anomaly_count"] = min(entry.get("anomaly_count", 0) + 1, PHASE5_ANOMALY_CAP)
        entry["last_anomaly_at"] = now_iso
        if not entry.get("first_anomaly_at"):
            entry["first_anomaly_at"] = now_iso
    else:
        # Streak broken
        entry["anomaly_count"] = 0
        entry["first_anomaly_at"] = None
        entry["emitted_at"] = None
    
    history[scrape_type] = entry
    _phase5_save_anomaly_history(history)
    
    # Emit sustained if threshold crossed AND not already emitted at this scan
    count = entry.get("anomaly_count", 0)
    if count < PHASE5_ANOMALY_EMIT_THRESHOLD:
        return False
    last_emitted = entry.get("emitted_at")
    if last_emitted and last_emitted == now_iso:
        return False  # anti-dupe within same scan
    
    # Emit
    try:
        SIGNAL_CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
        env_id = f"agent_scraper_sustained_anomaly_{int(time.time())}_{_signal_secrets.token_hex(3)}"
        emitted_at = datetime.now(_signal_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = (datetime.now(_signal_tz.utc) + _signal_timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        severity = "critical" if count >= 8 else "high"
        
        envelope = {
            "_schema":    SIGNAL_CONTRACT_SCHEMA,
            "id":         env_id,
            "emitted_at": emitted_at,
            "expires_at": expires_at,
            "source": {
                "name":    "agent_scraper",
                "tier":    "B",
                "version": "v1.0+sprint43_phase5",
            },
            "signal_type":     "sustained_anomaly",
            "severity":        severity,
            "phase_relevance": None,
            "decay": {
                "half_life_hours": 3,
                "shape":           "exponential",
            },
            "direction":       "neutral",
            "confluence_with": [],
            "payload": {
                "headline": f"[scraper:sustained_anomaly] {scrape_type} anomaly persistent across {count} scans",
                "details":  (f"Scrape type '{scrape_type}' has reported anomaly_flag=true in "
                             f"{count} consecutive scans. This is genuine narrative dominance, "
                             f"not a one-time spike. consumers should weight accordingly."),
                "raw": {
                    "scrape_type":      scrape_type,
                    "anomaly_count":    count,
                    "first_anomaly_at": entry.get("first_anomaly_at"),
                    "last_anomaly_at":  entry.get("last_anomaly_at"),
                    "example_payload":  example_payload,
                    "timestamp":        now_iso,
                },
            },
        }
        
        final_path = SIGNAL_CONTRACTS_DIR / f"{env_id}.json"
        tmp_path = SIGNAL_CONTRACTS_DIR / f"{env_id}.json.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, default=str)
        os.replace(str(tmp_path), str(final_path))
        
        # Mark emitted at this scan
        entry["emitted_at"] = now_iso
        history[scrape_type] = entry
        _phase5_save_anomaly_history(history)
        
        _log(f"[signal][phase5] sustained_anomaly emit: {scrape_type} count={count}")
        return True
    except Exception as e:
        _log(f"[signal][phase5] sustained_anomaly emit err: {e}")
        return False


# ════════════════════════════════════════════════════════════════════════════
# END Phases 3+4+5 insertion
# ════════════════════════════════════════════════════════════════════════════


import secrets as _signal_secrets
from datetime import timezone as _signal_tz, timedelta as _signal_timedelta

SIGNAL_CONTRACTS_DIR = _BASE / "signal_contracts"
SIGNAL_CONTRACT_SCHEMA = "signal-contract-v1"

# Which scrape types are signal-worthy. Lookups (x_user, dex_token specific) skip.
_SIGNAL_WORTHY_SCRAPES = {"x_trending", "dex_solana_top", "pump_recent"}
_DATAPOINT_SCRAPES = {
    "coinbase_rank":  {"signal_type": "retail_attention",  "half_life": 8},
    "google_trends":  {"signal_type": "retail_attention",  "half_life": 8},
}

# Scrape type → envelope signal_type per spec
_SCRAPE_SIGNAL_TYPE = {
    "x_trending":      "sentiment",
}

# Scrape type → default expiry hours
_SCRAPE_EXPIRY_HOURS = {
    "x_trending":      6,    # trending topics decay fast
    "dex_solana_top":  12,   # top movers stay relevant longer
    "pump_recent":     4,    # new launches decay very fast in meme regime
}

# Crypto-relevant keywords for trending topic detection
_CRYPTO_TRENDING_KEYWORDS = [
    "btc", "bitcoin", "eth", "ethereum", "sol", "solana", "crypto",
    "pump", "fartcoin", "trump", "memecoin", "altcoin", "doge", "shib",
    "$", "satoshi", "vitalik", "fed", "powell", "etf", "halving", "binance",
    "coinbase", "blackrock", "saylor", "musk",
]


def _signal_classify_x_trending(scrape_result: dict, max_results: int) -> tuple:
    """Classify x_trending scrape → (direction, severity, anomaly_flag).
    
    Anomaly: ≥3 of top 10 trends are crypto-relevant → narrative is dominating.
    Direction stays neutral; local LLM at ingest reads payload to decide.
    """
    trends = scrape_result.get("trends", []) if isinstance(scrape_result, dict) else []
    if not trends:
        return ("neutral", "low", False)
    
    top10 = trends[:10]
    crypto_count = 0
    for t in top10:
        name = (t.get("trend_name", "") or "").lower()
        if any(kw in name for kw in _CRYPTO_TRENDING_KEYWORDS):
            crypto_count += 1
    
    anomaly = crypto_count >= 3
    severity = "high" if anomaly else ("medium" if crypto_count >= 1 else "low")
    return ("neutral", severity, anomaly)


def _signal_classify_dex_top(scrape_result: dict, max_results: int) -> tuple:
    """Classify dex_solana_top scrape → (direction, severity, anomaly_flag).
    
    Severity scales with result set size. Direction neutral — payload-driven at ingest.
    """
    tokens = scrape_result.get("tokens", []) if isinstance(scrape_result, dict) else []
    if not tokens:
        return ("neutral", "low", False)
    
    severity = "medium" if len(tokens) >= max(5, max_results // 2) else "low"
    return ("neutral", severity, False)


def _signal_classify_pump_recent(scrape_result: dict, max_results: int) -> tuple:
    """Classify pump_recent scrape → (direction, severity, anomaly_flag).
    
    Pump.fun launch count is a tempo indicator for meme regime. Direction
    stays neutral (count itself is the signal, not buy/sell bias).
    """
    launches = scrape_result.get("launches", []) if isinstance(scrape_result, dict) else []
    if not launches:
        launches = scrape_result.get("tokens", [])  # fallback
    
    if not launches:
        return ("neutral", "low", False)
    
    severity = "medium" if len(launches) >= 5 else "low"
    return ("neutral", severity, False)


def _signal_compute_tier(scrape_result: dict) -> str:
    """B tier by default per spec — scraped data has manipulation/brigading risk.
    Per-envelope downgrade to C if result was very thin or partial. Cannot upgrade
    above B for this source.
    """
    if not isinstance(scrape_result, dict) or not scrape_result.get("ok"):
        return "C"
    
    result_size = 0
    for key in ("trends", "tokens", "launches"):
        items = scrape_result.get(key)
        if isinstance(items, list):
            result_size += len(items)
    
    if result_size < 2:
        return "C"
    
    return "B"


def _signal_excerpt_scrape(scrape_type: str, scrape_result: dict) -> dict:
    """Build a compact excerpt of the scrape result for envelope payload.raw.
    Avoid bloating envelopes with full scrape payloads.
    """
    if not isinstance(scrape_result, dict):
        return {}
    
    excerpt = {}
    if scrape_type == "x_trending":
        trends = scrape_result.get("trends", [])[:10]
        excerpt["top_trends"] = [
            {
                "name":     t.get("trend_name"),
                "category": t.get("category"),
                "count":    t.get("post_count_text"),
            }
            for t in trends
        ]
    elif scrape_type == "dex_solana_top":
        tokens = scrape_result.get("tokens", [])[:10]
        excerpt["top_tokens"] = [
            {
                "symbol": t.get("symbol") or t.get("name"),
                "ca":     t.get("ca"),
                "url":    t.get("url"),
            }
            for t in tokens
        ]
        try:
            full = scrape_result.get("tokens", [])
            if full:
                snap = {
                    "scraped_at": datetime.now(_signal_tz.utc).isoformat(),
                    "count": len(full),
                    # which path produced this ("page_scrape" = the real trending board).
                    "selector_used": scrape_result.get("selector_used"),
                    "tokens": full,
                }
                snap_path = BOT_LOGS / "dex_solana_top_latest.json"
                tmp = snap_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(snap), encoding="utf-8")
                tmp.replace(snap_path)
        except Exception as _se:
            print(f"[scraper] dex_solana_top snapshot write err: {_se}")
    elif scrape_type == "pump_recent":
        launches = scrape_result.get("launches") or scrape_result.get("tokens", [])
        launches = launches[:10]
        excerpt["recent_launches"] = [
            {
                "symbol": t.get("symbol") or t.get("name"),
                "ca":     t.get("ca"),
                "url":    t.get("url"),
            }
            for t in launches
        ]
    return excerpt


def _signal_emit_datapoint_envelope(scrape_type: str, scrape_result: dict, summary_text: str) -> bool:
    """Sprint 44: emit ONE Signal Contract envelope for a single-value data-point
    scrape (coinbase_rank / google_trends). No
    persistence/confluence — these are direct readings consumers ingest each sweep."""
    try:
        cfg = _DATAPOINT_SCRAPES.get(scrape_type, {})
        SIGNAL_CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
        env_id = f"agent_scraper_{scrape_type}_{int(time.time())}_{_signal_secrets.token_hex(3)}"
        emitted_at = datetime.now(_signal_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        half_life = int(cfg.get("half_life", 6))
        expires_at = (datetime.now(_signal_tz.utc) + _signal_timedelta(hours=half_life * 2)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Severity: most data points are medium; coinbase top-10 is a strong top tell.
        severity = "medium"
        if scrape_type == "coinbase_rank" and scrape_result.get("in_top_10"):
            severity = "high"
        envelope = {
            "_schema":    SIGNAL_CONTRACT_SCHEMA,
            "id":         env_id,
            "emitted_at": emitted_at,
            "expires_at": expires_at,
            "source":     {"name": "agent_scraper", "tier": "B", "version": "v1.0+sprint44_datapoint"},
            "signal_type":     cfg.get("signal_type", "scraper_datapoint"),
            "severity":        severity,
            "phase_relevance": None,
            "decay":           {"half_life_hours": half_life, "shape": "exponential"},
            "confluence_with": [],
            "payload": {
                "headline": f"[scraper:{scrape_type}] {summary_text.splitlines()[0][:160] if summary_text else scrape_type}",
                "details":  summary_text[:600] if summary_text else "",
                "raw":      scrape_result,
            },
        }
        final_path = SIGNAL_CONTRACTS_DIR / f"{env_id}.json"
        tmp_path = SIGNAL_CONTRACTS_DIR / f"{env_id}.json.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, default=str)
        os.replace(str(tmp_path), str(final_path))
        return True
    except Exception as e:
        _log(f"[signal] datapoint envelope err for {scrape_type}: {e}")
        return False


def _signal_emit_envelope(task: dict, scrape_result: dict, summary_text: str) -> bool:
    """Emit ONE Signal Contract envelope for a signal-worthy scrape.
    
    Returns True on success, False if scrape isn't signal-worthy (lookup) or failed.
    """
    scrape_type = task.get("scrape_type", "unknown")
    
    if not isinstance(scrape_result, dict) or not scrape_result.get("ok"):
        return False
    
    # Sprint 44: data-point scrapes emit a single envelope directly — skip the
    # meme persistence/confluence machinery below.
    if scrape_type in _DATAPOINT_SCRAPES:
        return _signal_emit_datapoint_envelope(scrape_type, scrape_result, summary_text)
    
    # Filter: skip lookup-type scrapes
    if scrape_type not in _SIGNAL_WORTHY_SCRAPES:
        return False
    
    try:
        SIGNAL_CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
        max_results = task.get("max_results", 20)
        
        # ── Phase 1: persistence filtering ──────────────────────────────
        # Update the appearance cache with current scan's items. This
        # mutates the items list (adds `_appearance_count` field).
        # Then filter to only those meeting the persistence floor — those
        # are the "signal" items, the rest is noise.
        item_list_key = {
            "x_trending":     "trends",
            "dex_solana_top": "tokens",
            "pump_recent":    "launches",  # primary
        }.get(scrape_type)
        
        raw_items = []
        if item_list_key and isinstance(scrape_result.get(item_list_key), list):
            raw_items = scrape_result[item_list_key]
        elif scrape_type == "pump_recent" and isinstance(scrape_result.get("tokens"), list):
            raw_items = scrape_result["tokens"]   # fallback per existing classifier
        
        # Mutate raw_items with appearance counts + save cache
        annotated_items = _phase1_update_appearance_cache(scrape_type, raw_items)
        persistent_items = _phase1_filter_to_persistent(scrape_type, annotated_items)
        max_persistence_seen = max(
            (it.get("_appearance_count", 1) for it in annotated_items if isinstance(it, dict)),
            default=1
        )
        
        # If NOTHING passed the persistence floor, suppress emit entirely.
        # This is the core noise reduction — first 1-2 scans after deploy
        # will emit nothing for tracked scrape types (cache warming up).
        # By scan 3+ persistent items start appearing and envelopes resume.
        if scrape_type in PHASE1_PERSISTENCE_MIN_EMIT and not persistent_items:
            _log(f"[signal][phase1] {scrape_type}: no items past persistence floor "
                 f"(max seen={max_persistence_seen}, floor={PHASE1_PERSISTENCE_MIN_EMIT[scrape_type]}) — suppressing envelope")
            return False
        
        # Build a "persistent-only" scrape_result for the classifier so severity
        # reflects the FILTERED count, not the raw count. Preserve the original
        # scrape_result for the envelope payload (the agent still sees everything).
        if scrape_type in PHASE1_PERSISTENCE_MIN_EMIT and item_list_key:
            filtered_scrape_result = dict(scrape_result)
            filtered_scrape_result[item_list_key] = persistent_items
        else:
            filtered_scrape_result = scrape_result
        
        # Phase 2: update confluence cache + emit confluence envelopes for any
        # symbol that's now in 2+ scrape types within the window.
        try:
            confluent = _phase2_update_confluence_cache(scrape_type, persistent_items if persistent_items else raw_items)
            if confluent:
                _phase2_emit_confluence_envelopes(scrape_type, confluent)
        except Exception as e:
            _log(f"[signal][phase2] confluence pass err: {e}")
        
        # Phase 3: pump.fun rug filter — only applies to pump_recent
        try:
            if scrape_type == "pump_recent":
                _phase3_record_pump_launches(raw_items)
                # Filter out launches past the window that never got DEX follow-up
                pre_filter_count = len(persistent_items)
                persistent_items = [
                    it for it in persistent_items
                    if not _phase3_should_suppress_pump_item(it)
                ]
                if len(persistent_items) < pre_filter_count:
                    _log(f"[signal][phase3] pump_recent: suppressed {pre_filter_count - len(persistent_items)} likely-rugged launches")
                # Re-filter scrape_result for severity calc
                if item_list_key:
                    filtered_scrape_result = dict(scrape_result)
                    filtered_scrape_result[item_list_key] = persistent_items
            elif scrape_type == "dex_solana_top":
                _phase3_record_dex_followup(raw_items)
        except Exception as e:
            _log(f"[signal][phase3] rug filter err: {e}")
        
        # Phase 4: agent-inbox fallback for unknown persistent symbols
        try:
            for item in persistent_items:
                sym = _phase2_extract_symbol_from_item(scrape_type, item)
                if not sym:
                    continue
                if sym in _PHASE4_KNOWN_SYMBOLS:
                    continue
                if _phase4_already_asked(sym):
                    continue
                _phase4_queue_unknown_ask(
                    sym, scrape_type,
                    item.get("_appearance_count", 1) if isinstance(item, dict) else 1,
                    item if isinstance(item, dict) else {}
                )
        except Exception as e:
            _log(f"[signal][phase4] unknown queue err: {e}")
        
        # If after Phase 3 rug filter NOTHING is left, suppress
        if scrape_type in PHASE1_PERSISTENCE_MIN_EMIT and not persistent_items:
            _log(f"[signal][phase3] {scrape_type}: nothing persistent after rug filter — suppressing")
            return False
        
        if scrape_type == "x_trending":
            direction, severity, anomaly = _signal_classify_x_trending(filtered_scrape_result, max_results)
        elif scrape_type == "dex_solana_top":
            direction, severity, anomaly = _signal_classify_dex_top(filtered_scrape_result, max_results)
        elif scrape_type == "pump_recent":
            direction, severity, anomaly = _signal_classify_pump_recent(filtered_scrape_result, max_results)
        else:
            return False
        
        # Phase 5: sustained anomaly tracking — fire separate envelope when
        # the anomaly_flag persists across scans.
        try:
            _phase5_update_and_emit_sustained_anomaly(
                scrape_type, anomaly,
                {"max_persistence": max_persistence_seen, "item_count": len(persistent_items)}
            )
        except Exception as e:
            _log(f"[signal][phase5] sustained anomaly err: {e}")
        
        # Phase 1: bump severity when persistence is deep
        severity_bump = _phase1_compute_severity_bump(scrape_type, persistent_items)
        if severity_bump > 0:
            old_severity = severity
            severity = _phase1_apply_severity_bump(severity, severity_bump)
            if severity != old_severity:
                _log(f"[signal][phase1] {scrape_type}: severity bumped {old_severity} → {severity} "
                     f"(max persistence={max_persistence_seen})")
        
        tier = _signal_compute_tier(scrape_result)
        signal_type = _SCRAPE_SIGNAL_TYPE.get(scrape_type, "flow")
        expiry_hours = _SCRAPE_EXPIRY_HOURS.get(scrape_type, 6)
        half_life = max(1, expiry_hours // 4)
        
        env_id = f"agent_scraper_{int(time.time())}_{_signal_secrets.token_hex(3)}"
        emitted_at = datetime.now(_signal_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = (datetime.now(_signal_tz.utc) + _signal_timedelta(hours=expiry_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        headline = f"[{scrape_type}] {summary_text[:150]}"
        if anomaly:
            headline = f"[ANOMALY:{scrape_type}] {summary_text[:140]}"
        
        envelope = {
            "_schema":    SIGNAL_CONTRACT_SCHEMA,
            "id":         env_id,
            "emitted_at": emitted_at,
            "expires_at": expires_at,
            "source": {
                "name":    "agent_scraper",
                "tier":    tier,
                "version": "v1.0+sprint33",
            },
            "signal_type":     signal_type,
            "severity":        severity,
            "phase_relevance": None,
            "decay": {
                "half_life_hours": half_life,
                "shape":           "exponential",
            },
            "direction":       direction,
            "confluence_with": [],
            "payload": {
                "headline": headline,
                "details":  summary_text,
                "raw": {
                    "scrape_type":     scrape_type,
                    "task_id":         task.get("task_id"),
                    "target":          task.get("target"),
                    "max_results":     max_results,
                    "anomaly_flag":    anomaly,
                    "scrape_excerpt":  _signal_excerpt_scrape(scrape_type, scrape_result),
                    "requested_by":    task.get("requested_by"),
                    # sustained signals higher than one-time spikes.
                    "persistence_max_seen":   max_persistence_seen,
                    "persistence_item_count": len(persistent_items),
                    "persistence_floor":      PHASE1_PERSISTENCE_MIN_EMIT.get(scrape_type),
                    "persistence_bump":       severity_bump,
                },
            },
        }
        
        final_path = SIGNAL_CONTRACTS_DIR / f"{env_id}.json"
        tmp_path = SIGNAL_CONTRACTS_DIR / f"{env_id}.json.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, default=str)
        os.replace(str(tmp_path), str(final_path))
        return True
    
    except Exception as e:
        _log(f"[signal] emit error for {scrape_type}: {e}")
        return False

SCRAPER_PROFILE_DIR  = str(_BASE / "scraper_profile")
# ONE resolved profile, shared with the launcher's Sign in to X and the console status (x_session.py):
# bots/scraper_profile by default; BROWSER_USER_DATA_DIR (+ BROWSER_PROFILE_NAME) is an explicit opt-in.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import x_session as _xs
    BROWSER_PROFILE_DIR, BROWSER_PROFILE_NAME = _xs.profile()
except Exception:
    _xs = None
    BROWSER_PROFILE_DIR = os.getenv("BROWSER_USER_DATA_DIR") or SCRAPER_PROFILE_DIR
    BROWSER_PROFILE_NAME = (os.getenv("BROWSER_PROFILE_NAME") or "Default") if os.getenv("BROWSER_USER_DATA_DIR") else None


def _x_record_session(page, profile_dir: str) -> None:
    """After an X page load: record whether this profile is really logged in (account switcher
    visible) or hit the login wall. Feeds the honest 'Connected (verified)' status. No values read."""
    if _xs is None or os.path.abspath(profile_dir) != os.path.abspath(BROWSER_PROFILE_DIR):
        return
    try:
        url = page.url or ""
        if "x.com" not in url and "twitter.com" not in url:
            return
        if "/login" in url or "/i/flow/login" in url:
            _xs.record(False); return
        h = page.evaluate("""() => {
            const a = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]');
            if (!a) return null;
            const m = a.innerText.match(/@[A-Za-z0-9_]+/);
            return m ? m[0] : '@?';
        }""")
        if h:
            _xs.record(True, "" if h == "@?" else h)
    except Exception:
        pass

# Inert marker on every Chrome this bot launches. Chrome ignores unrecognized
# switches; this exists purely so the boot orphan guard can identify OUR strays
# without ever matching a browser the owner opened himself. Do NOT replace this with
# a profile-dir match - see _kill_orphan_scraper_chrome.
SCRAPER_LAUNCH_MARKER = "--agent-scraper-owned"


def _profile_launch_args(user_data_dir: str) -> list:
    """Marker always. --profile-directory only when pointed at a multi-profile
    Chrome dir; the dedicated profile has no named sub-profile."""
    args = [SCRAPER_LAUNCH_MARKER]
    same = os.path.abspath(user_data_dir) == os.path.abspath(SCRAPER_PROFILE_DIR)
    if not same and BROWSER_PROFILE_NAME:
        args.append(f"--profile-directory={BROWSER_PROFILE_NAME}")
    return args


def _kill_orphan_scraper_chrome() -> None:
    """Boot-only. Kill ONLY Chrome carrying SCRAPER_LAUNCH_MARKER, so a crashed
    prior scrape cannot sit on the profile lock and push the next launch into a
    retry inside a 120s fire window.

    LOCKED BUILD NOTE: agent_browser's guard matches cmdline on
    `*browser_profile*`, which is safe there. It is NOT safe here - this bot's
    profile dir can be pointed at the owner's real Chrome user-data dir via env, and
    that pattern would kill his live browser. Marker match only.
    """
    if os.name != "nt":
        return
    ps = (
        "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{SCRAPER_LAUNCH_MARKER}*' }} | "
        "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }"
    )
    try:
        _lu_subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           timeout=15, capture_output=True)
        _log("boot: cleared orphan scraper-Chrome (if any)")
    except Exception as e:
        _log(f"boot: orphan-Chrome cleanup skipped: {e}")

POLL_INTERVAL = 5  # check for new tasks every 5 seconds
DEFAULT_TIMEOUT = 15000  # 15s per page operation

# Browser mode — default is HEADED (uses real Chrome window with logged-in session).
# X /explore and other auth-gated pages need the real session, which headless can't
# always pick up cleanly. Headed is slower (~5-10s vs 3s headless) but reliable.
# Set AGENT_SCRAPER_HEADLESS=true in .env if you want headless for non-auth tasks.
SCRAPER_HEADLESS = _envv("AGENT_SCRAPER_HEADLESS", "false").lower() in ("true", "1", "yes")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _log(msg: str):
    line = f"[{_now_iso()}] {msg}"
    print(f"[scraper] {line}")
    try:
        with open(SCRAPE_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _save_json(path: Path, data) -> None:
    """Atomic write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def write_heartbeat(status: str, current_task: str = ""):
    try:
        _save_json(HEARTBEAT_FILE, {
            "timestamp": _now_iso(),
            "status": status,
            "current_task": current_task[:80],
            "version": "1.0_sprint28",
        })
    except Exception:
        pass


# ── scrape implementations ───────────────────────────────────────────────────
# Each scrape function takes a Playwright page, returns dict of findings.
# Multiple selector fallbacks — if X/DexScreener changes DOM, we degrade gracefully.

def _is_captcha_or_blocked(page) -> bool:
    """Best-effort detection for common anti-bot / CAPTCHA challenges.
    Returns True if the page looks blocked (so caller can fail fast and report
    the specific error instead of returning empty data that poisons downstream).
    """
    try:
        title = (page.title() or "").lower()
        content = (page.content() or "").lower()
        indicators = [
            "captcha",
            "cloudflare",
            "just a moment",
            "attention required",
            "verify you are human",
            "access denied",
            "rate limited",
            "challenge",
            "cf-chl",
            "please wait",
        ]
        for ind in indicators:
            if ind in title or ind in content:
                return True
        # Pump.fun / X specific common blocks
        if "pump.fun" in page.url and ("challenge" in content or "verify" in content):
            return True
        if "x.com" in page.url or "twitter.com" in page.url:
            if "something went wrong" in content or "try again" in content:
                return True
    except Exception:
        pass
    return False

def scrape_x_trending(page, max_results: int = 20) -> dict:
    """Get trending list from X.
    
    Strategy: DOM scrape of x.com/explore (needs the signed-in session).
    """
    # Path B: DOM scraping (requires logged-in session — usually fails in headless)
    page.goto("https://x.com/explore", timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
    if _is_captcha_or_blocked(page):
        return {"ok": False, "error": "captcha_or_challenge", "url": page.url, "site": "x.com/explore"}
    
    trend_selectors = [
        '[data-testid="trend"]',
        'div[data-testid="trend"]',
        'article[role="article"]',
    ]
    
    trends = []
    selector_used = None
    
    for selector in trend_selectors:
        try:
            page.wait_for_selector(selector, timeout=8000, state="visible")
            
            trends = page.evaluate("""(maxResults) => {
                const items = document.querySelectorAll('[data-testid="trend"]');
                const results = [];
                for (let i = 0; i < Math.min(items.length, maxResults); i++) {
                    const el = items[i];
                    const nameEl = el.querySelector('div[dir="ltr"] span') 
                                 || el.querySelector('[data-testid="trendName"]')
                                 || el.querySelector('div[dir="ltr"]');
                    const name = nameEl ? nameEl.innerText.trim() : null;
                    const allDivs = el.querySelectorAll('div[dir="ltr"]');
                    let category = null;
                    if (allDivs.length > 0) {
                        const firstText = allDivs[0].innerText.trim();
                        if (firstText && firstText !== name) category = firstText;
                    }
                    let postCount = null;
                    for (const div of allDivs) {
                        const txt = div.innerText.trim();
                        if (txt.match(/\\d[\\d,.]*[KMB]?\\s*(posts|Posts)/)) {
                            postCount = txt;
                            break;
                        }
                    }
                    if (name) {
                        results.push({
                            rank: i + 1,
                            trend_name: name,
                            category: category,
                            post_count_text: postCount,
                        });
                    }
                }
                return results;
            }""", max_results)
            
            if trends:
                selector_used = selector
                break
        except Exception as e:
            _log(f"x_trending DOM selector {selector} failed: {e}")
            continue
    
    return {
        "trends": trends,
        "trend_count": len(trends),
        "url": page.url,
        "scraped_at": _now_iso(),
        "selector_used": selector_used,
        "ok": len(trends) > 0,
        "source": "dom_scrape" if selector_used else "failed",
    }


def scrape_x_user(page, handle: str) -> dict:
    """Scrape a user profile for follower count + bio."""
    handle = handle.lstrip("@")
    url = f"https://x.com/{handle}"
    page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
    
    try:
        page.wait_for_selector('[data-testid="UserName"]', timeout=8000)
    except Exception:
        return {"ok": False, "error": "user_profile_not_loaded", "url": url}
    
    profile = page.evaluate("""() => {
        const out = {};
        
        // Display name
        const nameEl = document.querySelector('[data-testid="UserName"] span');
        out.display_name = nameEl ? nameEl.innerText : null;
        
        // Bio
        const bioEl = document.querySelector('[data-testid="UserDescription"]');
        out.bio = bioEl ? bioEl.innerText : null;
        
        // Follower count — link to /followers
        const followersLink = document.querySelector('a[href$="/followers"], a[href$="/verified_followers"]');
        if (followersLink) {
            const span = followersLink.querySelector('span span') || followersLink.querySelector('span');
            out.followers_text = span ? span.innerText : null;
        }
        
        // Following count
        const followingLink = document.querySelector('a[href$="/following"]');
        if (followingLink) {
            const span = followingLink.querySelector('span span') || followingLink.querySelector('span');
            out.following_text = span ? span.innerText : null;
        }
        
        // Verified
        out.verified = !!document.querySelector('svg[aria-label="Verified account"]')
                     || !!document.querySelector('[data-testid="icon-verified"]');
        
        return out;
    }""")
    
    profile["handle"] = handle
    profile["url"] = url
    profile["scraped_at"] = _now_iso()
    profile["ok"] = bool(profile.get("display_name"))
    return profile


def scrape_x_search(page, query: str, max_results: int = 10) -> dict:
    """Sprint 53 — SEARCH X BY QUERY. The missing capability: none of the existing X
    scrapers (x_trending / x_user / x_fyp) can answer "what is X saying about THIS
    token?" This one can.
    """
    from urllib.parse import quote
    if not query:
        return {"ok": False, "error": "x_search requires a query", "scraped_at": _now_iso()}

    # f=live -> Latest tab (chronological). Top is engagement-ranked = easiest to game.
    url = f"https://x.com/search?q={quote(query)}&src=typed_query&f=live"
    try:
        page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
    except Exception as e:
        return {"ok": False, "error": f"x_search nav failed: {e}", "query": query}

    try:
        page.wait_for_selector('article[data-testid="tweet"]', timeout=10000)
    except Exception:
        return {"ok": True, "scrape_type": "x_search", "query": query,
                "posts": [], "count": 0, "url": url, "scraped_at": _now_iso(),
                "note": "no posts found for this query (may simply be no chatter)"}

    collected = {}
    scrolls = 0
    max_scrolls = 10
    while len(collected) < max_results and scrolls < max_scrolls:
        batch = page.evaluate("""() => {
            const out = [];
            for (const a of document.querySelectorAll('article[data-testid="tweet"]')) {
                try {
                    const link = a.querySelector('a[href*="/status/"]');
                    const href = link ? link.getAttribute('href') : null;
                    if (!href) continue;
                    let tweet_id = null;
                    const sIdx = href.indexOf('/status/');
                    if (sIdx >= 0) {
                        let digits = '';
                        for (const ch of href.slice(sIdx + 8)) {
                            if (ch >= '0' && ch <= '9') digits += ch; else break;
                        }
                        tweet_id = digits || null;
                    }
                    if (!tweet_id) continue;
                    let handle = null;
                    const userLink = a.querySelector('[data-testid="User-Name"] a[href^="/"]');
                    if (userLink) {
                        const uh = userLink.getAttribute('href');
                        if (uh) handle = uh.split('/').filter(Boolean)[0] || null;
                    }
                    const textEl = a.querySelector('[data-testid="tweetText"]');
                    const text = textEl ? textEl.innerText : "";
                    const promoted = !!Array.from(a.querySelectorAll('span'))
                        .find(s => { const t=(s.innerText||'').trim(); return t==='Ad' || t==='Promoted'; });
                    // engagement counts — used downstream to sniff bot vs organic
                    const grab = (tid) => {
                        const el = a.querySelector('[data-testid="'+tid+'"]');
                        if (!el) return 0;
                        const t = (el.getAttribute('aria-label') || el.innerText || '').replace(/[^0-9]/g,'');
                        return t ? parseInt(t,10) : 0;
                    };
                    const replies = grab('reply'), reposts = grab('retweet'), likes = grab('like');
                    let ts = null;
                    const timeEl = a.querySelector('time');
                    if (timeEl) ts = timeEl.getAttribute('datetime');
                    out.push({ tweet_id, handle, text, promoted, replies, reposts, likes,
                               posted_at: ts,
                               url: "https://x.com/" + (handle || "i") + "/status/" + tweet_id });
                } catch (e) {}
            }
            return out;
        }""")
        for post in batch:
            tid = post.get("tweet_id")
            if tid and tid not in collected and not post.get("promoted"):
                collected[tid] = post
        try:
            page.mouse.wheel(0, 3000)
        except Exception:
            page.evaluate("window.scrollBy(0, 3000)")
        page.wait_for_timeout(1200)
        scrolls += 1

    posts = list(collected.values())[:max_results]
    return {
        "ok": True,
        "scrape_type": "x_search",
        "query": query,
        "posts": posts,
        "count": len(posts),
        "url": url,
        "scraped_at": _now_iso(),
    }


def _fetch_dexscreener_trending(max_results: int = 42) -> list:
    """Approximate DexScreener's 'Trending 6H' board via the free API — no metas (those
    lag: a token only gets a meta stamp AFTER it's already popular), no page scrape (the
    website hard-blocks automated browsers), no cost. Checked to
    match the real board (Ricky/SR20/Jimothy ranked correctly).

    Method: merge three FRESH feeds (top boosts + latest boosts + latest profiles) ->
    enrich each with full pair data -> filter SOL/stable + age-cap + liq floor ->
    re-rank by a momentum score (recent volume + h6/h1 gains + txn velocity)."""
    import urllib.request
    base = "https://api.dexscreener.com"
    hdrs = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    NON_TOKEN = {"SOL", "WSOL", "USDC", "USDT", "USDH", "MSOL", "STSOL", "JITOSOL", "JLP"}
    MAX_AGE_DAYS = 90
    MIN_LIQ = 10000

    def _get(url):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            _log(f"dexscreener api {url} err: {e}")
            return None

    # 1. gather fresh Solana CAs from three feeds (deduped)
    sol_cas, seen_ca = [], set()
    for feed_url in ("token-boosts/top/v1", "token-boosts/latest/v1", "token-profiles/latest/v1"):
        feed = _get(f"{base}/{feed_url}")
        if isinstance(feed, list):
            for b in feed:
                if b.get("chainId") == "solana":
                    ca = b.get("tokenAddress")
                    if ca and ca not in seen_ca:
                        seen_ca.add(ca)
                        sol_cas.append(ca)
    if not sol_cas:
        return []

    # 2. enrich with full pair data (batches of 30)
    seen, toks = set(), []
    for i in range(0, len(sol_cas), 30):
        batch = sol_cas[i:i + 30]
        data = _get(f"{base}/tokens/v1/solana/{','.join(batch)}")
        if not isinstance(data, list):
            continue
        for pair in data:
            base_tok = pair.get("baseToken") or {}
            sym = (base_tok.get("symbol") or "").upper()
            ca = base_tok.get("address")
            if not ca or ca in seen or sym in NON_TOKEN:
                continue
            seen.add(ca)
            txns = pair.get("txns") or {}
            h24t = txns.get("h24") or {}
            created = pair.get("pairCreatedAt")
            liq = (pair.get("liquidity") or {}).get("usd") or 0
            # age-cap + liq floor
            if created:
                try:
                    age_days = (time.time() - float(created) / 1000.0) / 86400.0
                    if age_days > MAX_AGE_DAYS:
                        continue
                except Exception:
                    pass
            if liq < MIN_LIQ:
                continue
            h1 = (pair.get("priceChange") or {}).get("h1")
            h6 = (pair.get("priceChange") or {}).get("h6")
            h24 = (pair.get("priceChange") or {}).get("h24")
            vol24 = (pair.get("volume") or {}).get("h24") or 0
            tx24 = (h24t.get("buys") or 0) + (h24t.get("sells") or 0)
            # momentum score (proven to match the Trending 6H ordering)
            score = (vol24 ** 0.5) + max(0, h6 or 0) * 50 + max(0, h1 or 0) * 30 + (tx24 ** 0.4) * 5
            toks.append({
                "ca": ca, "symbol": base_tok.get("symbol"), "name": base_tok.get("name"),
                "url": pair.get("url") or f"https://dexscreener.com/solana/{ca}",
                "price_usd": pair.get("priceUsd"),
                "liquidity_usd": liq,
                "volume_24h": vol24,
                "price_change_h1": h1, "price_change_24h": h24, "price_change_h6": h6,
                "pair_created_at": created,
                "market_cap": pair.get("marketCap") or pair.get("fdv"),
                "chain": "solana",
                "_score": score,
            })

    toks.sort(key=lambda x: x["_score"], reverse=True)
    for i, t in enumerate(toks, 1):
        t["rank"] = i
        t.pop("_score", None)
    return toks[:max_results]


def scrape_dex_solana_top(page, max_results: int = 20) -> dict:
    """Top trending Solana tokens — approximated from the free DexScreener API (merged
    fresh feeds + momentum rank). Proven to match the website's Trending 6H board without
    scraping it (Cloudflare-blocked) or walking metas (laggy)."""
    try:
        toks = _fetch_dexscreener_trending(max_results)
        if toks:
            return {"tokens": toks, "token_count": len(toks),
                    "url": "https://api.dexscreener.com (trending feeds)",
                    "scraped_at": _now_iso(), "selector_used": "trending_api", "ok": True}
    except Exception as e:
        _log(f"trending feeds failed, no fallback: {e}")


    return {"tokens": [], "token_count": 0, "url": "dexscreener_api",
            "scraped_at": _now_iso(), "selector_used": None, "ok": False}


def scrape_dex_token(page, ca: str) -> dict:
    """Get specific token data: DOM scrape of the DexScreener page."""
    
    # Original DOM fallback
    url = f"https://dexscreener.com/solana/{ca}"
    page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
    
    try:
        page.wait_for_selector('div', timeout=8000)
        page.wait_for_timeout(2500)
    except Exception:
        return {"ok": False, "error": "page_not_loaded", "url": url, "ca": ca}
    
    detail = page.evaluate("""() => {
        const out = {};
        out.raw_text = document.body.innerText.substring(0, 4000);
        const text = out.raw_text;
        const priceMatch = text.match(/\\$[\\d,]+\\.[\\d]+/);
        out.price_text = priceMatch ? priceMatch[0] : null;
        const liqMatch = text.match(/Liquidity[:\\s]+\\$([\\d,.]+[KMB]?)/i);
        out.liquidity_text = liqMatch ? '$' + liqMatch[1] : null;
        const mcapMatch = text.match(/(?:Market Cap|FDV|MCAP)[:\\s]+\\$([\\d,.]+[KMB]?)/i);
        out.mcap_text = mcapMatch ? '$' + mcapMatch[1] : null;
        const volMatch = text.match(/Volume[:\\s]+\\$([\\d,.]+[KMB]?)/i);
        out.volume_text = volMatch ? '$' + volMatch[1] : null;
        const changeMatch = text.match(/(-?[\\d.]+%)\\s*(?:24[hH]|H24)/);
        out.change_24h_text = changeMatch ? changeMatch[1] : null;
        const pairMatch = text.match(/([A-Z0-9]+)\\s*\\/\\s*(SOL|USDC|USDT)/);
        out.pair_text = pairMatch ? pairMatch[0] : null;
        return out;
    }""")
    
    detail["ca"] = ca
    detail["url"] = url
    detail["scraped_at"] = _now_iso()
    detail["source"] = "dom_scrape"
    detail["ok"] = bool(detail.get("price_text") or detail.get("raw_text", "").strip())
    return detail


def scrape_pump_recent(page, max_results: int = 20) -> dict:
    """Scrape recent token launches from pump.fun.
    
    NOTE: This is pure DOM and frequently hits anti-bot / CAPTCHA on pump.fun.
    Primary defense is the API fallbacks in the other main scrapes (x_trending, dex_solana_top).
    If this keeps failing, consider offloading pump launches to agent_browser or
    an external feed.
    """
    page.goto("https://pump.fun", timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
    if _is_captcha_or_blocked(page):
        return {"ok": False, "error": "captcha_or_challenge", "url": page.url, "site": "pump.fun"}
    
    try:
        page.wait_for_timeout(3000)  # pump.fun is JS-heavy
    except Exception:
        pass
    
    tokens = page.evaluate("""(maxResults) => {
        // Grab visible token cards — pump.fun structure shifts often
        const cards = document.querySelectorAll('[class*="card"], [class*="token"], a[href*="/coin"]');
        const results = [];
        const seen = new Set();
        for (const card of cards) {
            const text = (card.innerText || '').trim();
            if (text.length < 5 || seen.has(text)) continue;
            seen.add(text);
            const href = card.getAttribute('href') || card.querySelector('a')?.getAttribute('href') || null;
            results.push({
                rank: results.length + 1,
                raw_text: text.substring(0, 300),
                href: href,
            });
            if (results.length >= maxResults) break;
        }
        return results;
    }""", max_results)
    
    return {
        "tokens": tokens,
        "token_count": len(tokens),
        "url": page.url,
        "scraped_at": _now_iso(),
        "ok": len(tokens) > 0,
    }


# ════════════════════════════════════════════════════════════════════════════
# crashes the sweep. Coinglass/Trends selectors are best-effort — verify live.
# ════════════════════════════════════════════════════════════════════════════

def scrape_coinbase_rank(page, max_results: int = 100) -> dict:
    """US App Store top-free rank of the Coinbase app — a classic retail-FOMO /
    cycle-top tell with no free API. Reads Apple's public marketing RSS JSON
    (stable), finds Coinbase's position in the top-free chart."""
    url = "https://rss.applemarketingtools.com/api/v2/us/apps/top-free/100/apps.json"
    try:
        page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
        body = page.evaluate("() => document.body.innerText || ''")
        data = json.loads(body)
        apps = (data.get("feed") or {}).get("results") or []
        rank, name = None, None
        for i, app in enumerate(apps, start=1):
            if "coinbase" in (app.get("name") or "").lower():
                rank, name = i, app.get("name")
                break
        return {
            "rank": rank,                       # None = not in top 100
            "app_name": name,
            "chart_size": len(apps),
            "in_top_10": bool(rank and rank <= 10),
            "url": url, "scraped_at": _now_iso(),
            "ok": len(apps) > 0,                # ok if chart read, even if Coinbase absent
        }
    except Exception as e:
        return {"ok": False, "error": f"coinbase_rank: {e}", "scraped_at": _now_iso()}


def scrape_google_trends(page, term: str = "Bitcoin") -> dict:
    """Retail attention proxy — Google Trends interest for a term. trends.google.com
    is a heavy SPA whose interest-over-time needs token-gated widget calls, so this
    is best-effort: load the explore page, extract whatever current-interest text is
    visible. More reliable long-term route is pytrends — flagged. Verify live."""
    from urllib.parse import quote
    term = term or "Bitcoin"
    url = f"https://trends.google.com/trends/explore?q={quote(term)}&date=now%207-d"
    try:
        page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        text = page.evaluate("() => document.body.innerText || ''")
        avg = None
        m = re.search(r"(?:Average|Avg)\D{0,10}(\d{1,3})\b", text, re.I)
        if m:
            avg = int(m.group(1))
        ok = avg is not None
        return {
            "term": term, "interest_avg_7d": avg,   # 0-100 Trends scale
            "url": url, "scraped_at": _now_iso(), "ok": ok,
            "error": None if ok else "no_interest_value (SPA — consider pytrends; verify live)",
        }
    except Exception as e:
        return {"ok": False, "error": f"google_trends: {e}", "scraped_at": _now_iso()}


# Registry — maps scrape_type → function


SCRAPERS = {
    "x_trending": scrape_x_trending,
    "x_user": scrape_x_user,
    "dex_solana_top": scrape_dex_solana_top,
    "dex_token": scrape_dex_token,
    "pump_recent": scrape_pump_recent,
    "coinbase_rank": scrape_coinbase_rank,
    "google_trends": scrape_google_trends,
    # Sprint 53 — search X by query ($ticker or CA). The sniper uses this to pull
    # real chatter on a specific token for opportunity/hold packets.
    "x_search": scrape_x_search,
}


def execute_scrape(scrape_type: str, target: Optional[str] = None,
                     max_results: int = 20, extra: Optional[dict] = None) -> dict:
    """Run a single scrape using Playwright. Returns findings dict."""
    if scrape_type not in SCRAPERS:
        return {"ok": False, "error": f"unknown_scrape_type: {scrape_type}"}
    
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "ok": False,
            "error": "playwright_not_installed",
            "fix": "pip install playwright && playwright install chromium",
        }
    
    fn = SCRAPERS[scrape_type]
    
    with sync_playwright() as p:
        # so X is already logged in. Headed mode by default — needed for auth-gated
        # pages like /explore. Set AGENT_SCRAPER_HEADLESS=true to override.
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=BROWSER_PROFILE_DIR,
                headless=SCRAPER_HEADLESS,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                ] + _profile_launch_args(BROWSER_PROFILE_DIR)
                  + ([] if SCRAPER_HEADLESS else ["--start-minimized"]),  # minimize the window in headed
                viewport={"width": 1280, "height": 900},
                # Extra headers can help a bit with naive blocks
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        except Exception as e:
            _log(f"profile locked: {e} - using dedicated profile dir (session status not recorded for it)")
            dedicated = Path(SCRAPER_PROFILE_DIR)
            dedicated.mkdir(parents=True, exist_ok=True)
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(dedicated),
                headless=SCRAPER_HEADLESS,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                ] + _profile_launch_args(str(dedicated))
                  + ([] if SCRAPER_HEADLESS else ["--start-minimized"]),
                viewport={"width": 1280, "height": 900},
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        
        try:
            ctx._ms_profile = str(dedicated) if "dedicated" in locals() else BROWSER_PROFILE_DIR
        except Exception:
            pass
        page = ctx.new_page()
        # Basic JS stealth to reduce some automated detection
        try:
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            """)
        except Exception:
            pass
        try:
            # Pass target/max_results based on scraper signature
            if scrape_type == "x_user":
                if not target:
                    return {"ok": False, "error": "x_user requires target=handle"}
                result = fn(page, target)
            elif scrape_type == "dex_token":
                if not target:
                    return {"ok": False, "error": "dex_token requires target=ca"}
                result = fn(page, target)
            elif scrape_type == "x_search":
                if not target:
                    return {"ok": False, "error": "x_search requires target=query ($TICKER or CA)"}
                result = fn(page, target, max_results or 10)
            elif scrape_type == "google_trends":
                result = fn(page, target or "Bitcoin")   # target carries the term
            else:
                result = fn(page, max_results)
            if scrape_type.startswith("x_"):
                _x_record_session(page, getattr(ctx, "_ms_profile", BROWSER_PROFILE_DIR))
        finally:
            try:
                page.close()
                ctx.close()
            except Exception:
                pass
        
        return result


# ── format result for inbox ──────────────────────────────────────────────────
def format_scrape_as_summary(scrape_type: str, scrape_result: dict, target: Optional[str] = None) -> str:
    """Convert scrape result into natural-language summary for inbox event."""
    if not scrape_result.get("ok"):
        return f"({scrape_type} scrape failed: {scrape_result.get('error', 'unknown')})"
    
    if scrape_type == "x_trending":
        trends = scrape_result.get("trends", [])
        lines = ["Trending on X (scraped from /explore):"]
        for t in trends[:10]:
            count = t.get("post_count_text") or "(no count)"
            cat = t.get("category", "")
            cat_part = f" [{cat}]" if cat and cat != t.get("trend_name") else ""
            lines.append(f"{t.get('rank', '?')}. {t.get('trend_name', '?')}{cat_part} — {count}")
        return "\n".join(lines)
    
    elif scrape_type == "x_user":
        return (f"X user @{scrape_result.get('handle', '?')}: "
                f"{scrape_result.get('display_name', '?')} | "
                f"Followers: {scrape_result.get('followers_text', '?')} | "
                f"Bio: {scrape_result.get('bio', '(none)')[:200]}")
    
    elif scrape_type == "dex_solana_top":
        tokens = scrape_result.get("tokens", [])
        lines = [f"Top tokens on DexScreener Solana ({len(tokens)} found):"]
        for t in tokens[:10]:
            ca_short = t.get("ca", "")[:8] + "..." + t.get("ca", "")[-4:] if t.get("ca") else "?"
            text_preview = (t.get("raw_text", "") or "")[:150].replace("\n", " | ")
            lines.append(f"{t.get('rank', '?')}. {ca_short} — {text_preview}")
        return "\n".join(lines)
    
    elif scrape_type == "dex_token":
        return (f"DexScreener {scrape_result.get('ca', '?')[:8]}...: "
                f"price={scrape_result.get('price_text', '?')} | "
                f"mcap={scrape_result.get('mcap_text', '?')} | "
                f"liquidity={scrape_result.get('liquidity_text', '?')} | "
                f"24h={scrape_result.get('change_24h_text', '?')} | "
                f"pair={scrape_result.get('pair_text', '?')}")
    
    elif scrape_type == "pump_recent":
        tokens = scrape_result.get("tokens", [])
        lines = [f"Recent on pump.fun ({len(tokens)} cards visible):"]
        for t in tokens[:5]:
            text = (t.get("raw_text", "") or "")[:120].replace("\n", " | ")
            lines.append(f"{t.get('rank', '?')}. {text}")
        return "\n".join(lines)
    
    elif scrape_type == "coinbase_rank":
        r = scrape_result.get("rank")
        if r:
            return (f"Coinbase App Store rank (US top-free): #{r}"
                    + (" — TOP 10, retail-FOMO territory" if scrape_result.get("in_top_10") else ""))
        return f"Coinbase not in App Store top-{scrape_result.get('chart_size', 100)} free (low retail interest)"
    
    elif scrape_type == "google_trends":
        return (f"Google Trends '{scrape_result.get('term', '?')}' 7d interest: "
                f"{scrape_result.get('interest_avg_7d', '?')}/100")
    
    return f"Scrape complete: {json.dumps(scrape_result)[:500]}"


def _archive_scrape_to_done(response: dict) -> None:
    """Sprint 44: keep a permanent copy of every completed scrape in the done
    folder. The relay file (agent_scraper_response.json) is transient — the
    listener consumes + clears it — but this data is worth keeping, so we drop a
    dated, bot-named artifact here. Non-fatal: never blocks the scrape."""
    try:
        if response.get("status") != "success":
            return  # only keep real data; failed scrapes have nothing to archive
        scrape_type = "unknown"
        findings = response.get("findings") or []
        if findings and isinstance(findings[0], dict):
            scrape_type = findings[0].get("scrape_type", "unknown")
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        fname = f"agent_scraper - scrape_{scrape_type}_{ts}.json"
        _save_json(SCRAPE_DONE_DIR / fname, response)
    except Exception as e:
        _log(f"scrape archive err: {e}")


def write_scraper_response(task: dict, scrape_result: dict, summary_text: str):
    """Append a response to the requester's channel (see _response_channel_for:
    agent_scraper_response.json)
    so the right consumer ingests it, and archive a permanent copy to the done folder."""
    scrape_type = task.get("scrape_type", "unknown")
    
    # Build sample list from result (whatever's structurally relevant)
    samples = []
    if scrape_type == "x_trending":
        for t in scrape_result.get("trends", [])[:5]:
            samples.append({
                "author": "@x_dom_scrape",
                "text": f"{t.get('trend_name', '?')} — {t.get('post_count_text', '')}",
                "tweet_id": None,
                "engagement": {"category": t.get("category")},
            })
    elif scrape_type == "dex_solana_top":
        for t in scrape_result.get("tokens", [])[:5]:
            samples.append({
                "author": "@dexscreener_scrape",
                "text": (t.get("raw_text", "") or "")[:200],
                "tweet_id": None,
                "engagement": {"ca": t.get("ca"), "url": t.get("url")},
            })
    
    # Determine finding type
    if scrape_type == "x_trending":
        finding_type = "trending_topic"
    elif scrape_type in ("dex_solana_top", "pump_recent"):
        finding_type = "tweet_observation"  # reusing this type loosely
    else:
        finding_type = "vibe_summary"
    
    response = {
        "task_id": task.get("task_id", f"scrape_{int(time.time() * 1000)}"),
        "originating_action_id": task.get("originating_action_id"),
        "requested_by": task.get("requested_by"),
        "query": task.get("query") or task.get("scrape_type", ""),
        "completed_at": _now_iso(),
        "findings": [{
            "type": finding_type,
            "topic": None,
            "summary": summary_text,
            "sample_tweets": samples,
            "post_count_estimate": None,
            "source": "playwright_scraper",
            "scrape_type": scrape_type,
            "raw_result": scrape_result,  # preserve full data for debugging
        }] if scrape_result.get("ok") else [],
        "status": "success" if scrape_result.get("ok") else "failed",
        "error": None if scrape_result.get("ok") else scrape_result.get("error", "scrape_failed"),
        "source": "playwright_scraper",
    }
    
    # Sprint 45: route to the response channel
    # (shared RESPONSE_FILE). Append, don't clobber.
    out_file = _response_channel_for(task)
    existing = _load_json(out_file, {"responses": []})
    if not isinstance(existing, dict) or "responses" not in existing:
        existing = {"responses": []}
    existing["responses"].append(response)
    _save_json(out_file, existing)

    # Sprint 44: keep a permanent copy of the completed scrape.
    _archive_scrape_to_done(response)


# ── main daemon ───────────────────────────────────────────────────────────────
def _drain_task(done_task: dict) -> None:
    """v1.1.0: remove ONE completed task from the shared task file, keeping
    everything else.

    main_loop used to load every task, process them all, then unlink the whole
    file. Each scrape launches its own Chrome, so that window is minutes wide,
    and every writer (e.g. meme_sniper) does
    read-append-write. Anything appended DURING the batch was deleted unread.
    That is the real task-loss bug: not contention on write, destruction on clear.

    Re-reads the file at drain time so appends that landed mid-batch survive.
    Matches on task_id; falls back to exact-dict identity for legacy tasks that
    carry no id. Removes one occurrence only.
    """
    try:
        if not TASK_FILE.exists():
            return
        data = _load_json(TASK_FILE, None)
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            return
        tasks = data["tasks"]
        done_id = done_task.get("task_id")

        remaining, dropped = [], False
        for t in tasks:
            if not dropped and isinstance(t, dict):
                if done_id and t.get("task_id") == done_id:
                    dropped = True
                    continue
                if not done_id and t == done_task:
                    dropped = True
                    continue
            remaining.append(t)

        if remaining:
            data["tasks"] = remaining
            _save_json(TASK_FILE, data)
        else:
            try:
                TASK_FILE.unlink()
            except Exception:
                pass
    except Exception as e:
        _log(f"[drain] err: {e}")


def process_task(task: dict) -> bool:
    """Process a single scraper task. Returns True on success.
    
    Phase 4 wire-in: absorbs the agent's unknown-symbol replies at task start
    so the known-symbol cache is fresh before this task's emit pipeline.
    Flushes accumulated unknown-symbol asks at task end.
    """
    # Phase 4: absorb pending the agent replies before processing
    try:
        _phase4_absorb_agent_unknown_response()
    except Exception as e:
        _log(f"[phase4] absorb err: {e}")
    
    scrape_type = task.get("scrape_type")
    # Sprint 44: manifest entries carry the search/trends arg as query/term.
    target = task.get("target") or task.get("query") or task.get("term")
    max_results = task.get("max_results", 20)
    
    _log(f"processing task_id={task.get('task_id')} type={scrape_type} target={target}")
    write_heartbeat("scraping", f"{scrape_type} {target or ''}")
    
    try:
        result = execute_scrape(
            scrape_type,
            target=target,
            max_results=max_results,
            extra={
                "reply_text": task.get("reply_text") or "",
                "ui_mode": task.get("ui_mode") or "reply",
                "tweet_id": target,
            },
        )
        summary = format_scrape_as_summary(scrape_type, result, target=target)
        write_scraper_response(task, result, summary)
        
        envelope_emitted = _signal_emit_envelope(task, result, summary)
        if envelope_emitted:
            _log(f"[signal] envelope emitted for {scrape_type}")
        
        _log(f"task complete: ok={result.get('ok')}")
        return result.get("ok", False)
    except Exception as e:
        import traceback
        _log(f"scrape failed: {e}")
        traceback.print_exc()
        # Write a failed response so the executor's caller knows
        write_scraper_response(task, {"ok": False, "error": str(e)}, f"(scrape exception: {e})")
        return False
    finally:
        # Phase 4: flush accumulated unknown-symbol asks as ONE inbox packet
        try:
            _phase4_flush_unknown_queue()
        except Exception as e:
            _log(f"[phase4] flush err: {e}")
        write_heartbeat("idle")


_LU_SELF         = os.path.abspath(__file__)
_LU_LASTGOOD     = _LU_SELF + ".last-good"
_LU_MARKER       = str(BOT_LOGS / "agent_scraper_reload_marker.json")
_LU_STOP_FILE    = str(BOT_LOGS / "agent_scraper_no_reload")
_LU_SOURCE_SKILL = "agent-scraper"
_LU_MIN_UPTIME_S = 120
_LU_AUTORELOAD   = True
_LU_BOOT_TS      = time.time()
_LU_OWNER_INBOX   = _BASE.parent / "owner_inbox"
_lu_pending_reported = False


def _lu_hash(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return _lu_hashlib.sha256(fh.read()).hexdigest()[:8]
    except Exception:
        return "unknown"


def _lu_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


_LU_BOOT_MTIME = _lu_mtime(_LU_SELF)
_LU_BOOT_HASH  = _lu_hash(_LU_SELF)


def _lu_write_report(kind: str, severity: str, summary: str, detail: dict) -> None:
    """Live-update report -> owner_inbox, shared envelope
    (kind / severity / dedupe_key / source_skill / summary + detail)."""
    try:
        _LU_OWNER_INBOX.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"agent_scraper - {kind}_{ts}.md"
        lines = [
            "---",
            f"kind: {kind}",
            f"severity: {severity}",
            f"dedupe_key: agent_scraper:{kind}:{detail.get('to_hash', _LU_BOOT_HASH)}",
            f"source_skill: {_LU_SOURCE_SKILL}",
            f"summary: {summary}",
            "---",
            "",
            f"# {kind} - agent_scraper",
            "",
            f"**Time:** {_now_iso()}",
            f"**Summary:** {summary}",
            "",
            "## Detail",
            "",
        ]
        for k, v in detail.items():
            lines.append(f"- **{k}:** {v}")
        with open(_LU_OWNER_INBOX / fname, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        _log(f"live-update report [{kind}]: {fname}")
    except Exception as e:
        _log(f"live-update report err: {e}")


def _lu_snapshot_last_good() -> None:
    """Copy the running source to .last-good. Only ever called from a boot that
    reached the poll loop, so .last-good is a previously-clean version."""
    try:
        _lu_shutil.copy2(_LU_SELF, _LU_LASTGOOD)
    except Exception as e:
        _log(f"live-update last-good snapshot err: {e}")


def _lu_on_boot() -> None:
    """A present marker means this boot completed a patch reload -> report it,
    then snapshot last-good and clear. A cold boot just sets the baseline."""
    try:
        marker = _load_json(Path(_LU_MARKER), None)
    except Exception:
        marker = None
    if marker:
        _lu_write_report(
            "bot_restart", "info",
            f"agent_scraper rebooted to {_LU_BOOT_HASH}, healthy",
            {"from_hash": marker.get("from_hash", "?"),
             "to_hash": _LU_BOOT_HASH,
             "detected_at": marker.get("detected_at", "?")},
        )
        try:
            os.remove(_LU_MARKER)
        except Exception:
            pass
    _lu_snapshot_last_good()


def _lu_compiles(path: str) -> bool:
    """Full compile(), not ast.parse - a mid-write save or a bad patch must not
    be exec'd into. Returns False on a half-written or unparseable file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        compile(src, path, "exec")
        return True
    except Exception:
        return False


def _lu_check_and_reload() -> None:
    """Called at the TOP of the poll loop = the safe point. No context is open
    there (every scrape closes its own in a finally)."""
    global _lu_pending_reported
    try:
        if _lu_mtime(_LU_SELF) <= _LU_BOOT_MTIME:
            return
        new_hash = _lu_hash(_LU_SELF)
        if new_hash == _LU_BOOT_HASH:
            return   # touched, not changed

        if (not _LU_AUTORELOAD) or os.path.exists(_LU_STOP_FILE):
            if not _lu_pending_reported:
                _lu_write_report(
                    "bot_restart_failed", "high",
                    f"agent_scraper patch {new_hash} landed; auto-reload OFF, "
                    f"MANUAL RESTART needed (still running old {_LU_BOOT_HASH})",
                    {"to_hash": new_hash,
                     "reason": "stop_file" if os.path.exists(_LU_STOP_FILE) else "autoreload_disabled"},
                )
                _lu_pending_reported = True
            return

        if (time.time() - _LU_BOOT_TS) < _LU_MIN_UPTIME_S:
            return   # boot contention window

        if not _lu_compiles(_LU_SELF):
            _log(f"live-update: {new_hash} does not compile yet (mid-write?) - retrying next tick")
            return

        _lu_snapshot_last_good()
        _save_json(Path(_LU_MARKER), {
            "from_hash":   _LU_BOOT_HASH,
            "to_hash":     new_hash,
            "detected_at": _now_iso(),
            "lastgood":    _LU_LASTGOOD,
        })
        write_heartbeat("live_update", f"reloading -> {new_hash}")
        _log(f"live-update: reloading {_LU_BOOT_HASH} -> {new_hash} (re-exec in place)")
        try:
            os.execv(sys.executable, [sys.executable, _LU_SELF] + sys.argv[1:])
        except Exception as e:
            _log(f"live-update: os.execv failed, staying on current code: {e}")
            _lu_write_report(
                "bot_restart_failed", "high",
                f"agent_scraper patch {new_hash} detected but re-exec failed; "
                f"STILL RUNNING old {_LU_BOOT_HASH}",
                {"error": str(e)[:200], "to_hash": new_hash},
            )
            try:
                os.remove(_LU_MARKER)
            except Exception:
                pass
    except Exception as e:
        _log(f"live_update check err: {e}")


def main_loop():
    print(f"[scraper] the agent Scraper online")
    print(f"[scraper] Watching for tasks at: {TASK_FILE}")
    print(f"[scraper] Response → {RESPONSE_FILE}")
    print(f"[scraper] Poll interval: {POLL_INTERVAL}s")
    print(f"[scraper] Browser mode: {'HEADLESS' if SCRAPER_HEADLESS else 'HEADED (minimized window)'}"
            + (" — set AGENT_SCRAPER_HEADLESS=true to switch" if not SCRAPER_HEADLESS else ""))
    
    # Check Playwright is installed
    try:
        import playwright  # noqa
        _log("Playwright import OK")
    except ImportError:
        _log("❌ Playwright not installed. Run: pip install playwright && playwright install chromium")
        return
    
    # v1.1.0: clear our own strays before the first launch, then set the
    # live-update baseline / report a completed reload.
    _kill_orphan_scraper_chrome()
    _lu_on_boot()

    write_heartbeat("idle")
    
    while True:
        try:
            # v1.1.0 live-update: top of the poll loop is the safe point -
            # no Playwright context is open here.
            _lu_check_and_reload()

            # pause flag (console "Sign in to X"): safe point, no Playwright context open,
            # so the profile is free while we wait. A flag older than 30 min is removed.
            if _PAUSE_FILE.exists():
                try:
                    if time.time() - _PAUSE_FILE.stat().st_mtime > 1800:
                        _PAUSE_FILE.unlink()
                        _log("pause flag older than 30 min, removed; resuming")
                    else:
                        write_heartbeat("paused", "x_sign_in")
                        time.sleep(2)
                        continue
                except FileNotFoundError:
                    pass

            write_heartbeat("idle")
            
            if not TASK_FILE.exists():
                time.sleep(POLL_INTERVAL)
                continue
            
            data = _load_json(TASK_FILE, None)
            if not isinstance(data, dict) or "tasks" not in data:
                _log("task file format unrecognized, clearing")
                try: TASK_FILE.unlink()
                except Exception: pass
                time.sleep(POLL_INTERVAL)
                continue
            
            tasks = data.get("tasks", [])
            if not tasks:
                try: TASK_FILE.unlink()
                except Exception: pass
                time.sleep(POLL_INTERVAL)
                continue
            
            for task in tasks:
                try:
                    process_task(task)
                finally:
                    _drain_task(task)
            
            
        except KeyboardInterrupt:
            print("[scraper] stopped")
            break
        except Exception as e:
            import traceback
            _log(f"main loop error: {e}")
            traceback.print_exc()
            write_heartbeat("error")
            time.sleep(POLL_INTERVAL)
        
        time.sleep(POLL_INTERVAL)


# ── CLI for one-shot testing ─────────────────────────────────────────────────
if __name__ == "__main__":
    if "--login" in sys.argv:
        from playwright.sync_api import sync_playwright as _spw
        print("=" * 70)
        print("  SCRAPER LOGIN — opening the profile the scraper actually uses")
        print("=" * 70)
        _dedicated = os.path.abspath(BROWSER_PROFILE_DIR) == os.path.abspath(SCRAPER_PROFILE_DIR)
        _used, _why = BROWSER_PROFILE_DIR, (
            "dedicated scraper profile (v1.1.0 default)" if _dedicated
            else f"shared Chrome profile ({BROWSER_PROFILE_NAME}) via BROWSER_USER_DATA_DIR")
        with _spw() as _p:
            try:
                _ctx = _p.chromium.launch_persistent_context(
                    user_data_dir=BROWSER_PROFILE_DIR, headless=False,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                          "--disable-infobars", "--start-maximized"]
                         + _profile_launch_args(BROWSER_PROFILE_DIR),
                    no_viewport=True)
            except Exception as _e:
                # Do NOT fall back to another profile here: the login must land in the profile
                # the scraper and the status check use, or the status would lie.
                print(f"\n  !! profile is locked or unavailable ({_e.__class__.__name__}): {BROWSER_PROFILE_DIR}")
                print("  !! Close any Chrome using it (or pause the scraper) and try again. Nothing changed.")
                sys.exit(2)
            if False:
                _used = SCRAPER_PROFILE_DIR
                _ctx = _p.chromium.launch_persistent_context(
                    user_data_dir=_used, headless=False,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                          "--disable-infobars", "--start-maximized"]
                         + _profile_launch_args(_used),
                    no_viewport=True)
            print(f"\n  profile : {_used}")
            print(f"  reason  : {_why}")
            _pg = _ctx.pages[0] if _ctx.pages else _ctx.new_page()
            try:
                _pg.goto("https://x.com/home", timeout=60000)
            except Exception as _ge:
                print(f"  (navigation warning: {_ge})")
            print("\n  Sign in or switch accounts in the window, then come back here.")
            print("  To switch: click your avatar -> Add an existing account / Log out.")
            print("\n  Press ENTER when you are logged in as the account you want scraped...")
            try:
                input()
            except EOFError:
                pass
            # Confirm what actually stuck, rather than assuming.
            try:
                _pg.goto("https://x.com/home", timeout=45000)
                _pg.wait_for_timeout(3000)
                _handle = _pg.evaluate(
                    """() => {
                        const a = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]');
                        if (!a) return null;
                        const m = a.innerText.match(/@[A-Za-z0-9_]+/);
                        return m ? m[0] : null;
                    }""")
                if _xs is not None:
                    _u = _pg.url or ""
                    if _handle:
                        _xs.record(True, _handle)
                    elif "/login" in _u or "/i/flow/login" in _u:
                        _xs.record(False)
                if _handle:
                    print(f"\n  ✓ logged in as {_handle} — this profile is what every scrape will use")
                else:
                    print("\n  ⚠ could not read the account handle. If the timeline is visible you are "
                          "probably fine; if you see a login page, the session did NOT stick.")
            except Exception as _ve:
                print(f"\n  ⚠ verification failed: {_ve}")
            _ctx.close()
        print("\n  Done. Session saved to that profile directory.")
        sys.exit(0)

    if "--once" in sys.argv:
        idx = sys.argv.index("--once")
        scrape_type = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "x_trending"
        target = sys.argv[idx + 2] if len(sys.argv) > idx + 2 else None
        
        print(f"=== one-shot scrape: type={scrape_type} target={target} ===")
        result = execute_scrape(scrape_type, target=target)
        print()
        print("--- raw result ---")
        print(json.dumps(result, indent=2, default=str)[:3000])
        print()
        print("--- formatted summary ---")
        print(format_scrape_as_summary(scrape_type, result, target=target))
    else:
        main_loop()