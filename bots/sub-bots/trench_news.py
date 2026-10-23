"""
trench_news.py - verified alert sub-bot for meaningful meme-space changes.

A change counts only when it is BOTH:
  1. announced  - an official source changed (pump.fun docs, pump.fun's public GitHub docs,
                  Jupiter's developer changelog, Meteora docs, the xStocks asset list), and
  2. landed     - real on-chain volume shows it is in use (DexScreener, Solana pairs, summed
                  24h volume >= TRENCH_NEWS_MIN_VOLUME_USD for the change's search terms).
Announced-but-not-landed changes wait in bot_logs/trench_news_state.json and are rechecked
each cycle for TRENCH_NEWS_PENDING_DAYS. Nothing is alerted on rumor.

VENUE_ADAPT (auto | ask | off, default ask):
  ask   alert the owner (alerts.py channels / Telegram) and write owner_inbox/trench_news_*.md
  auto  same alert, plus a proposal in json_relay/venue_adapt/ for the agent to act on.
        It never edits code or settings itself.
  off   log only, no alerts.

LLM (only to summarise a diff into title / kind / search terms): Grok first, local Ollama
fallback (llm_providers.py when present; otherwise GROK_API_KEY/XAI_API_KEY then OLLAMA_URL).
With no LLM the change is still logged, but it cannot be checked for volume, so no alert.

Logs: bot_logs/trench_news.console.log (stdout via the launcher), bot_logs/trench_news.jsonl
(menu tab), bot_logs/trench_news_heartbeat.json.

CLI:
  Normally started by meme_sniper itself (daemon thread, stops with Sniper). No separate step.
  Cadence: TRENCH_NEWS_INTERVAL_S (default 259200 = 3 days), last run kept in trench_news_state.json,
  so a Sniper restart never triggers an early re-fetch. Alerts are fingerprinted (source + title)
  and stored in alerted_fp: the same change is never delivered twice.
  python trench_news.py            standalone loop (only if you run without Sniper)
  python trench_news.py --once     one pass
  python trench_news.py --selftest offline checks, touches nothing real
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


def _e(k, d=""):
    v = os.environ.get(k)
    return d if v is None or not str(v).strip() else str(v).strip()


def _layout():
    """Drop: bots/sub-bots/trench_news.py -> root/bot_logs, root/owner_inbox.
    Flat layout: bots/trench_news.py -> bots/bot_logs, <workspace>/owner_inbox."""
    here = Path(__file__).resolve().parent
    env = _e("WORKSPACE_DIR")
    if here.name == "sub-bots":
        ws = Path(env).resolve() if env else here.parent.parent
        logs = ws / "bot_logs"
        inbox = ws / "owner_inbox"
    else:
        ws = Path(env).resolve() if env else here.parent
        logs = here / "bot_logs" if (here / "bot_logs").is_dir() else ws / "bot_logs"
        inbox = ws / "owner_inbox"
    return ws, here, logs, inbox


def _load_dotenv(here: Path) -> None:
    """Fill os.environ from bots/.env (setdefault: the launcher's env wins). Values never printed."""
    for cand in (here / ".env", here.parent / ".env"):
        if cand.is_file():
            try:
                for ln in cand.read_text(encoding="utf-8-sig").splitlines():
                    ln = ln.strip()
                    if ln and not ln.startswith("#") and "=" in ln:
                        k, v = ln.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            except Exception:
                pass
            return


WS, _HERE, _LOGS, _INBOX = _layout()
_load_dotenv(_HERE)
BOT_LOGS = Path(_e("WS_BOT_LOGS") or _LOGS)
STATE = BOT_LOGS / "trench_news_state.json"
LOG = BOT_LOGS / "trench_news.jsonl"
HEARTBEAT = BOT_LOGS / "trench_news_heartbeat.json"
OWNER_INBOX = Path(_e("TRENCH_NEWS_OWNER_INBOX") or _INBOX)
RELAY = (_HERE / "json_relay" if (_HERE / "json_relay").is_dir() else WS / "json_relay") / "venue_adapt"
AGENT_INBOX = WS / "inbox"   # "trench_news - *" files route to the sniper lane (lane_run)
UA = {"User-Agent": "meme-sniper-trench-news/1.0"}

# Official sources only. Each entry: id, url, kind (html|github_commits|json), venue.
SOURCES = [
    {"id": "pumpfun_custom_pairs", "url": "https://pump.fun/docs/custom-pairs", "kind": "html", "venue": "pump.fun"},
    {"id": "pumpfun_fees", "url": "https://pump.fun/docs/fees", "kind": "html", "venue": "pump.fun"},
    {"id": "pumpfun_public_docs", "url": "https://api.github.com/repos/pump-fun/pump-public-docs/commits?per_page=10",
     "kind": "github_commits", "venue": "pump.fun"},
    {"id": "jupiter_changelog", "url": "https://developers.jup.ag/changelog/developer-platform", "kind": "html", "venue": "jupiter"},
    {"id": "meteora_programs", "url": "https://docs.meteora.ag/get-started/pushing-the-boundaries-of-defi", "kind": "html", "venue": "meteora"},
    {"id": "xstocks_assets", "url": "https://api.xstocks.fi/api/v2/public/assets?network=Solana&pageSize=100",
     "kind": "xstocks", "venue": "xstocks"},
]


def _now():
    return datetime.now().isoformat(timespec="seconds")


_BG = {"on": False}


def _log(msg):
    line = f"[{datetime.now():%H:%M:%S}] [trench] {msg}"
    if not _BG["on"]:
        print(line, flush=True)
    try:
        BOT_LOGS.mkdir(parents=True, exist_ok=True)
        with open(BOT_LOGS / "trench_news.console.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _jsonl(rec):
    try:
        BOT_LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": _now(), **rec}, default=str) + "\n")
    except Exception:
        pass


def _load_state():
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(st):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, STATE)


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


def _text_lines(html: str) -> list:
    t = _TAG.sub("\n", html)
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    t = re.sub(r"&amp;", "&", t)
    out = []
    for ln in t.splitlines():
        ln = " ".join(ln.split())
        if len(ln) >= 12 and not re.fullmatch(r"[\W\d_]+", ln):
            out.append(ln)
    return out


def snapshot(src) -> list:
    """Return the meaningful lines for a source (what we diff)."""
    raw = _get(src["url"])
    if src["kind"] == "github_commits":
        rows = json.loads(raw)
        return [f"{c.get('sha', '')[:7]} {((c.get('commit') or {}).get('message') or '').splitlines()[0][:200]}"
                for c in rows if isinstance(c, dict)]
    if src["kind"] == "xstocks":
        d = json.loads(raw)
        return sorted(f"{n.get('symbol')} {n.get('name')}" for n in d.get("nodes") or [])
    return _text_lines(raw)


def diff(old: list, new: list) -> list:
    o = set(old or [])
    return [ln for ln in new if ln not in o][:60]


# ── LLM (Grok cloud, Ollama local fallback) ──────────────────────────────────
def _llm(prompt: str) -> str | None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import asyncio
        import llm_providers  # drop: shared provider chain (grok, ollama)
        res = asyncio.run(llm_providers.generate_chain(prompt, max_tokens=400, temperature=0.1))
        txt = res[0] if isinstance(res, tuple) else (res.get("text") if isinstance(res, dict) else res)
        if txt:
            return str(txt)
    except Exception:
        pass
    key = _e("GROK_API_KEY") or _e("XAI_API_KEY")
    if key:
        try:
            body = json.dumps({"model": _e("GROK_TEXT_MODEL", "grok-4.7"), "temperature": 0.1, "max_tokens": 400,
                               "messages": [{"role": "user", "content": prompt}]}).encode()
            req = urllib.request.Request(_e("GROK_API_BASE", "https://api.x.ai/v1").rstrip("/") + "/chat/completions",
                                         data=body, headers={**UA, "Content-Type": "application/json",
                                                             "Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"]
        except Exception as ex:
            _log(f"grok failed: {type(ex).__name__}")
    if _e("OLLAMA_ENABLED", "true").lower() in ("1", "true", "yes", "on"):
        try:
            body = json.dumps({"model": _e("OLLAMA_MODEL", "qwen3:14b-q4_K_M"), "prompt": prompt,
                               "stream": False, "options": {"temperature": 0.1}}).encode()
            req = urllib.request.Request(_e("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/generate",
                                         data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read()).get("response")
        except Exception as ex:
            _log(f"ollama failed: {type(ex).__name__}")
    return None


PROMPT = """You review changes to an OFFICIAL {venue} source ({url}) for a Solana memecoin trading bot.
New lines since last check:
---
{lines}
---
Is this a meaningful change for meme traders (new launch feature, new pair type, stock-meme pairing,
venue shift, fee change, new API the bot depends on)? Ignore typos, dates, layout, legal boilerplate.
Answer ONLY JSON: {{"meaningful": true|false, "title": "<=80 chars", "kind": "feature|pairing|venue|fees|api|other",
"summary": "<=240 chars, facts from the lines only", "search_terms": ["<=3 DexScreener search terms that
would show the change being traded, e.g. a ticker or pair symbol; [] if none"]}}"""


def summarize(src, lines) -> dict | None:
    txt = _llm(PROMPT.format(venue=src["venue"], url=src["url"], lines="\n".join(lines[:40])[:4000]))
    if not txt:
        return None
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except Exception:
        d = None
    return d if isinstance(d, dict) else None


# ── landed check: real volume on DexScreener ─────────────────────────────────
def landed(terms: list) -> dict:
    total, pairs = 0.0, 0
    for t in (terms or [])[:3]:
        try:
            d = json.loads(_get("https://api.dexscreener.com/latest/dex/search?q=" + urllib.parse.quote(str(t)[:40])))
        except Exception:
            continue
        for p in d.get("pairs") or []:
            if p.get("chainId") != "solana":
                continue
            v = float(((p.get("volume") or {}).get("h24")) or 0)
            if v > 0:
                total += v
                pairs += 1
    need = float(_e("TRENCH_NEWS_MIN_VOLUME_USD", "250000"))
    return {"volume_24h_usd": round(total), "pairs": pairs, "landed": total >= need, "threshold": need}


# ── alerts ────────────────────────────────────────────────────────────────────
def _send(msg: str) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import alerts  # drop: shared channels (telegram, discord, email, ntfy)
        r = alerts.send_sync(msg, source="trench_news")
        return "sent" if any(v == "sent" or v is True for v in (r or {}).values()) else str(r)[:80]
    except ImportError:
        pass
    except Exception as ex:
        return f"alerts error {type(ex).__name__}"
    tok, chat = _e("TELEGRAM_TOKEN") or _e("TELEGRAM_BOT_TOKEN"), _e("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return "no channel configured"
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg, "disable_web_page_preview": "true"}).encode()
        with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                                           data=data), timeout=15) as r:
            return "sent" if json.loads(r.read()).get("ok") else "telegram not ok"
    except Exception as ex:
        return f"telegram error {type(ex).__name__}"


