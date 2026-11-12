"""
edge_map.py - schema helpers for the edge v2 durability patch.

WHAT THIS IS FOR: the dual-gate / projection map / map report were prose in a
skill. Prose is optional. This module makes the map a STRUCTURED FIELD on the
position and on the close record, so forgetting to write one becomes visible
instead of silent.

WHAT THIS IS NOT:
  - not a buy gate. Nothing here blocks, sizes, or arms anything.
  - not a sell trigger. Nothing here emits a sell verb, ever.
  - not a capital knob. No trail / SL / TP / size / max-hold value is read or
    written by this file.
  - not a pattern_engine edit. This module does not import or touch it.

A missing map is a WARNING, never a hard block. The owner's override outranks the
schema; the schema's job is to make the omission expensive to ignore, not to
stop the trade.
"""

import re

__all__ = [
    "parse_projection", "empty_edge_map", "path_status_hint",
    "actual_vs_map", "suggested_size_band_from_map_clarity",
    "MAP_CLARITY_VALUES", "TEAM_HUMAN_READ_VALUES", "FUNNY_RESONATE_VALUES",
    "EXIT_REASON_VALUES", "LANE_VALUES",
]

MAP_CLARITY_VALUES     = ("clean_123", "partial", "vibes_only_funny", "vibes_only", "weak")
TEAM_HUMAN_READ_VALUES = ("stick", "farm", "unknown", "failed")
FUNNY_RESONATE_VALUES  = ("hit", "miss", "untested", "n/a")
EXIT_REASON_VALUES     = ("invalidation_named", "floor_conscious", "sensor_flinch",
                          "owner_order", "sl_honor")
LANE_VALUES            = ("vibes", "metrics", "map", "team", "timing", "decision", "none")


def empty_edge_map() -> dict:
    """The shape, with everything unset. Used when no PROJECTION block was written
    so the field EXISTS and reads as absent, rather than the key being missing and
    every downstream reader having to guess whether it was never written or lost."""
    return {
        "prior": None, "sequel": None, "catalyst": None,
        "entry_mcap": None, "base_mcap": None, "good_mcap": None, "moon_mcap": None,
        "moon_condition": None, "kill": None,
        "downside_floor_mcap": None, "downside_floor_pnl_pct": None,
        "map_clarity": None, "catalyst_ts": None,
        "team_human_read": "unknown", "funny_resonate": "untested",
        "_parsed": False,
        "_source": None,
    }


# ── number parsing ──────────────────────────────────────────────────────────
# The agent writes mcaps the way a human says them: "180k", "$1.2M", "4,500,000".
# Accepting only bare digits would silently drop most real blocks.
_NUM_RE = re.compile(
    r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([kKmMbB])?\b"
)
_MULT = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def _to_number(text):
    """First money-shaped number in a string -> float, or None."""
    if not text:
        return None
    m = _NUM_RE.search(str(text))
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suf = (m.group(2) or "").lower()
    return val * _MULT.get(suf, 1)


def _pct(text):
    """A percentage like '-45%' or '-45' -> float, or None."""
    if not text:
        return None
    m = re.search(r"(-?[0-9]+(?:\.[0-9]+)?)\s*%?", str(text))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _extract_block(reasoning: str):
    """Pull the fenced PROJECTION block out of free-text reasoning.

    Tolerant on purpose: ```PROJECTION, ``` projection, a bare PROJECTION: header
    with no fence at all. A parser that only accepts one exact spelling would fail
    silently on a real map and report 'no map written', which is the worst possible
    error here - it would blame the agent for the parser.
    """
    if not reasoning:
        return None
    txt = str(reasoning)
    m = re.search(r"```+\s*projection\b(.*?)```+", txt, re.S | re.I)
    if m:
        return m.group(1)
    m = re.search(r"^\s*projection\s*:?\s*$(.*?)(?=^\s*```|\Z)", txt, re.S | re.I | re.M)
    if m:
        return m.group(1)
    if re.search(r"\bprojection\b", txt, re.I) and re.search(r"\b(base|moon|kill)\b", txt, re.I):
        return txt          # unfenced but clearly a map - parse the whole thing
    return None


def _line_for(block: str, *keys):
    """The remainder of the first line whose label matches any key.

    Handles '1 prior - x', '1. prior: x', 'prior = x', '- base: 180k'.
    """
    for raw in (block or "").split("\n"):
        line = raw.strip().lstrip("-*• ").strip()
        if not line:
            continue
        low = line.lower()
        for k in keys:
            m = re.match(r"^\(?\d*\)?[.)]?\s*" + re.escape(k) + r"\b\s*[:\-=]?\s*(.*)$", low)
            if m:
                # return the ORIGINAL-case remainder, sliced at the same offset
                return line[len(line) - len(m.group(1)):].strip() if m.group(1) else ""
    return None


