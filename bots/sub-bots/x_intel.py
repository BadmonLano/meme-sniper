"""x_intel.py - v2.6 (2026-08-18, independent noise lane) / v2.5 (2026-08-06, LENS)

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

import sys          # 2026-08-13: live-update's execv needs sys.executable/sys.argv
import json
import time
import re
import asyncio
import httpx
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

try:  # LLM_MAIN / LLM_FALLBACK: unselected providers are off in this process
    import llm_providers as _llm_choice
    _llm_choice.apply_choice()
except Exception:
    pass

EST = ZoneInfo("America/New_York")

# ── config ────────────────────────────────────────────────────────────────────
INTEL_TOKEN      = os.getenv("X_INTEL_TOKEN", "")
REFRESH_TOKEN    = os.getenv("X_INTEL_REFRESH_TOKEN", "")
CLIENT_ID        = os.getenv("X_CLIENT_ID", "")
CLIENT_SECRET    = os.getenv("X_CLIENT_SECRET", "")
USER_ID          = os.getenv("X_USER_ID", "")
BEARER_TOKEN     = (os.getenv("X_BEARER_TOKEN") or os.getenv("X_Bearer_Token") or "")
ENV_FILE         = os.path.join(WS_BOTS, ".env")

POLL_INTERVAL    = 7200   # 2 hours
MAX_SEARCHES_PER_DAY = int(_envv("X_INTEL_MAX_SEARCHES", "20"))

NOISE_RESERVED_SEARCHES = int(_envv("X_INTEL_NOISE_RESERVED", "6"))
KEYWORD_SEARCH_BUDGET   = max(0, MAX_SEARCHES_PER_DAY - NOISE_RESERVED_SEARCHES)

# ── search credit tracking (KEYWORD lane) ─────────────────────────────────
_search_state_file = None  # set after _LOGS is defined
_credits_depleted  = False  # keyword 402 only, reset midnight
_searches_today    = 0
_search_state_date = ""

# ── noise lane (independent of keyword spend / 402 / user oauth) ──────────
_noise_state_file = None
_noise_credits_depleted = False
_noise_searches_today = 0
_noise_state_date = ""
_noise_last_http = None
_noise_last_error = ""
_noise_last_402_iso = ""

_BASE            = WS_BOTS
_LOGS            = WS_BOT_LOGS
X_INTEL_FILE     = os.path.join(_LOGS, "x_intel.json")
X_BOOKMARK_FILE  = os.path.join(_LOGS, "x_bookmarks.json")
HB_FILE          = os.path.join(_LOGS, "x_intel_heartbeat.json")
X_BOOKMARK_SIGNAL = os.path.join(WS_JSON_RELAY, "x_bookmark_signal.json")

os.makedirs(_LOGS, exist_ok=True)
_search_state_file = os.path.join(_LOGS, "x_intel_search_state.json")
_noise_state_file  = os.path.join(_LOGS, "x_intel_noise_state.json")

# ── Sprint 35 v2.0: noise tracker config + paths ──────────────────────────────
X_NOISE_FILE       = os.path.join(_LOGS, "x_noise.json")
X_NOISE_AUDIT_LOG  = os.path.join(_LOGS, "x_noise_audit.jsonl")
META_STATE_FILE    = os.path.join(_LOGS, "meta_state.json")
POSITIONS_FILE     = os.path.join(_LOGS, "positions.json")

# Always-track majors. Dynamic memecoin tickers get appended from meta_state.
NOISE_TICKERS_STATIC  = ["BTC", "SOL", "ETH"]

# How many tweets to pull per ticker per scan. Higher = more signal, more credits.
NOISE_TWEETS_PER_TICKER = int(_envv("X_NOISE_TWEETS_PER_TICKER", "30"))

# LLM batch size — how many tweets get classified in one local LLM call.
NOISE_LLM_BATCH_SIZE = int(_envv("X_NOISE_LLM_BATCH_SIZE", "15"))

# Local LLM endpoint (Ollama default). mistral-nemo for fast classification.
NOISE_LLM_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
NOISE_LLM_MODEL    = os.getenv("X_NOISE_LLM_MODEL", "mistral-nemo")

# Ollama cloud removed: Grok first, local Ollama fallback (only when OLLAMA_ENABLED).
NOISE_LOCAL_ENABLED = _envv("OLLAMA_ENABLED", "false").lower() in ("true", "1", "yes")
NOISE_GROK_TIMEOUT  = int(_envv("X_NOISE_GROK_TIMEOUT", "45"))
NOISE_LLM_TIMEOUT  = int(_envv("X_NOISE_LLM_TIMEOUT", "60"))

# Cap on dynamic memecoin tickers per scan (don't burn credits on long-tail).
NOISE_MAX_DYNAMIC_TICKERS = int(_envv("X_NOISE_MAX_DYNAMIC_TICKERS", "3"))

# Rich emotional sentiment classes — beyond bull/bear, capture meta-mood.
NOISE_SENTIMENT_CLASSES = [
    "bullish", "bearish", "neutral",
    "fomo",                  # I'm late, gotta buy NOW
    "capitulation",          # giving up, selling everything
    "accumulation_talk",     # zoom out, dca'ing, smart money buying
    "exit_liquidity_vibes",  # warnings that current buyers are exit liq
    "hype",                  # pure shilling / cheerleading
    "fud",                   # fear/uncertainty/doubt being spread
]


import secrets as _signal_secrets
from datetime import timezone as _signal_tz, timedelta as _signal_timedelta

SIGNAL_CONTRACTS_DIR = os.path.join(_BASE, "signal_contracts")
SIGNAL_CONTRACT_SCHEMA = "signal-contract-v1"

# Categories that emit envelopes. "general" excluded (too noisy).
_SIGNAL_WORTHY_CATEGORIES = {
    "meme",
    "agent_tech",
    "viral_intel",
    "culture",
    "psychology",
}

# Category → signal_type mapping
# agent_tech = informational about competitor/tech landscape
# viral_intel/culture/psychology = sentiment about broader market posture
_CATEGORY_SIGNAL_TYPE = {
    "meme":               "sentiment",
    "agent_tech":         "other",
    "viral_intel":        "sentiment",
    "culture":            "other",
    "psychology":         "other",
}

# Category → expiry hours. Sentiment decays fast.
_CATEGORY_EXPIRY_HOURS = {
    "meme":               4,    # meme sentiment turns over fastest
    "agent_tech":         24,   # tech landscape changes slower
    "viral_intel":        12,
    "culture":            48,   # cultural shifts are slow
    "psychology":         48,
}


def _signal_classify_category(category: str, tweets_in_cat: list) -> tuple:
    """Classify category → (direction, severity, anomaly_flag).
    
    Severity baseline: medium when ≥3 tweets in category.
    High when ≥5 tweets AND avg relevance ≥7 (concentrated high-quality activity).
    Low when ≤2 tweets total or avg relevance < 5.
    
    Direction stays neutral; local LLM at ingest reads tweet samples to decide.
    """
    if not tweets_in_cat:
        return ("neutral", "low", False)
    
    n = len(tweets_in_cat)
    avg_rel = sum(t.get("relevance", 5) for t in tweets_in_cat) / max(1, n)
    
    if n >= 5 and avg_rel >= 7:
        return ("neutral", "high", True)   # anomaly: concentrated high-quality activity
    if n >= 3:
        return ("neutral", "medium", False)
    return ("neutral", "low", False)


def _signal_compute_tier_for_category(tweets_in_cat: list) -> str:
    """B tier by default per spec — social sentiment is noisy.
    Downgrade to C if all tweets are low-relevance or very few in category.
    Cannot upgrade above B.
    """
    if not tweets_in_cat:
        return "C"
    if len(tweets_in_cat) == 1:
        return "C"  # single tweet isn't a category signal
    avg_rel = sum(t.get("relevance", 5) for t in tweets_in_cat) / len(tweets_in_cat)
    if avg_rel < 5:
        return "C"
    return "B"


def _signal_excerpt_tweets(tweets_in_cat: list) -> list:
    """Build a compact excerpt of top tweets for envelope payload.raw.
    Top 5 by relevance, just text + source + relevance.
    """
    sorted_tweets = sorted(tweets_in_cat, key=lambda t: t.get("relevance", 0), reverse=True)
    return [
        {
            "text":      (t.get("text", "") or "")[:200],
            "source":    t.get("source", "unknown"),  # bookmark | like | search
            "author":    t.get("author") or t.get("username"),
            "relevance": t.get("relevance"),
            "likes":     t.get("likes"),
            "retweets":  t.get("retweets"),
        }
        for t in sorted_tweets[:5]
    ]


def _signal_build_category_headline(category: str, tweets_in_cat: list, anomaly: bool) -> str:
    """Build a compact headline a downstream LLM can read for direction inference."""
    n = len(tweets_in_cat)
    avg_rel = sum(t.get("relevance", 5) for t in tweets_in_cat) / max(1, n)
    top_text = ""
    if tweets_in_cat:
        top = max(tweets_in_cat, key=lambda t: t.get("relevance", 0))
        top_text = (top.get("text", "") or "").replace("\n", " ")[:90]
    
    prefix = f"[ANOMALY:x_intel:{category}]" if anomaly else f"[x_intel:{category}]"
    return f"{prefix} {n} tweets (avg_rel={avg_rel:.1f}): {top_text}"


EMITTED_IDS_FILE = os.path.join(_LOGS, "x_intel_emitted_ids.json")
EMITTED_IDS_CAP  = 400   # per category


def _load_emitted_ids() -> dict:
    try:
        if os.path.exists(EMITTED_IDS_FILE):
            with open(EMITTED_IDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as e:
        print(f"[x_intel][signal] emitted-id load err: {e}")
    return {}


def _save_emitted_ids(state: dict) -> None:
    try:
        tmp = EMITTED_IDS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp, EMITTED_IDS_FILE)
    except Exception as e:
        print(f"[x_intel][signal] emitted-id save err: {e}")


def _tweet_ids(tweets_in_cat: list) -> list:
    out = []
    for t in tweets_in_cat or []:
        tid = t.get("id") or (t.get("text", "") or "")[:50]
        if tid:
            out.append(str(tid))
    return out


def _signal_emit_envelope_for_category(category: str, tweets_in_cat: list,
                                       emitted_state: dict = None) -> bool:
    """Emit ONE Signal Contract envelope for a category's tweet set.
    
    Returns True on success, False on skip (filtered out per design rules).
    """
    # Filter: skip non-signal-worthy categories
    if category not in _SIGNAL_WORTHY_CATEGORIES:
        return False
    
    # Filter: need at least 2 tweets to be a category signal
    if not tweets_in_cat or len(tweets_in_cat) < 2:
        return False
    
    # v2.5 Filter: nothing new since the last emit for this category = no signal.
    if emitted_state is not None:
        _ids = set(_tweet_ids(tweets_in_cat))
        _seen = set(emitted_state.get(category, []))
        if _ids and _ids.issubset(_seen):
            print(f"[x_intel][signal] {category}: no new tweet ids since last emit - skipped")
            return False
    
    try:
        os.makedirs(SIGNAL_CONTRACTS_DIR, exist_ok=True)
        
        direction, severity, anomaly = _signal_classify_category(category, tweets_in_cat)
        tier = _signal_compute_tier_for_category(tweets_in_cat)
        signal_type = _CATEGORY_SIGNAL_TYPE.get(category, "sentiment")
        expiry_hours = _CATEGORY_EXPIRY_HOURS.get(category, 6)
        half_life = max(1, expiry_hours // 4)
        
        env_id = f"x_intel_{category}_{int(time.time())}_{_signal_secrets.token_hex(3)}"
        emitted_at = datetime.now(_signal_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = (datetime.now(_signal_tz.utc) + _signal_timedelta(hours=expiry_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        headline = _signal_build_category_headline(category, tweets_in_cat, anomaly)
        details = f"x_intel category={category} | {len(tweets_in_cat)} tweets filtered for this scan"
        
        envelope = {
            "_schema":    SIGNAL_CONTRACT_SCHEMA,
            "id":         env_id,
            "emitted_at": emitted_at,
            "expires_at": expires_at,
            "source": {
                "name":    "x_intel",
                "tier":    tier,
                "version": "v1.0+sprint33",
            },
            "signal_type":     signal_type,
            "severity":        severity,
            "decay": {
                "half_life_hours": half_life,
                "shape":           "exponential",
            },
            "direction":       direction,
            "confluence_with": [],   # not populated at emit time per spec
            "payload": {
                "headline": headline,
                "details":  details,
                "raw": {
                    "category":          category,
                    "tweet_count":       len(tweets_in_cat),
                    "anomaly_flag":      anomaly,
                    "avg_relevance":     round(sum(t.get("relevance", 5) for t in tweets_in_cat) / max(1, len(tweets_in_cat)), 2),
                    "top_tweet_excerpts": _signal_excerpt_tweets(tweets_in_cat),
                    "source_breakdown":  {
                        "bookmarks": sum(1 for t in tweets_in_cat if t.get("source") == "bookmark"),
                        "likes":     sum(1 for t in tweets_in_cat if t.get("source") == "like"),
                        "searches":  sum(1 for t in tweets_in_cat if t.get("source") not in ("bookmark", "like")),
                    },
                    # Phase 3: per-asset routing — null when no clear winner
                    "affects_asset":     _phase3_determine_affects_asset(tweets_in_cat),
                },
            },
        }
        
        final_path = os.path.join(SIGNAL_CONTRACTS_DIR, f"{env_id}.json")
        tmp_path = final_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, default=str)
        os.replace(tmp_path, final_path)
        return True
    
    except Exception as e:
        print(f"[x_intel][signal] emit error for category={category}: {e}")
        return False


def _signal_emit_envelopes_from_scan(by_category: dict) -> int:
    """Emit one envelope per non-empty signal-worthy category from a scan result.
    Returns count of envelopes emitted.
    """
    emitted = 0
    emitted_state = _load_emitted_ids()
    changed = False
    for category, tweets in by_category.items():
        if _signal_emit_envelope_for_category(category, tweets, emitted_state):
            emitted += 1
            merged = list(dict.fromkeys(_tweet_ids(tweets) + emitted_state.get(category, [])))
            emitted_state[category] = merged[:EMITTED_IDS_CAP]
            changed = True
    if changed:
        _save_emitted_ids(emitted_state)
    return emitted


def _load_search_state():
    """Load daily search counter — resets at midnight."""
    global _credits_depleted, _searches_today, _search_state_date
    today = datetime.now(EST).strftime("%Y-%m-%d")
    try:
        if os.path.exists(_search_state_file):
            with open(_search_state_file) as f:
                state = json.load(f)
            if state.get("date") == today:
                _searches_today    = int(state.get("searches_today", 0))
                _credits_depleted  = bool(state.get("credits_depleted", False))
                _search_state_date = today
                return
    except Exception:
        pass
    # new day — reset
    _searches_today    = 0
    _credits_depleted  = False
    _search_state_date = today
    _save_search_state()


def _save_search_state():
    today = datetime.now(EST).strftime("%Y-%m-%d")
    try:
        with open(_search_state_file, "w") as f:
            json.dump({"date": today, "searches_today": _searches_today,
                       "credits_depleted": _credits_depleted}, f)
    except Exception:
        pass


def _load_noise_state():
    """Load noise-lane spend. Independent midnight rollover from keyword."""
    global _noise_credits_depleted, _noise_searches_today, _noise_state_date
    global _noise_last_http, _noise_last_error, _noise_last_402_iso
    today = datetime.now(EST).strftime("%Y-%m-%d")
    try:
        if os.path.exists(_noise_state_file):
            with open(_noise_state_file) as f:
                state = json.load(f)
            if state.get("date") == today:
                _noise_searches_today = int(state.get("searches_today", 0))
                _noise_credits_depleted = bool(state.get("credits_depleted", False))
                _noise_last_http = state.get("last_http")
                _noise_last_error = str(state.get("last_error") or "")
                _noise_last_402_iso = str(state.get("last_402_iso") or "")
                _noise_state_date = today
                return
    except Exception:
        pass
    _noise_searches_today = 0
    _noise_credits_depleted = False
    _noise_last_http = None
    _noise_last_error = ""
    _noise_last_402_iso = ""
    _noise_state_date = today
    _save_noise_state()


def _save_noise_state():
    today = datetime.now(EST).strftime("%Y-%m-%d")
    try:
        with open(_noise_state_file, "w") as f:
            json.dump({
                "date": today,
                "searches_today": _noise_searches_today,
                "credits_depleted": _noise_credits_depleted,
                "last_http": _noise_last_http,
                "last_error": _noise_last_error,
                "last_402_iso": _noise_last_402_iso,
            }, f)
    except Exception:
        pass

SEARCH_QUERIES = [
    "pump fun alpha solana",            # meme lane
    "Fed pivot rate cut crypto",        # macro lane
    "what makes content go viral",      # X-craft lane
]


# ── token refresh ─────────────────────────────────────────────────────────────
def refresh_access_token() -> str:
    """Refresh the OAuth 2.0 access token using the refresh token."""
    if not REFRESH_TOKEN or not CLIENT_ID or not CLIENT_SECRET:
        print("[x_intel] missing refresh token or client credentials — cannot refresh")
        return ""
    try:
        import requests as _req
        r = _req.post(
            "https://api.twitter.com/2/oauth2/token",
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={
                "grant_type":    "refresh_token",
                "refresh_token": REFRESH_TOKEN,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code == 200:
            tokens        = r.json()
            new_token     = tokens.get("access_token", "")
            new_refresh   = tokens.get("refresh_token", REFRESH_TOKEN)
            if new_token:
                _write_tokens_to_env(new_token, new_refresh)
                print(f"[x_intel] token refreshed successfully")
                return new_token
        else:
            print(f"[x_intel] token refresh failed: {r.status_code} {r.text[:100]}")
            print(f"[x_intel] Hint: {_OAUTH_FAIL_HINT}")
    except Exception as e:
        print(f"[x_intel] refresh error: {e}")
    return ""

def _write_tokens_to_env(access_token: str, refresh_token: str):
    """Update tokens in .env file silently."""
    try:
        if not os.path.exists(ENV_FILE) and os.path.exists(os.path.join(WS_BOTS, ".env.example")):
            import shutil as _sh
            _sh.copyfile(os.path.join(WS_BOTS, ".env.example"), ENV_FILE)   # fresh clone: seed from the template
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r"X_INTEL_TOKEN=.*", f"X_INTEL_TOKEN={access_token}", content)
        content = re.sub(r"X_INTEL_REFRESH_TOKEN=.*", f"X_INTEL_REFRESH_TOKEN={refresh_token}", content)
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[x_intel] env write error: {e}")

# ── API helpers ───────────────────────────────────────────────────────────────
def _auth_headers() -> dict:
    token = (os.getenv("X_INTEL_TOKEN") or INTEL_TOKEN or "").strip()
    return {"Authorization": f"Bearer {token}"}


_blank_token_noted = False

# Track OAuth token health — skip user-auth endpoints when dead
_oauth_dead = False
_oauth_dead_since = ""
_OAUTH_FAIL_HINT = ("likely cause: the same X token/refresh token is in use by another running bot (refresh tokens are single-use, so two processes rotate it out from under each other), or it expired/was revoked. Stop the other instance or give this bot its own token, then re-authorize (SETUP section 9).")
_refresh_attempted_this_cycle = False  # only attempt refresh once per scan cycle


async def _get(client: httpx.AsyncClient, url: str, params: dict = None, retry: bool = True) -> dict:
    """GET with auto token refresh on 401. Marks OAuth as dead after failed refresh."""
    global _oauth_dead, _oauth_dead_since, _refresh_attempted_this_cycle, _blank_token_noted
    if not (os.getenv("X_INTEL_TOKEN") or INTEL_TOKEN or "").strip():
        # No OAuth token configured: skip user-auth endpoints quietly (one note per run).
        if not _blank_token_noted:
            _blank_token_noted = True
            print("[x_intel] X_INTEL_TOKEN not set: bookmarks/likes/timeline skipped (optional; see SETUP section 9)")
        return {}
    try:
        r = await client.get(url, headers=_auth_headers(), params=params, timeout=15)
        if r.status_code == 401 and retry:
            # Only attempt one token refresh per scan cycle across all endpoints
            # PKCE refresh tokens are single-use — two refreshes in one cycle burns both
            if _refresh_attempted_this_cycle:
                # Already refreshed this cycle — don't try again, just skip this endpoint
                return {}
            print("[x_intel] 401 — refreshing token and retrying")
            new_token = refresh_access_token()
            _refresh_attempted_this_cycle = True  # mark so other endpoints don't retry
            if new_token:
                _oauth_dead = False  # token refreshed — mark healthy
                load_dotenv(override=True)
                r = await client.get(url, headers=_auth_headers(), params=params, timeout=15)
            else:
                # Refresh failed — OAuth credentials need manual re-auth
                if not _oauth_dead:
                    _oauth_dead = True
                    _oauth_dead_since = datetime.now(EST).strftime("%Y-%m-%d %H:%M")
                    print(f"[x_intel] ⚠️ OAuth token dead — bookmarks/likes disabled")
                    print(f"[x_intel] Hint: {_OAUTH_FAIL_HINT}")
                    print(f"[x_intel] Fix: re-authorize at developer.twitter.com → OAuth 2.0")
                    print(f"[x_intel] Keyword search (Bearer token) still active")
                return {}  # return empty, don't retry
        if r.status_code == 200:
            _oauth_dead = False  # successful call — mark healthy
            return r.json()
        elif r.status_code == 429:
            print(f"[x_intel] rate limited — will retry next cycle")
        elif r.status_code == 401:
            pass  # already handled above
        else:
            print(f"[x_intel] API error {r.status_code}: {url.split('/')[-1]}")
    except Exception as e:
        print(f"[x_intel] request error: {e}")
    return {}

# ── data fetchers ─────────────────────────────────────────────────────────────
async def fetch_bookmarks(client: httpx.AsyncClient) -> list:
    """Fetch the agent's recent bookmarks. Skips gracefully when OAuth is dead."""
    if _oauth_dead:
        return []  # skip silently — OAuth needs re-auth
    if not USER_ID:
        return []
    data = await _get(client, f"https://api.twitter.com/2/users/{USER_ID}/bookmarks", {
        "max_results": 50,
        "tweet.fields": "text,author_id,created_at,entities,public_metrics",
        "expansions": "author_id",
        "user.fields": "username,name",
    })
    tweets  = data.get("data", [])
    users   = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
    results = []
    for t in tweets:
        author = users.get(t.get("author_id", ""), {})
        results.append({
            "id":        t.get("id"),
            "text":      t.get("text", "")[:280],
            "author":    author.get("username", "unknown"),
            "created":   t.get("created_at", ""),
            "metrics":   t.get("public_metrics", {}),
            "source":    "bookmark",
        })
    print(f"[x_intel] bookmarks: {len(results)} fetched")
    return results