def notify(item: dict) -> str:
    mode = _e("VENUE_ADAPT", "ask").lower()
    if mode not in ("auto", "ask", "off"):
        mode = "ask"
    if mode == "off":
        return "off"
    msg = (f"Trench News ({item['venue']}): {item['title']}\n{item['summary']}\n"
           f"Landed: ${item['landed']['volume_24h_usd']:,} 24h volume across {item['landed']['pairs']} Solana pairs.\n"
           f"Source: {item['url']}\n"
           + ("Reply in owner commands if you want the agent to adapt to it." if mode == "ask"
              else "VENUE_ADAPT=auto: a proposal was queued for the agent (no code or settings change)."))
    out = _send(msg)
    try:
        OWNER_INBOX.mkdir(parents=True, exist_ok=True)
        (OWNER_INBOX / f"trench_news_{item['id']}_{datetime.now():%Y%m%d_%H%M%S}.md").write_text(msg, encoding="utf-8")
    except Exception:
        pass
    try:   # the agent gets the same change once, as a sniper-lane inbox packet
        AGENT_INBOX.mkdir(parents=True, exist_ok=True)
        (AGENT_INBOX / f"trench_news - {item['id']}_{datetime.now():%Y%m%d_%H%M%S}.json").write_text(json.dumps(
            {"type": "trench_news", "from": "trench_news", "to": "meme_sniper", "venue_adapt": mode,
             "fingerprint": item["id"], **{k: item.get(k) for k in ("venue", "title", "kind", "summary", "url", "landed")}},
            indent=1), encoding="utf-8")
    except Exception:
        pass
    if mode == "auto":
        try:
            RELAY.mkdir(parents=True, exist_ok=True)
            (RELAY / f"{item['id']}.json").write_text(json.dumps({"type": "venue_adapt_proposal", "from": "trench_news",
                                                                  "to": "meme_sniper", **item}, indent=1), encoding="utf-8")
        except Exception:
            pass
    return out


