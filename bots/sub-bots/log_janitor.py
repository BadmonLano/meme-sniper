"""log_janitor.py — v2.5.0 (Sprint 38-adjacent — GPM Cert 007 fixes)
=================================================================

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
import shutil
import hashlib
import re
import asyncio
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

EST     = ZoneInfo("America/New_York")
_BASE   = WS_BOTS                                                  # <workspace>/bots
_LOGS   = WS_BOT_LOGS

_HEARTBEAT_FILE = os.path.join(_LOGS, "log_janitor_heartbeat.json")

def _write_bot_heartbeat(status: str = "alive", **extra) -> None:
    try:
        now_iso = datetime.now(EST).isoformat()
        payload = {"components": {"log_janitor": {"status": status, "last_update": now_iso,
                                                    "pid": os.getpid(),
                                                    "note": "deep clean is 14d cadence; this beat is the hourly disk guard",
                                                    **extra}},
                    "last_overall_update": now_iso}
        tmp = _HEARTBEAT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, _HEARTBEAT_FILE)
    except Exception as _hbe:
        log(f"heartbeat write err: {_hbe}")
_ARCHIVE = os.path.join(_LOGS, "archive")

# Sprint 29.7 — workspace-wide paths beyond bot_logs/
_WORKSPACE = WS_ROOT                                  # …\workspace
_INBOX     = os.path.join(_WORKSPACE, "inbox")
_INBOX_RES = os.path.join(_WORKSPACE, "inbox_results", "done")
_LEARN_INBOX   = os.path.join(_LOGS, "learnings_inbox")
_LEARN_ARCH    = os.path.join(_LOGS, "learnings_archive")
_AUTOPSY_DIR   = os.path.join(_LOGS, "autopsy_reports")

# Sprint 33+ — inbox_results curation (this session)
_INBOX_DISCARDED = os.path.join(_WORKSPACE, "inbox_results", "discarded")

# Sprint 42 — protected paths (code_tuner owns these; janitor never touches)
# These are directory basenames; prune_old_files() refuses to operate on them.
_SPRINT42_PROTECTED_DIRS = frozenset([
    "source_snapshots",   # code_tuner full-file snapshots (rotation owned by code_tuner)
])

_SPRINT42_PROTECTED_FILES = frozenset([
    "bots_list.json",        # code_tuner + warden dual-owned registry
    "metrics_current.json",  # code_tuner refreshes every 30 min
    "code_tuner_perf_state.json",            # per-bot perf cycle state
    "code_tuner_deep_audit_state.json",      # per-bot deep audit state
    "code_tuner_heartbeat.json",             # warden Layer 4 input
    "code_tuner.log",                        # code_tuner operations log (has its own trim cadence)
])

os.makedirs(_ARCHIVE, exist_ok=True)

def _run_stamp():
    """Date stamp for archive files and discard folders.

    Computed when a run uses it, not frozen at import. A long-lived process
    must not keep rewriting one archive file and one discard folder forever.
    """
    return datetime.now(EST).strftime("%Y-%m-%d")


_DEEP_CLEAN_STAMP_FILE = os.path.join(_LOGS, "log_janitor_last_deep_clean.json")
_DEEP_CLEAN_INTERVAL = timedelta(days=14)


def _read_last_deep_clean():
    """Last successful deep-clean time, or None when it cannot be proved.

    A missing, unreadable, or incomplete stamp is not a timestamp. Callers
    must not invent one and must not skip a deep clean on that basis.
    """
    try:
        with open(_DEEP_CLEAN_STAMP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        raw = data.get("finished_at")
        if not raw or not isinstance(raw, str):
            return None
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=EST)
        return dt.astimezone(EST)
    except Exception:
        return None


def _write_last_deep_clean():
    """Persist success only after a deep-clean pass actually finishes."""
    now = datetime.now(EST)
    payload = {"finished_at": now.isoformat(), "version": "v2.5.0"}
    os.makedirs(_LOGS, exist_ok=True)
    tmp = _DEEP_CLEAN_STAMP_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, _DEEP_CLEAN_STAMP_FILE)


def _is_protected_or_canary(path_or_name):
    """Lockpass (2026-08-06): hard refuse-to-touch. NEVER prune/purge a canary (doctrine:
    canary is the tripwire, code must hard-block it) or a Sprint-42 protected file - no
    matter what list names it. Enforced, not just logged."""
    p = str(path_or_name).replace("\\", "/").lower()
    if "canary" in p:
        return True
    return os.path.basename(str(path_or_name)) in _SPRINT42_PROTECTED_FILES


_INBOX_CLASSIFIER_RULES = [
    ("sniper_daily_read_audit_",      "keep", "sniper_daily_read_audit"),
    # Autopsy reports — the agent's deep-dive postmortems on trades
    ("autopsy_",                      "keep", "autopsy_report"),
    ("sniper_autopsy_",               "keep", "sniper_autopsy"),
    # The agent's decisions / intel
    ("agent_decision_",              "keep", "agent_decision"),
    ("agent_intel_",                 "keep", "agent_intel"),
    # Overseer judgments — the agent reviews these himself (not a Claude-as-judge path)
    ("overseer_",                     "keep", "overseer_judgment"),
    # Generic signal-rejection packets that include reasoning (training negative examples)
    ("signal_rejected_",              "keep", "signal_rejection"),
    ("meme_signal_rejected_",         "keep", "meme_signal_rejection"),

    ("P2_meme_sniper_patch_landed_ack_", "keep", "sniper_patch_landed_ack"),

    ("P2_sniper_meeting_response_",   "inspect_meeting_response", "sniper_meeting_response"),

    (".json",                "discard", "bare_json_junk_artifact"),  # a file literally named ".json"


    # Per-bot 2-day perf reviews (rolling, every 48h per bot, ~16 bots)
    ("P3_perf_review_",               "keep", "code_tuner_perf_review"),
    # 30-day deep audit packets (per-bot, monthly cadence)
    ("P3_deep_audit_",                "keep", "code_tuner_deep_audit"),
    # Source delta packets — fired when a tracked bot/skill source hash changes
    ("P3_source_updated_",            "keep", "code_tuner_source_delta"),
    # Source-fetch packets (the agent requested a specific function/lines via meeting_watcher)
    ("P3_source_fetch_",              "keep", "code_tuner_source_fetch"),

    # Setup mode packets — the agent's bot configuration audit trail (high signal: shows
    # which bots the agent deemed worth monitoring vs skipping, with reasoning)
    ("P3_code_tuner_setup_invitation_", "keep", "code_tuner_setup_invitation"),
    ("P3_code_tuner_discovery_",      "keep", "code_tuner_setup_discovery"),
    ("P2_code_tuner_setup_rejected_", "keep", "code_tuner_setup_rejected"),

    # code_tuner meeting_watcher response packets (same status surface as bot
    # meeting responses; same inspect_meeting_response handler applies)
    ("P2_code_tuner_meeting_response_", "inspect_meeting_response", "code_tuner_meeting_response"),

    ("P2_code_request_routed_",       "keep", "code_tuner_owner_routing"),

    # ── DISCARD: noise (caller still inspects content for size=0, dup, etc.) ──
    # Routine poll cycles that produced nothing actionable
    ("scan_no_action_",               "discard", "no_action_scan"),
    ("poll_empty_",                   "discard", "empty_poll"),
    ("heartbeat_drop_",               "discard", "heartbeat_drop"),

    # ── LEGACY / HISTORICAL PREFIXES (pre-Sprint 33/41 classifier, May 2026 and earlier) ──
    # These were flooding the unknown list; all historical training/audit data → KEEP
    ("2026",                        "keep", "legacy_date_prefixed"),
    ("P1_",                         "keep", "legacy_warden_p1"),
    ("P2_",                         "keep", "legacy_warden_p2"),
    ("P3_",                         "keep", "legacy_warden_p3"),
    ("1_x",                         "keep", "legacy_x_evt"),
    ("j6_action_",                  "keep", "j6_action"),
    ("owner_signal_",                "keep", "owner_signal"),
    ("meme_sniper_",                "keep", "meme_sniper_packet"),
    ("missed_runner_",              "keep", "missed_runner"),
    ("sniper_morning_",             "keep", "sniper_morning"),
    ("temp_meme_",                  "keep", "temp_meme"),
    ("weight_fit_",                 "keep", "weight_fit"),
    ("x_evt_",                      "keep", "x_evt_legacy"),
    ("janitor_anomaly_",            "keep", "janitor_anomaly"),

    # ── 2026-08-19: unknown inbox_results/done prefixes (492-file anomaly) ──
    ("browser_state",               "keep", "browser_state"),
    ("code_tuner",                  "keep", "code_tuner"),
    ("coin_call",                   "keep", "coin_call"),
    ("decision_agent",             "keep", "decision_agent"),
    ("inbox_digest",                "keep", "inbox_digest"),
    ("opportunity_refire",          "keep", "opportunity_refire"),
    ("position_check",              "keep", "position_check"),
    ("x_action",                    "keep", "x_action"),
    ("Eve_",                        "keep", "token_named_sniper_receipt"),
    ("TOAD_",                       "keep", "token_named_sniper_receipt"),

    # DISCARD: drain/temp cruft in done/ only. never live inbox.
    ("drain2_",                     "discard", "drain_script_cruft"),
    ("drain3_",                     "discard", "drain_script_cruft"),
    ("t00.txt",                     "discard", "scratch_txt"),
    ("t01.txt",                     "discard", "scratch_txt"),
    ("t02.txt",                     "discard", "scratch_txt"),
    ("t03.txt",                     "discard", "scratch_txt"),
    ("t04.txt",                     "discard", "scratch_txt"),
    ("t05.txt",                     "discard", "scratch_txt"),
    ("t06.txt",                     "discard", "scratch_txt"),
    ("t07.txt",                     "discard", "scratch_txt"),
    ("t08.txt",                     "discard", "scratch_txt"),
    ("t09.txt",                     "discard", "scratch_txt"),
    ("t10.txt",                     "discard", "scratch_txt"),
    ("t11.txt",                     "discard", "scratch_txt"),
    ("_hb0123",                     "discard", "heartbeat_scratch"),
    ("_pass",                       "discard", "drain_pass_scratch"),
    ("_sniper",                     "discard", "sniper_scratch"),
    ("_tmp",                        "discard", "tmp_scratch"),

    ("_drain",                      "discard", "drain_scratch"),
    ("_v.txt",                      "discard", "scratch_v_txt"),
]

# Discard reasons (used by classifier output for audit clarity)
_DISCARD_REASONS = {
    "empty_file":          "file is 0 bytes or empty JSON object",
    "duplicate":           "content hash matches another file within 1h window",
    "matched_discard_rule": "filename matched a discard classifier rule",
    "failed_no_recovery":  "packet contains error field with no recovery path",
}


_DUP_WINDOW_S = 3600


def _hash_is_recent_duplicate(file_hash, file_mtime, seen):
    """True only if an identical file already seen this scan is within 1 hour.

    seen must be hash -> list of mtimes. A bare set of hashes (any match in the
    done/ scan) is not a 1-hour window and does not discard.
    """
    if not file_hash or file_mtime is None or not isinstance(seen, dict):
        return False
    times = seen.get(file_hash) or []
    try:
        fm = float(file_mtime)
    except (TypeError, ValueError):
        return False
    for t in times:
        try:
            if abs(fm - float(t)) <= _DUP_WINDOW_S:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _classify_inbox_result_file(filepath, content_hash_seen_recently=None, file_mtime=None):
    """Classify a single file in inbox_results/done/.
    
    Returns: (action: "keep"|"discard"|"unknown", label: str, reason: str|None, file_hash: str|None)
    
    The classifier is conservative: when in doubt, KEEP. False keeps cost
    disk space. False discards lose training data forever.
    """
    fname = os.path.basename(filepath)
    
    # Quick check: empty file
    try:
        size = os.path.getsize(filepath)
        if size <= 2:  # empty or just "{}" or "[]"
            return ("discard", "empty_file", _DISCARD_REASONS["empty_file"], None)
    except OSError:
        return ("unknown", "unreadable", "stat failed", None)
    
    # Match classifier rules by prefix
    classification = None
    label = None
    for prefix, action, lbl in _INBOX_CLASSIFIER_RULES:
        if fname.startswith(prefix):
            classification = action
            label = lbl
            break

    if classification is None and re.match(r"^[a-z][a-z0-9_]+ - .+", fname):
        classification = "keep"
        label = "conforming_bot_packet"
    
    # Read content for inspection-required cases + dedup hashing
    file_hash = None
    payload = None
    raw_text = None
    if classification in ("inspect_meeting_response", "keep") or classification is None:
        try:
            with open(filepath, "rb") as f:
                raw = f.read()
            file_hash = hashlib.sha1(raw).hexdigest()[:16]
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = None  # not JSON, that's fine for non-packet files
            try:
                raw_text = raw.decode("utf-8", errors="ignore")
            except Exception:
                raw_text = None
        except Exception:
            return ("unknown", "unreadable", "read failed", None)

    if classification == "inspect_meeting_response":
        if raw_text and "**status:**" in raw_text:
            return ("keep", label, None, file_hash)
        # Malformed meeting response (no status field) — keep but anomaly flag
        return ("keep", label, None, file_hash)

    # Generic KEEP path — check for dup against recent set
    if classification == "keep":
        if _hash_is_recent_duplicate(file_hash, file_mtime, content_hash_seen_recently):
            return ("discard", label, _DISCARD_REASONS["duplicate"], file_hash)
        return ("keep", label, None, file_hash)

    if classification == "discard":
        return ("discard", label, _DISCARD_REASONS["matched_discard_rule"], file_hash)

    # No prefix matched — unknown. Default to KEEP and let the agent triage.
    return ("unknown", "unrecognized_prefix", "no classifier rule matched filename", file_hash)


def _write_anomaly_packet(anomaly_type, summary, details):
    """Write a janitor anomaly packet to workspace/inbox/ for the agent's review.
    
    Doctrine: packets go to inbox/, NEVER inbox_results/. Anomaly packets are
    for things that genuinely need the agent's eyes — unknown file types, zero-output
    BAILs, abnormal discard volumes. Routine "I ran successfully" never writes one.
    """
    try:
        os.makedirs(_INBOX, exist_ok=True)
        ts = datetime.now(EST).strftime("%Y%m%d_%H%M%S")
        filename = f"log_janitor - anomaly_{anomaly_type}_{ts}.json"
        filepath = os.path.join(_INBOX, filename)
        
        packet = {
            "id":          f"log_janitor_anomaly_{anomaly_type}_{ts}",
            "type":        "janitor_anomaly",
            "from":        "log_janitor",
            "to":          "agent",
            "_written_at": datetime.now(EST).isoformat(),
            "_doctrine":   "log_janitor detected something that needs the agent's eyes. Routine maintenance never writes packets; anomalies do. Packets land in workspace/inbox/, NEVER inbox_results/.",
            "anomaly_type": anomaly_type,
            "summary":      summary,
            "details":      details,
            "expires_at":   (datetime.now(EST) + timedelta(days=14)).isoformat(),
        }
        
        tmp = filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(packet, f, indent=2, default=str)
        os.replace(tmp, filepath)
        log(f"anomaly packet written: {filename}")
        return filepath
    except Exception as e:
        log(f"anomaly packet write FAILED: {e}")
        return None


def curate_inbox_results_done():
    """Sprint 33+ replacement for the indiscriminate 60-day prune of inbox_results/done/.
    
    Classifies every file:
      - KEEP → stays in done/ (training data goldmine, kept indefinitely)
      - DISCARD → moved to inbox_results/discarded/<YYYY-MM-DD>/<filename>
      - UNKNOWN → kept + logged in unknown_types list, anomaly packet written
    
    Then runs a 30-day prune over the discarded folder (final-stage delete).
    """
    if not os.path.exists(_INBOX_RES):
        return
    
    os.makedirs(_INBOX_DISCARDED, exist_ok=True)
    today_discard_dir = os.path.join(_INBOX_DISCARDED, _run_stamp())
    
    # Stats
    kept = 0
    discarded = 0
    unknowns = []
    discard_label_counts = {}
    keep_label_counts = {}
    discard_examples = []  # first 5 of each label for the log
    
    # Hash -> mtimes seen this scan. A duplicate is discarded only when another
    # identical file is within 1 hour, not because the hash appears anywhere in done/.
    recent_hash_times = {}
    
    files = []
    try:
        files = [f for f in os.listdir(_INBOX_RES)
                 if os.path.isfile(os.path.join(_INBOX_RES, f))]
    except Exception as e:
        log(f"curate_inbox_results_done: listdir failed: {e}")
        return
    
    if not files:
        log("inbox_results/done/: empty, nothing to curate")
        return
    
    log(f"inbox_results/done/: curating {len(files)} files...")
    
    for fname in files:
        fpath = os.path.join(_INBOX_RES, fname)
        try:
            fmtime = os.path.getmtime(fpath)
        except OSError:
            fmtime = None
        action, label, reason, fhash = _classify_inbox_result_file(
            fpath, recent_hash_times, fmtime)
        
        if fhash and fmtime is not None:
            recent_hash_times.setdefault(fhash, []).append(fmtime)
        
        if action == "keep":
            kept += 1
            keep_label_counts[label] = keep_label_counts.get(label, 0) + 1
            continue
        
        if action == "discard":
            try:
                os.makedirs(today_discard_dir, exist_ok=True)
                target = os.path.join(today_discard_dir, fname)
                # If target exists (re-run on same day), append a numeric suffix
                if os.path.exists(target):
                    name, ext = os.path.splitext(fname)
                    i = 1
                    while os.path.exists(os.path.join(today_discard_dir, f"{name}_{i}{ext}")):
                        i += 1
                    target = os.path.join(today_discard_dir, f"{name}_{i}{ext}")
                shutil.move(fpath, target)
                discarded += 1
                discard_label_counts[label] = discard_label_counts.get(label, 0) + 1
                if discard_label_counts[label] <= 3:
                    discard_examples.append({"file": fname, "label": label, "reason": reason})
            except Exception as e:
                log(f"  failed to discard {fname}: {e}")
            continue
        
        if action == "unknown":
            kept += 1
            keep_label_counts["unknown_kept"] = keep_label_counts.get("unknown_kept", 0) + 1
            unknowns.append({"file": fname, "reason": reason})
            continue
    
    # Log summary
    log(f"  KEPT:      {kept} files")
    if keep_label_counts:
        for lbl, n in sorted(keep_label_counts.items(), key=lambda x: -x[1])[:8]:
            log(f"    {lbl}: {n}")
    log(f"  DISCARDED: {discarded} files → {today_discard_dir}")
    if discard_label_counts:
        for lbl, n in sorted(discard_label_counts.items(), key=lambda x: -x[1]):
            log(f"    {lbl}: {n}")
    
    # Anomaly: unknown file types — surface to the agent so he can add a classifier rule
    if unknowns:
        # Group by inferred prefix (first 2 underscore-separated tokens)
        prefix_groups = {}
        for u in unknowns:
            tokens = u["file"].split("_")
            inferred = "_".join(tokens[:2]) if len(tokens) >= 2 else u["file"]
            prefix_groups.setdefault(inferred, []).append(u["file"])
        
        log(f"  UNKNOWNS:  {len(unknowns)} files (kept by default, anomaly packet written)")
        for prefix, samples in list(prefix_groups.items())[:5]:
            log(f"    prefix '{prefix}': {len(samples)} files (sample: {samples[0]})")
        
        _write_anomaly_packet(
            anomaly_type="unknown_inbox_result_types",
            summary=f"log_janitor found {len(unknowns)} files in inbox_results/done/ with unrecognized prefixes. They were KEPT by default. Add classifier rules to log_janitor._INBOX_CLASSIFIER_RULES so future runs categorize them as keep/discard.",
            details={
                "unknown_file_count": len(unknowns),
                "inferred_prefixes": {k: len(v) for k, v in prefix_groups.items()},
                "sample_files_per_prefix": {k: v[:3] for k, v in prefix_groups.items()},
            },
        )
    
    # Anomaly: discard volume way above normal — could indicate a bot writing junk
    if discarded > 500:
        _write_anomaly_packet(
            anomaly_type="abnormal_discard_volume",
            summary=f"log_janitor moved {discarded} files to discarded/ in one run. Normal is < 100. Check if a bot is writing junk or if dedup is too aggressive.",
            details={
                "discarded_count":      discarded,
                "kept_count":           kept,
                "discard_by_label":     discard_label_counts,
                "examples":             discard_examples,
            },
        )
    
    # 30-day prune over the discarded archive (final-stage delete)
    # Each day-subfolder gets pruned if its mtime is > 30 days old.
    try:
        cutoff = datetime.now(EST).timestamp() - (30 * 24 * 3600)
        pruned_days = 0
        for sub in os.listdir(_INBOX_DISCARDED):
            sub_path = os.path.join(_INBOX_DISCARDED, sub)
            if not os.path.isdir(sub_path):
                continue
            try:
                if os.path.getmtime(sub_path) < cutoff:
                    shutil.rmtree(sub_path)
                    pruned_days += 1
            except Exception as e:
                log(f"  could not prune discarded/{sub}: {e}")
        if pruned_days:
            log(f"  discarded/: pruned {pruned_days} day-folders older than 30 days")
    except Exception as e:
        log(f"  discarded folder prune failed: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# END SPRINT 33+ INBOX_RESULTS CURATION
# ═════════════════════════════════════════════════════════════════════════════


def log(msg):
    print(f"[janitor] {msg}")


def archive_path(filename):
    name, ext = os.path.splitext(filename)
    return os.path.join(_ARCHIVE, f"{name}_{_run_stamp()}{ext}")


def _read_text_with_bom_fallback(filepath):
    """
    Sprint 29.7 v2.1 fix: parlay_history.json was UTF-16 (\\xff\\xfe BOM at byte 0).
    Try UTF-8 first, fall back to UTF-16 LE/BE, fall back to latin-1 with replace.
    Never raises — returns None on truly bad data.
    """
    encodings = [
        ("utf-8-sig", "strict"),   # handles UTF-8 BOM if present
        ("utf-8",     "strict"),
        ("utf-16",    "strict"),   # auto-detects LE/BE from BOM
        ("utf-16-le", "strict"),
        ("utf-16-be", "strict"),
        ("latin-1",   "replace"),  # last resort, never fails
    ]
    for enc, errors in encodings:
        try:
            with open(filepath, "r", encoding=enc, errors=errors) as f:
                return f.read()
        except Exception:
            continue
    return None


def _load_json_safely(filepath):
    """
    Read + parse a JSON file with BOM/encoding fallback. Returns None on
    failure. Caller logs the failure if it cares.
    """
    text = _read_text_with_bom_fallback(filepath)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _try_salvage_jsonl(filepath):
    """
    v2.1.1 NEW: when a "_log.json" file fails full-file JSON parse, it might
    actually be a JSONL (one JSON per line) or a corrupted JSONL with one bad
    line at the end. Try line-by-line parse, return list of recovered dicts.
    Returns None if we can't recover anything.
    
    This recovers files like passed_filter_log.json where mid-write truncation
    left an incomplete final line.
    """
    text = _read_text_with_bom_fallback(filepath)
    if not text:
        return None
    
    salvaged = []
    bad_lines = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip array brackets if present (some files start/end with [/])
        if line in ("[", "]"):
            continue
        # Strip trailing comma if it's there
        if line.endswith(","):
            line = line[:-1]
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                salvaged.append(obj)
            elif isinstance(obj, list):
                salvaged.extend(o for o in obj if isinstance(o, dict))
        except Exception:
            bad_lines += 1
            continue
    
    if salvaged:
        return {"salvaged": salvaged, "bad_lines": bad_lines}
    return None


def trim_json_dict(filepath, keep_last_keys, sort_by=None):
    """v2.1.2 NEW: trim a dict-shaped JSON file by keeping the last N keys."""
    if not os.path.exists(filepath):
        return
    try:
        data = _load_json_safely(filepath)
        if data is None:
            log(f"⚠️  {os.path.basename(filepath)}: unreadable — SKIPPED")
            return
        if not isinstance(data, dict):
            log(f"  {os.path.basename(filepath)}: not a dict ({type(data).__name__}) — handler may need update")
            return
        
        original_count = len(data)
        if original_count <= keep_last_keys:
            log(f"{os.path.basename(filepath)}: {original_count} keys — no trim needed")
            return
        
        items = list(data.items())
        
        if sort_by:
            def _key_fn(kv):
                v = kv[1]
                if isinstance(v, dict):
                    return v.get(sort_by) or ""
                return ""
            try:
                items.sort(key=_key_fn)
            except Exception:
                items.sort(key=lambda kv: kv[0])
        else:
            try:
                items.sort(key=lambda kv: kv[0])
            except Exception:
                pass
        
        # SAFETY GUARD: don't produce empty
        kept = dict(items[-keep_last_keys:])
        dropped = dict(items[:-keep_last_keys])
        
        if not kept and original_count > 0:
            log(f"⚠️  {os.path.basename(filepath)}: trim would zero file — BAILING (file preserved)")
            return
        
        # Archive dropped items
        if dropped:
            try:
                arch = archive_path(os.path.basename(filepath))
                existing = _load_json_safely(arch) or {}
                if not isinstance(existing, dict):
                    existing = {}
                existing.update(dropped)
                with open(arch, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2, default=str)
            except Exception as e:
                log(f"  {os.path.basename(filepath)}: archive failed (continuing): {e}")
        
        tmp = filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(kept, f, indent=2, default=str)
        os.replace(tmp, filepath)
        log(f"{os.path.basename(filepath)} [dict]: {original_count} → {len(kept)} keys (archived {len(dropped)})")
    except Exception as e:
        log(f"Error trimming dict {filepath}: {e}")


def trim_corruptible_log(filepath, keep_last=300):
    """
    v2.1.1 NEW: like trim_json_array but with JSONL salvage fallback. Use for
    "_log.json" files that bots append to (passed_filter_log, skip_log style)
    where mid-write corruption is possible.
    
    Strategy:
      1. Try full-file JSON parse (the normal path)
      2. If that fails, try line-by-line salvage
      3. Whichever works, write back as a clean JSON array (so future runs
         use the fast path)
    """
    if not os.path.exists(filepath):
        return
    try:
        data = _load_json_safely(filepath)
        salvage_used = False
        bad_lines = 0
        
        if data is None or not isinstance(data, list):
            # Try salvage
            salvage = _try_salvage_jsonl(filepath)
            if salvage is None:
                log(f"⚠️  {os.path.basename(filepath)}: unrecoverable — SKIPPED")
                return
            data = salvage["salvaged"]
            bad_lines = salvage["bad_lines"]
            salvage_used = True
        
        original_count = len(data)
        
        if salvage_used:
            log(f"  {os.path.basename(filepath)}: salvaged {original_count} entries from corrupted file ({bad_lines} bad lines dropped)")
        
        # Trim to keep_last
        if original_count <= keep_last and not salvage_used:
            log(f"{os.path.basename(filepath)}: {original_count} entries — no trim needed")
            return
        
        old_entries = data[:-keep_last] if original_count > keep_last else []
        if old_entries:
            arch = archive_path(os.path.basename(filepath))
            existing = []
            if os.path.exists(arch):
                existing = _load_json_safely(arch) or []
                if not isinstance(existing, list):
                    existing = []
            existing.extend(old_entries)
            with open(arch, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, default=str)
        
        trimmed = data[-keep_last:]
        tmp = filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, indent=2, default=str)
        os.replace(tmp, filepath)
        
        if salvage_used:
            log(f"{os.path.basename(filepath)}: rewrote as clean array ({len(trimmed)} entries kept)")
        else:
            log(f"{os.path.basename(filepath)}: {original_count} → {len(trimmed)} entries (archived {len(old_entries)})")
    except Exception as e:
        log(f"Error trimming corruptible log {filepath}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# JSON ARRAY TRIMMERS
# ═════════════════════════════════════════════════════════════════════════════

def trim_json_array(filepath, keep_last):
    """Trim a JSON array file — archive old entries, keep last N."""
    if not os.path.exists(filepath):
        return
    try:
        data = _load_json_safely(filepath)
        if data is None:
            log(f"⚠️  {os.path.basename(filepath)}: unreadable (encoding/parse error) — SKIPPED")
            return
        if not isinstance(data, list):
            log(f"  {os.path.basename(filepath)}: not a list ({type(data).__name__}) — handler may need update")
            return
        original_count = len(data)
        if original_count <= keep_last:
            log(f"{os.path.basename(filepath)}: {original_count} entries — no trim needed")
            return

        old_entries = data[:-keep_last]
        arch = archive_path(os.path.basename(filepath))
        existing = []
        if os.path.exists(arch):
            existing = _load_json_safely(arch) or []
            if not isinstance(existing, list):
                existing = []
        existing.extend(old_entries)
        with open(arch, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, default=str)

        trimmed = data[-keep_last:]
        tmp = filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, indent=2, default=str)
        os.replace(tmp, filepath)
        log(f"{os.path.basename(filepath)}: {original_count} → {len(trimmed)} entries (archived {len(old_entries)})")
    except Exception as e:
        log(f"Error trimming {filepath}: {e}")


def trim_autopsy_reports(filepath, keep_last=100):
    """v2.5.0 (Cert 007): watch-aware trim for autopsy_reports.json.

    The file mixes REAL position closes with watch-only/virtual autopsies
    (amount_sol empty, pnl 0 — tokens observed, never held). A plain FIFO cap
    let phantom volume (~84/day observed in the field) flush real trade history
    out of the live file in under two days. Real rows keep priority for the cap;
    watch-only rows fill whatever slots remain, newest first. Everything dropped
    is archived exactly like trim_json_array — nothing is destroyed."""
    if not os.path.exists(filepath):
        return
    try:
        data = _load_json_safely(filepath)
        if data is None:
            log(f"⚠️  {os.path.basename(filepath)}: unreadable — SKIPPED")
            return
        if not isinstance(data, list):
            log(f"  {os.path.basename(filepath)}: not a list ({type(data).__name__})")
            return
        original_count = len(data)
        if original_count <= keep_last:
            log(f"{os.path.basename(filepath)}: {original_count} entries — no trim needed")
            return

        def _is_real(a):
            if not isinstance(a, dict):
                return False
            try:
                if float(a.get("amount_sol") or 0) > 0:
                    return True
                return float(a.get("pnl_sol", a.get("realized_pnl_sol", 0)) or 0) != 0
            except (TypeError, ValueError):
                return False

        # never evict amount_sol>0 (or exit_failed still-holding with sol at risk)
        # just to keep a watch-only row. cap watch-only first. 100 number unchanged.
        real  = [a for a in data if _is_real(a)]
        watch = [a for a in data if not _is_real(a)]
        kept_real  = real[-keep_last:]                     # newest real, up to cap
        slots_left = keep_last - len(kept_real)
        kept_watch = watch[-slots_left:] if slots_left > 0 else []
        kept_ids   = {id(a) for a in kept_real} | {id(a) for a in kept_watch}
        trimmed    = [a for a in data if id(a) in kept_ids]   # preserve original order
        old_entries = [a for a in data if id(a) not in kept_ids]

        arch = archive_path(os.path.basename(filepath))
        existing = []
        if os.path.exists(arch):
            existing = _load_json_safely(arch) or []
            if not isinstance(existing, list):
                existing = []
        existing.extend(old_entries)
        with open(arch, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, default=str)

        tmp = filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, indent=2, default=str)
        os.replace(tmp, filepath)
        log(f"{os.path.basename(filepath)}: {original_count} → {len(trimmed)} entries "
            f"({len(kept_real)} real trades protected, {len(kept_watch)} watch-only kept, "
            f"archived {len(old_entries)})")
    except Exception as e:
        log(f"Error trimming {filepath}: {e}")


def trim_log_file(filepath, keep_lines=500):
    """Trim a .log text file — archive old lines, keep last N."""
    if not os.path.exists(filepath):
        return
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        original_count = len(lines)
        if original_count <= keep_lines:
            log(f"{os.path.basename(filepath)}: {original_count} lines — no trim needed")
            return

        old_lines = lines[:-keep_lines]
        arch = archive_path(os.path.basename(filepath))
        with open(arch, "a", encoding="utf-8") as f:
            f.writelines(old_lines)

        tmp = filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(lines[-keep_lines:])
        os.replace(tmp, filepath)
        log(f"{os.path.basename(filepath)}: {original_count} → {keep_lines} lines (archived {len(old_lines)})")
    except Exception as e:
        log(f"Error trimming {filepath}: {e}")


def trim_jsonl_file(filepath, keep_lines):
    """
    Trim a .jsonl append-only file — keep last N lines, archive the rest.
    Sprint 29.7: this is NEW. v1 didn't trim .jsonl files at all, which is
    why files like rugcheck_verdict_history.jsonl, brain.jsonl, autopsies.jsonl
    were growing forever.
    """
    if not os.path.exists(filepath):
        return
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        original = len(lines)
        if original <= keep_lines:
            log(f"{os.path.basename(filepath)}: {original} lines — no trim needed")
            return

        old_lines = lines[:-keep_lines]
        arch = archive_path(os.path.basename(filepath))
        with open(arch, "a", encoding="utf-8") as f:
            f.writelines(old_lines)

        tmp = filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(lines[-keep_lines:])
        os.replace(tmp, filepath)
        log(f"{os.path.basename(filepath)}: {original} → {keep_lines} lines (archived {len(old_lines)})")
    except Exception as e:
        log(f"Error trimming {filepath}: {e}")


def trim_markdown_log(filepath, keep_blocks, separator_patterns=("\n## ", "\n---\n")):
    """
    Sprint 29.7 v2.1 NEW: trim an append-only markdown log (e.g. BROWSE_LOG.md)
    by keeping the last N session blocks. A "block" is delimited by either
    `\\n## ` or `\\n---\\n` (BROWSE_LOG uses both). Old blocks go to archive.
    """
    if not os.path.exists(filepath):
        return
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()
        original_size = len(content)

        # Find every block boundary (offset of each separator occurrence)
        boundaries = [0]  # always include start
        for sep in separator_patterns:
            i = 0
            while True:
                j = content.find(sep, i)
                if j < 0:
                    break
                # Use the separator's leading newline position so blocks contain
                # the heading on their leading edge
                boundaries.append(j + 1)  # +1 to skip the leading \n
                i = j + len(sep)
        boundaries = sorted(set(boundaries))

        if len(boundaries) <= keep_blocks:
            log(f"{os.path.basename(filepath)}: {len(boundaries)} blocks — no trim needed")
            return

        # Take from the (-keep_blocks)-th boundary onward
        cut_at = boundaries[-keep_blocks]
        archived_text = content[:cut_at]
        kept_text = content[cut_at:]

        arch = archive_path(os.path.basename(filepath))
        with open(arch, "a", encoding="utf-8") as f:
            f.write(archived_text)

        tmp = filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(kept_text)
        os.replace(tmp, filepath)

        log(f"{os.path.basename(filepath)}: {len(boundaries)} → {keep_blocks} blocks "
            f"({original_size:,} → {len(kept_text):,} chars, archived {original_size - len(kept_text):,})")
    except Exception as e:
        log(f"Error trimming markdown log {filepath}: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# SPECIAL HANDLERS
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
# FOLDER PRUNERS (Sprint 29.7 NEW)
# ═════════════════════════════════════════════════════════════════════════════

def prune_old_files(dirpath, days_old, label=None, exts=None, name_prefix=None):
    """
    Delete files in `dirpath` older than `days_old` days.
    Optionally filter by extension list (e.g. ['.png', '.jpg']).
    Returns count deleted.

    Sprint 42 protection: refuse to prune source_snapshots/ regardless of
    age — code_tuner owns that directory's lifecycle (rotation, .previous
    tracking). Janitor sweeping it would destroy diff history.
    """
    if not os.path.exists(dirpath):
        return 0
    # Sprint 42 protected paths — janitor never touches these
    dir_basename = os.path.basename(dirpath.rstrip(os.sep))
    if dir_basename in _SPRINT42_PROTECTED_DIRS or "canary" in dirpath.replace("\\", "/").lower():
        log(f"prune_old_files: REFUSING to prune protected dir '{dir_basename}' "
            f"(code_tuner owns lifecycle)")
        return 0
    label = label or os.path.basename(dirpath)
    cutoff = datetime.now(EST).timestamp() - (days_old * 24 * 3600)
    deleted = 0
    for fname in os.listdir(dirpath):
        fpath = os.path.join(dirpath, fname)
        if not os.path.isfile(fpath):
            continue
        if exts and not any(fname.lower().endswith(e) for e in exts):
            continue
        if name_prefix and not fname.startswith(name_prefix):
            continue
        if _is_protected_or_canary(fpath):
            continue  # lockpass: never prune a protected file or a canary
        try:
            if os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1
        except Exception:
            pass
    if deleted:
        log(f"{label}/: deleted {deleted} files older than {days_old} days")
    return deleted


def prune_keep_last_n_files(dirpath, keep_n, label=None, exts=None):
    """
    Keep the most recent N files in dirpath, delete the rest.
    Useful for autopsy_reports/ where we want bounded count, not bounded age.
    """
    if not os.path.exists(dirpath):
        return 0
    label = label or os.path.basename(dirpath)
    candidates = []
    for fname in os.listdir(dirpath):
        fpath = os.path.join(dirpath, fname)
        if not os.path.isfile(fpath):
            continue
        if exts and not any(fname.lower().endswith(e) for e in exts):
            continue
        candidates.append((os.path.getmtime(fpath), fpath))
    candidates.sort(reverse=True)  # newest first
    if len(candidates) <= keep_n:
        return 0
    to_delete = candidates[keep_n:]
    deleted = 0
    for _, fpath in to_delete:
        if _is_protected_or_canary(fpath):
            log(f"{label}/: keeping protected/canary {os.path.basename(fpath)} past the {keep_n} cap")
            continue
        try:
            os.remove(fpath)
            deleted += 1
        except Exception:
            pass
    if deleted:
        log(f"{label}/: pruned to last {keep_n} files (deleted {deleted})")
    return deleted


# ═════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═════════════════════════════════════════════════════════════════════════════

def get_file_size_kb(filepath):
    if os.path.exists(filepath):
        return os.path.getsize(filepath) / 1024
    return 0


def report_sizes(label="size report"):
    log(f"File sizes ({label}):")
    files_with_sizes = []
    if os.path.exists(_LOGS):
        for fname in os.listdir(_LOGS):
            fpath = os.path.join(_LOGS, fname)
            if os.path.isfile(fpath):
                size_kb = get_file_size_kb(fpath)
                if size_kb > 5:
                    files_with_sizes.append((size_kb, fname))
    files_with_sizes.sort(reverse=True)
    for size_kb, fname in files_with_sizes[:30]:  # top 30 biggest
        log(f"  {fname}: {size_kb:.1f} KB")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN JANITOR PASS
# ═════════════════════════════════════════════════════════════════════════════

# ============================================================================
#   LIVE-UPDATE (element e) - async daemon core + run_janitor guard
# ============================================================================
# log_janitor is an async daemon (deep-clean every 14d + hourly disk guard). It reloads in
# place when log_janitor.py changes on disk, but ONLY when no janitor pass is in flight (a _LJ_IN_FLIGHT
# guard on run_janitor, which does the pruning/writes) - so os.execv never fires mid-prune.
# A compile()-check before execv survives the save mid-write race. The on-disk reload can stay.
# It is not "the owner applies." This bot does not edit other bots' .py or its own source.
# The agent handles his own patches. Reload notes go to the agent's inbox\, the agent handles his own patches.
import sys as _lu_sys
import shutil as _lu_shutil
import hashlib as _lu_hashlib
import time as _lu_time
import functools as _lu_functools

_LJ_IN_FLIGHT = 0  # >0 while run_janitor prunes/writes


def _lj_inflight(fn):
    @_lu_functools.wraps(fn)
    def _w(*a, **k):
        global _LJ_IN_FLIGHT
        _LJ_IN_FLIGHT += 1
        try:
            return fn(*a, **k)
        finally:
            _LJ_IN_FLIGHT -= 1
    return _w


_LU_SELF = os.path.abspath(__file__)
_LU_MARKER = os.path.join(WS_BOT_LOGS, "log_janitor_reload.json")
_LU_LASTGOOD = _LU_SELF + ".last-good"


def _lu_mtime(pp):
    try:
        return os.path.getmtime(pp)
    except Exception:
        return 0.0


def _lu_hash(pp):
    try:
        with open(pp, "rb") as f:
            return _lu_hashlib.sha256(f.read()).hexdigest()[:8]
    except Exception:
        return ""


_LU_BOOT_MTIME = _lu_mtime(_LU_SELF)
_LU_BOOT_HASH = _lu_hash(_LU_SELF)
_LU_BOOT_TS = _lu_time.time()


def _lu_write_report(kind, severity, summary, extra=None):
    """Reload note for the agent. Lands in inbox\\log_janitor - …, same family as anomaly packets.

    Never writes the owner's inbox. The agent handles his own patches.
    """
    try:
        os.makedirs(_INBOX, exist_ok=True)
        ts = datetime.now(EST).strftime("%Y%m%d_%H%M%S")
        fpath = os.path.join(_INBOX, f"log_janitor - {kind}_{ts}.md")
        fm = {"kind": kind, "severity": severity, "dedupe_key": f"log_janitor|{kind}",
              "source_skill": "log-janitor", "summary": summary}
        lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["---", "",
                 f"# log_janitor {kind}", summary]
        if extra:
            lines += ["", "```json", json.dumps(extra, indent=2, default=str), "```"]
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        log(f"[live_update] report err: {e}")


def _lu_snapshot_last_good():
    try:
        _lu_shutil.copy2(_LU_SELF, _LU_LASTGOOD)
    except Exception:
        pass


def _lu_on_boot():
    marker = None
    try:
        if os.path.exists(_LU_MARKER):
            with open(_LU_MARKER, "r", encoding="utf-8") as f:
                marker = json.load(f)
    except Exception:
        marker = None
    if isinstance(marker, dict):
        _lu_write_report("bot_restart", "info",
                         f"log_janitor reloaded {marker.get('from_hash')} -> {marker.get('to_hash')} (live-update, healthy)",
                         marker)
        try:
            os.remove(_LU_MARKER)
        except Exception:
            pass
    _lu_snapshot_last_good()


async def live_update_watcher_loop():
    """Reload when this file changes on disk, only past min-uptime, with NO janitor pass in flight,
    and only once the on-disk source compiles (guards the mid-write race).
    The agent handles his own patches. This reload is not the owner applying a patch."""
    log(f"[live_update] watcher online (boot {_LU_BOOT_HASH})")
    while True:
        try:
            if ((_lu_time.time() - _LU_BOOT_TS) >= 120 and _LJ_IN_FLIGHT == 0
                    and _lu_mtime(_LU_SELF) > _LU_BOOT_MTIME
                    and _lu_hash(_LU_SELF) != _LU_BOOT_HASH):
                try:
                    with open(_LU_SELF, "r", encoding="utf-8") as _sf:
                        compile(_sf.read(), _LU_SELF, "exec")
                except Exception:
                    await asyncio.sleep(30); continue  # mid-write / bad patch: retry
                new_hash = _lu_hash(_LU_SELF)
                _lu_snapshot_last_good()
                try:
                    os.makedirs(os.path.dirname(_LU_MARKER), exist_ok=True)
                    with open(_LU_MARKER, "w", encoding="utf-8") as f:
                        json.dump({"from_hash": _LU_BOOT_HASH, "to_hash": new_hash,
                                   "detected_at": datetime.now(EST).isoformat()}, f)
                except Exception:
                    pass
                log(f"[live_update] reloading {_LU_BOOT_HASH} -> {new_hash} (safe point, re-exec)")
                try:
                    os.execv(_lu_sys.executable, [_lu_sys.executable, _LU_SELF] + _lu_sys.argv[1:])
                except Exception as e:
                    log(f"[live_update] os.execv failed, staying on current code: {e}")
                    _lu_write_report("bot_restart_failed", "high",
                                     f"patch {new_hash} detected but re-exec failed; STILL RUNNING old {_LU_BOOT_HASH}",
                                     {"error": str(e)[:200]})
                    try:
                        os.remove(_LU_MARKER)
                    except Exception:
                        pass
        except Exception as e:
            log(f"[live_update] watcher err: {e}")
        await asyncio.sleep(30)


@_lj_inflight
def run_janitor():
    log(f"=== Log Janitor v2.5.0 starting — {_run_stamp()} ===")
    log(f"Sprint 42 protected dirs: {sorted(_SPRINT42_PROTECTED_DIRS)}")
    log(f"Sprint 42 protected files: {sorted(_SPRINT42_PROTECTED_FILES)}")
    report_sizes("BEFORE trim")
    print()

    # ── JSON array files — keep last N ────────────────────────────────────────
    trim_json_array(os.path.join(_LOGS, "trades_history.json"),       keep_last=200)
    trim_autopsy_reports(os.path.join(_LOGS, "autopsy_reports.json"), keep_last=100)  # v2.5.0: watch-aware
    trim_json_array(os.path.join(_LOGS, "missed_runners.json"),       keep_last=200)
    trim_json_array(os.path.join(_LOGS, "parlay_history.json"),       keep_last=100)
    trim_json_dict( os.path.join(_LOGS, "autopsy_queue.json"),        keep_last_keys=50)
    trim_json_array(os.path.join(_LOGS, "observer_queue.json"),       keep_last=50)
    trim_json_dict( os.path.join(_LOGS, "pump_alerted.json"),         keep_last_keys=200)
    trim_json_array(os.path.join(_LOGS, "decision_history.json"),     keep_last=200)
    trim_json_dict( os.path.join(_LOGS, "rug_skip_history.json"),     keep_last_keys=500, sort_by="skipped_at")

    # New activity + handoff files
    trim_json_array(os.path.join(_LOGS, "x_activity_log.json"),       keep_last=100)
    trim_json_array(os.path.join(_LOGS, "agent_owned_threads.json"), keep_last=50)
    trim_json_array(os.path.join(_LOGS, "x_interactions.json"),       keep_last=500)
    trim_json_array(os.path.join(_LOGS, "bot_alerts.json"),           keep_last=200)
    trim_json_dict( os.path.join(_LOGS, "scout_intel.json"),          keep_last_keys=100, sort_by="ts")
    trim_json_array(os.path.join(_LOGS, "wealth_opportunities.json"), keep_last=100)

    # Sprint 29.7 — added missing JSON arrays
    trim_json_array(os.path.join(_LOGS, "browse_results.json"),       keep_last=200)
    trim_json_array(os.path.join(_LOGS, "browser_response.json"),     keep_last=50)
    # deep_research_cache.json is a mint-keyed dict that Sniper caps at 200 itself;
    # the old list trim here was a silent no-op. Removed 2026-10-14.
    trim_json_dict( os.path.join(_LOGS, "deployer_cache.json"),       keep_last_keys=200, sort_by="cached_at")
    trim_json_dict( os.path.join(_LOGS, "funder_cache.json"),         keep_last_keys=200, sort_by="cached_at")
    trim_json_dict( os.path.join(_LOGS, "dex_paid_watch.json"),       keep_last_keys=100, sort_by="ts")
    trim_json_array(os.path.join(_LOGS, "agent_signals.json"),       keep_last=100)

    # Sprint 29.7 v2.1 — surfaced by first run output (large files not in trim list)
    trim_json_array(os.path.join(_LOGS, "agent_decisions.json"),     keep_last=200)
    trim_json_dict( os.path.join(_LOGS, "agent_intel.json"),         keep_last_keys=100, sort_by="ts")
    trim_json_dict( os.path.join(_LOGS, "boost_history.json"),        keep_last_keys=200, sort_by="ts")
    # v2.1.1: passed_filter_log.json + skip_log.json are bot-appended files prone
    # to mid-write corruption. Use the salvage-capable handler.
    trim_corruptible_log(os.path.join(_LOGS, "passed_filter_log.json"), keep_last=300)
    trim_corruptible_log(os.path.join(_LOGS, "skip_log.json"),          keep_last=2000)
    trim_json_array(os.path.join(_LOGS, "wallet_signal_history.json"), keep_last=200)
    trim_json_array(os.path.join(_LOGS, "security_warden.json"),      keep_last=200)

    # ── Special handlers ──────────────────────────────────────────────────────

    # ── Active bot .log files (Sprint 29.7 — pruned retired-bot entries) ──────
    trim_log_file(os.path.join(_LOGS, "trades.log"),                 keep_lines=1000)
    trim_log_file(os.path.join(_LOGS, "claude_vision_usage.log"),    keep_lines=200)
    trim_log_file(os.path.join(_LOGS, "baseline_resets.log"),        keep_lines=300)
    # Sprint 29.7 v2.1 — surfaced by first run

    # ── Append-only markdown logs (Sprint 29.7 v2.1 NEW) ──────────────────────
    trim_markdown_log(os.path.join(_LOGS, "BROWSE_LOG.md"),          keep_blocks=200)

    # ── .JSONL append-only files (Sprint 29.7 — these were growing FOREVER) ───
    trim_jsonl_file(os.path.join(_LOGS, "rugcheck_verdict_history.jsonl"), keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "patterns.jsonl"),                  keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "trades.jsonl"),                    keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "macro.jsonl"),                     keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "synthetic.jsonl"),                 keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "thesis.jsonl"),                    keep_lines=1000)
    trim_jsonl_file(os.path.join(_LOGS, "memory.jsonl"),                    keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "x_intel.jsonl"),                   keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "learnings.jsonl"),                 keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "ledger_transfers.jsonl"),          keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "narrative_intel_cache_audit.jsonl"), keep_lines=1000)
    trim_jsonl_file(os.path.join(_LOGS, "narrative_llm_diag.jsonl"),        keep_lines=1000)
    trim_jsonl_file(os.path.join(_LOGS, "deep_research_response_history.jsonl"), keep_lines=500)
    trim_jsonl_file(os.path.join(_LOGS, "social_research_response_history.jsonl"), keep_lines=500)
    trim_jsonl_file(os.path.join(_LOGS, "signals_history.jsonl"),           keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "signals_response_history.jsonl"),  keep_lines=1000)
    trim_jsonl_file(os.path.join(_LOGS, "chart_history.jsonl"),             keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "sessions.jsonl"),                  keep_lines=1000)
    trim_jsonl_file(os.path.join(_LOGS, "agent_replies.jsonl"),            keep_lines=1000)
    trim_jsonl_file(os.path.join(_LOGS, "autopsies.jsonl"),                 keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "brain.jsonl"),                     keep_lines=2000)
    trim_jsonl_file(os.path.join(_LOGS, "corrections.jsonl"),               keep_lines=1000)
    # learnings_summarizer history
    trim_jsonl_file(os.path.join(_LOGS, "learnings_summarizer_history.jsonl"), keep_lines=500)
    # NOTE: skip_log.json + passed_filter_log.json are handled above by
    # trim_corruptible_log (handles JSONL or JSON with mid-write recovery)
    # markets are simmed. Treat as JSON array, keep last 100 simulations.

    # ── Chart PNGs — delete older than 30 days ────────────────────────────────
    prune_old_files(os.path.join(_LOGS, "charts"),         days_old=30, label="charts (memes)", exts=[".png", ".jpg"])
    # v2.5.0: Sprint 37 one-envelope meme pipeline writes generated PNGs here — was unbounded
    prune_old_files(os.path.join(_LOGS, "meme_factory_images"), days_old=30, label="meme factory images", exts=[".png", ".jpg"])

    # ── Disk-fill guard — also run inside the deep clean (belt and suspenders).
    # The hourly disk_guard_loop is the primary defense; this ensures a guard pass
    # happens on every deep clean too. Prevents the screenshot/temp disk-fill that
    # took the whole system down.
    try:
        disk_guard(emergency=False)
    except Exception as e:
        log(f"  disk_guard within run_janitor err: {e}")

    # ── Sprint 29.7 NEW: workspace-level housekeeping ─────────────────────────

    prune_old_files(_LEARN_INBOX, days_old=7, label="learnings_inbox", exts=[".md"])

    # learnings_archive: contains daily raw archives + .bak baselines.
    # Keep 90 days worth — DREAMS pipeline absorbs them, no need to keep forever.
    prune_old_files(_LEARN_ARCH, days_old=90, label="learnings_archive", exts=[".md", ".bak"])

    # autopsy_reports/ folder — autopsy_writer dumps individual .md files here.
    # Keep last 500 reports (count-based, not age-based).
    prune_keep_last_n_files(_AUTOPSY_DIR, keep_n=500, label="autopsy_reports", exts=[".md", ".json"])

    # The agent's typed-event packet inbox: prune done/expired older than 30d
    if os.path.exists(_INBOX):
        for sub in ("done", "expired", "failed"):
            sd = os.path.join(_INBOX, sub)
            prune_old_files(sd, days_old=30, label=f"inbox/{sub}", exts=[".json", ".md"])

    _inbox_res = os.path.join(_WORKSPACE, "inbox_results")
    for sub in ("expired", "failed", "archived"):
        sd = os.path.join(_inbox_res, sub)
        if os.path.exists(sd):
            prune_old_files(sd, days_old=30, label=f"inbox_results/{sub}", exts=[".json", ".md"])

    if os.path.exists(_INBOX_RES):
        curate_inbox_results_done()

    SESSION_DIRS = [os.path.abspath(os.path.expanduser(_d.strip()))
                    for _d in os.getenv("AGENT_SESSION_DIRS", "").split(os.pathsep) if _d.strip()]
    session_cutoff = datetime.now(EST).timestamp() - (14 * 24 * 3600)
    total_session_deleted = 0
    for sdir in SESSION_DIRS:
        if not os.path.exists(sdir):
            continue
        try:
            for fname in os.listdir(sdir):
                fpath = os.path.join(sdir, fname)
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < session_cutoff:
                    try:
                        os.remove(fpath)
                        total_session_deleted += 1
                    except Exception as e:
                        log(f"Could not delete session file {fname}: {e}")
        except Exception as e:
            log(f"Could not scan {sdir}: {e}")
    if total_session_deleted:
        log(f"Session files: deleted {total_session_deleted} files older than 14 days (FIXED path)")


    # ── Archive folder retention — delete archives older than 90 days ─────────
    # Janitor creates archive files weekly. Without retention they pile up.
    prune_old_files(_ARCHIVE, days_old=90, label="archive", exts=[".json", ".log", ".jsonl"])

    print()
    report_sizes("AFTER trim")
    log(f"=== Log Janitor v2.5.0 complete — archives in bot_logs/archive/ ===")
    try:
        _write_last_deep_clean()
    except Exception as e:
        log(f"deep clean finished but last-success stamp was NOT written: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# DAEMON LOOP
# ═════════════════════════════════════════════════════════════════════════════


def _prune_dir_by_age_and_cap(path, max_age_days, max_total_mb, exts=None, label=""):
    """Prune a directory two ways: delete files older than max_age_days, then if
    the dir is still over max_total_mb, delete oldest files until under cap.
    Used for screenshot dirs that grow unbounded. Returns (deleted, freed_mb)."""
    if not os.path.isdir(path):
        return 0, 0.0
    now = time.time()
    cutoff = now - (max_age_days * 86400)
    deleted = 0
    freed = 0.0
    files = []
    try:
        for name in os.listdir(path):
            fp = os.path.join(path, name)
            if not os.path.isfile(fp):
                continue
            if exts and not any(name.lower().endswith(e) for e in exts):
                continue
            try:
                st = os.stat(fp)
                files.append((st.st_mtime, st.st_size, fp))
            except OSError:
                pass
    except Exception as e:
        log(f"  disk_guard: cannot list {label or path}: {e}")
        return 0, 0.0

    # Pass 1: age prune
    survivors = []
    for mtime, size, fp in files:
        if mtime < cutoff:
            try:
                os.remove(fp)
                deleted += 1
                freed += size / (1024 * 1024)
            except OSError:
                survivors.append((mtime, size, fp))
        else:
            survivors.append((mtime, size, fp))

    # Pass 2: size cap — if still over, delete oldest first
    total_mb = sum(s for _m, s, _f in survivors) / (1024 * 1024)
    if total_mb > max_total_mb:
        survivors.sort()  # oldest first
        for mtime, size, fp in survivors:
            if total_mb <= max_total_mb:
                break
            try:
                os.remove(fp)
                deleted += 1
                freed += size / (1024 * 1024)
                total_mb -= size / (1024 * 1024)
            except OSError:
                pass

    if deleted:
        log(f"  disk_guard: {label or path}: removed {deleted} files, freed {freed:.0f} MB")
    return deleted, freed


def disk_guard(emergency=False):
    """Frequent, lightweight pass that prevents the disk-fill cascade. Targets the
    exact culprits that took the system down: unbounded screenshot dirs. Runs hourly (not every 14 days like the deep
    clean) because a runaway fill happens in HOURS, not weeks.

    emergency=True is triggered when free disk drops below the floor: prune harder
    (shorter age, lower caps)."""
    log(f"disk_guard pass ({'EMERGENCY' if emergency else 'routine'})")

    # Screenshot dirs grow unbounded — nothing else prunes them.
    shot_age = 2 if emergency else 7        # days
    shot_cap = 200 if emergency else 1000   # MB per dir
    for sub in ("browser_screenshots", "trajectory_screenshots"):
        _prune_dir_by_age_and_cap(
            os.path.join(_LOGS, sub),
            max_age_days=shot_age, max_total_mb=shot_cap,
            exts=[".png", ".jpg", ".jpeg", ".webp"], label=sub)


def _free_disk_gb(path=None):
    """Free space in GB on the volume holding `path` (default: _LOGS)."""
    try:
        target = path or _LOGS
        usage = shutil.disk_usage(target)
        return usage.free / (1024 ** 3)
    except Exception:
        return None


async def disk_guard_loop():
    """Hourly disk guard — independent of the 14-day deep clean. Escalates to an
    emergency pass when free space drops below the floor. This is the layer that
    actually prevents the 'system shitted itself' disk-fill, because it runs on a
    timescale that matches how fast the disk fills."""
    GUARD_INTERVAL_S = int(_envv("JANITOR_DISK_GUARD_SECONDS", str(3600)))
    FREE_FLOOR_GB = float(_envv("JANITOR_FREE_FLOOR_GB", "5.0"))
    log(f"disk_guard_loop active — every {GUARD_INTERVAL_S//60}min, emergency floor {FREE_FLOOR_GB} GB")
    while True:
        _write_bot_heartbeat("alive", loop="disk_guard")
        try:
            free = _free_disk_gb()
            emergency = (free is not None and free < FREE_FLOOR_GB)
            if emergency:
                log(f"⚠ disk_guard: free space {free:.1f} GB below floor {FREE_FLOOR_GB} GB — EMERGENCY prune")
                _write_anomaly_packet(
                    "disk_space_low",
                    f"Free disk dropped to {free:.1f} GB (floor {FREE_FLOOR_GB} GB). Emergency prune ran.",
                    "Screenshot dirs + stale browser-use temp pruned hard. User Downloads is not touched. "
                    "If this recurs, a bot is writing faster than the guard clears — investigate.")
            disk_guard(emergency=emergency)
        except Exception as e:
            log(f"disk_guard_loop err: {type(e).__name__}: {e}")
        await asyncio.sleep(GUARD_INTERVAL_S)


async def main_loop():
    """Deep clean every 14 days. Skip on startup when a proved last success is younger than 14 days.

    No stamp, or a stamp that cannot be read, is not treated as recent: the pass runs.
    The hourly disk guard is a different loop and is not skipped here.
    """
    interval = _DEEP_CLEAN_INTERVAL.total_seconds()
    while True:
        last = _read_last_deep_clean()
        now = datetime.now(EST)
        if last is not None and (now - last) < _DEEP_CLEAN_INTERVAL:
            wait = max(1.0, interval - (now - last).total_seconds())
            next_run = now + timedelta(seconds=wait)
            log(f"Deep clean skipped: last success {last.strftime('%Y-%m-%d %H:%M ET')} "
                f"is under 14 days. Next run {next_run.strftime('%Y-%m-%d %H:%M ET')}. "
                f"Hourly disk guard still runs.")
            await asyncio.sleep(wait)
            continue
        if last is None:
            log("No proved last-success deep-clean stamp — running deep clean (not inventing a timestamp).")
        try:
            run_janitor()
        except Exception as e:
            log(f"FATAL janitor error (continuing): {e}")
        last = _read_last_deep_clean()
        now = datetime.now(EST)
        if last is not None and (now - last) < _DEEP_CLEAN_INTERVAL:
            wait = max(1.0, interval - (now - last).total_seconds())
        else:
            # Pass did not record success. Do not invent a stamp and do not hot-loop.
            wait = interval
        next_run = datetime.now(EST) + timedelta(seconds=wait)
        log(f"Next run scheduled: {next_run.strftime('%Y-%m-%d %H:%M ET')}")
        await asyncio.sleep(wait)


async def _run_all_loops():
    """Deep clean (14d) + disk guard (hourly) run concurrently. The guard is the
    fast layer that prevents disk-fill; the deep clean is the slow intelligent
    curation. They're independent so a 14-day cadence never gates disk safety."""
    _lu_on_boot()  # live-update: report a completed reload (if any) + snapshot last-good
    await asyncio.gather(main_loop(), disk_guard_loop(), live_update_watcher_loop())