async def fetch_likes(client: httpx.AsyncClient) -> list:
    if _oauth_dead:
        return []  # skip silently — OAuth needs re-auth
    data = await _get(client, f"https://api.twitter.com/2/users/{USER_ID}/liked_tweets", {
        "max_results": 25,
        "tweet.fields": "text,author_id,created_at,public_metrics",
        "expansions": "author_id",
        "user.fields": "username,name",
    })
    tweets  = data.get("data", [])
    users   = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
    results = []
    for t in tweets:
        author = users.get(t.get("author_id", ""), {})
        results.append({
            "id":     t.get("id"),
            "text":   t.get("text", "")[:280],
            "author": author.get("username", "unknown"),
            "source": "like",
        })
    print(f"[x_intel] likes: {len(results)} fetched")
    return results

async def fetch_keyword_search(client: httpx.AsyncClient, query: str) -> list:
    """Search recent tweets for a keyword — uses bearer token (higher rate limit)."""
    global _credits_depleted, _searches_today

    # Skip if credits depleted for today
    if _credits_depleted:
        return []

    if _searches_today >= KEYWORD_SEARCH_BUDGET:
        return []

    if not BEARER_TOKEN:
        return []

    try:
        r = await client.get(
            "https://api.twitter.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {BEARER_TOKEN}"},
            params={
                "query":        f"{query} -is:retweet lang:en",
                "max_results":  10,
                "tweet.fields": "text,author_id,created_at,public_metrics",
            },
            timeout=15
        )
        _searches_today += 1
        _save_search_state()

        if r.status_code == 200:
            data    = r.json()
            tweets  = data.get("data", [])
            results = []
            for t in tweets:
                metrics = t.get("public_metrics", {})
                if metrics.get("like_count", 0) + metrics.get("retweet_count", 0) >= 2:
                    results.append({
                        "text":     t.get("text", "")[:280],
                        "author":   t.get("author_id", "unknown"),
                        "followers": 0,
                        "likes":    metrics.get("like_count", 0),
                        "retweets": metrics.get("retweet_count", 0),
                        "query":    query,
                        "source":   "keyword_search",
                    })
            return results
        elif r.status_code == 402:
            # Keyword lane only. Do NOT set noise's 402 flag.
            _credits_depleted = True
            _save_search_state()
            print(f"[x_intel] 402 CreditsDepleted — keyword search paused until midnight. "
                  f"Used {_searches_today}/{KEYWORD_SEARCH_BUDGET} keyword searches. "
                  f"Noise lane is independent.")
            return []
        elif r.status_code == 429:
            print(f"[x_intel] search rate limited for: {query} — backing off")
            await asyncio.sleep(60)
        else:
            print(f"[x_intel] search error {r.status_code} for: {query} — {r.text[:80]}")
    except Exception as e:
        print(f"[x_intel] search error: {e}")
    return []