def fingerprint(source: str, title: str) -> str:
    """Stable id for one change: source + normalised title (case, spacing, punctuation ignored)."""
    norm = re.sub(r"[^a-z0-9]+", " ", str(title or "").lower()).strip()
    return hashlib.sha1(f"{source}|{norm}".encode()).hexdigest()[:16]


# ── one pass ──────────────────────────────────────────────────────────────────
def run_once() -> dict:
    st = _load_state()
    snaps, pending = st.setdefault("snapshots", {}), st.setdefault("pending", {})
    alerted_fp = st.setdefault("alerted_fp", {})   # fingerprint -> alerted_at; never alert twice
    res = {"checked": 0, "changed": 0, "alerted": 0, "pending": 0, "errors": 0}
    for src in SOURCES:
        try:
            lines = snapshot(src)
        except Exception as ex:
            res["errors"] += 1
            _jsonl({"event": "source_error", "source": src["id"], "error": type(ex).__name__})
            continue
        res["checked"] += 1
        old = snaps.get(src["id"])
        snaps[src["id"]] = {"at": _now(), "hash": hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16],
                            "lines": lines[:800]}
        if old is None:
            _jsonl({"event": "baseline", "source": src["id"], "lines": len(lines)})
            continue
        new = diff(old.get("lines") or [], lines)
        if not new:
            continue
        res["changed"] += 1
        s = summarize(src, new)
        if not s:
            _jsonl({"event": "changed_no_llm", "source": src["id"], "new_lines": new[:5]})
            continue
        if not s.get("meaningful"):
            _jsonl({"event": "changed_not_meaningful", "source": src["id"], "title": s.get("title")})
            continue
        cid = fingerprint(src["id"], s.get("title"))
        chash = hashlib.sha256("\n".join(sorted(new)).encode()).hexdigest()[:16]
        seen = st.setdefault("seen", {})
        if cid in alerted_fp or cid in pending or chash in seen.values():
            _jsonl({"event": "duplicate_ignored", "source": src["id"], "fingerprint": cid})
            continue
        seen[cid] = chash
        pending[cid] = {"id": cid, "source": src["id"], "venue": src["venue"], "url": src["url"],
                        "title": str(s.get("title") or "")[:80], "kind": s.get("kind"),
                        "summary": str(s.get("summary") or "")[:240],
                        "search_terms": [str(x) for x in (s.get("search_terms") or [])][:3],
                        "announced_at": _now()}
        _jsonl({"event": "announced", **pending[cid]})
    keep_days = float(_e("TRENCH_NEWS_PENDING_DAYS", "7"))
    for cid, it in list(pending.items()):
        try:
            age_d = (datetime.now() - datetime.fromisoformat(it["announced_at"])).total_seconds() / 86400
        except Exception:
            age_d = 0
        if not it.get("search_terms"):
            if age_d > keep_days:
                pending.pop(cid, None)
                _jsonl({"event": "expired_unverifiable", "id": cid, "title": it.get("title")})
            continue
        lv = landed(it["search_terms"])
        it["last_check"] = {"at": _now(), **lv}
        if lv["landed"]:
            pending.pop(cid, None)
            if cid in alerted_fp:              # already delivered once: never again
                _jsonl({"event": "duplicate_ignored", "fingerprint": cid, "title": it.get("title")})
                continue
            it["landed"] = lv
            alerted_fp[cid] = _now()           # record BEFORE sending, then persist
            _save_state(st)
            out = notify(it)
            _jsonl({"event": "verified_alert", "alert": out, **it})
            st.setdefault("alerted", []).append({"id": cid, "title": it["title"], "at": _now()})
            st["alerted"] = st["alerted"][-200:]
            res["alerted"] += 1
        elif age_d > keep_days:
            pending.pop(cid, None)
            _jsonl({"event": "expired_not_landed", "id": cid, "title": it.get("title"), **lv})
    res["pending"] = len(pending)
    _save_state(st)
    try:
        HEARTBEAT.write_text(json.dumps({"at": _now(), "status": "ok", **res}), encoding="utf-8")
    except Exception:
        pass
    _log(f"pass: {res}")
    return res