def main():
    args = sys.argv[1:]
    if "--purge-retired" in args:
        purge_retired_files()
        return
    if "--guard-once" in args:
        log("Manual --guard-once mode: single disk_guard pass, exit")
        free = _free_disk_gb()
        disk_guard(emergency=(free is not None and free < float(_envv("JANITOR_FREE_FLOOR_GB", "5.0"))))
        return
    if "--once" in args:
        log("Manual --once mode: single pass, exit")
        run_janitor()
        return
    asyncio.run(_run_all_loops())


# ═════════════════════════════════════════════════════════════════════════════
# RETIRED-BOT FILE PURGE (Sprint 29.7 v2.1 NEW)
# ═════════════════════════════════════════════════════════════════════════════

# List files left behind by bots you have retired (names relative to bot_logs).
# Empty by default: nothing ships retired. This
# function deletes them with backups (moved to bot_logs/archive/retired_<DATE>/).
# Run ONCE manually: python log_janitor.py --purge-retired
# The daemon must not move retired files on its own. This stays flag-only.

RETIRED_BOT_FILES: list = []


def purge_retired_files():
    """
    One-shot deletion of files belonging to retired bots. Files are MOVED to
    bot_logs/archive/retired_<DATE>/ instead of permanently deleted, so you
    can recover if any of them turn out to still be needed.
    """
    if not RETIRED_BOT_FILES:
        log("RETIRED_BOT_FILES is empty - nothing to purge.")
        return
    stamp = _run_stamp()
    log(f"=== RETIRED-BOT PURGE — {stamp} ===")
    log("Files will be MOVED to archive/retired_<DATE>/ — not permanently deleted.")
    log("Flag-only: the daemon does not call this.")
    log(f"Archive location: {os.path.join(_ARCHIVE, f'retired_{stamp}')}")
    print()

    purge_archive = os.path.join(_ARCHIVE, f"retired_{stamp}")
    os.makedirs(purge_archive, exist_ok=True)

    moved = 0
    skipped = 0
    total_bytes_freed = 0

    for fname in RETIRED_BOT_FILES:
        src = os.path.join(_LOGS, fname)
        if not os.path.exists(src):
            skipped += 1
            continue
        if _is_protected_or_canary(src):
            log(f"  🛡 SKIP {fname} (protected/canary - never purged)")
            skipped += 1
            continue
        try:
            size_kb = os.path.getsize(src) / 1024
            total_bytes_freed += os.path.getsize(src)
            dst = os.path.join(purge_archive, fname)
            os.replace(src, dst)
            log(f"  ✅ moved {fname} ({size_kb:.1f} KB) → archive/retired_{stamp}/")
            moved += 1
        except Exception as e:
            log(f"  ❌ {fname}: {e}")

    print()
    log(f"=== PURGE COMPLETE ===")
    log(f"  Files moved:    {moved}")
    log(f"  Files not found: {skipped}")
    log(f"  Disk freed:     {total_bytes_freed / 1024 / 1024:.2f} MB")
    log(f"")
    log(f"To recover files: move them back from {purge_archive}/")
    log(f"To permanently delete: rm -r {purge_archive}/  (or wait 90 days for auto-prune)")


if __name__ == "__main__":
    main()