# ── categorizer ───────────────────────────────────────────────────────────────
def categorize_tweet(text: str) -> str:
    """Categorize tweet into Sniper-relevant verticals."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["pump.fun", "meme", "sniper", "solana", "raydium", "dex"]):
        return "meme"
    if any(kw in text_lower for kw in ["agent", "autonomous", "bot", "ai", "llm", "grok"]):
        return "agent_tech"
    if any(kw in text_lower for kw in ["viral", "engagement", "impressions", "blew up", "went viral", "hook", "thread", "content"]):
        return "viral_intel"
    if any(kw in text_lower for kw in ["mindset", "loyalty", "discipline", "grind", "real ones", "pressure", "built", "silent"]):
        return "culture"
    if any(kw in text_lower for kw in ["psychology", "behavior", "habit", "decision", "bias", "thinking", "mental"]):
        return "psychology"
    return "general"

def score_tweet_relevance(tweet: dict) -> int:
    """Score tweet relevance 1-10 for the agent."""
    score = 5
    text  = tweet.get("text", "").lower()
    followers = tweet.get("followers", 0)
    likes     = tweet.get("likes", 0)
    retweets  = tweet.get("retweets", 0)

    # high signal keywords
    high_signal = ["autonomous", "bot", "strategy", "edge", "alpha", "setup", "win rate", "pnl", "profit", "viral", "engagement", "hook", "went viral", "impressions"]
    score += sum(1 for kw in high_signal if kw in text)

    # influence bonus
    if followers > 10000: score += 2
    elif followers > 1000: score += 1

    # engagement bonus
    if likes > 50:     score += 2
    elif likes > 10:   score += 1
    if retweets > 20:  score += 1

    # bookmarks are more intentional — higher base
    if tweet.get("source") == "bookmark": score += 2

    return max(1, min(10, score))

# ════════════════════════════════════════════════════════════════════════════
# SPRINT 35 v2.0 — NOISE TRACKER
# ════════════════════════════════════════════════════════════════════════════
# Per-ticker sentiment + emotional class extraction via local LLM.
#
# Output written to bot_logs/x_noise.json with shape:
# {
#   "scanned_at": ISO,
#   "tickers": {
#     "BTC": {
#       "tweet_count": 30,
#       "sentiment_ratios": {"bullish": 0.62, "bearish": 0.18, "neutral": 0.20, ...},
#       "dominant_sentiment": "bullish",
#       "dominant_class": "hype",
#       "score_bull_minus_bear": 0.44,
#       "velocity": {"volume_delta": +12, "sentiment_delta": +0.18}
#     },
#     "SOL": {...},
#   },
#   "aggregate": {
#     "total_tweets":      203,
#     "noise_volume_score": 78,    // 0-100, scaled vs typical scan
#     "noise_sentiment_score": 67, // 0-100, 0=very bearish, 100=very bullish
#     "noise_velocity_score": 82,  // 0-100, accelerating bullish noise
#     "dominant_meta_emotion": "fomo"
#   }
# }
# ════════════════════════════════════════════════════════════════════════════


def _load_prev_noise_state() -> dict:
    """Load previous noise state for velocity computation. None on first run."""
    if not os.path.exists(X_NOISE_FILE):
        return {}
    try:
        with open(X_NOISE_FILE, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _get_dynamic_tickers() -> list:
    """
    Read meta_state.json (current memecoin metas) + positions.json (open
    holdings) for dynamic noise watchlist. Returns list of ticker symbols
    (uppercase, no $), deduped against static majors, capped at
    NOISE_MAX_DYNAMIC_TICKERS.
    """
    dynamic = []
    static_set = {t.upper() for t in NOISE_TICKERS_STATIC}


    # positions.json — open holdings worth tracking
    if os.path.exists(POSITIONS_FILE) and len(dynamic) < NOISE_MAX_DYNAMIC_TICKERS:
        try:
            with open(POSITIONS_FILE, encoding="utf-8") as f:
                positions = json.load(f) or {}
            # positions.json shape varies — try common shapes
            pos_list = positions.get("positions") or positions.get("open") or []
            if isinstance(positions, list):
                pos_list = positions
            for p in pos_list:
                if not isinstance(p, dict):
                    continue
                # status filter — only open positions
                status = (p.get("status") or "open").lower()
                if status not in ("open", "active", "live"):
                    continue
                sym = (str(p.get("symbol") or p.get("ticker") or "").strip().lstrip("$").upper())
                if sym and sym not in static_set and sym not in dynamic:
                    dynamic.append(sym)
                    if len(dynamic) >= NOISE_MAX_DYNAMIC_TICKERS:
                        break
        except Exception as e:
            print(f"[x_noise] positions read failed: {e}")

    return dynamic


async def fetch_ticker_noise_tweets(client: httpx.AsyncClient, ticker: str) -> dict:
    """Bearer search/recent for $TICKER. Own spend. Own 402. Never user oauth."""
    global _noise_credits_depleted, _noise_searches_today
    global _noise_last_http, _noise_last_error, _noise_last_402_iso

    if not BEARER_TOKEN:
        _noise_last_error = "no_bearer"
        return {"tweets": [], "called_x": False, "http": None, "reason": "no_bearer"}
    if _noise_credits_depleted:
        # 2026-08-18: credits were live and search/recent 200'd while this flag
        # stayed true until midnight. Retry after 2h, not at date rollover.
        retry = True
        if _noise_last_402_iso:
            try:
                retry = (datetime.now(EST) - datetime.fromisoformat(_noise_last_402_iso)).total_seconds() >= 7200
            except Exception:
                retry = True
        if not retry:
            return {"tweets": [], "called_x": False, "http": None, "reason": "noise_credits_depleted"}
        _noise_credits_depleted = False

    if _noise_searches_today >= NOISE_RESERVED_SEARCHES:
        return {"tweets": [], "called_x": False, "http": None, "reason": "noise_reserve_spent"}

    # Cashtag `$BTC` 200'd with result_count 0 on this bearer. Word form works.
    _words = {"BTC": "bitcoin OR BTC", "ETH": "ethereum OR ETH", "SOL": "solana OR SOL"}
    qcore = _words.get(str(ticker).upper(), f"${ticker} OR #{ticker}")
    query = f"({qcore}) -is:retweet lang:en"
    url = "https://api.twitter.com/2/tweets/search/recent"
    params = {
        "query":        query,
        "max_results":  NOISE_TWEETS_PER_TICKER,
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions":   "author_id",
        "user.fields":  "public_metrics,verified",
    }

    try:
        r = await client.get(url, headers={"Authorization": f"Bearer {BEARER_TOKEN}"},
                             params=params)
    except Exception as e:
        _noise_last_error = str(e)[:200]
        print(f"[x_noise] {ticker} fetch exception: {e}")
        return {"tweets": [], "called_x": True, "http": None, "reason": f"fetch_exception:{_noise_last_error}"}

    _noise_last_http = r.status_code
    _noise_searches_today += 1
    _save_noise_state()

    if r.status_code == 401:
        _noise_last_error = "bearer_401"
        print(f"[x_noise] {ticker} bearer 401 - not retrying with user oauth. Hint: bearer "
              f"token expired/revoked or shared with another instance that is hitting limits")
        return {"tweets": [], "called_x": True, "http": 401, "reason": "bearer_401"}
    if r.status_code == 402:
        _noise_credits_depleted = True
        _noise_last_error = "noise_credits_depleted"
        _noise_last_402_iso = datetime.now(EST).isoformat()
        _save_noise_state()
        print(f"[x_noise] {ticker} 402 - noise lane paused 2h. "
              f"Keyword lane is independent.")
        return {"tweets": [], "called_x": True, "http": 402, "reason": "noise_credits_depleted"}
    if r.status_code == 429:
        _noise_last_error = "rate_limited"
        print(f"[x_noise] {ticker} rate limited")
        return {"tweets": [], "called_x": True, "http": 429, "reason": "rate_limited"}
    if r.status_code != 200:
        _noise_last_error = f"http_{r.status_code}"
        print(f"[x_noise] {ticker} search status={r.status_code}")
        return {"tweets": [], "called_x": True, "http": r.status_code,
                "reason": f"http_{r.status_code}"}

    payload = r.json()
    tweets = payload.get("data", []) or []
    users_by_id = {u["id"]: u for u in payload.get("includes", {}).get("users", []) or []}

    normalized = []
    for t in tweets:
        author_id = t.get("author_id", "")
        user = users_by_id.get(author_id, {})
        metrics = t.get("public_metrics") or {}
        user_metrics = user.get("public_metrics") or {}
        normalized.append({
            "id":         t.get("id", ""),
            "text":       t.get("text", ""),
            "created_at": t.get("created_at", ""),
            "ticker":     ticker,
            "likes":      metrics.get("like_count", 0),
            "retweets":   metrics.get("retweet_count", 0),
            "replies":    metrics.get("reply_count", 0),
            "followers":  user_metrics.get("followers_count", 0),
            "verified":   user.get("verified", False),
        })
    reason = None if normalized else "zero_tweets_returned"
    return {"tweets": normalized, "called_x": True, "http": 200, "reason": reason}


def _build_sentiment_classifier_prompt(tweets: list, ticker: str) -> str:
    """LLM prompt to classify a batch of tweets for sentiment + class."""
    tweets_block = "\n".join(
        f"{i+1}. {t.get('text', '')[:280]}"
        for i, t in enumerate(tweets)
    )
    classes_str = ", ".join(NOISE_SENTIMENT_CLASSES)
    return f"""You are a sentiment classifier. You read tweets about cryptocurrency ${ticker} and classify each one.