DEFAULT_INTERVAL_S = 259200   # every 3 days


def _interval() -> float:
    try:
        return max(600.0, float(_e("TRENCH_NEWS_INTERVAL_S", str(DEFAULT_INTERVAL_S))))
    except ValueError:
        return float(DEFAULT_INTERVAL_S)


def due(st: dict | None = None, now: float | None = None) -> bool:
    """Run only if TRENCH_NEWS_INTERVAL_S passed since the last run (persisted, survives restarts)."""
    st = _load_state() if st is None else st
    return (now or time.time()) - float(st.get("last_run_ts") or 0) >= _interval()


def run_if_due() -> dict | None:
    st = _load_state()
    if not due(st):
        return None
    res = run_once()
    st = _load_state()
    st["last_run_ts"] = time.time()
    st["last_run_at"] = _now()
    _save_state(st)
    return res


_LOCK_FH = {"fh": None}


def _acquire_lock() -> bool:
    """One trench_news per install (OS lock, freed automatically when the process exits)."""
    try:
        BOT_LOGS.mkdir(parents=True, exist_ok=True)
        fh = open(BOT_LOGS / "trench_news.lock", "a+")
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_FH["fh"] = fh
        (BOT_LOGS / "trench_news.pid").write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception:
        return False


def _loop() -> None:
    while True:
        try:
            run_if_due()
        except Exception as ex:
            _log(f"pass error: {type(ex).__name__}: {str(ex)[:120]}")
        time.sleep(min(3600.0, _interval()))   # wake hourly, run only when due


