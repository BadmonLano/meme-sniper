"""Type-shift tracker for solana meme metas.

Not a buyer. Rolls mint types over 1h / 4h / 24h and writes one json the
sniper already knows how to attach. A shift is a type gaining share, not
one ticker printing.

Types:
  quantum-born, qday-game, privacy-hedge, ticker-beta,
  caller-farm, animal, ai, political, other
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

TYPES = (
    "quantum-born",
    "qday-game",
    "privacy-hedge",
    "ticker-beta",
    "caller-farm",
    "animal",
    "ai",
    "political",
    "other",
)

WINDOWS = (("1h", 3600), ("4h", 4 * 3600), ("24h", 86400))

# name/ticker/narrative keywords. first match wins, so quantum subtypes
# sit above the generic buckets.
_RULES = (
    ("quantum-born", ("qubit", "quantum born", "quantum-born", "ibm quantum", "quantum rng", "quantum seed")),
    ("qday-game", ("q-day", "qday", "satoshi crack", "crack satoshi", "harvest now", "quantum race")),
    ("privacy-hedge", ("zcash", "zec", "monero", "privacy coin", "privacy hedge")),
    ("ticker-beta", ("qubt", "ionq", "rgti", "qbts", "quantum stock")),
    ("caller-farm", ("caller", "shill farm", "caller-farm", "call farm")),
    ("animal", ("animal", "dog", "cat", "frog", "pepe", "monkey")),
    ("ai", (" ai", "ai ", "agent", "gpt", "llm")),
    ("political", ("politic", "trump", "election", "maga")),
)

_NARRATIVE_MAP = {
    "animal": "animal",
    "ai": "ai",
    "political": "political",
    "food": "other",
    "war": "political",
    "geo_political": "political",
}


def classify(narrative: str | None = None, ticker: str | None = None, name: str | None = None, text: str | None = None) -> str:
    blob = " ".join(x for x in (ticker, name, narrative, text) if x).lower()
    padded = f" {blob} "
    for label, keys in _RULES:
        if any(k in padded or k in blob for k in keys):
            return label
    narr = (narrative or "").strip().lower()
    if narr in _NARRATIVE_MAP:
        return _NARRATIVE_MAP[narr]
    if narr and narr not in ("unknown", "other", "random"):
        return "other"
    return "other"


def _share(counts: Counter, total: int) -> dict:
    if total <= 0:
        return {t: 0.0 for t in TYPES}
    return {t: round(counts.get(t, 0) / total, 4) for t in TYPES}


def roll(events: list[dict], now: float | None = None, prev: dict | None = None) -> dict:
    """events: {mint, ts, type, volume, ticker, clone_of?}"""
    now = now if now is not None else time.time()
    windows = {}
    for name, span in WINDOWS:
        rows = [e for e in events if now - float(e.get("ts") or 0) <= span]
        counts = Counter(e.get("type") or "other" for e in rows)
        vol = Counter()
        clones = Counter()
        seen = defaultdict(set)
        for e in rows:
            t = e.get("type") or "other"
            vol[t] += float(e.get("volume") or 0)
            seen[t].add(e.get("mint"))
            if e.get("clone_of"):
                clones[t] += 1
        total = len(rows)
        vol_total = sum(vol.values()) or 0
        windows[name] = {
            "mints": total,
            "share": _share(counts, total),
            "volume_share": _share(vol, vol_total) if vol_total else _share(Counter(), 0),
            "clone_rate": {
                t: round(clones.get(t, 0) / counts[t], 4) if counts.get(t) else 0.0
                for t in TYPES
            },
            "leaders": [t for t, _n in counts.most_common(3) if counts[t] > 0],
        }

    prev_share = ((prev or {}).get("windows") or {}).get("4h", {}).get("share") or {}
    shifts = []
    cur = windows["4h"]["share"]
    for t in TYPES:
        delta = round(cur.get(t, 0) - float(prev_share.get(t) or 0), 4)
        if delta >= 0.15 and windows["4h"]["mints"] >= 4:
            shifts.append({"type": t, "window": "4h", "share_delta": delta, "share": cur.get(t, 0)})
    shifts.sort(key=lambda s: s["share_delta"], reverse=True)

    watch = None
    if shifts:
        watch = {
            "type": shifts[0]["type"],
            "rule": "watch the second or third clean mint in the gaining type, not the first ticker with the word in the name",
            "buy": False,
        }

    return {
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "updated_at_ts": now,
        "types": list(TYPES),
        "windows": windows,
        "shifts": shifts,
        "watch": watch,
        "buy": False,
        "sample_size": len(events),
        "_source": "meta_tracker",
    }


def atomic_write(path: str | Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