def parse_projection(reasoning: str, entry_mcap=None) -> dict:
    """Parse the agent's PROJECTION block into the edge_map schema.

    Returns a fully-shaped edge_map. `_parsed` is False when no block was found -
    the caller warns and carries on. This function NEVER raises: a malformed map
    must not be able to take down a buy the agent already decided.
    """
    out = empty_edge_map()
    if entry_mcap is not None:
        out["entry_mcap"] = _to_number(entry_mcap) if isinstance(entry_mcap, str) else entry_mcap
    try:
        block = _extract_block(reasoning)
        if not block:
            return out
        out["_parsed"] = True
        out["_source"] = "reasoning_projection_block"

        out["prior"]    = _line_for(block, "prior") or None
        out["sequel"]   = _line_for(block, "sequel") or None
        out["catalyst"] = _line_for(block, "catalyst") or None
        out["kill"]     = _line_for(block, "kill", "invalidation", "invalidate") or None

        for key, names in (("base_mcap", ("base",)),
                           ("good_mcap", ("good",)),
                           ("moon_mcap", ("moon",))):
            line = _line_for(block, *names)
            if line:
                out[key] = _to_number(line)
                # moon carries its condition in an "only if ..." clause
                if key == "moon_mcap":
                    cond = re.search(r"only if\s*(.+)$", line, re.I)
                    if cond:
                        out["moon_condition"] = cond.group(1).strip()

        floor = _line_for(block, "downside_floor", "downside floor", "floor")
        if floor:
            out["downside_floor_mcap"] = _to_number(floor)
            fp = re.search(r"(-?[0-9]+(?:\.[0-9]+)?)\s*%", floor)
            if fp:
                out["downside_floor_pnl_pct"] = _pct(fp.group(0))

        clarity = _line_for(block, "map_clarity", "clarity")
        if clarity:
            c = clarity.strip().lower().replace(" ", "_").replace("-", "_")
            out["map_clarity"] = c if c in MAP_CLARITY_VALUES else "partial"

        cts = _line_for(block, "catalyst_ts", "catalyst_time", "catalyst_at")
        if cts:
            out["catalyst_ts"] = cts.strip() or None

        thr = _line_for(block, "team_human_read", "team")
        if thr:
            t = thr.strip().lower()
            if t in TEAM_HUMAN_READ_VALUES:
                out["team_human_read"] = t

        fr = _line_for(block, "funny_resonate", "funny")
        if fr:
            f = fr.strip().lower()
            if f in FUNNY_RESONATE_VALUES:
                out["funny_resonate"] = f

        em = _line_for(block, "entry_mcap", "entry")
        if em and out.get("entry_mcap") is None:
            out["entry_mcap"] = _to_number(em)

        # Clarity is inferrable when unstated: 1+2+3 all present is clean_123.
        if not out["map_clarity"]:
            have = sum(1 for k in ("prior", "sequel", "catalyst") if out.get(k))
            out["map_clarity"] = "clean_123" if have == 3 else ("partial" if have else "weak")
    except Exception as e:      # never raise into a buy path
        out["_parse_error"] = f"{type(e).__name__}: {str(e)[:160]}"
    return out


def path_status_hint(edge_map: dict, now_iso: str = None) -> str:
    """FYI only: how old is the catalyst. Based ONLY on catalyst_ts.

    Returns unknown | fresh | stale | dead. This is CONTEXT ON A PACKET, never a
    trigger - nothing in this codebase may act on it, and it carries no verb.
    """
    from datetime import datetime, timezone
    ts = (edge_map or {}).get("catalyst_ts")
    if not ts:
        return "unknown"
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso \
            else datetime.now(t.tzinfo or timezone.utc)
        hrs = (now - t).total_seconds() / 3600.0
    except Exception:
        return "unknown"
    if hrs < 0:
        return "unknown"          # a future catalyst is not a freshness reading
    if hrs <= 24:
        return "fresh"
    if hrs <= 96:
        return "stale"
    return "dead"


def actual_vs_map(edge_map: dict, exit_mcap=None, peak_mcap=None) -> str:
    """Where the outcome landed against the map that was written at entry.

    below_floor | base_miss | base_hit | good_hit | moon_hit

    Graded on PEAK, not exit: the map is a question about whether the thesis's
    path ever happened. Selling before a level the token later reached is a
    DECISION failure, not a map failure, and those are different lanes - which is
    the whole reason lane_that_failed exists.
    """
    em = edge_map or {}
    ref = peak_mcap if peak_mcap is not None else exit_mcap
    if ref is None:
        return "base_miss"
    floor = em.get("downside_floor_mcap")
    if floor is not None and exit_mcap is not None and exit_mcap < floor:
        return "below_floor"
    for level, label in (("moon_mcap", "moon_hit"),
                         ("good_mcap", "good_hit"),
                         ("base_mcap", "base_hit")):
        v = em.get(level)
        if v is not None and ref >= v:
            return label
    return "base_miss"