def start_background() -> str:
    """Called by meme_sniper at boot. Daemon thread: stops when Sniper stops. Never raises."""
    try:
        if _e("TRENCH_NEWS_ENABLED", "true").lower() not in ("1", "true", "yes", "on"):
            return "disabled"
        if _LOCK_FH["fh"] is not None:
            return "already running"
        if not _acquire_lock():
            return "another instance holds the lock"
        import threading
        _BG["on"] = True
        threading.Thread(target=_loop, daemon=True, name="trench_news").start()
        _log(f"started inside Sniper (VENUE_ADAPT={_e('VENUE_ADAPT', 'ask')}, every {_interval():.0f}s)")
        return "started"
    except Exception as ex:
        return f"error {type(ex).__name__}"


def selftest() -> bool:
    global STATE, notify, landed, BOT_LOGS, HEARTBEAT, LOG
    ok = True

    def t(n, c):
        nonlocal ok
        ok &= bool(c)
        print(("PASS " if c else "FAIL ") + n)
    t("diff finds new lines", diff(["a line here ok"], ["a line here ok", "new feature line"]) == ["new feature line"])
    t("html to lines", "Custom Pairs are live now" in _text_lines("<p>Custom Pairs are live now</p><script>x</script>"))
    os.environ["VENUE_ADAPT"] = "off"
    t("venue_adapt off sends nothing", notify({"id": "x", "venue": "v", "title": "t", "summary": "s", "url": "u",
                                               "landed": {"volume_24h_usd": 1, "pairs": 1}}) == "off")
    import tempfile
    keep = (STATE, BOT_LOGS, HEARTBEAT, LOG)
    _tmp = Path(tempfile.mkdtemp())
    STATE, BOT_LOGS, HEARTBEAT, LOG = _tmp / "state.json", _tmp, _tmp / "hb.json", _tmp / "tn.jsonl"
    try:
        os.environ["TRENCH_NEWS_INTERVAL_S"] = "259200"
        t("first run is due", due({}))
        t("not due 1 day after last run", not due({"last_run_ts": time.time() - 86400}))
        t("due after 3 days", due({"last_run_ts": time.time() - 259201}))
        t("fingerprint stable across case/punctuation",
          fingerprint("s", "Custom Pairs: LIVE!") == fingerprint("s", "custom pairs live"))
        # pending item lands -> alerted once, never twice (also after a 'restart' = reload state)
        sent = []
        _n, _l = notify, landed
        notify = lambda it: sent.append(it["id"]) or "sent"
        landed = lambda terms: {"volume_24h_usd": 999999, "pairs": 3, "landed": True, "threshold": 1}
        fp = fingerprint("src", "New pair type")
        _save_state({"snapshots": {}, "pending": {fp: {"id": fp, "source": "src", "venue": "v", "url": "u",
                     "title": "New pair type", "summary": "s", "search_terms": ["X"], "announced_at": _now()}}})
        _srcs = SOURCES[:]
        SOURCES.clear()
        try:
            run_once()
            st = _load_state()
            st["pending"][fp] = {"id": fp, "source": "src", "venue": "v", "url": "u", "title": "New pair type",
                                 "summary": "s", "search_terms": ["X"], "announced_at": _now()}
            _save_state(st)
            run_once()
        finally:
            SOURCES.extend(_srcs)
            notify, landed = _n, _l
        t("landed change alerted exactly once", sent == [fp])
    finally:
        STATE, BOT_LOGS, HEARTBEAT, LOG = keep
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return 0 if selftest() else 1
    BOT_LOGS.mkdir(parents=True, exist_ok=True)
    if _e("TRENCH_NEWS_ENABLED", "true").lower() not in ("1", "true", "yes", "on"):
        _log("TRENCH_NEWS_ENABLED=false, exiting")
        return 0
    if a.once:              # manual pass; ignores the 3-day cadence on purpose
        run_once()
        return 0
    if not _acquire_lock():
        _log("another trench_news (inside Sniper) already runs; exiting")
        return 0
    _log(f"started standalone (VENUE_ADAPT={_e('VENUE_ADAPT', 'ask')}, every {_interval():.0f}s)")
    _loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
