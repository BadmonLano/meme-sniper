"""
celeb_card.py — the celeb_post relay card (v1.0.5). Agents decide; nothing auto-buys.

Any bot (X Intel, the bundled x_celeb_watch, or an agent) that sees a verified /
large-follower X account post a Solana CA calls emit_card(). The card lands in
json_relay/celeb_post_cards.json. An agent reads it, reasons, and only if it wants
the trade writes a normal buy to json_relay/agent_signals.json with the card's
`celeb_post` block attached. Sniper's celeb rule (v1.0.4) then re-checks on-chain.

Schema (schema = "celeb_post_card/1"):
{
  "schema": "celeb_post_card/1", "card_id": "<post_id>:<ca>", "emitted_at": iso, "source": str,
  "ca": str, "chain": "solana",
  "celeb_post": {handle, followers, verified, post_id, posted_ts, text, url},
  "context": {
    "shill_history": {"prior_cards": int, "prior_cas": [..], "first_seen": iso|None},
    "post_deleted": bool|None,           # None = not rechecked yet
    "creator": str|None, "creator_sold": bool|None, "creator_balance_pct": float|None,
    "funding_cluster": "clean"|"fanout_funder"|"second_coin"|"unknown",
    "rule_preview": {enter, veto, wait, reason}   # what Sniper's celeb rule says now
  },
  "decision": "agent"                    # never "auto"
}
Missing data stays null/"unknown"; agents must treat unknown as risk, not as clean.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = "celeb_post_card/1"
CARDS_FILE = "celeb_post_cards.json"
MAX_CARDS = 300
_B58 = r"[1-9A-HJ-NP-Za-km-z]"
CA_RE = re.compile(rf"(?<!{_B58})({_B58}{{32,44}})(?!{_B58})")


def _f(k, d):
    try:
        return float(os.environ.get(k) or d)
    except ValueError:
        return float(d)


def find_cas(text: str) -> list:
    """Solana-looking addresses in a post, pump.fun ones first, de-duplicated."""
    out = []
    for m in CA_RE.findall(text or ""):
        if m not in out and not m.lower().startswith("http"):
            out.append(m)
    return sorted(out, key=lambda a: 0 if a.endswith("pump") else 1)


def is_celeb(author: dict) -> bool:
    try:
        fol = int(author.get("followers") or 0)
    except (TypeError, ValueError):
        fol = 0
    return bool(author.get("verified")) and fol >= _f("CELEB_MIN_FOLLOWERS", 250000)


def _iso(ts=None):
    return datetime.fromtimestamp(ts or time.time(), tz=timezone.utc).isoformat()


def load_cards(relay_dir) -> list:
    p = Path(relay_dir) / CARDS_FILE
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("cards", []) if isinstance(d, dict) else []
    except Exception:
        return []


def _save(relay_dir, cards: list) -> None:
    p = Path(relay_dir) / CARDS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA, "cards": cards[-MAX_CARDS:]}, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def shill_history(cards: list, handle: str, ca: str) -> dict:
    prior = [c for c in cards if (c.get("celeb_post") or {}).get("handle", "").lower() == (handle or "").lower()
             and c.get("ca") != ca]
    return {"prior_cards": len(prior), "prior_cas": [c.get("ca") for c in prior][-10:],
            "first_seen": prior[0].get("emitted_at") if prior else None}


def cluster_verdict(rule: Optional[dict]) -> str:
    r = (rule or {}).get("reason") or ""
    if "fan-out" in r:
        return "fanout_funder"
    if "cluster" in r:
        return "second_coin"
    if (rule or {}).get("enter") or (rule or {}).get("wait"):
        return "clean"
    return "unknown"


def build_card(post: dict, ca: str, cards: list, facts: Optional[dict] = None,
               rule: Optional[dict] = None, source: str = "x_celeb_watch") -> dict:
    cp = {k: post.get(k) for k in ("handle", "followers", "verified", "post_id", "posted_ts", "text", "url")}
    if not cp.get("url") and cp.get("handle") and cp.get("post_id"):
        cp["url"] = f"https://x.com/{cp['handle']}/status/{cp['post_id']}"
    bal = (facts or {}).get("creator_balance_pct")
    return {
        "schema": SCHEMA, "card_id": f"{cp.get('post_id')}:{ca}", "emitted_at": _iso(), "source": source,
        "ca": ca, "chain": "solana", "celeb_post": cp,
        "context": {
            "shill_history": shill_history(cards, cp.get("handle"), ca),
            "post_deleted": post.get("deleted"),
            "creator": (facts or {}).get("creator"),
            "creator_sold": None if bal is None else bal < _f("CELEB_CREATOR_MAX_PCT", 1),
            "creator_balance_pct": None if bal is None else round(float(bal), 3),
            "funding_cluster": cluster_verdict(rule),
            "rule_preview": {k: (rule or {}).get(k) for k in ("enter", "veto", "wait", "reason")},
        },
        "decision": "agent",
    }


def emit_card(relay_dir, card: dict) -> bool:
    """Append if new (dedupe on card_id). Returns True when written."""
    cards = load_cards(relay_dir)
    if any(c.get("card_id") == card.get("card_id") for c in cards):
        return False
    cards.append(card)
    _save(relay_dir, cards)
    return True


def mark_deleted(relay_dir, post_id: str, deleted: bool = True) -> int:
    cards = load_cards(relay_dir)
    n = 0
    for c in cards:
        if (c.get("celeb_post") or {}).get("post_id") == post_id and c["context"].get("post_deleted") is not deleted:
            c["context"]["post_deleted"] = deleted
            n += 1
    if n:
        _save(relay_dir, cards)
    return n