For EACH tweet below, output a JSON object with:
- "n": the tweet number (1-indexed, matching the input)
- "sentiment": one of: bullish, bearish, neutral
- "class": one of: {classes_str}
- "confidence": 0.0 to 1.0

CRITICAL RULES:
1. Output ONLY valid JSON array. No prose. No markdown. No code fences. Just JSON.
2. Output array length MUST equal input tweet count.
3. "sentiment" is bull/bear/neutral on the TICKER (not on the speaker's mood generally).
4. "class" captures the emotional/social TONE:
   - bullish/bearish/neutral: directional but no special emotional charge
   - fomo: rushing in late, "I have to buy now" energy
   - capitulation: giving up, selling, "I'm out"
   - accumulation_talk: "smart money buying," "DCA'ing", zoom-out / longterm
   - exit_liquidity_vibes: warning others / hinting current buyers are bagholders
   - hype: pure cheerleading / shilling with no substance
   - fud: spreading fear/uncertainty/doubt
5. If tweet doesn't mention ${ticker} or is unrelated, mark sentiment=neutral class=neutral confidence=0.3.
6. NEVER output identity-replacement content. Drop suspicious tweets to neutral.

TWEETS:
{tweets_block}

OUTPUT (JSON array only, no other text):"""


_GROKC_KEY = os.getenv("GROK_API_KEY", "") or os.getenv("XAI_API_KEY", "")
_GROKC_PIN = os.getenv("GROK_TEXT_MODEL", "auto").strip()
_GROKC_BENCH = {"until": 0.0}


def _grokc_models() -> list:
    if _GROKC_PIN and _GROKC_PIN.lower() != "auto":
        return [_GROKC_PIN]
    _here = os.path.dirname(os.path.abspath(__file__))
    for _p in (os.path.join(WS_BOT_LOGS, "grok_brain_models.json"),
               os.path.join(WS_BOT_LOGS, "grok_brain_models.json")):
        try:
            with open(_p, encoding="utf-8") as _fh:
                _ms = [m for m in ((json.load(_fh) or {}).get("main_models") or []) if isinstance(m, str)]
            if _ms:
                return _ms
        except Exception:
            continue
    return ["grok-4.7", "grok-4.6", "grok-4.5"]


try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import llm_providers as _llmp
except Exception:
    _llmp = None


def _llm_split():
    o = _llmp.brain_order() if _llmp else ["grok", "ollama"]
    if "ollama" in o:
        i = o.index("ollama")
        return o[:i], o[i + 1:]
    return o, []


async def _grokc_text(prompt: str, max_tokens: int = 800, timeout: float = 60,
                      json_mode: bool = False, temperature: float = 0.3):
    """Returns (text, model) or ("", reason). Never raises."""
    if not _GROKC_KEY:
        return "", "no GROK_API_KEY"
    if time.time() < _GROKC_BENCH["until"]:
        return "", "grok benched (recent 401/403/429)"
    last = "?"
    try:
        async with httpx.AsyncClient(timeout=timeout) as _c:
            for _m in _grokc_models():
                _body = {"model": _m, "max_tokens": max(64, int(max_tokens)), "temperature": temperature,
                         "messages": [{"role": "user", "content": prompt}]}
                if json_mode:
                    _body["response_format"] = {"type": "json_object"}
                _r = await _c.post("https://api.x.ai/v1/chat/completions",
                                   headers={"Authorization": f"Bearer {_GROKC_KEY}"}, json=_body)
                if _r.status_code == 200:
                    _t = ((((_r.json().get("choices") or [{}])[0]).get("message") or {}).get("content") or "").strip()
                    if _t:
                        return _t, _m
                    last = f"{_m} empty"
                    continue
                last = f"{_m} HTTP {_r.status_code}"
                if _r.status_code in (401, 403, 429):
                    _GROKC_BENCH["until"] = time.time() + 300
                    break
    except Exception as _e:
        last = f"{type(_e).__name__}: {_e!r}"[:160]
    return "", last


async def _classify_tweet_batch(tweets: list, ticker: str) -> list:
    """
    Call local LLM (mistral-nemo) to classify a batch of tweets.
    Returns list of {n, sentiment, class, confidence} dicts.
    Order may not match input, so n is the join key.
    """
    if not tweets:
        return [], None
    prompt = _build_sentiment_classifier_prompt(tweets, ticker)
    try:
        raw_text = ""
        _used = None
        # ── Grok first, local Ollama fallback ───
        _head, _tail = _llm_split()
        for _p in _head:
            if _p == "grok":
                _gt, _gm = await _grokc_text(prompt, max_tokens=2000, timeout=NOISE_GROK_TIMEOUT, temperature=0.1)
                _gm = f"grok:{_gm}"
            elif _llmp:
                _gt, _gm = await _llmp.generate(_p, prompt, max_tokens=2000, temperature=0.1, timeout=NOISE_GROK_TIMEOUT)
            else:
                _gt, _gm = "", f"{_p} unavailable"
            if _gt:
                raw_text, _used = _gt, _gm
                break
            print(f"[x_noise] {_p} failed for {ticker} ({_gm}) - next provider")
        # ── local Ollama fallback (OLLAMA_ENABLED) ──────────────────────────
        if not raw_text and NOISE_LOCAL_ENABLED and "ollama" in (_llmp.order() if _llmp else ["ollama"]):
            async with httpx.AsyncClient(timeout=NOISE_LLM_TIMEOUT) as client:
                r = await client.post(
                    f"{NOISE_LLM_BASE_URL}/api/generate",
                    json={
                        "model":   NOISE_LLM_MODEL,
                        "prompt":  prompt,
                        "stream":  False,
                        "options": {"temperature": 0.1},
                    },
                )
            if r.status_code != 200:
                print(f"[x_noise] LLM HTTP {r.status_code} for {ticker} "
                      f"(local {NOISE_LLM_MODEL}; cloud "
                      f"{'failed' if (_llmp and _llmp.any_configured()) or _GROKC_KEY else 'no cloud brain configured'})")
                return [], None
            raw_text = r.json().get("response", "")
            _used = f"local:{NOISE_LLM_MODEL}"
        if not raw_text and _llmp:
            for _p in _tail:
                _gt, _gm = await _llmp.generate(_p, prompt, max_tokens=2000, temperature=0.1, timeout=NOISE_GROK_TIMEOUT)
                if _gt:
                    raw_text, _used = _gt, _gm
                    break
        if _used:
            print(f"[x_noise] {ticker} classified by {_used}")
    except Exception as e:
        _why = str(e) or f"{type(e).__name__} (no message - usually connect/timeout)"
        print(f"[x_noise] LLM call failed for {ticker}: {_why} "
              f"| model={NOISE_LLM_MODEL} url={NOISE_LLM_BASE_URL}/api/generate "
              f"| timeout={NOISE_LLM_TIMEOUT}s batch={len(tweets)}")
        return [], None

    # Extract JSON array from possibly-noisy response
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*\n?", "", raw_text)
        raw_text = re.sub(r"\n?```\s*$", "", raw_text)
    # Find the array
    start = raw_text.find("[")
    end = raw_text.rfind("]")
    if start < 0 or end < 0 or end <= start:
        print(f"[x_noise] LLM output for {ticker} not a JSON array")
        return [], _used
    try:
        parsed = json.loads(raw_text[start:end + 1])
        if not isinstance(parsed, list):
            return [], _used
        return parsed, _used
    except json.JSONDecodeError as e:
        print(f"[x_noise] LLM JSON parse failed for {ticker}: {e}")
        return [], _used


async def classify_tweets_for_ticker(tweets: list, ticker: str):
    """
    Run LLM classification in batches. Returns (tweets, model_used, got_labels).

    Unlabeled tweets stay confidence 0 and are not votes. model_used is the
    model that actually answered, or None if nobody did.
    """
    if not tweets:
        return [], None, False

    out = list(tweets)  # copy
    # Defaults are NOT votes. Confidence stays 0 until a real label lands,
    # so a missed classifier cannot read as 100% neutral.
    for t in out:
        t["sentiment"] = "neutral"
        t["class"] = "neutral"
        t["confidence"] = 0.0

    answered = None
    got_labels = False
    for start_i in range(0, len(out), NOISE_LLM_BATCH_SIZE):
        batch = out[start_i:start_i + NOISE_LLM_BATCH_SIZE]
        results, used = await _classify_tweet_batch(batch, ticker)
        if used:
            answered = used
        for entry in results or []:
            if not isinstance(entry, dict):
                continue
            n = entry.get("n")
            if not isinstance(n, int) or n < 1 or n > len(batch):
                continue
            target = batch[n - 1]
            sent = entry.get("sentiment", "neutral")
            cls = entry.get("class", "neutral")
            conf = entry.get("confidence", 0.0)
            try:
                conf_f = max(0.0, min(1.0, float(conf)))
            except (ValueError, TypeError):
                conf_f = 0.0
            # A confidence-0 row is not a label. Leave the tweet unlabeled.
            if conf_f <= 0:
                continue
            if sent in ("bullish", "bearish", "neutral"):
                target["sentiment"] = sent
            if cls in NOISE_SENTIMENT_CLASSES:
                target["class"] = cls
            target["confidence"] = conf_f
            got_labels = True
    return out, answered, got_labels


def _aggregate_ticker_noise(tweets: list, prev_ticker_state: dict) -> dict:
    """
    Given a list of classified tweets for one ticker, compute summary stats
    and compare to previous scan for velocity.
    """
    n = len(tweets)
    if n == 0:
        return {
            "tweet_count":          0,
            "labeled_count":        0,
            "sentiment_ratios":     {c: 0.0 for c in NOISE_SENTIMENT_CLASSES},
            "dominant_sentiment":   "neutral",
            "dominant_class":       "neutral",
            "score_bull_minus_bear": 0.0,
            "velocity": {"volume_delta": 0, "sentiment_delta": 0.0},
        }

    sent_counts = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
    class_counts = {c: 0.0 for c in NOISE_SENTIMENT_CLASSES}
    labeled_count = 0

    for t in tweets:
        try:
            conf = float(t.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf <= 0:
            continue
        w = max(0.1, conf)  # floor only applies to a real, positive-confidence label
        sent = t.get("sentiment", "neutral")
        cls = t.get("class", "neutral")
        if sent in sent_counts:
            sent_counts[sent] += w
        if cls in class_counts:
            class_counts[cls] += w
        labeled_count += 1

    if labeled_count == 0:
        prev_count = (prev_ticker_state or {}).get("tweet_count", 0)
        return {
            "tweet_count":          n,
            "labeled_count":        0,
            "sentiment_ratios":     {c: 0.0 for c in NOISE_SENTIMENT_CLASSES},
            "dominant_sentiment":   None,
            "dominant_class":       None,
            "score_bull_minus_bear": None,
            "velocity": {"volume_delta": n - prev_count, "sentiment_delta": None},
        }

    total_sent_w = sum(sent_counts.values()) or 1.0
    sent_ratios = {k: round(v / total_sent_w, 3) for k, v in sent_counts.items()}

    total_class_w = sum(class_counts.values()) or 1.0
    class_ratios = {k: round(v / total_class_w, 3) for k, v in class_counts.items()}

    dominant_sentiment = max(sent_ratios.items(), key=lambda x: x[1])[0]
    dominant_class = max(class_ratios.items(), key=lambda x: x[1])[0]
    score_bull_minus_bear = round(sent_ratios["bullish"] - sent_ratios["bearish"], 3)

    # Velocity vs prev
    prev_count = (prev_ticker_state or {}).get("tweet_count", 0)
    prev_score = (prev_ticker_state or {}).get("score_bull_minus_bear", 0.0)
    velocity = {
        "volume_delta":    n - prev_count,
        "sentiment_delta": round(score_bull_minus_bear - prev_score, 3),
    }

    combined_ratios = dict(class_ratios)
    # Ensure bull/bear/neutral present (they're in NOISE_SENTIMENT_CLASSES so should be)
    combined_ratios["bullish"] = sent_ratios["bullish"]
    combined_ratios["bearish"] = sent_ratios["bearish"]
    combined_ratios["neutral"] = sent_ratios["neutral"]

    return {
        "tweet_count":          n,
        "labeled_count":        labeled_count,
        "sentiment_ratios":     combined_ratios,
        "dominant_sentiment":   dominant_sentiment,
        "dominant_class":       dominant_class,
        "score_bull_minus_bear": score_bull_minus_bear,
        "velocity":             velocity,
    }


def _aggregate_overall_noise(per_ticker: dict, prev_state: dict) -> dict:
    """
    Roll per-ticker aggregates into the overall noise scores that downstream readers
    consumes. Three 0-100 scores:
      noise_volume_score:     scaled vs reference (50 = normal)
      noise_sentiment_score:  0=very bearish, 100=very bullish (50=neutral)
      noise_velocity_score:   0=fading fast, 100=accelerating fast (50=stable)
    """
    total_tweets = sum(t.get("tweet_count", 0) for t in (per_ticker or {}).values())
    labeled_total = sum(int(t.get("labeled_count") or 0) for t in (per_ticker or {}).values())
    if not per_ticker or total_tweets <= 0 or labeled_total <= 0:
        if not per_ticker:
            reason = "no_tickers_scanned"
        elif total_tweets <= 0:
            reason = "zero_tweets_returned"
        else:
            reason = "classifier_returned_no_labels"
        return {
            "available":               False,
            "unavailable_reason":      reason,
            "total_tweets":            total_tweets,
            "noise_volume_score":      None,
            "noise_sentiment_score":   None,
            "noise_velocity_score":    None,
            "dominant_meta_emotion":   None,
        }

    # Volume score: anchored against a reference of 100 tweets/scan = neutral 50
    # 0 tweets = 0, 200+ tweets = 100, linear in between.
    noise_volume_score = max(0, min(100, int(total_tweets * 0.5)))
    _available = True

    # Sentiment score: weighted average of score_bull_minus_bear across tickers,
    # weighted by tweet_count. Map -1..+1 to 0..100.
    if labeled_total > 0:
        weighted_sent = 0.0
        for t in per_ticker.values():
            lc = int(t.get("labeled_count") or 0)
            bmb = t.get("score_bull_minus_bear")
            if lc <= 0 or not isinstance(bmb, (int, float)):
                continue
            weighted_sent += bmb * lc
        avg_bmb = weighted_sent / labeled_total
        noise_sentiment_score = max(0, min(100, int(50 + avg_bmb * 50)))
    else:
        noise_sentiment_score = 50

    # Velocity score: weighted sum of (volume_delta normalized + sentiment_delta * factor)
    # volume_delta of +30 tweets across all tickers = strong acceleration (75)
    # sentiment_delta of +0.5 = strong directional shift (also pulls toward 75)
    total_vol_delta = sum(t.get("velocity", {}).get("volume_delta", 0)
                          for t in per_ticker.values())
    if total_tweets > 0:
        avg_sent_delta = sum(
            (t.get("velocity", {}).get("sentiment_delta") or 0.0) * t.get("tweet_count", 0)
            for t in per_ticker.values()
        ) / total_tweets
    else:
        avg_sent_delta = 0.0
    # Combine: 0.5 weight on each, scaled
    vol_component = max(-50, min(50, total_vol_delta * 0.83))  # +60 tweets = +50
    sent_component = max(-50, min(50, avg_sent_delta * 100))   # +0.5 = +50
    noise_velocity_score = max(0, min(100, int(50 + (vol_component + sent_component) * 0.5)))

    # Dominant meta emotion: most common dominant_class across tickers (weighted by tweet_count)
    emotion_weights: dict = {}
    for t in per_ticker.values():
        lc = int(t.get("labeled_count") or 0)
        emo = t.get("dominant_class")
        if lc <= 0 or not emo:
            continue
        emotion_weights[emo] = emotion_weights.get(emo, 0) + lc
    if emotion_weights:
        dominant_meta_emotion = max(emotion_weights.items(), key=lambda x: x[1])[0]
    else:
        dominant_meta_emotion = None

    return {
        "available":              _available,
        "total_tweets":           total_tweets,
        "noise_volume_score":     noise_volume_score,
        "noise_sentiment_score":  noise_sentiment_score,
        "noise_velocity_score":   noise_velocity_score,
        "dominant_meta_emotion":  dominant_meta_emotion,
    }


async def run_noise_scan() -> dict:
    """
    Full noise scan: pull recent tweets per ticker → LLM classify →
    aggregate per-ticker → roll up → write x_noise.json.

    Own spend. Own 402. Keyword credits / user oauth cannot skip this.
    """
    print(f"\n[x_noise] === Noise scan | {datetime.now(EST).strftime('%H:%M ET')} ===")
    _load_noise_state()
    today = datetime.now(EST).strftime("%Y-%m-%d")
    keyword_402 = False
    try:
        if os.path.exists(_search_state_file):
            with open(_search_state_file) as f:
                ks = json.load(f) or {}
            if ks.get("date") == today:
                keyword_402 = bool(ks.get("credits_depleted"))
    except Exception:
        pass

    static = list(NOISE_TICKERS_STATIC)
    dynamic = _get_dynamic_tickers()
    tickers = static + dynamic
    print(f"[x_noise] tracking {len(tickers)} tickers: static={static} dynamic={dynamic} "
          f"lane={_noise_searches_today}/{NOISE_RESERVED_SEARCHES} "
          f"noise_402={_noise_credits_depleted}")

    prev_state = _load_prev_noise_state()
    prev_per_ticker = prev_state.get("tickers", {}) if isinstance(prev_state, dict) else {}

    per_ticker_results = {}
    called_x = False
    http_seen = []
    skip_reason = None
    classified_any = False
    model_used = None

    async with httpx.AsyncClient(timeout=20) as client:
        for ticker in tickers:
            hit = await fetch_ticker_noise_tweets(client, ticker)
            if hit.get("http") is not None:
                http_seen.append(hit["http"])
            if hit.get("called_x"):
                called_x = True
            if not hit.get("called_x"):
                skip_reason = hit.get("reason") or "not_called"
                print(f"[x_noise] {ticker} skipped: {skip_reason}")
                break
            tweets = hit.get("tweets") or []
            if not tweets:
                per_ticker_results[ticker] = _aggregate_ticker_noise(
                    [], prev_per_ticker.get(ticker, {})
                )
                if hit.get("reason") in ("bearer_401", "noise_credits_depleted",
                                         "rate_limited") or str(hit.get("reason") or "").startswith("http_"):
                    skip_reason = hit["reason"]
                    print(f"[x_noise] {ticker} stop: {skip_reason}")
                    break
                continue
            try:
                classified, used_model, got_labels = await classify_tweets_for_ticker(tweets, ticker)
                if used_model:
                    model_used = used_model
                if got_labels:
                    classified_any = True
                else:
                    skip_reason = skip_reason or "classifier_returned_no_labels"
            except Exception as e:
                print(f"[x_noise] classification failed for {ticker}: {e}")
                classified = tweets
                skip_reason = skip_reason or "classifier_returned_no_labels"
            per_ticker_results[ticker] = _aggregate_ticker_noise(
                classified, prev_per_ticker.get(ticker, {})
            )
            print(f"[x_noise] {ticker}: {per_ticker_results[ticker]['tweet_count']} tweets, "
                  f"dominant={per_ticker_results[ticker]['dominant_sentiment']}/"
                  f"{per_ticker_results[ticker]['dominant_class']}, "
                  f"bmb={per_ticker_results[ticker]['score_bull_minus_bear']:+.2f}")
            await asyncio.sleep(1)

    aggregate = _aggregate_overall_noise(per_ticker_results, prev_state)
    if not called_x:
        aggregate["unavailable_reason"] = skip_reason or "no_tickers_scanned"
    elif aggregate.get("total_tweets", 0) <= 0 and skip_reason:
        aggregate["unavailable_reason"] = skip_reason
    aggregate["called_x"] = called_x
    aggregate["http_last"] = http_seen[-1] if http_seen else _noise_last_http
    aggregate["http_seen"] = http_seen

    output = {
        "scanned_at":              datetime.now(EST).isoformat(),
        "lane":                    "noise",
        "called_x":                called_x,
        "http_last":               aggregate["http_last"],
        "tickers":                 per_ticker_results,
        "aggregate":               aggregate,
        "tickers_tracked":         tickers,
        "tickers_static":          static,
        "tickers_dynamic":         dynamic,
        "model_used":              model_used,
        "classifier_ran":          classified_any,
        "noise_searches_today":    _noise_searches_today,
        "noise_reserved":          NOISE_RESERVED_SEARCHES,
        "noise_credits_depleted":  _noise_credits_depleted,
        "keyword_credits_depleted": keyword_402,
        "oauth_dead":              _oauth_dead,
        "oauth_hint":              _OAUTH_FAIL_HINT if _oauth_dead else None,
    }

    # Atomic write
    tmp = X_NOISE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, default=str)
        os.replace(tmp, X_NOISE_FILE)
    except Exception as e:
        print(f"[x_noise] write failed: {e}")
        return output

    # Audit row (jsonl)
    try:
        with open(X_NOISE_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "scanned_at":              output["scanned_at"],
                "called_x":                called_x,
                "unavailable_reason":      aggregate.get("unavailable_reason"),
                "http_last":               aggregate.get("http_last"),
                "tickers_tracked":         tickers,
                "total_tweets":            aggregate["total_tweets"],
                "noise_volume_score":      aggregate["noise_volume_score"],
                "noise_sentiment_score":   aggregate["noise_sentiment_score"],
                "noise_velocity_score":    aggregate["noise_velocity_score"],
                "dominant_meta_emotion":   aggregate["dominant_meta_emotion"],
            }, default=str) + "\n")
    except Exception:
        pass

    print(f"[x_noise] done — called_x={called_x} "
          f"reason={aggregate.get('unavailable_reason')} "
          f"http={aggregate.get('http_last')} "
          f"total={aggregate['total_tweets']} "
          f"vol={aggregate['noise_volume_score']} "
          f"sent={aggregate['noise_sentiment_score']} "
          f"vel={aggregate['noise_velocity_score']} "
          f"meta={aggregate['dominant_meta_emotion']}")
    
    # Phase 2: sustained emotion pass — emit sustained_emotion envelopes for
    # tickers whose dominant_class has persisted across the threshold count.
    try:
        if PHASE2_ENABLED:
            _phase2_sustained_emotion_pass(per_ticker_results, output["scanned_at"])
        else:
            print("[x_intel][phase2] PARKED - no sustained-emotion pass "
                  "(set X_INTEL_PHASE2_ENABLED=true to unpark)")
    except Exception as e:
        print(f"[x_noise][phase2] sustained pass err: {e}")
    
    return output


# ════════════════════════════════════════════════════════════════════════════
# END SPRINT 35 v2.0 NOISE TRACKER
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
# PHASE 2: SUSTAINED EMOTION TRACKING
# ════════════════════════════════════════════════════════════════════════════
# Per-ticker emotional-class persistence. Fires sustained_emotion envelopes
# when same dominant_class persists across N consecutive scans.

X_INTEL_EMOTION_HISTORY_FILE = os.path.join(_LOGS, "x_intel_emotion_history.json")

# Threshold per class. Trade-relevant classes fire faster.
PHASE2_SUSTAINED_THRESHOLDS = {
    "fomo":                 3,   # trade-relevant — parabolic forming
    "capitulation":         3,   # trade-relevant — washout completing
    "exit_liquidity_vibes": 3,   # trade-relevant — distribution warning
    "accumulation_talk":    4,   # mild — smart money rotating in
    "hype":                 4,   # mild — could be authentic or pump
    "fud":                  4,   # mild — could be real concern or shakeout
    "bullish":              4,
    "bearish":              4,
    "neutral":              5,   # conservative — neutral persistence is less actionable
}

PHASE2_SUSTAINED_CAP = 20   # cap counter to prevent overflow

# Map class to envelope direction
_PHASE2_CLASS_DIRECTION = {
    "fomo":                 "bullish",
    "capitulation":         "bearish",
    "exit_liquidity_vibes": "bearish",
    "accumulation_talk":    "bullish",
    "hype":                 "bullish",
    "fud":                  "bearish",
    "bullish":              "bullish",
    "bearish":              "bearish",
    "neutral":              "neutral",
}


def _phase2_load_emotion_history() -> dict:
    """Load persistent emotion history. Shape:
      {
        "<ticker>": {
          "current_class":    str,
          "count":            int,                       # consecutive scans
          "first_seen_at":    iso,
          "last_seen_at":     iso,
          "last_emit_scan":   iso | null,
        }
      }
    """
    try:
        if os.path.exists(X_INTEL_EMOTION_HISTORY_FILE):
            with open(X_INTEL_EMOTION_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as e:
        print(f"[x_intel][phase2] history load err: {e}")
    return {}


def _phase2_save_emotion_history(history: dict) -> None:
    """Atomic save."""
    try:
        os.makedirs(os.path.dirname(X_INTEL_EMOTION_HISTORY_FILE), exist_ok=True)
        tmp = X_INTEL_EMOTION_HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, default=str)
        os.replace(tmp, X_INTEL_EMOTION_HISTORY_FILE)
    except Exception as e:
        print(f"[x_intel][phase2] history save err: {e}")


def _phase2_update_emotion_history(per_ticker_results: dict, scan_ts: str) -> dict:
    """Update per-ticker emotion streaks for this scan.
    
    For each ticker, compare current dominant_class to previous:
      - Match → increment count (capped)
      - Mismatch → reset count to 1 with new class
      - Ticker absent this scan → clear from history (streak broken)
    
    Returns updated history dict.
    """
    history = _phase2_load_emotion_history()
    
    # Process tickers present this scan
    tickers_this_scan = set()
    for ticker, result in (per_ticker_results or {}).items():
        if not isinstance(result, dict):
            continue
        # Only track tickers that actually had tweets — empty scans don't reset streak
        if result.get("tweet_count", 0) == 0:
            tickers_this_scan.add(ticker)  # mark as "seen" but skip update
            continue
        
        tickers_this_scan.add(ticker)
        current_class = result.get("dominant_class", "neutral")
        existing = history.get(ticker, {})
        prev_class = existing.get("current_class")
        
        if prev_class == current_class:
            # Streak continues
            new_count = min(existing.get("count", 0) + 1, PHASE2_SUSTAINED_CAP)
            history[ticker] = {
                "current_class":  current_class,
                "count":          new_count,
                "first_seen_at":  existing.get("first_seen_at", scan_ts),
                "last_seen_at":   scan_ts,
                "last_emit_scan": existing.get("last_emit_scan"),
            }
        else:
            # Class changed (or first scan for this ticker) → reset (incl. emit tracking)
            history[ticker] = {
                "current_class":   current_class,
                "count":           1,
                "first_seen_at":   scan_ts,
                "last_seen_at":    scan_ts,
                "last_emit_scan":  None,
                "last_emit_tier":  -1,  # no emit yet for this streak
            }
    
    # Tickers absent this scan → clear (streak broken)
    absent = [t for t in history.keys() if t not in tickers_this_scan]
    for t in absent:
        del history[t]
    
    _phase2_save_emotion_history(history)
    return history


# Severity tier boundaries — emit fires when count CROSSES these thresholds,
# not every scan. Tiers: medium (initial threshold), high (5+), critical (8+).
_PHASE2_SEVERITY_TIER_BOUNDARIES = [3, 5, 8]   # boundaries between medium/high/critical


def _phase2_severity_tier(count: int) -> int:
    """Return the severity tier index for a given count.
    0 = below medium, 1 = medium, 2 = high, 3 = critical."""
    tier = 0
    for boundary in _PHASE2_SEVERITY_TIER_BOUNDARIES:
        if count >= boundary:
            tier += 1
    return tier


def _phase2_should_emit_sustained(ticker: str, entry: dict) -> bool:
    """Decide whether to emit sustained_emotion for this ticker.
    
    Emit policy: fire ONCE when count first crosses class threshold, then
    again ONLY when count crosses a severity tier boundary (medium→high
    at count=5, high→critical at count=8). Prevents per-scan envelope spam
    while still surfacing meaningful escalations.
    
    Criteria:
      - count >= threshold for the current class
      - haven't already emitted at this exact scan timestamp (anti-dupe)
      - severity tier this scan is HIGHER than tier at last emit
        (or no previous emit for this streak)
    """
    current_class = entry.get("current_class", "neutral")
    count = entry.get("count", 0)
    threshold = PHASE2_SUSTAINED_THRESHOLDS.get(current_class, 4)
    
    if count < threshold:
        return False
    
    # Anti-dupe: same scan timestamp = already emitted
    last_emit = entry.get("last_emit_scan")
    last_seen = entry.get("last_seen_at")
    if last_emit and last_seen and last_emit == last_seen:
        return False
    
    # Tier-based dedup: only re-emit when severity tier escalates.
    # Track tier-at-last-emit on entry; emit only if current tier > that tier.
    last_emit_tier = entry.get("last_emit_tier", -1)
    current_tier = _phase2_severity_tier(count)
    if current_tier <= last_emit_tier:
        return False
    
    return True


def _phase2_emit_sustained_emotion_envelope(ticker: str, entry: dict,
                                              ticker_result: dict) -> bool:
    """Emit sustained_emotion signal contract envelope."""
    try:
        os.makedirs(SIGNAL_CONTRACTS_DIR, exist_ok=True)
        
        current_class = entry.get("current_class", "neutral")
        count = entry.get("count", 0)
        direction = _PHASE2_CLASS_DIRECTION.get(current_class, "neutral")
        
        # Severity scales: deeper streak = higher severity
        if count >= 8:
            severity = "critical"
        elif count >= 5:
            severity = "high"
        else:
            severity = "medium"
        
        expiry_hours = 6   # noise envelopes decay fast
        half_life = max(1, expiry_hours // 3)
        
        env_id = f"x_intel_sustained_{ticker}_{int(time.time())}_{_signal_secrets.token_hex(3)}"
        emitted_at = datetime.now(_signal_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = (datetime.now(_signal_tz.utc) + _signal_timedelta(hours=expiry_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        score_bmb = ticker_result.get("score_bull_minus_bear", 0)
        tweet_count = ticker_result.get("tweet_count", 0)
        
        headline = (
            f"[x_intel:sustained_emotion] ${ticker} {current_class.upper()} "
            f"persistent across {count} scans (bull-bear={score_bmb:+.2f})"
        )
        details = (
            f"X retail emotion class '{current_class}' has been dominant on ${ticker} "
            f"for {count} consecutive scans. Direction implication: {direction}. "
            f"Last scan: {tweet_count} tweets, bull-minus-bear score {score_bmb:+.2f}. "
            f"Sustained emotional regime, not one-off chatter."
        )
        
        envelope = {
            "_schema":    SIGNAL_CONTRACT_SCHEMA,
            "id":         env_id,
            "emitted_at": emitted_at,
            "expires_at": expires_at,
            "source": {
                "name":    "x_intel",
                "tier":    "B",   # social = always B tier (brigadeable)
                "version": "v1.0+sprint43_phase2",
            },
            "signal_type":     "sustained_emotion",
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
                "details":  details,
                "raw": {
                    "ticker":             ticker,
                    "affects_asset":      ticker,   # Phase 2 also doubles as per-asset routing
                    "emotional_class":    current_class,
                    "consecutive_scans":  count,
                    "first_seen_at":      entry.get("first_seen_at"),
                    "last_seen_at":       entry.get("last_seen_at"),
                    "tweet_count":        tweet_count,
                    "score_bull_minus_bear": score_bmb,
                    "sentiment_ratios":   ticker_result.get("sentiment_ratios", {}),
                    "velocity":           ticker_result.get("velocity", {}),
                    "timestamp":          datetime.now(EST).isoformat(),
                },
            },
        }
        
        final_path = os.path.join(SIGNAL_CONTRACTS_DIR, f"{env_id}.json")
        tmp_path = final_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, default=str)
        os.replace(tmp_path, final_path)
        
        # Mark emit at current scan timestamp + severity tier (anti-dupe)
        history = _phase2_load_emotion_history()
        if ticker in history:
            history[ticker]["last_emit_scan"] = entry.get("last_seen_at")
            history[ticker]["last_emit_tier"] = _phase2_severity_tier(count)
            _phase2_save_emotion_history(history)
        
        return True
    except Exception as e:
        print(f"[x_intel][phase2] sustained emit err for {ticker}: {e}")
        return False


PHASE2_ENABLED = _envv("X_INTEL_PHASE2_ENABLED", "false").lower() in ("1", "true", "yes")


def _phase2_sustained_emotion_pass(per_ticker_results: dict, scan_ts: str) -> int:
    """End-of-noise-scan: update emotion streaks + emit sustained envelopes.
    Returns count emitted."""
    if not per_ticker_results:
        return 0
    
    history = _phase2_update_emotion_history(per_ticker_results, scan_ts)
    
    emit_count = 0
    for ticker, entry in history.items():
        if _phase2_should_emit_sustained(ticker, entry):
            ticker_result = per_ticker_results.get(ticker, {})
            if _phase2_emit_sustained_emotion_envelope(ticker, entry, ticker_result):
                emit_count += 1
    
    if emit_count > 0:
        print(f"[x_intel][phase2] emitted {emit_count} sustained_emotion envelope(s)")
    return emit_count


# ════════════════════════════════════════════════════════════════════════════
# END PHASE 2
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
# PHASE 3: PER-ASSET ROUTING ON CATEGORY ENVELOPES
# ════════════════════════════════════════════════════════════════════════════
# we don't have shared modules between bots.

# Note: re is already imported at top of file
_PHASE3_ASSET_PATTERNS = [
    ("BTC", [
        re.compile(r"\bBTC\b"),
        re.compile(r"\bbitcoin\b(?!\s+cash)", re.IGNORECASE),
        # X uses $BTC convention heavily
        re.compile(r"\$BTC\b", re.IGNORECASE),
    ]),
    ("ETH", [
        re.compile(r"\bETH\b"),
        re.compile(r"\bethereum\b(?!\s+classic)", re.IGNORECASE),
        re.compile(r"\$ETH\b", re.IGNORECASE),
    ]),
    ("SOL", [
        re.compile(r"\bSOL\b"),
        re.compile(r"\bsolana\b", re.IGNORECASE),
        re.compile(r"\$SOL\b", re.IGNORECASE),
    ]),
    ("JUP", [
        re.compile(r"\bJUP\b"),
        re.compile(r"\bjupiter\b(?!\s+(?:airline|education))", re.IGNORECASE),
        re.compile(r"\$JUP\b", re.IGNORECASE),
    ]),
]


def _phase3_count_asset_mentions(text: str) -> dict:
    """Count asset mentions in a single text. Returns {asset: count}."""
    if not text:
        return {}
    counts = {"BTC": 0, "SOL": 0, "ETH": 0, "JUP": 0}
    for canonical, patterns in _PHASE3_ASSET_PATTERNS:
        # Each asset gets ONE hit per text even if multiple patterns match
        for pat in patterns:
            if pat.search(text):
                counts[canonical] += 1
                break
    return counts


def _phase3_determine_affects_asset(tweets_in_cat: list) -> str | None:
    """Tally asset mentions across all tweets in a category. Returns the
    dominant asset, or None if no asset is mentioned or no clear dominance.
    
    Dominance threshold: an asset must have 2x+ the mentions of any other
    AND appear in at least 33% of tweets. Otherwise, classify as
    multi-asset / macro (returns None).
    """
    if not tweets_in_cat:
        return None
    
    totals = {"BTC": 0, "SOL": 0, "ETH": 0, "JUP": 0}
    tweet_count = 0
    for t in tweets_in_cat:
        text = t.get("text", "") if isinstance(t, dict) else str(t)
        if not text:
            continue
        tweet_count += 1
        counts = _phase3_count_asset_mentions(text)
        for asset, c in counts.items():
            totals[asset] += c
    
    if tweet_count == 0 or sum(totals.values()) == 0:
        return None
    
    # Sort by count desc
    sorted_assets = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    top_asset, top_count = sorted_assets[0]
    second_count = sorted_assets[1][1] if len(sorted_assets) > 1 else 0
    
    if top_count <= tweet_count // 3:
        return None
    if second_count > 0 and top_count < second_count * 2:
        return None
    
    return top_asset


# ════════════════════════════════════════════════════════════════════════════
# END PHASE 3
# ════════════════════════════════════════════════════════════════════════════


# ── main scan ─────────────────────────────────────────────────────────────────


import hashlib as _lu_hashlib
import shutil as _lu_shutil

_LU_SELF         = os.path.abspath(__file__)
_LU_LASTGOOD     = _LU_SELF + ".last-good"
_LU_MARKER       = os.path.join(_LOGS, "x_intel_reload_marker.json")
_LU_STOP_FILE    = os.path.join(_LOGS, "x_intel_no_reload")
_LU_OWNER_INBOX   = os.path.join(os.path.dirname(_BASE), "owner_inbox")
_LU_SOURCE_SKILL = "x-intel"
_LU_POLL_S       = 30
_LU_MIN_UPTIME_S = 120
_LU_AUTORELOAD   = True
_LU_BOOT_TS      = time.time()
_LU_IN_FLIGHT    = 0          # scans + bookmark POSTs
_lu_pending_reported = False


def _lu_enter():
    global _LU_IN_FLIGHT
    _LU_IN_FLIGHT += 1


def _lu_exit():
    global _LU_IN_FLIGHT
    _LU_IN_FLIGHT = max(0, _LU_IN_FLIGHT - 1)


def _lu_inflight(fn):
    """Decorator: mark a critical section so no reload fires inside it."""
    async def _wrapped(*a, **kw):
        _lu_enter()
        try:
            return await fn(*a, **kw)
        finally:
            _lu_exit()
    _wrapped.__name__ = getattr(fn, "__name__", "wrapped")
    _wrapped.__doc__ = fn.__doc__
    return _wrapped


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
    try:
        os.makedirs(_LU_OWNER_INBOX, exist_ok=True)
        ts = datetime.now(EST).strftime("%Y%m%d_%H%M%S")
        lines = [
            "---",
            f"kind: {kind}",
            f"severity: {severity}",
            f"dedupe_key: x_intel:{kind}:{detail.get('to_hash', _LU_BOOT_HASH)}",
            f"source_skill: {_LU_SOURCE_SKILL}",
            f"summary: {summary}",
            "---",
            "",
            f"# {kind} - x_intel",
            "",
            f"**Time:** {datetime.now(EST).isoformat()}",
            f"**Summary:** {summary}",
            "",
            "## Detail",
            "",
        ]
        for k, v in detail.items():
            lines.append(f"- **{k}:** {v}")
        with open(os.path.join(_LU_OWNER_INBOX, f"x_intel - {kind}_{ts}.md"),
                  "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(f"[x_intel][live-update] report [{kind}]")
    except Exception as e:
        print(f"[x_intel][live-update] report err: {e}")


def _lu_snapshot_last_good() -> None:
    try:
        _lu_shutil.copy2(_LU_SELF, _LU_LASTGOOD)
    except Exception as e:
        print(f"[x_intel][live-update] last-good snapshot err: {e}")


def _lu_on_boot() -> None:
    marker = None
    try:
        if os.path.exists(_LU_MARKER):
            with open(_LU_MARKER, "r", encoding="utf-8") as fh:
                marker = json.load(fh)
    except Exception:
        marker = None
    if marker:
        _lu_write_report(
            "bot_restart", "info",
            f"x_intel rebooted to {_LU_BOOT_HASH}, healthy",
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
    """Full compile(), not ast.parse - a mid-write save must not be exec'd."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        compile(src, path, "exec")
        return True
    except Exception:
        return False


async def live_update_watcher_loop() -> None:
    global _lu_pending_reported
    print(f"[x_intel][live-update] watching (poll {_LU_POLL_S}s, boot {_LU_BOOT_HASH})")
    while True:
        try:
            changed = (_lu_mtime(_LU_SELF) > _LU_BOOT_MTIME
                       and _lu_hash(_LU_SELF) != _LU_BOOT_HASH)
            if changed:
                new_hash = _lu_hash(_LU_SELF)
                stop = os.path.exists(_LU_STOP_FILE)
                if (not _LU_AUTORELOAD) or stop:
                    if not _lu_pending_reported:
                        _lu_write_report(
                            "bot_restart_failed", "high",
                            f"x_intel patch {new_hash} landed; auto-reload OFF, MANUAL "
                            f"RESTART needed (still running old {_LU_BOOT_HASH})",
                            {"to_hash": new_hash,
                             "reason": "stop_file" if stop else "autoreload_disabled"},
                        )
                        _lu_pending_reported = True
                elif (time.time() - _LU_BOOT_TS) < _LU_MIN_UPTIME_S:
                    pass
                elif _LU_IN_FLIGHT != 0:
                    print(f"[x_intel][live-update] patch {new_hash} pending - "
                          f"{_LU_IN_FLIGHT} op(s) in flight")
                elif not _lu_compiles(_LU_SELF):
                    print(f"[x_intel][live-update] {new_hash} does not compile yet "
                          "(mid-write?) - retrying next tick")
                else:
                    _lu_snapshot_last_good()
                    try:
                        tmp = _LU_MARKER + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as fh:
                            json.dump({"from_hash": _LU_BOOT_HASH, "to_hash": new_hash,
                                       "detected_at": datetime.now(EST).isoformat(),
                                       "lastgood": _LU_LASTGOOD}, fh, indent=2)
                        os.replace(tmp, _LU_MARKER)
                    except Exception:
                        pass
                    print(f"[x_intel][live-update] reloading {_LU_BOOT_HASH} -> {new_hash}")
                    try:
                        os.execv(sys.executable, [sys.executable, _LU_SELF] + sys.argv[1:])
                    except Exception as e:
                        print(f"[x_intel][live-update] execv failed, staying on old code: {e}")
                        _lu_write_report(
                            "bot_restart_failed", "high",
                            f"x_intel patch {new_hash} detected but re-exec failed; "
                            f"STILL RUNNING old {_LU_BOOT_HASH}",
                            {"error": str(e)[:200], "to_hash": new_hash},
                        )
                        try:
                            os.remove(_LU_MARKER)
                        except Exception:
                            pass
        except Exception as e:
            print(f"[x_intel][live-update] watcher err: {e}")
        await asyncio.sleep(_LU_POLL_S)


@_lu_inflight
async def run_scan(light: bool = False):
    """Full intel scan - bookmarks + likes + keyword search.

    light=True (pre-sweep path): bookmarks and likes only. No keyword fanout,
    no noise scan. The 2h main loop owns the daily search budget.
    """
    global _refresh_attempted_this_cycle
    _refresh_attempted_this_cycle = False  # reset for this cycle
    _load_search_state()
    _mode = "LIGHT (pre-sweep)" if light else "FULL"
    print(f"\n[x_intel] === Scan {_mode} | {datetime.now(EST).strftime('%H:%M ET')} ===")

    async with httpx.AsyncClient(timeout=15) as client:
        # fetch bookmarks and likes in parallel
        bookmarks, likes = await asyncio.gather(
            fetch_bookmarks(client),
            fetch_likes(client),
        )

        # keyword searches - stagger to avoid rate limits
        search_results = []
        if not light:
            for query in SEARCH_QUERIES:
                results = await fetch_keyword_search(client, query)
                search_results.extend(results)
                await asyncio.sleep(1)  # 1s between searches

    # combine all intel
    all_intel = bookmarks + likes + search_results

    # deduplicate by tweet ID or text prefix
    seen = set()
    unique_intel = []
    for item in all_intel:
        key = item.get("id") or item.get("text", "")[:50]
        if key not in seen:
            seen.add(key)
            item["category"]  = categorize_tweet(item.get("text", ""))
            item["relevance"] = score_tweet_relevance(item)
            unique_intel.append(item)

    # filter low relevance
    filtered = [t for t in unique_intel if t["relevance"] >= 5]
    filtered.sort(key=lambda x: x["relevance"], reverse=True)

    # group by category
    by_category = {}
    for item in filtered:
        cat = item["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(item)

    # top picks
    top_picks = filtered[:5]

    # build output
    output = {
        "last_updated":    datetime.now(EST).isoformat(),
        "scan_summary": {
            "bookmarks_fetched":  len(bookmarks),
        "oauth_healthy":      not _oauth_dead,
        "oauth_dead_since":   _oauth_dead_since if _oauth_dead else None,
        "searches_today":     _searches_today,
        "searches_limit":     MAX_SEARCHES_PER_DAY,
        "credits_depleted":   _credits_depleted,
            "likes_fetched":      len(likes),
            "search_results":     len(search_results),
            "total_after_filter": len(filtered),
        },
        "top_picks":       top_picks,
        "by_category":     by_category,
        "bookmarks_raw":   bookmarks[:20],  # full bookmark list for the agent
    }

    # write output
    tmp = X_INTEL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    os.replace(tmp, X_INTEL_FILE)
    
    try:
        env_count = _signal_emit_envelopes_from_scan(by_category)
        if env_count > 0:
            print(f"[x_intel][signal] emitted {env_count} envelope(s) to signal_contracts/")
    except Exception as e:
        print(f"[x_intel][signal] emit pass failed: {e}")

    # write bookmark history separately
    existing_bookmarks = []
    if os.path.exists(X_BOOKMARK_FILE):
        try:
            with open(X_BOOKMARK_FILE) as f:
                existing_bookmarks = json.load(f)
        except Exception:
            pass

    # append new bookmarks not already in history
    existing_ids = {b.get("id") for b in existing_bookmarks}
    new_bookmarks = [b for b in bookmarks if b.get("id") not in existing_ids]
    if new_bookmarks:
        existing_bookmarks = (new_bookmarks + existing_bookmarks)[:500]
        tmp = X_BOOKMARK_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(existing_bookmarks, f, indent=2, default=str)
        os.replace(tmp, X_BOOKMARK_FILE)
        print(f"[x_intel] {len(new_bookmarks)} new bookmarks added to history")

    _write_heartbeat("scan", last_scan_items=len(filtered))

    print(f"[x_intel] scan done — {len(filtered)} relevant items | top: {top_picks[0]['text'][:60] if top_picks else 'none'}")

    # Noise is its own lane. Keyword 402 / daily keyword count cannot skip it.
    if light:
        print("[x_intel] light scan complete - keyword fanout and noise scan skipped")
        return output
    try:
        await run_noise_scan()
    except Exception as e:
        print(f"[x_noise] scan failed cleanly: {e}")

    return output

# ── bookmark executor ────────────────────────────────────────────────────────
@_lu_inflight
async def execute_bookmark_signal():
    """
    Watch for x_bookmark_signal.json written by the agent.
    The agent writes: {"tweet_id": "123", "reason": "why he bookmarked it"}
    x_intel executes the API call and deletes the file.
    """
    if not os.path.exists(X_BOOKMARK_SIGNAL):
        return

    try:
        with open(X_BOOKMARK_SIGNAL) as f:
            signal = json.load(f)

        tweet_id = signal.get("tweet_id", "")
        reason   = signal.get("reason", "")

        if not tweet_id:
            os.remove(X_BOOKMARK_SIGNAL)
            return

        intel_token   = os.getenv("X_INTEL_TOKEN", "")
        agent_userid = os.getenv("X_USER_ID", "")

        if not intel_token or not agent_userid:
            print("[x_intel] bookmark skipped — missing token or user ID")
            return

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.twitter.com/2/users/{agent_userid}/bookmarks",
                headers={
                    "Authorization": f"Bearer {intel_token}",
                    "Content-Type": "application/json"
                },
                json={"tweet_id": tweet_id}
            )
            if r.status_code in (200, 201):
                print(f"[x_intel] the agent bookmarked {tweet_id} — {reason[:60]}")
                # log to bookmark history
                existing = []
                if os.path.exists(X_BOOKMARK_FILE):
                    try:
                        with open(X_BOOKMARK_FILE) as f:
                            existing = json.load(f)
                    except Exception:
                        pass
                existing.insert(0, {
                    "id":         tweet_id,
                    "reason":     reason,
                    "bookmarked_by": "agent_autonomous",
                    "ts":         datetime.now(EST).isoformat(),
                    "source":     "agent_curation",
                })
                existing = existing[:500]
                tmp = X_BOOKMARK_FILE + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(existing, f, indent=2, default=str)
                os.replace(tmp, X_BOOKMARK_FILE)
            elif r.status_code == 401:
                print("[x_intel] bookmark 401 — refreshing token")
                new_token = refresh_access_token()
                if new_token:
                    load_dotenv(override=True)
            else:
                print(f"[x_intel] bookmark failed {r.status_code}: {r.text[:100]}")

        # always delete signal file after processing
        os.remove(X_BOOKMARK_SIGNAL)

    except Exception as e:
        print(f"[x_intel] bookmark executor error: {e}")
        try:
            os.remove(X_BOOKMARK_SIGNAL)
        except Exception:
            pass


# ── main loop ─────────────────────────────────────────────────────────────────


def _write_heartbeat(beat: str, last_scan_items: int = None) -> None:
    """v2.5: one heartbeat writer, and it carries degradation.

    `status` is degraded whenever the bot cannot actually do its job - OAuth
    dead (no bookmarks/likes), keyword budget spent, or credits flagged - so a
    monitor can tell "running" from "working". The old writers hardcoded
    status:alive and hid every outage behind a fresh mtime.
    """
    reasons = []
    if _oauth_dead:
        reasons.append("oauth_dead")
    if _credits_depleted:
        reasons.append("keyword_credits_depleted")
    if _noise_credits_depleted:
        reasons.append("noise_credits_depleted")
    if _searches_today >= KEYWORD_SEARCH_BUDGET:
        reasons.append("keyword_budget_spent")
    if not BEARER_TOKEN:
        reasons.append("no_bearer_token")
    payload = {
        "timestamp":               datetime.now(EST).isoformat(),
        "status":                  "degraded" if reasons else "alive",
        "beat":                    beat,
        "degraded_reasons":        reasons,
        "oauth_healthy":           not _oauth_dead,
        "searches_today":          _searches_today,
        "searches_limit":          MAX_SEARCHES_PER_DAY,
        "keyword_budget":          KEYWORD_SEARCH_BUDGET,
        "keyword_credits_depleted": _credits_depleted,
        "noise_reserved":          NOISE_RESERVED_SEARCHES,
        "noise_searches_today":    _noise_searches_today,
        "noise_credits_depleted":  _noise_credits_depleted,
    }
    if last_scan_items is not None:
        payload["last_scan_items"] = last_scan_items
    try:
        tmp = HB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        os.replace(tmp, HB_FILE)
    except Exception as e:
        print(f"[x_intel] heartbeat write err: {e}")


async def _main_scan_and_bookmark_loop():
    """Existing scan + bookmark poll loop, extracted for asyncio.gather."""
    while True:
        try:
            await run_scan()
        except Exception as e:
            print(f"[x_intel] scan error: {e}")
            import traceback; traceback.print_exc()
        
        # check for the agent bookmark signals between full scans
        for _ in range(POLL_INTERVAL // 60):
            await execute_bookmark_signal()
            await asyncio.sleep(60)


async def main():
    print("[x_intel] X Intelligence Reader online")
    print(f"[x_intel] Polling every {POLL_INTERVAL//3600} hours")
    print(f"[x_intel] Output: {X_INTEL_FILE}")
    print(f"[x_intel] Daily search cap: {MAX_SEARCHES_PER_DAY} queries")

    # Load today's search state (respects credit budget across restarts)
    _load_search_state()
    _load_noise_state()
    if _credits_depleted:
        print("[x_intel] keyword 402 today — keyword search disabled until midnight. noise lane is independent.")
    elif _searches_today > 0:
        print(f"[x_intel] keyword resuming: {_searches_today}/{KEYWORD_SEARCH_BUDGET}")
    if _noise_credits_depleted:
        print("[x_intel] noise 402 today — noise lane paused until midnight")
    elif _noise_searches_today > 0:
        print(f"[x_intel] noise resuming: {_noise_searches_today}/{NOISE_RESERVED_SEARCHES}")

    if not INTEL_TOKEN or INTEL_TOKEN == "your_oauth2_token_here":
        print("[x_intel] ⚠️ X_INTEL_TOKEN not set — bookmarks/likes disabled (search still runs)")
    if not USER_ID:
        print("[x_intel] ⚠️ X_USER_ID not set — bookmarks/likes disabled")
    if not BEARER_TOKEN:
        print("[x_intel] ⚠️ X_Bearer_Token not set — keyword search disabled")

    
    # v2.5: report a completed reload / set the last-good baseline before work.
    _lu_on_boot()

    # Run main scan loop + live-update watcher concurrently
    await asyncio.gather(
        _main_scan_and_bookmark_loop(),
        live_update_watcher_loop(),
    )

if __name__ == "__main__":
    asyncio.run(main())