def suggested_size_band_from_map_clarity(edge_map: dict) -> dict:
    """ADVISORY ONLY - spec section E, explicitly non-binding.

    Never writes amount_sol. Never gates a buy. The agent writes the size and
    reverse_size_kill_v1 still applies on top. This exists so the packet can SHOW
    the band the map clarity implies, not so anything can act on it.
    """
    c = (edge_map or {}).get("map_clarity")
    band = {
        "clean_123":        "medium/high eligible",
        "partial":          "0.1-0.15",
        "vibes_only":       "0.1 probe",
        "vibes_only_funny": "0.1 probe",
        "weak":             "no buy",
    }.get(c)
    return {
        "map_clarity": c,
        "suggested_band": band,
        "binding": False,
        "_note": ("Advisory. The agent writes amount_sol; reverse_size_kill_v1 still "
                  "applies. Nothing reads this to size anything."),
    }


import json
import os

DEPLOYER_MEMORY_FILENAME = "deployer_memory.json"


def load_deployer_memory(path: str) -> dict:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get_deployer_note(path: str, wallet: str) -> dict:
    """What we remember about this wallet. Never a verdict.

    Returns {} when the wallet is unknown - which is the common case and is NOT a
    negative signal. An unknown deployer is unknown, not bad.
    """
    if not wallet:
        return {}
    mem = load_deployer_memory(path)
    rec = mem.get(wallet)
    if not isinstance(rec, dict):
        return {}
    return {
        "wallet": wallet,
        "last_team_human_read": rec.get("last_team_human_read"),
        "notes": rec.get("notes"),
        "mints": (rec.get("mints") or [])[-8:],
        "outcomes": (rec.get("outcomes") or [])[-8:],
        "seen_count": len(rec.get("mints") or []),
        "binding": False,
        "_note": ("Human memory of this deployer, not a gate. Never auto-blocks. "
                  "Separate from deployer_history, which is automated PnL reputation."),
    }


def record_deployer_outcome(path: str, wallet: str, mint: str, ticker: str,
                            team_human_read: str = None, pnl_pct=None,
                            lesson: str = None, cap: int = 40) -> bool:
    """Append a closed outcome to this wallet's memory. Best-effort, never raises.

    Called on CLOSE, from the map report - so the memory is built out of graded
    outcomes rather than opinions formed at entry, when the token still looked good.
    `last_team_human_read` only advances when a real read is supplied; a close with
    no read leaves the previous judgement standing rather than blanking it.
    """
    if not wallet or not path:
        return False
    try:
        mem = load_deployer_memory(path)
        rec = mem.get(wallet)
        if not isinstance(rec, dict):
            rec = {"last_team_human_read": None, "notes": None, "mints": [], "outcomes": []}
        if team_human_read in TEAM_HUMAN_READ_VALUES and team_human_read != "unknown":
            rec["last_team_human_read"] = team_human_read
        if mint and mint not in (rec.get("mints") or []):
            rec.setdefault("mints", []).append(mint)
        rec.setdefault("outcomes", []).append({
            "mint": mint, "ticker": ticker,
            "pnl_pct": pnl_pct,
            "team_human_read": team_human_read,
            "lesson": (lesson or None),
        })
        rec["mints"] = rec["mints"][-cap:]
        rec["outcomes"] = rec["outcomes"][-cap:]
        mem[wallet] = rec
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2, default=str)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


PHASE_VALUES = ("ignition_attention", "base_accumulation", "resolution_spike",
                "giveback", "dead", "unknown")


