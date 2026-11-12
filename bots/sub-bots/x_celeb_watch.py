"""
x_celeb_watch.py — optional watcher: verified / 250k+ X accounts posting a Solana CA
-> celeb_post card in json_relay/celeb_post_cards.json (v1.0.5). Never buys.

Uses YOUR X API bearer token from bots/.env (X_BEARER_TOKEN). Nothing is committed.
Two sources, both optional:
  CELEB_WATCH_HANDLES  comma list of handles to poll (user timelines)
  CELEB_WATCH_QUERY    recent-search query (default: pump.fun-style CA posts by verified accounts)
Rate limit: one cycle per CELEB_WATCH_INTERVAL_S (180), backoff on 429 using x-rate-limit-reset.
Dedupe: per post_id+CA (state in bot_logs/x_celeb_watch_state.json) and in the card file.
Deleted posts: cards from the last 24h are rechecked; a missing post flips post_deleted=true.
Enrichment (creator sold, funding cluster) uses Sniper's celeb_post readers when an RPC URL
is set (SOLANA_RPC_URL or HELIUS_RPC_URL); otherwise those fields stay unknown.
Fail-safe: no token / API error -> logs a line and emits nothing.
Off-switch: CELEB_WATCH=false.  Run: python bots/sub-bots/x_celeb_watch.py [--once]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOTS = HERE.parent
ROOT = BOTS.parent
sys.path.insert(0, str(BOTS))
import celeb_card as cc  # noqa: E402

API = "https://api.x.com/2"
DEFAULT_QUERY = '(pump OR "pump.fun" OR CA) is:verified -is:retweet -is:reply'
USER_FIELDS = "public_metrics,verified,verified_type,username"


def _dotenv():
    p = BOTS / ".env"
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass


def _on(k, d="true"):
    return (os.environ.get(k) or d).lower() in ("1", "true", "yes", "on")


def _f(k, d):
    try:
        return float(os.environ.get(k) or d)
    except ValueError:
        return float(d)


def relay_dir() -> Path:
    ws = os.environ.get("WORKSPACE_DIR")
    return Path(ws) / "json_relay" if ws else ROOT / "json_relay"


STATE = ROOT / "bot_logs" / "x_celeb_watch_state.json"


def _load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"seen": {}, "since_id": None, "next_ok_ts": 0, "user_ids": {}}


def _save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    seen = st.get("seen", {})
    if len(seen) > 5000:
        st["seen"] = dict(sorted(seen.items(), key=lambda kv: kv[1])[-2500:])
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st), encoding="utf-8")
    os.replace(tmp, STATE)


class RateLimited(Exception):
    def __init__(self, reset):
        self.reset = reset


def _get(path, params, token, opener=urllib.request.urlopen):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "meme-sniper/1.0.5"})
    try:
        with opener(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited(float(e.headers.get("x-rate-limit-reset") or time.time() + 900))
        if e.code == 404:
            return {"_404": True}
        raise


def _author_map(resp) -> dict:
    out = {}
    for u in ((resp or {}).get("includes") or {}).get("users") or []:
        out[u.get("id")] = {"handle": u.get("username"),
                            "followers": (u.get("public_metrics") or {}).get("followers_count"),
                            "verified": bool(u.get("verified") or u.get("verified_type") in ("blue", "business", "government"))}
    return out


def posts_from_response(resp) -> list:
    """[(post_dict, [cas])] for celeb authors only."""
    authors = _author_map(resp)
    out = []
    for t in (resp or {}).get("data") or []:
        a = authors.get(t.get("author_id")) or {}
        if not cc.is_celeb(a):
            continue
        cas = cc.find_cas(t.get("text") or "")
        if not cas:
            continue
        ts = None
        try:
            from datetime import datetime
            ts = datetime.fromisoformat(str(t.get("created_at")).replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
        out.append(({**a, "post_id": t.get("id"), "posted_ts": ts, "text": t.get("text"),
                     "url": f"https://x.com/{a.get('handle')}/status/{t.get('id')}"}, cas))
    return out


async def _enrich(post, ca):
    """Best effort on-chain context via Sniper's celeb rule readers. (facts, rule) or (None, None)."""
    rpc_url = os.environ.get("SOLANA_RPC_URL") or os.environ.get("HELIUS_RPC_URL")
    if not rpc_url:
        return None, None
    try:
        import celeb_post as cp

        def call(method, params):
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
            req = urllib.request.Request(rpc_url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode()).get("result")

        async def rpc(method, params):
            return await asyncio.to_thread(call, method, params)

        sigs = await rpc("getSignaturesForAddress", [ca, {"limit": 1000}])
        if not sigs or len(sigs) >= 1000:
            return None, None
        oldest = min(sigs, key=lambda s: s.get("blockTime") or 1e12)
        tx = await rpc("getTransaction", [oldest["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        keys = (((tx or {}).get("transaction") or {}).get("message") or {}).get("accountKeys") or []
        creator = next((k.get("pubkey") for k in keys if isinstance(k, dict) and k.get("signer")), None)
        facts = await cp.gather_facts(ca, creator, oldest.get("blockTime"), rpc)
        if facts is None:
            return {"creator": creator}, None
        return facts, cp.evaluate(post, facts)
    except Exception:
        return None, None


async def cycle(token: str, st: dict, get=_get, enrich=_enrich, now=None) -> int:
    now = time.time() if now is None else now
    if now < float(st.get("next_ok_ts") or 0):
        return 0
    rd = relay_dir()
    found = []
    try:
        q = os.environ.get("CELEB_WATCH_QUERY") or DEFAULT_QUERY
        if q and q.lower() != "off":
            params = {"query": q, "max_results": 50, "tweet.fields": "created_at,author_id",
                      "expansions": "author_id", "user.fields": USER_FIELDS}
            if st.get("since_id"):
                params["since_id"] = st["since_id"]
            resp = get("/tweets/search/recent", params, token)
            ids = [t.get("id") for t in (resp or {}).get("data") or []]
            if ids:
                st["since_id"] = max(ids, key=int)
            found += posts_from_response(resp)
        for h in [x.strip().lstrip("@") for x in (os.environ.get("CELEB_WATCH_HANDLES") or "").split(",") if x.strip()]:
            uid = st.setdefault("user_ids", {}).get(h)
            if not uid:
                u = get(f"/users/by/username/{h}", {"user.fields": USER_FIELDS}, token)
                uid = ((u or {}).get("data") or {}).get("id")
                if not uid:
                    continue
                st["user_ids"][h] = uid
            resp = get(f"/users/{uid}/tweets", {"max_results": 10, "tweet.fields": "created_at,author_id",
                                                "expansions": "author_id", "user.fields": USER_FIELDS}, token)
            found += posts_from_response(resp)
        # deleted-post recheck (last 24h of cards, max 10 per cycle)
        recent = [c for c in cc.load_cards(rd) if c["context"].get("post_deleted") is not True
                  and (now - float((c.get("celeb_post") or {}).get("posted_ts") or 0)) < 86400][-10:]
        for c in recent:
            pid = c["celeb_post"]["post_id"]
            r = get(f"/tweets/{pid}", {}, token)
            gone = bool((r or {}).get("_404")) or bool((r or {}).get("errors") and not (r or {}).get("data"))
            if gone:
                cc.mark_deleted(rd, pid, True)
    except RateLimited as e:
        st["next_ok_ts"] = e.reset
        print(f"[x_celeb_watch] rate limited until {time.strftime('%H:%M:%S', time.localtime(e.reset))}")
    except Exception as e:
        print(f"[x_celeb_watch] fetch error {type(e).__name__}; nothing emitted this cycle")
    n = 0
    for post, cas in found:
        for ca in cas[:2]:
            key = f"{post['post_id']}:{ca}"
            if key in st.setdefault("seen", {}):
                continue
            st["seen"][key] = now
            facts, rule = await enrich(post, ca)
            card = cc.build_card(post, ca, cc.load_cards(rd), facts, rule, source="x_celeb_watch")
            if cc.emit_card(rd, card):
                n += 1
                print(f"[x_celeb_watch] card @{post.get('handle')} {ca[:6]}… cluster={card['context']['funding_cluster']}")
    return n


def main():
    _dotenv()
    if not _on("CELEB_WATCH"):
        print("[x_celeb_watch] CELEB_WATCH=false, exiting")
        return
    token = (os.environ.get("X_BEARER_TOKEN") or "").strip()
    if not token:
        print("[x_celeb_watch] no X_BEARER_TOKEN in bots/.env, exiting (fail safe)")
        return
    once = "--once" in sys.argv
    while True:
        st = _load_state()
        n = asyncio.run(cycle(token, st))
        _save_state(st)
        if once:
            print(f"[x_celeb_watch] {n} card(s)")
            return
        time.sleep(max(60.0, _f("CELEB_WATCH_INTERVAL_S", 180)))


if __name__ == "__main__":
    main()