def classify_phase(snap: dict) -> dict:
    """Return the four packet fields from a candidate snapshot.

    snap keys used (all optional): mcap, age_minutes, volume_5m/1h/24h,
    price_change_5m/1h/24h, peak_mcap.
    """
    out = {"phase_guess": "unknown", "base_mcap_zone": {"low": None, "high": None},
           "resolution_target_mcap": None, "invalidation_under_base": None,
           "_basis": None}
    try:
        def num(k):
            v = (snap or {}).get(k)
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        mcap = num("mcap")
        age  = num("age_minutes")
        v5, v1h, v24 = num("volume_5m"), num("volume_1h"), num("volume_24h")
        c5, c1h, c24 = num("price_change_5m"), num("price_change_1h"), num("price_change_24h")
        peak = num("peak_mcap")

        if mcap is None:
            return out

        # Hourly run-rate vs the 24h average: >1 means it is busier NOW than it has
        # been. This is the closest a snapshot gets to "volume expanding".
        rate = None
        if v1h is not None and v24 and v24 > 0:
            rate = v1h / (v24 / 24.0)

        fresh = age is not None and age <= 180          # 3h
        vertical = (c1h is not None and c1h >= 40) or (c5 is not None and c5 >= 25)
        # a coil reads as: 24h still up, but the recent legs have gone quiet
        coiling = (c24 is not None and c24 > 0
                   and c1h is not None and abs(c1h) <= 12
                   and (c5 is None or abs(c5) <= 8))
        breaking = (c1h is not None and c1h >= 20 and (rate is None or rate >= 1.3))
        fading = ((c24 is not None and c24 <= -35)
                  or (peak is not None and peak > 0 and mcap <= peak * 0.55)
                  or (c1h is not None and c1h <= -15
                      and c24 is not None and c24 >= 50))
        dead_vol = (v1h is not None and v24 is not None
                    and v24 > 0 and (v1h / (v24 / 24.0)) < 0.25)
        lower_highs = (c24 is not None and c24 < 0 and c1h is not None and c1h < 0)

        stalled = rate is not None and rate < 0.10        # <10% of its own 24h pace
        if stalled or (dead_vol and lower_highs):
            out["phase_guess"] = "dead"
            out["_basis"] = ("volume collapsed to {:.1%} of its 24h pace - no bid, "
                             "not a base".format(rate) if stalled
                             else "dead volume + lower highs")
        elif fresh and vertical and not coiling:
            out["phase_guess"] = "ignition_attention"
            out["_basis"] = "fresh + vertical from launch, no coil yet"
        elif breaking and not fresh:
            out["phase_guess"] = "resolution_spike"
            out["_basis"] = "breaking up on expanding volume"
        elif fading:
            # deliberately BEFORE coiling: a -25% hour on a green 24h print would
            # otherwise satisfy neither, or worse, look like a quiet band.
            out["phase_guess"] = "giveback"
            out["_basis"] = "sharp reversal off the run - back into/below the base"
        elif coiling:
            out["phase_guess"] = "base_accumulation"
            out["_basis"] = "post-spike chop holding a band, range declining"

        # ── the rungs ──────────────────────────────────────────────────────
        # Base zone: where the token is actually holding. Anchored on the CURRENT
        # mcap in a base, and on the retrace floor once it has run.
        if out["phase_guess"] == "base_accumulation":
            lo, hi = mcap * 0.80, mcap * 1.25
        elif peak and peak > 0 and out["phase_guess"] in ("giveback", "resolution_spike"):
            lo, hi = peak * 0.30, peak * 0.55
        elif out["phase_guess"] == "ignition_attention":
            # PROVISIONAL map (2026-10-15): no base exists yet, but a card with no
            # map is useless. The ignition spike usually retraces 30-55% before a
            # base forms, so name that retrace band as the PROVISIONAL base and flag it.
            _anchor = max(peak or 0, mcap or 0)   # spike peak when known (2026-10-15)
            lo, hi = (_anchor * 0.45, _anchor * 0.70) if _anchor else (None, None)
            out["base_provisional"] = bool(mcap)
        else:
            lo, hi = (mcap * 0.75, mcap * 1.20) if mcap else (None, None)

        if lo is not None:
            out["base_mcap_zone"] = {"low": round(lo), "high": round(hi)}
            # Invalidation sits under the BASE, not under the entry - the thesis is
            # "this base holds", so losing the base is what kills it, whatever price
            # you happened to get in at.
            out["invalidation_under_base"] = round(lo * 0.85)
            # NEXT RUNG, not moon. Anchored on the base MIDPOINT, not the base high:
            # The owner's Tusk receipt is a ~100k base resolving at ~280k, i.e. ~2.8x the
            # base LEVEL. Using the high inflates it (125k * 2.8 = 350k) and quietly
            # turns a sellable rung into a target nobody hits - which is the exact
            # failure the doctrine exists to stop.
            #
            # A dead token gets NO target. Naming a rung for something with no bid
            # is the same lie in the other direction.
            if out["phase_guess"] != "dead":
                _mult = 2.8
                if c24 is not None:
                    if c24 >= 500:
                        _mult = 1.5
                    elif c24 >= 200:
                        _mult = 2.0
                out["resolution_target_mcap"] = round(((lo + hi) / 2.0) * _mult)
                out["_target_multiple"] = _mult
    except Exception as e:
        out["_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return out
