"""sniper_ui.py: the Meme Sniper console (dashboard, logs, settings, skills, goals, alerts,
bag actions, health, recap). Opened from bots/sniper.py (menu "Console"). It runs inside the
supervisor process, reads state files only and never places trades. Engine metrics come from
bot_logs/sniper_health.json (written by meme_sniper.py)."""
from __future__ import annotations

import ast as _ast
import hashlib
import json
import os

def _envv(key, default=None):
    """os.getenv, but a blank value (KEY= in .env) counts as unset and returns the default."""
    v = os.environ.get(key)
    return default if v is None or not str(v).strip() else v

import re as _re
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_BASE = Path(__file__).resolve().parent            # bots/


def _drop_root() -> Path:
    v = (os.environ.get("WORKSPACE_DIR") or "").strip()
    envf = _BASE / ".env"
    if not v and envf.exists():
        for ln in envf.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if ln.strip().startswith("WORKSPACE_DIR="):
                v = ln.split("=", 1)[1].strip().strip('"').strip("'")
    return Path(v).expanduser().resolve() if v else _BASE.parent


_WORKSPACE = _drop_root()
_BOT_LOGS = _WORKSPACE / "bot_logs"
_JSON_RELAY = _WORKSPACE / "json_relay"
MEME_SNIPER_FILTER_FILE = _BASE / "tuner" / "meme_sniper_filter.json"

# v1.0.1: the tracked file is meme_sniper_filter.default.json; the live copy (meme_sniper_filter.json) is
# git-ignored, so runs never dirty a clone. First run copies the default. SNIPER_FILTER_SEED_DEFAULT=0 = no copy.
MEME_SNIPER_FILTER_DEFAULT = MEME_SNIPER_FILTER_FILE.with_name("meme_sniper_filter.default.json")
try:
    if (not MEME_SNIPER_FILTER_FILE.exists() and MEME_SNIPER_FILTER_DEFAULT.exists()
            and str(os.environ.get("SNIPER_FILTER_SEED_DEFAULT", "1")).strip().lower() not in ("0", "false", "off", "no")):
        import shutil as _fshutil
        _fshutil.copyfile(MEME_SNIPER_FILTER_DEFAULT, MEME_SNIPER_FILTER_FILE)
except Exception:
    pass
_UI_STATE: dict = {"active": False}
_ACTIVE_OVERRIDES: dict = {}
_DROP_HOOKS: dict = {}          # sniper.py sets "stop" (stop all children)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _now_ts() -> float:
    return time.time()


def _log(msg, prefix: str = "ui") -> None:
    try:
        _BOT_LOGS.mkdir(parents=True, exist_ok=True)
        with open(_BOT_LOGS / "sniper_ui.log", "a", encoding="utf-8") as f:
            f.write(f"[{prefix}] [{_now_iso()}] {msg}\n")
    except Exception:
        pass


_SECRET_RX = _re.compile(r"(api[-_]?key=|token=|secret=)[^&\s]+|[1-9A-HJ-NP-Za-km-z]{60,}", _re.I)


def _redact(s) -> str:
    return _SECRET_RX.sub(lambda m: (m.group(1) or "") + "***", str(s))


def _save_json_atomic(p, obj) -> None:
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
    os.replace(tmp, p)


def _rotate_knob_history_if_needed(kn, key) -> None:
    h = kn.get("history")
    if isinstance(h, list) and len(h) > 50:
        kn["history"] = h[-50:]


_TP_CONST_CACHE: dict = {}

def _tp_const(name: str, src: str, depth: int = 0):
    """Value of a top-level `NAME = <expr>` in the engine source, safely evaluated."""
    if name in _TP_CONST_CACHE:
        return _TP_CONST_CACHE[name]
    if depth > 4:
        raise ValueError("const depth")
    m = _re.search(r"^" + _re.escape(name) + r"\s*(?::[^=\n]*)?=\s*(.+)$", src, flags=_re.M)
    if not m:
        raise NameError(name)
    val = _tp_safe_eval(_ast.parse(m.group(1).split("  #")[0].strip(), mode="eval").body, src, depth + 1)
    _TP_CONST_CACHE[name] = val
    return val

def _tp_safe_eval(node, src: str, depth: int = 0):
    import operator as _op
    if isinstance(node, _ast.Constant):
        return node.value
    if isinstance(node, _ast.Name):
        if node.id in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[node.id]
        return _tp_const(node.id, src, depth)
    if isinstance(node, (_ast.List, _ast.Tuple, _ast.Set)):
        vals = [_tp_safe_eval(e, src, depth) for e in node.elts]
        return tuple(vals) if isinstance(node, _ast.Tuple) else vals
    if isinstance(node, _ast.Dict):
        return {_tp_safe_eval(k, src, depth): _tp_safe_eval(v, src, depth)
                for k, v in zip(node.keys, node.values)}
    if isinstance(node, _ast.UnaryOp) and isinstance(node.op, (_ast.USub, _ast.UAdd, _ast.Not)):
        x = _tp_safe_eval(node.operand, src, depth)
        return -x if isinstance(node.op, _ast.USub) else (+x if isinstance(node.op, _ast.UAdd) else not x)
    ops = {_ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mult: _op.mul, _ast.Div: _op.truediv,
           _ast.FloorDiv: _op.floordiv, _ast.Mod: _op.mod}
    if isinstance(node, _ast.BinOp) and type(node.op) in ops:
        l, r = _tp_safe_eval(node.left, src, depth), _tp_safe_eval(node.right, src, depth)
        if isinstance(l, str) and isinstance(r, (int, float)) and type(node.op) is _ast.Mult:
            raise ValueError("no string repeat")
        return ops[type(node.op)](l, r)
    if isinstance(node, _ast.JoinedStr):
        raise ValueError("f-string")
    if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name)
            and node.func.id in ("int", "float", "str", "round", "min", "max", "tuple", "list")
            and not node.keywords):
        fn = {"int": int, "float": float, "str": str, "round": round, "min": min,
              "max": max, "tuple": tuple, "list": list}[node.func.id]
        return fn(*[_tp_safe_eval(a, src, depth) for a in node.args])
    raise ValueError(type(node).__name__)


def _load_tunable_params() -> dict:
    """TUNABLE_PARAMS read from meme_sniper.py source (literal), so the engine is never imported."""
    try:
        # 2026-10-14: parse ONLY the TUNABLE_PARAMS statement. ast.parse of the whole 40k-line
        # engine took ~5.4 s at import and was the boot lag before the menu appeared.
        src = (_BASE / "meme_sniper.py").read_text(encoding="utf-8")
        tree = None
        m = _re.search(r"^TUNABLE_PARAMS\s*(?::[^=\n]*)?=", src, flags=_re.M)
        if m:
            lines = src[m.start():].split("\n")
            for i in range(1, len(lines)):
                if lines[i][:1] not in ("", " ", "\t", "}", ")", "]", "#"):
                    try:
                        tree = _ast.parse("\n".join(lines[:i]))
                        break
                    except SyntaxError:
                        continue
        if tree is None:
            tree = _ast.parse(src)
        for n in tree.body:
            if isinstance(n, _ast.Assign) and any(getattr(t, "id", "") == "TUNABLE_PARAMS" for t in n.targets):
                out = {}
                if isinstance(n.value, _ast.Dict):
                    for k, v in zip(n.value.keys, n.value.values):
                        try:
                            key = _ast.literal_eval(k)
                        except Exception:
                            continue
                        try:
                            out[key] = _ast.literal_eval(v)
                            continue
                        except Exception:
                            pass
                        # 2026-10-15: non-literal entry (refers to engine constants or
                        # arithmetic). Evaluate SAFELY - no imports, no calls beyond
                        # int/float/str/round/min/max/tuple/list - else show read-only.
                        try:
                            ent = _tp_safe_eval(v, src)
                            if isinstance(ent, dict):
                                out[key] = ent
                        except Exception:
                            try:
                                out[key] = {"type": "str", "default": None, "_readonly": True,
                                            "_expr": _ast.unparse(v)[:300],
                                            "description": "Computed in the engine - shown read-only."}
                            except Exception:
                                continue
                return out
    except Exception:
        pass
    return {}


TUNABLE_PARAMS = _load_tunable_params()


def get_override_sync(name: str, fallback=None):
    o = _ACTIVE_OVERRIDES.get(name)
    if isinstance(o, dict) and "value" in o:
        return o["value"]
    try:
        kn = json.loads(MEME_SNIPER_FILTER_FILE.read_text(encoding="utf-8-sig")).get("knobs", {}).get(name)
        if isinstance(kn, dict) and kn.get("value") is not None:
            return kn["value"]
    except Exception:
        pass
    return fallback


def write_inbox_packet_generic(packet: dict, prefix: str = "packet", identifier: str = "") -> Path:
    d = _WORKSPACE / "inbox"; d.mkdir(parents=True, exist_ok=True)
    p = d / f"meme_sniper - {prefix}_{str(identifier)[:12]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    _save_json_atomic(p, packet)
    return p


# engine health, mirrored from bot_logs/sniper_health.json
_UI_HEALTH: dict = {}
_GROK_FAILED_AT = 0.0
GROK_COOLDOWN_SECONDS = 0
_LAST_TEXT_LLM_SOURCE = ""
OLLAMA_ENABLED = False
_LAST_RPC_ERROR: dict = {}


def _drop_health_refresh() -> None:
    global _GROK_FAILED_AT, GROK_COOLDOWN_SECONDS, _LAST_TEXT_LLM_SOURCE, OLLAMA_ENABLED
    try:
        d = json.loads((_UI_PATHS["logs"] / "sniper_health.json").read_text(encoding="utf-8"))
    except Exception:
        return
    for k in ("grok", "grok_err", "rpc"):
        if isinstance(d.get(k), dict):
            _UI_HEALTH[k] = d[k]
    _GROK_FAILED_AT = float(d.get("grok_failed_at") or 0.0)
    GROK_COOLDOWN_SECONDS = float(d.get("grok_cooldown_s") or 0)
    _LAST_TEXT_LLM_SOURCE = str(d.get("llm_source") or "")
    OLLAMA_ENABLED = bool(d.get("ollama_enabled"))
    _LAST_RPC_ERROR.clear(); _LAST_RPC_ERROR.update(d.get("rpc_err") or {})


_RED_HOLD_STATE_FILE = _BOT_LOGS / "red_hold_review_state.json"


def _red_hold_review_pass(positions_path: Optional[Path] = None, state_path: Optional[Path] = None) -> int:
    """SNIPER_MAX_RED_HOLD_H (filter knob, 0 = off). A RED bag held past the limit gets a
    review card to the agent's inbox, at most once per 6h per mint. NEVER sells: Meme Sniper has no
    auto-sell on this path; the agent decides (set_protection / exit) after reading the card."""
    lim = float(get_override_sync("SNIPER_MAX_RED_HOLD_H", 0) or 0)
    if lim <= 0:
        return 0
    pp = positions_path or (_BOT_LOGS / "positions.json")
    sp = state_path or _RED_HOLD_STATE_FILE
    try:
        with open(pp, encoding="utf-8-sig") as f:
            pos = json.load(f)
    except Exception:
        return 0
    try:
        with open(sp, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    now, n = _now_ts(), 0
    for mint, p in (pos.items() if isinstance(pos, dict) else []):
        if not isinstance(p, dict):
            continue
        try:
            entry, last = float(p.get("entry_price") or 0), float(p.get("last_price_usd") or 0)
            t0 = p.get("opened_at_ts")
            if not t0 and p.get("opened_at"):
                t0 = datetime.fromisoformat(str(p["opened_at"])).timestamp()
            t0 = float(t0 or 0)
        except Exception:
            continue
        if not (entry and last and t0) or last >= entry:
            continue
        held_h = (now - t0) / 3600.0
        if held_h < lim or now - float(state.get(mint) or 0) < 6 * 3600:
            continue
        pkt = {"type": "red_hold_review", "from": "meme_sniper", "to": "agent", "fired_at": _now_iso(),
               "severity": "decision_request", "mint": mint, "ticker": p.get("ticker"),
               "held_hours": round(held_h, 2), "limit_hours": lim,
               "pnl_pct": round((last - entry) / entry * 100.0, 2), "mode": p.get("mode"),
               "armed_protection": p.get("armed_protection"),
               "ask": ("This bag has been RED longer than SNIPER_MAX_RED_HOLD_H. Nothing was sold (no auto-sell). "
                       "Review the thesis: hold, tighten SL/TP via set_protection, or exit."),
               "context": {"mint": mint}}
        try:
            write_inbox_packet_generic(pkt, prefix="red_hold_review", identifier=mint)
            state[mint] = now
            n += 1
            _log(f"red_hold_review: {p.get('ticker')} red {held_h:.1f}h >= {lim}h, card to the agent (no sell)", prefix="exitesc")
        except Exception as e:
            _log(f"red_hold_review card err: {e}", prefix="exitesc")
    if n:
        try:
            _save_json_atomic(sp, state)
        except Exception:
            pass
    return n




# =============================================================================
#   SNIPER UI (v14.3 appify): banner + menu in this window while the engine
#   trades. Display only: never spawns or supervises other bots. Fault
#   isolated: any UI error is logged to bot_logs/meme_sniper_ui_errors.log and
#   the UI turns itself off; trading carries on. No TTY or SNIPER_UI=0 -> no UI,
#   behaviour exactly as before.
# =============================================================================
import collections as _ui_collections
import threading as _ui_threading

_UI_RING = _ui_collections.deque(maxlen=3000)
_UI_LOCK = _ui_threading.Lock()
_UI_PATHS = {"root": _WORKSPACE, "logs": _BOT_LOGS, "relay": _JSON_RELAY,
             "filter": MEME_SNIPER_FILTER_FILE, "env": _BASE / ".env"}
_UI_CONSOLE_LOG_MAX = 20 * 1024 * 1024
_UI_GREEN, _UI_PURPLE, _UI_BG = "#39FF14", "#8A2BE2", "#000000"
_UI_TAGLINE = "Snipe, build, launch, all from one repo."
_UI_SOL_MINT = "So11111111111111111111111111111111111111112"
_UI_PRICE = {"at": 0.0, "prices": {}, "sol_usd": None, "sol_bal": None, "bal_at": 0.0, "err": None}
_UI_WORDMARK = [
    "\u2588\u2584 \u2584\u2588 \u2588\u2580\u2580 \u2588\u2584 \u2584\u2588 \u2588\u2580\u2580   \u2588\u2580\u2580 \u2588\u2584  \u2588 \u2588 \u2588\u2580\u2588 \u2588\u2580\u2580 \u2588\u2580\u2588",
    "\u2588 \u2580 \u2588 \u2588\u2580\u2580 \u2588 \u2580 \u2588 \u2588\u2580\u2580   \u2580\u2580\u2588 \u2588 \u2580\u2584\u2588 \u2588 \u2588\u2580\u2580 \u2588\u2580\u2580 \u2588\u2580\u2584",
    "\u2580   \u2580 \u2580\u2580\u2580 \u2580   \u2580 \u2580\u2580\u2580   \u2580\u2580\u2580 \u2580   \u2580 \u2580 \u2580   \u2580\u2580\u2580 \u2580 \u2580",
]
_UI_MENU = [("1", "Live dashboard"), ("2", "Logs"), ("3", "Settings"), ("4", "Skills"),
            ("5", "Launch a token"), ("6", "Sign in to X"),
            ("7", "Quit UI (engine keeps trading)"), ("8", "Stop Sniper")]


def _ui_console_log() -> Path:
    """Where this process's own output goes while the UI owns the screen. Engine-hosted UI: the
    engine console (same file the launcher writes, meme_sniper.console.log). Launcher / console-only:
    the UI process gets its own sniper_ui.console.log so it never mixes into a child's log."""
    name = "meme_sniper.console.log" if _UI_STATE.get("launched_with_ui") else "sniper_ui.console.log"
    return _UI_PATHS["logs"] / name


def _ui_err(where: str) -> None:
    try:
        _UI_PATHS["logs"].mkdir(parents=True, exist_ok=True)
        with open(_UI_PATHS["logs"] / "meme_sniper_ui_errors.log", "a", encoding="utf-8") as f:
            f.write(f"{_now_iso()} {where}\n{traceback.format_exc()}\n")
    except Exception:
        pass


def _ui_sink(text: str) -> None:
    """Engine output while the UI owns the screen: ring buffer + console log file."""
    try:
        with _UI_LOCK:
            for ln in str(text).splitlines():
                if ln.strip():
                    _UI_RING.append(ln)
            p = _ui_console_log()
            p.parent.mkdir(parents=True, exist_ok=True)
            try:
                if p.exists() and p.stat().st_size > _UI_CONSOLE_LOG_MAX:
                    os.replace(p, p.with_suffix(".log.1"))
            except Exception:
                pass
            with open(p, "a", encoding="utf-8", errors="replace") as f:
                f.write(str(text) if str(text).endswith("\n") else str(text) + "\n")
    except Exception:
        pass


class _UIStream:
    """Replaces sys.stdout/stderr while the UI is up so stray prints and tracebacks never hit the screen."""
    encoding = "utf-8"

    def __init__(self):
        self._buf = ""

    def write(self, s):
        try:
            self._buf += str(s)
            if "\n" in self._buf:
                head, self._buf = self._buf.rsplit("\n", 1)
                _ui_sink(head + "\n")
        except Exception:
            pass
        return len(s) if isinstance(s, str) else 0

    def flush(self):
        if self._buf:
            _ui_sink(self._buf); self._buf = ""

    def isatty(self):
        return False


def _ui_should_start() -> bool:
    if "--no-ui" in sys.argv:
        return False
    if (os.environ.get("SNIPER_UI") or "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    try:
        return bool(sys.stdin and sys.stdin.isatty() and sys.__stdout__ and sys.__stdout__.isatty())
    except Exception:
        return False


def _ui_activate() -> None:
    sys.stdout = _UIStream()
    sys.stderr = _UIStream()
    _UI_STATE["active"] = True


def _ui_deactivate() -> None:
    _UI_STATE["active"] = False
    for s in (sys.stdout, sys.stderr):
        try:
            s.flush()
        except Exception:
            pass
    sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__


# -- keys ---------------------------------------------------------------------
def _ui_getkey(timeout: float) -> str:
    """One key or '' after timeout. Esc -> 'esc'."""
    if os.name == "nt":
        import msvcrt
        end = time.time() + timeout
        while time.time() < end:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    c2 = msvcrt.getwch()
                    return {"H": "up", "P": "down", "I": "pgup", "Q": "pgdn", "G": "home", "O": "end"}.get(c2, "")
                return "esc" if ch == "\x1b" else ch
            time.sleep(0.05)
        return ""
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if not r:
            return ""
        ch = os.read(fd, 1).decode("utf-8", "replace")
        if ch == "\x1b":
            seq = ""
            while select.select([sys.stdin], [], [], 0.03)[0] and len(seq) < 6:
                seq += os.read(fd, 1).decode("utf-8", "replace")
            return {"[A": "up", "[B": "down", "[5~": "pgup", "[6~": "pgdn", "[H": "home", "[1~": "home",
                    "OH": "home", "[F": "end", "[4~": "end", "OF": "end"}.get(seq, "esc" if not seq else "")
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _ui_back(k: str) -> bool:
    return k in ("q", "Q", "esc", "b", "B")


def _ui_keys(*pairs) -> str:
    """One key-hint style everywhere: _ui_keys(("Q", "Back"), ("X", "Bags")) -> '[Q] Back  [X] Bags'.
    Letter keys are case-insensitive (the live loop lowercases them)."""
    return "  ".join(f"[{k}] {v}" for k, v in pairs)


_UI_SCROLL_HINT = ("\u2191\u2193 PgUp/PgDn", "Scroll")


_UI_NATIVE = {}


def _ui_native_unit(env: dict | None = None) -> str:
    """Native coin of the active chain (first enabled adapter), e.g. SOL. Goals use this unit."""
    if env is None and "u" in _UI_NATIVE:
        return _UI_NATIVE["u"]
    try:
        import chains
        ad = chains.load_adapters(env if env is not None else dict(os.environ))
        for a in ad.values():
            sym = str(getattr(a, "native_symbol", "") or "").strip().upper()
            if sym:
                if env is None:
                    _UI_NATIVE["u"] = sym
                return sym
    except Exception:
        pass
    return "SOL"


def _ui_pause(con, msg: str = "") -> None:
    """Show a result and STAY until q / back / esc / Enter (no timed auto-return)."""
    if msg:
        con.print(msg)
    con.print(_ui_keys(("Q", "Back"), ("Enter", "Continue")), style="dim")
    if not sys.stdin.isatty() or os.environ.get("SNIPER_UI_SMOKE"):
        return
    while _UI_STATE.get("active", True):
        k = _ui_getkey(1.0)
        if k and (_ui_back(k) or k in ("\r", "\n", " ")):
            return


# -- helpers ------------------------------------------------------------------
def _ui_json(p: Path, default=None):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def _ui_alerts_mod():
    try:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("ms_alerts_ui", str(_BASE / "sub-bots" / "alerts.py"))
        _m = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_m)
        return _m
    except Exception:
        return None


def _ui_alerts_rows(env: dict) -> list:
    """[(status, label, needs)] status first. No values ever."""
    am = _ui_alerts_mod()
    if am is None:
        return [("Unavailable", "alerts.py missing", "")]
    return [(st["status"], st["label"], ", ".join(st["missing"]) if st["missing"]
             else ("-" if st["keys"] else st.get("note", ""))) for st in am.status(env)]


def _ui_alerts_screen(con, opener=None) -> dict:
    """Settings > Alerts: channels status-first, a test message per channel. q / Esc = back.
    Channels are chosen with ALERT_CHANNELS (Settings row or the wizard)."""
    from rich import box
    from rich.prompt import Prompt
    from rich.table import Table
    from rich.text import Text
    am = _ui_alerts_mod()
    done = {}
    while _UI_STATE.get("active", True):
        env = _ui_env()
        t = Table(box=box.SIMPLE_HEAD, header_style=f"bold {_UI_PURPLE}", title="Alerts", title_justify="left")
        for c in ("Status", "#", "Channel", "Needs"):
            t.add_column(c, no_wrap=True)
        rows = _ui_alerts_rows(env)
        for i, (st, lab, need) in enumerate(rows, 1):
            style = f"bold {_UI_GREEN}" if st == "On" else ("bold red" if st.startswith("On") else "dim")
            t.add_row(Text(st, style=style), str(i), lab, need)
        con.print(t)
        con.print(Text("ALERT_CHANNELS = " + (",".join(am.channels(env)) or "off") if am else "", style="dim"))
        v = Prompt.ask("Test which # (a = all on, q / Esc = back)", default="q", console=con).strip().lower()
        if v in ("q", "back", "esc", "\x1b", ""):
            return done
        if am is None:
            continue
        sts = am.status(env)
        pick = [s["channel"] for s in sts if s["on"]] if v == "a" else \
            ([sts[int(v) - 1]["channel"]] if v.isdigit() and 1 <= int(v) <= len(sts) else [])
        if not pick:
            con.print("[red]pick a number, a, or q[/]"); continue
        for ch in pick:
            if ch not in am.CHANNELS:
                con.print("[dim]iMessage comes with the Mac version.[/]"); continue
            if am.missing(ch, env):
                con.print(f"[yellow]{am.CHANNELS[ch][0]}: needs {', '.join(am.missing(ch, env))}[/]"); continue
            res = am.test(ch, env_override=env, opener=opener)
            for k2, st2 in res.items():
                lab = am.CHANNELS[k2][0] if k2 in am.CHANNELS else "Telegram, Backup Alert Bot"
                con.print(f"Test, {lab}: " + (f"[{_UI_GREEN}]sent[/]" if st2 == "sent" else f"[red]{st2}[/]"))
                for code, hint in am.HINTS.items():
                    if code in st2:
                        con.print(f"[dim]{hint}[/]")
            done.update(res)
    return done


def _ui_env() -> dict:
    out = {}
    try:
        p = _BASE / ".env"
        for ln in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                out[k.strip()] = _re.sub(r"\s+#.*$", "", v).strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def _ui_tail(p: Path, n: int, max_bytes: int = 262144) -> list:
    try:
        with open(p, "rb") as f:
            f.seek(0, 2); size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", "replace")
        lines = [l for l in data.splitlines() if l.strip()]
        return lines[-n:]
    except FileNotFoundError:
        return [f"(nothing yet: {p.name} is created when that process first writes. Start Sniper with menu 1.)"]
    except Exception as e:
        return [f"(cannot read {p.name}: {type(e).__name__})"]


def _ui_f(v, nd=4, pre="", suf=""):
    try:
        return f"{pre}{float(v):,.{nd}f}{suf}"
    except (TypeError, ValueError):
        return "-"


def _ui_http(url, payload=None, timeout=10.0):
    import urllib.request
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "meme-sniper-ui",
                                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _ui_refresh_prices(mints, env) -> None:
    now = time.time()
    if now - _UI_PRICE["at"] >= 30:
        _UI_PRICE["at"] = now
        try:
            want = [_UI_SOL_MINT] + [m for m in mints if m][:29]
            j = _ui_http("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(want))
            best = {}
            for p in (j or {}).get("pairs") or []:
                m = (p.get("baseToken") or {}).get("address")
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                if m and (m not in best or liq > best[m][1]):
                    best[m] = (float(p.get("priceUsd") or 0), liq)
            _UI_PRICE["prices"].update({m: v[0] for m, v in best.items()})
            _UI_PRICE["sol_usd"] = _UI_PRICE["prices"].get(_UI_SOL_MINT) or _UI_PRICE["sol_usd"]
            _UI_PRICE["err"] = None
        except Exception as e:
            _UI_PRICE["err"] = f"prices: {type(e).__name__}"
    addr = env.get("HOT_WALLET_ADDRESS") or env.get("WALLET_ADDRESS")
    if addr and now - _UI_PRICE["bal_at"] >= 30:
        _UI_PRICE["bal_at"] = now
        try:
            rpc = env.get("RPC_URL") or "https://api.mainnet-beta.solana.com"
            j = _ui_http(rpc, {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]})
            _UI_PRICE["sol_bal"] = j["result"]["value"] / 1e9
        except Exception as e:
            _UI_PRICE["err"] = f"balance: {type(e).__name__}"


def _ui_today_rows(path: Path, keys=("at", "ts", "timestamp", "logged_at", "declined_at")) -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    for ln in _ui_tail(path, 20000, max_bytes=4 * 1024 * 1024):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if not isinstance(r, dict):
            continue
        stamp = next((str(r.get(k)) for k in keys if r.get(k)), "")
        try:
            if stamp.startswith(today) or (stamp.replace(".", "").isdigit() and
                                           datetime.fromtimestamp(float(stamp)).strftime("%Y-%m-%d") == today):
                out.append(r)
        except Exception:
            pass
    return out


def _ui_age_s(stamp) -> float:
    try:
        if isinstance(stamp, (int, float)):
            return time.time() - float(stamp)
        return time.time() - datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 1e9


def _ui_heartbeats() -> list:
    """Per-bot heartbeat files first, then the engine as one summary row (+ any unhealthy engine parts)."""
    rows = []
    logs = _UI_PATHS["logs"]
    eng_p = logs / "meme_sniper_heartbeat.json"
    for p in sorted(logs.glob("*_heartbeat.json")) if logs.exists() else []:
        if p == eng_p:
            continue
        d = _ui_json(p, {}) or {}
        d = d if isinstance(d, dict) else {}
        stamp = next((d.get(k) for k in ("last_update", "ts", "at", "timestamp", "updated_at") if d.get(k)), None)
        age = _ui_age_s(stamp) if stamp else time.time() - (_ui_mtime(p) or time.time())
        status = str(d.get("status") or d.get("state") or ("stopped:" + str(d["stop_reason"]) if d.get("stop_reason") else "ok"))
        rows.append((p.stem.replace("_heartbeat", ""), status, age))
    eng = _ui_json(eng_p, {}) or {}
    comps = (eng.get("components") or {}) if isinstance(eng, dict) else {}
    if eng_p.exists():
        bad = []
        ok = 0
        for name, r in comps.items():
            st = str((r or {}).get("status") or "?")
            if st in ("ok", "running", "healthy", "alive"):
                ok += 1
            else:
                bad.append((f"  meme_sniper.{name}", st, _ui_age_s((r or {}).get("last_update"))))
        age = time.time() - (_ui_mtime(eng_p) or time.time())
        stop = eng.get("stop_reason") if isinstance(eng, dict) else None
        rows.insert(0, ("meme_sniper", f"{ok}/{len(comps)} ok" + (f" stop={stop}" if stop else ""), age))
        rows[1:1] = bad[:6] + ([(f"  +{len(bad) - 6} more", "", 0)] if len(bad) > 6 else [])
    return rows


def _ui_hb_color(status: str, age: float) -> str:
    if any(w in status for w in ("stale", "error", "dead", "crash", "stopped", "cancelled")) or age > 1800:
        return "red"
    if age > 600 or status in ("starting", "degraded"):
        return "yellow"
    return _UI_GREEN


def _ui_age_txt(age: float) -> str:
    if age >= 1e8:
        return "-"
    age = int(age)
    return f"{age}s" if age < 120 else (f"{age // 60}m" if age < 7200 else f"{age // 3600}h")


# -- views --------------------------------------------------------------------
# -- X session status (no browser launch, never reads cookie values) ----------
def _ui_x_profiles() -> list:
    """Profile dirs agent_scraper uses: BROWSER_USER_DATA_DIR/BROWSER_PROFILE_NAME if set, then bots/scraper_profile."""
    if _UI_PATHS.get("x_profiles"):
        return [Path(p) for p in _UI_PATHS["x_profiles"]]
    env = _ui_env()
    out = []
    ud = (env.get("BROWSER_USER_DATA_DIR") or os.environ.get("BROWSER_USER_DATA_DIR") or "").strip()
    if ud:
        out.append(Path(ud) / ((env.get("BROWSER_PROFILE_NAME") or "Default").strip() or "Default"))
    out.append(_BASE / "scraper_profile" / "Default")
    return out


def _ui_x_cookie_meta(profile: Path):
    """{name: expires_epoch|0} for auth_token/ct0/twid. Reads names + expiry only (immutable, read-only)."""
    import sqlite3
    for db in (profile / "Network" / "Cookies", profile / "Cookies"):
        if not db.exists():
            continue
        con = sqlite3.connect("file:" + db.as_posix() + "?mode=ro&immutable=1", uri=True, timeout=2)
        try:
            rows = con.execute("SELECT name, expires_utc FROM cookies WHERE name IN ('auth_token','ct0','twid') "
                               "AND (host_key LIKE '%x.com' OR host_key LIKE '%twitter.com')").fetchall()
        finally:
            con.close()
        out = {}
        for n, e in rows:
            exp = (float(e) / 1e6 - 11644473600) if e else 0.0
            out[n] = max(out.get(n, 0.0), exp)
        return out
    return None


def _ui_x_handle() -> str:
    env = _ui_env()
    for k in ("AGENT_X_HANDLE", "X_HANDLE", "X_USERNAME", "SCRAPER_X_HANDLE"):
        v = (env.get(k) or "").strip()
        if v:
            return v if v.startswith("@") else "@" + v
    d = _ui_json(_UI_PATHS["logs"] / "agent_scraper_session.json", {}) or {}
    h = str(d.get("handle") or "").strip() if isinstance(d, dict) else ""
    return (h if h.startswith("@") else "@" + h) if h else ""


def _ui_x_session():
    try:
        sys.path.insert(0, str(_BASE / "sub-bots"))
        import x_session
        return x_session
    except Exception:
        return None


def _ui_x_status(force: bool = False) -> dict:
    """Honest X status from x_session (the same profile the scraper and the login use):
    ok = Connected (verified), unverified = cookie present but no recent logged-in page,
    expired, none = missing. Never opens a browser, never reads cookie values."""
    now = time.time()
    c = _UI_STATE.get("x_status")
    if c and not force and now - c["at"] < 60:
        return c
    st = {"at": now, "state": "none", "text": "X: Missing", "color": "red", "profile": "-", "detail": ""}
    try:
        xs = _ui_x_session()
        if xs is None:
            st["detail"] = "x_session.py not found"
        else:
            env = dict(_ui_env())
            if _UI_PATHS.get("x_profiles"):       # smoke: point at a fake profile
                fp = Path(_UI_PATHS["x_profiles"][0])
                env.update(BROWSER_USER_DATA_DIR=str(fp.parent), BROWSER_PROFILE_NAME=fp.name)
            r = xs.status(env)
            state = {"verified": "ok", "unverified": "unverified", "expired": "expired"}.get(r["state"], "none")
            st.update(state=state, text="X: " + xs.describe(r), profile=r["profile"], detail=r["detail"],
                      handle=r.get("handle", ""),
                      color={"ok": _UI_GREEN, "unverified": "yellow", "expired": "yellow"}.get(state, "red"))
        hb = _ui_json(_UI_PATHS["logs"] / "agent_scraper_heartbeat.json", {}) or {}
        if isinstance(hb, dict) and hb.get("timestamp"):
            st["detail"] += f"; scraper heartbeat {_ui_age_txt(_ui_age_s(hb['timestamp']))} ago ({hb.get('status', '?')})"
    except Exception:
        _ui_err("x status")
    _UI_STATE["x_status"] = st
    return st


# -- hold times, PnL periods (baseline + archive). Trade history is never touched. --
def _ui_epoch(v):
    try:
        if v is None or v == "":
            return None
        if isinstance(v, (int, float)) or str(v).replace(".", "").isdigit():
            return float(v)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _ui_dur(mins) -> str:
    if mins is None:
        return "-"
    m = int(round(float(mins)))
    return f"{m}m" if m < 60 else (f"{m // 60}h{m % 60:02d}m" if m < 1440 else f"{m // 1440}d{(m % 1440) // 60}h")


def _ui_baseline() -> dict:
    """Current PnL period start. pnl_baseline.json, else the last sniper scoreboard reset, else all-time."""
    b = _ui_json(_UI_PATHS["logs"] / "pnl_baseline.json", {}) or {}
    if isinstance(b, dict) and b.get("since"):
        return b
    sr = _ui_json(_UI_PATHS["logs"] / "scoreboard_resets.json", {}) or {}
    for r in reversed((sr.get("resets") or []) if isinstance(sr, dict) else []):
        if isinstance(r, dict) and r.get("lane") == "sniper" and r.get("at"):
            return {"since": r["at"], "source": "scoreboard_resets.json"}
    return {"since": None, "source": "all-time"}


def _ui_closed_trades() -> list:
    ar = _ui_json(_UI_PATHS["logs"] / "autopsy_reports.json", None)
    ar = ar.get("reports") if isinstance(ar, dict) else ar
    ar = list(ar.values()) if isinstance(ar, dict) else (ar or [])
    return [r for r in ar if isinstance(r, dict) and not str(r.get("still_holding")).lower() == "true"]


def _ui_hold_stats(trades) -> dict:
    def avg(xs):
        xs = [float(x) for x in xs if x not in (None, "")]
        return sum(xs) / len(xs) if xs else None
    out = {"all": avg(t.get("hold_minutes") for t in trades)}
    out["win"] = avg(t.get("hold_minutes") for t in trades if str(t.get("trade_outcome")).lower() == "win")
    out["loss"] = avg(t.get("hold_minutes") for t in trades if str(t.get("trade_outcome")).lower() in ("loss", "rug"))
    return out


def _ui_period_stats(since_iso) -> dict:
    t0 = _ui_epoch(since_iso) or 0.0
    trades = [t for t in _ui_closed_trades() if (_ui_epoch(t.get("exit_at") or t.get("entry_at")) or 0) >= t0]
    pnl = _ui_json(_UI_PATHS["logs"] / "pnl.json", []) or []
    sells = [r for r in pnl if isinstance(r, dict) and str(r.get("action", "sell")) == "sell"
             and (_ui_epoch(r.get("timestamp")) or 0) >= t0]
    realized = 0.0
    for r in sells:
        try:
            realized += float(r.get("pnl_sol") or 0)
        except Exception:
            pass
    oc = [str(t.get("trade_outcome")).lower() for t in trades]
    return {"since": since_iso, "realized_sol": realized, "sells": len(sells), "trades": len(trades),
            "wins": oc.count("win"), "losses": oc.count("loss") + oc.count("rug"), "scratches": oc.count("scratch"),
            "hold": _ui_hold_stats(trades)}


def _ui_open_unrealized_sol() -> float:
    pos = _ui_json(_UI_PATHS["logs"] / "positions.json", {}) or {}
    tot = 0.0
    for mint, p in (pos.items() if isinstance(pos, dict) else []):
        try:
            now = _UI_PRICE["prices"].get(mint) or p.get("last_price_usd")
            tot += (float(now) - float(p["entry_price"])) / float(p["entry_price"]) * float(p.get("amount_sol") or 0)
        except Exception:
            pass
    return tot


def _ui_hold_panel(positions: dict):
    from rich.panel import Panel
    from rich.table import Table
    now_t = time.time()
    if now_t - _UI_STATE.get("hold_at", 0) > 30 or "hold" not in _UI_STATE:
        base = _ui_baseline()
        _UI_STATE["hold"] = (_ui_hold_stats(_ui_closed_trades()), _ui_period_stats(base.get("since")), base)
        _UI_STATE["hold_at"] = now_t
    allh, per, base = _UI_STATE["hold"]
    opens = []
    for p in list(positions.values())[:8]:
        if isinstance(p, dict):
            t0 = _ui_epoch(p.get("opened_at_ts") or p.get("opened_at") or p.get("entry_at"))
            opens.append(f"{p.get('ticker', '?')} {_ui_dur((now_t - t0) / 60) if t0 else '-'}")
    sol_usd = _UI_PRICE["sol_usd"]
    since = str(base.get("since") or "all-time")[:10]
    t = Table.grid(padding=(0, 1))
    t.add_column(style=f"bold {_UI_PURPLE}"); t.add_column()
    t.add_row("Hold All-Time", f"{_ui_dur(allh['all'])}  (winners {_ui_dur(allh['win'])} / losers {_ui_dur(allh['loss'])})")
    t.add_row(f"Hold Since {since}", f"{_ui_dur(per['hold']['all'])}  (winners {_ui_dur(per['hold']['win'])} / "
                                     f"losers {_ui_dur(per['hold']['loss'])})")
    t.add_row("Open Holds", ", ".join(opens) or "-")
    usd = f" (${per['realized_sol'] * sol_usd:,.2f})" if sol_usd else ""
    t.add_row(f"Period Since {since}", f"realized {per['realized_sol']:+.4f} SOL{usd} | {per['wins']}W/{per['losses']}L"
                                       f"/{per['scratches']}S of {per['trades']} closed")
    return Panel(t, title="Hold Times + PnL Period   " + _ui_keys(("A", "Past Periods"), ("R", "Reset Period: archive + start new")),
                 border_style=_UI_GREEN)


def _ui_pnl_snapshot(goals: str = "") -> dict:
    base = _ui_baseline()
    per = _ui_period_stats(base.get("since"))
    unreal = _ui_open_unrealized_sol()
    sol_usd = _UI_PRICE["sol_usd"]
    goals_file = _ui_json(_UI_PATHS["logs"] / "sniper_goals.json", None)
    return {"period_start": base.get("since") or "all-time", "period_end": _now_iso(),
            "baseline_source": base.get("source") or "pnl_baseline.json",
            "realized_pnl_sol": round(per["realized_sol"], 6),
            "realized_pnl_usd": round(per["realized_sol"] * sol_usd, 2) if sol_usd else None,
            "total_pnl_sol": round(per["realized_sol"] + unreal, 6),
            "total_pnl_usd": round((per["realized_sol"] + unreal) * sol_usd, 2) if sol_usd else None,
            "sol_usd_at_archive": sol_usd, "wins": per["wins"], "losses": per["losses"],
            "scratches": per["scratches"], "trade_count": per["trades"], "sells": per["sells"],
            "avg_hold_min": {k: (round(v, 1) if v is not None else None) for k, v in per["hold"].items()},
            "goals": {"note": goals or None, "targets": (goals_file or {}).get("goals") if isinstance(goals_file, dict) else None,
                      "progress": [{"kind": g.get("kind"), "unit": g.get("unit"), "target": g.get("target"),
                                    "pct": (lambda p: round(p["pct"], 1) if p["pct"] is not None else None)(_ui_goal_progress(g))}
                                   for g in _ui_goals()]}}


def _ui_pnl_reset(goals: str = "") -> dict:
    """Archive the current period, THEN move the baseline. History files are read-only here."""
    snap = _ui_pnl_snapshot(goals)
    snap.update(archived_at=_now_iso(), who="owner_ui")
    p = _UI_PATHS["logs"] / "pnl_archive.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False, default=str) + "\n")
    b = _UI_PATHS["logs"] / "pnl_baseline.json"
    tmp = b.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"since": snap["period_end"], "set_at": snap["period_end"], "set_by": "owner_ui",
                               "previous": snap["period_start"]}, indent=2), encoding="utf-8")
    os.replace(tmp, b)
    _ui_change_log({"file": str(b), "key": "pnl_period_reset", "from": snap["period_start"], "to": snap["period_end"],
                    "takes_effect": "dashboard now", "archive": str(p)})
    _UI_STATE.pop("hold", None)
    return snap


def _ui_archive_rows() -> list:
    out = []
    for ln in _ui_tail(_UI_PATHS["logs"] / "pnl_archive.jsonl", 500):
        try:
            r = json.loads(ln)
            if isinstance(r, dict):
                out.append(r)
        except Exception:
            pass
    return out[::-1]


def _ui_archive_view(page: int = 0, per: int = 15):
    from rich import box
    from rich.table import Table
    rows = _ui_archive_rows()
    t = Table(title="Past PnL Periods   " + _ui_keys(("Q", "Back"), _UI_SCROLL_HINT), box=box.SIMPLE_HEAD,
              header_style=f"bold {_UI_PURPLE}", expand=True)
    for c in ("Start", "End", "Realized SOL", "$", "Total SOL", "W/L/S", "Trades", "Avg Hold (W/L)", "Goals"):
        t.add_column(c, overflow="ellipsis", no_wrap=True)
    for r in rows[page * per:(page + 1) * per]:
        h = r.get("avg_hold_min") or {}
        t.add_row(str(r.get("period_start"))[:16], str(r.get("period_end"))[:16],
                  _ui_f(r.get("realized_pnl_sol"), 4), _ui_f(r.get("realized_pnl_usd"), 2, "$"),
                  _ui_f(r.get("total_pnl_sol"), 4), f"{r.get('wins')}/{r.get('losses')}/{r.get('scratches')}",
                  str(r.get("trade_count")), f"{_ui_dur(h.get('all'))} ({_ui_dur(h.get('win'))}/{_ui_dur(h.get('loss'))})",
                  (lambda gg: (gg.get("note") or ", ".join(f"{x.get('kind')} {x.get('target')}{x.get('unit')} {x.get('pct')}%"
                                                     for x in (gg.get("progress") or [])) or "-")
                   if isinstance(gg, dict) else str(gg or "-"))(r.get("goals"))[:40])
    if not rows:
        t.add_row("No archived periods yet", "", "", "", "", "", "", "", "")
    return t, max(1, (len(rows) + per - 1) // per)


def _ui_archive_screen(con) -> None:
    page = {"p": 0}

    def _render():
        return _UIScroll("archive", lambda: _ui_archive_view(0, 10 ** 6)[0])

    def _key(k):
        if _ui_scroll_key("archive", k):
            return
        if k in ("n", " "):
            _ui_scroll_key("archive", "pgdn")
        elif k == "p":
            _ui_scroll_key("archive", "pgup")
    _ui_live_loop(con, _render, _key)


def _ui_reset_screen(con) -> None:
    from rich.prompt import Confirm, Prompt
    snap = _ui_pnl_snapshot()
    con.clear()
    con.print(f"[bold]Current period[/] {snap['period_start']} -> now")
    con.print(f"realized {snap['realized_pnl_sol']:+.4f} SOL, total {snap['total_pnl_sol']:+.4f} SOL, "
              f"{snap['wins']}W/{snap['losses']}L/{snap['scratches']}S of {snap['trade_count']} closed")
    con.print("[dim]Trade history is not changed. This archives the period to pnl_archive.jsonl and starts a new one.[/]")
    if not Confirm.ask("Archive this period and start a new one?", default=False, console=con):
        return
    goals = Prompt.ask("goals / note for this period (optional)", default="", console=con)
    s = _ui_pnl_reset(goals)
    _ui_pause(con, f"[{_UI_GREEN}]Archived[/] {s['period_start']} -> {s['period_end']}; new period started")


# -- profit goals (daily / weekly / custom) with momentum ------------------------
def _ui_goals_file() -> Path:
    return _UI_PATHS["logs"] / "sniper_goals.json"


def _ui_goals() -> list:
    d = _ui_json(_ui_goals_file(), {}) or {}
    g = d.get("goals") if isinstance(d, dict) else None
    return [x for x in (g or []) if isinstance(x, dict) and x.get("target")]


def _ui_goals_save(goals: list) -> None:
    p = _ui_goals_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"goals": goals, "updated_at": _now_iso(), "by": "owner_ui"}, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _ui_goal_start(kind: str):
    now = datetime.now().astimezone()
    if kind == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if kind == "weekly":
        d = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return (d - timedelta(days=d.weekday())).isoformat()
    return _ui_baseline().get("since")


def _ui_goal_progress(g: dict) -> dict:
    """PnL (realized since start + open unrealized), in the goal's unit, plus 15-min momentum."""
    now = time.time()
    since = _ui_goal_start(g.get("kind", "custom"))
    sol = _ui_period_stats(since)["realized_sol"] + _ui_open_unrealized_sol()
    sol_usd = _UI_PRICE["sol_usd"]
    unit = str(g.get("unit") or _ui_native_unit()).upper()
    # Goals are in the chain's native coin. Legacy USD goals (from older builds) still render.
    cur = sol * sol_usd if unit == "USD" and sol_usd else (None if unit == "USD" else sol)
    target = float(g["target"])
    hist = _UI_STATE.setdefault("goal_hist", {}).setdefault(g.get("id", "?"), [])
    if cur is not None:
        hist.append((now, cur))
    hist[:] = [h for h in hist if now - h[0] <= 15 * 60 + 60]
    rate = None
    if len(hist) >= 2 and hist[-1][0] - hist[0][0] >= 60:
        rate = (hist[-1][1] - hist[0][1]) / ((hist[-1][0] - hist[0][0]) / 3600.0)
    pct = (cur / target * 100.0) if (cur is not None and target) else None
    eta = None
    if cur is not None and rate and rate > 0 and cur < target:
        eta = (target - cur) / rate * 60.0      # minutes
    return {"since": since, "cur": cur, "target": target, "unit": unit, "pct": pct, "rate": rate,
            "eta_min": eta, "hit": cur is not None and cur >= target}


def _ui_goals_panel():
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    goals = _ui_goals()
    t = Table.grid(padding=(0, 1))
    t.add_column(style=f"bold {_UI_PURPLE}"); t.add_column(); t.add_column()
    if not goals:
        t.add_row("Goals", Text("None set (press G)", style="dim"), "")
    for g in goals:
        p = _ui_goal_progress(g)
        label = f"{str(g.get('kind') or '').title()} {p['target']:g} {p['unit']}"
        if p["cur"] is None:
            t.add_row(label, Text("Waiting for SOL price (legacy USD goal)", style="dim"), ""); continue
        fill = int(max(0.0, min(1.0, (p["pct"] or 0) / 100.0)) * 24)
        if p["hit"]:
            bar = Text("\u2588" * 24 + "  GOAL HIT", style="bold #FFD700")
        else:
            col = "white" if p["rate"] is None else (_UI_GREEN if p["rate"] >= 0 else "red")
            bar = Text("\u2588" * fill, style=col) + Text("\u2591" * (24 - fill), style="dim")
            bar.append(f" {p['pct']:.0f}%" if (p["pct"] or 0) >= 0 else " below 0", style="" if (p["pct"] or 0) >= 0 else "red")
        cur = f"{p['cur']:+.4f}" if p["unit"] != "USD" else f"{p['cur']:+,.2f}"
        mom = "-" if p["rate"] is None else (("\u25b2 " if p["rate"] >= 0 else "\u25bc ") +
                                              (f"{p['rate']:+.4f}" if p["unit"] != "USD" else f"{p['rate']:+,.2f}") + "/h")
        mom_t = Text(f"{cur} {p['unit']}  {mom}", style=(_UI_GREEN if (p["rate"] or 0) >= 0 else "red"))
        if p["eta_min"] is not None:
            mom_t.append(f"  ETA {_ui_dur(p['eta_min'])}", style="dim")
        t.add_row(label, bar, mom_t)
    return Panel(t, title="Profit Goals   " + _ui_keys(("G", "Set / Remove")) + "   Momentum: last 15 min", border_style="#FFD700")


def _ui_goals_view():
    from rich.console import Group
    from rich.text import Text
    goals = _ui_goals()
    parts = [_ui_goals_panel()]
    for i, g in enumerate(goals, 1):
        parts.append(Text(f"  {i}. {g.get('kind')}  {g.get('target')} {g.get('unit')}  (set {str(g.get('set_at'))[:16]})"))
    parts.append(Text(_ui_keys(("A", "Add / Replace Goal"), ("D", "Remove Goal"), _UI_SCROLL_HINT, ("Q", "Back")), style="dim"))
    return Group(*parts)


def _ui_goals_screen(con) -> None:
    from rich.prompt import FloatPrompt, Prompt
    while _UI_STATE["active"]:
        k = _ui_live_loop(con, lambda: _UIScroll("goals", _ui_goals_view),
                          lambda k: None if _ui_scroll_key("goals", k) else ("exit" if k in ("a", "d") else None))
        if k is None:
            return
        goals = _ui_goals()
        if k == "a":
            kind = Prompt.ask("Kind", choices=["daily", "weekly", "custom"], default="daily",
                              case_sensitive=False, console=con).strip().lower()
            unit = _ui_native_unit()          # goals are in the active chain's native coin
            tgt = FloatPrompt.ask(f"Target in {unit} (positive)", console=con)
            if tgt <= 0:
                _ui_pause(con, "[red]Target must be > 0[/]"); continue
            goals = [g for g in goals if g.get("kind") != kind]          # one goal per kind
            goals.append({"id": f"{kind}", "kind": kind, "unit": unit, "target": tgt, "set_at": _now_iso()})
            _ui_goals_save(goals)
            _ui_change_log({"file": str(_ui_goals_file()), "key": f"goal:{kind}", "to": f"{tgt} {unit}",
                            "takes_effect": "dashboard now"})
        elif k == "d" and goals:
            s = Prompt.ask("goal # to remove (blank cancels)", default="", console=con)
            if s.isdigit() and 1 <= int(s) <= len(goals):
                g = goals.pop(int(s) - 1)
                _ui_goals_save(goals)
                _UI_STATE.get("goal_hist", {}).pop(g.get("id"), None)
                _ui_change_log({"file": str(_ui_goals_file()), "key": f"goal:{g.get('kind')}", "from": g.get("target"),
                                "to": None, "takes_effect": "dashboard now"})


# -- UI settings (alerts) ---------------------------------------------------------
_UI_SET_DEFAULTS = {
    "ALERT_SOUND": (True, "beep pattern on alerts"),
    "ALERT_TOAST": (True, "Windows desktop toast on alerts (falls back to beep)"),
    "ALERT_GOAL_HIT": (True, "alert when a profit goal is hit"),
    "ALERT_SL_TP": (True, "alert when a stop-loss / take-profit fires"),
    "ALERT_WARDEN": (True, "alert on new security_warden cards in owner_inbox"),
    "MUTED": (False, "mute all alerts (m toggles)"),
}


def _ui_set_file() -> Path:
    return _UI_PATHS["logs"] / "sniper_ui_settings.json"


def _ui_settings() -> dict:
    d = _ui_json(_ui_set_file(), {}) or {}
    d = d if isinstance(d, dict) else {}
    return {k: bool(d.get(k, v[0])) for k, v in _UI_SET_DEFAULTS.items()}


def _ui_settings_set(key: str, val: bool) -> None:
    cur = _ui_settings()
    old = cur.get(key)
    cur[key] = bool(val)
    p = _ui_set_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    _ui_mark_own_write(p)
    _ui_change_log({"file": str(p), "key": key, "from": old, "to": bool(val), "takes_effect": "live"})


# -- alerts -------------------------------------------------------------------------
def _ui_beep(kind: str) -> None:
    try:
        if os.name == "nt":
            import winsound
            pat = {"goal": [(880, 120), (1175, 120), (1568, 220)], "sltp": [(660, 180), (440, 260)],
                   "warden": [(1000, 90), (1000, 90), (1000, 90)]}.get(kind, [(800, 150)])
            for f, d in pat:
                winsound.Beep(f, d)
        else:
            sys.__stdout__.write("\a"); sys.__stdout__.flush()
    except Exception:
        pass


def _ui_toast(title: str, body: str) -> bool:
    if os.name != "nt":
        return False
    import subprocess as _sp
    esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "''")[:200]
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
          "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null;"
          f"$x = New-Object Windows.Data.Xml.Dom.XmlDocument; $x.LoadXml('<toast><visual><binding template=\"ToastGeneric\">"
          f"<text>{esc(title)}</text><text>{esc(body)}</text></binding></visual></toast>');"
          "$t = [Windows.UI.Notifications.ToastNotification]::new($x);"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Meme Sniper').Show($t)")
    try:
        r = _sp.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                    timeout=15, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:
        return False


def _ui_alert(kind: str, title: str, body: str) -> None:
    """kind: goal | sltp | warden. Respects Settings toggles + mute. Never raises."""
    try:
        s = _ui_settings()
        _ui_sink(f"[alert:{kind}] {title} - {body}")
        _UI_STATE["last_alert"] = (f"{title}: {body}", time.time())
        gate = {"goal": "ALERT_GOAL_HIT", "sltp": "ALERT_SL_TP", "warden": "ALERT_WARDEN"}.get(kind)
        if s["MUTED"] or (gate and not s[gate]):
            return
        def _go():
            toasted = _ui_toast(title, body) if s["ALERT_TOAST"] else False
            if s["ALERT_SOUND"] or (s["ALERT_TOAST"] and not toasted):
                _ui_beep(kind)
        _ui_threading.Thread(target=_go, daemon=True, name="sniper-ui-alert").start()
    except Exception:
        _ui_err("alert")


def _ui_alert_scan(first: bool = False) -> None:
    """One pass: new SL/TP sells in the execution ledger, new warden cards, goal hits."""
    st = _UI_STATE.setdefault("alert_scan", {})
    logs, root = _UI_PATHS["logs"], _UI_PATHS["root"]
    led = logs / "execution_ledger.jsonl"
    try:
        size = led.stat().st_size if led.exists() else 0
        off = st.get("ledger_off")
        if off is None or first or size < off:
            st["ledger_off"] = size
        elif size > off:
            with open(led, "rb") as f:
                f.seek(off)
                chunk = f.read().decode("utf-8", "replace")
            st["ledger_off"] = size
            for ln in chunk.splitlines():
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                why = " ".join(str(r.get(k) or "") for k in ("exit_reason", "trigger", "reason", "event")).lower()
                if r.get("event") in ("sell", "partial_sell", "protective_sell") and any(
                        w in why for w in ("sl", "stop", "tp", "take_profit", "take-profit", "protect")):
                    _ui_alert("sltp", f"{'TP' if ('tp' in why or 'take' in why) else 'SL'} fired: {r.get('ticker', '?')}",
                              f"{r.get('exit_reason') or r.get('trigger') or ''} pnl {r.get('pnl_sol', '?')} SOL")
    except Exception:
        _ui_err("alert ledger")
    try:
        li = root / "owner_inbox"
        seen = st.setdefault("warden_seen", None)
        cur = {p.name for p in li.glob("security_warden*")} if li.exists() else set()
        if seen is None or first:
            st["warden_seen"] = cur
        else:
            for n in sorted(cur - seen):
                _ui_alert("warden", "Warden alert", n[:120])
            st["warden_seen"] = cur
    except Exception:
        _ui_err("alert warden")
    try:
        hit = st.setdefault("goal_hit", {})
        for g in _ui_goals():
            p = _ui_goal_progress(g)
            key = f"{g.get('id')}|{p['since']}|{g.get('target')}"
            if p["hit"] and not hit.get(key):
                hit[key] = True
                if not first:
                    _ui_alert("goal", "GOAL HIT", f"{g.get('kind')} {g.get('target')} {g.get('unit')}")
            elif p["hit"]:
                pass
    except Exception:
        _ui_err("alert goals")


def _ui_alert_loop() -> None:
    _ui_alert_scan(first=True)
    while _UI_STATE.get("active"):
        time.sleep(10)
        try:
            _ui_alert_scan()
        except Exception:
            _ui_err("alert loop")


def _ui_toggle_mute() -> None:
    m = not _ui_settings()["MUTED"]
    _ui_settings_set("MUTED", m)
    _UI_STATE["ext_marker"] = ("alerts MUTED" if m else "alerts on", time.time())


# -- health line ------------------------------------------------------------------
def _ui_health_text_core():
    from rich.text import Text
    h = _UI_HEALTH
    t = Text()
    g = h.get("grok") or {}
    t.append("grok ", style=f"bold {_UI_PURPLE}")
    t.append(f"{g['ms']:.0f}ms {_ui_age_txt(_ui_age_s(g['at']))} ago" if g.get("ms") is not None else "-",
             style=_UI_GREEN if g else "dim")
    ge = h.get("grok_err")
    if ge:
        t.append(f" last err {ge['detail'][:40]} ({_ui_age_txt(_ui_age_s(ge['at']))})", style="yellow")
    try:
        cooling = bool(globals().get("_GROK_FAILED_AT")) and (_now_ts() - _GROK_FAILED_AT) < GROK_COOLDOWN_SECONDS
    except Exception:
        cooling = False
    src = str(globals().get("_LAST_TEXT_LLM_SOURCE") or "")
    fb = cooling or src.startswith("local:")
    t.append("  local-ollama fallback ", style=f"bold {_UI_PURPLE}")
    t.append(("ACTIVE" if fb else "standby") + ("" if globals().get("OLLAMA_ENABLED", False) else " (disabled)"),
             style="yellow" if fb else "dim")
    r = h.get("rpc") or {}
    t.append("  rpc ", style=f"bold {_UI_PURPLE}")
    t.append(f"{r.get('label', '-')} {r['ms']:.0f}ms" if r.get("ms") is not None else "-", style=_UI_GREEN if r else "dim")
    try:
        le = globals().get("_LAST_RPC_ERROR") or {}
        if le.get("at"):
            t.append(f" last err {le.get('method', '')} {_redact(str(le.get('detail', '')))[:40]} "
                     f"({_ui_age_txt(_ui_age_s(le['at']))})", style="yellow")
    except Exception:
        pass
    return t


# -- red-hold flag (dashboard) -------------------------------------------------------
def _ui_red_hold_h() -> float:
    d = _ui_json(_ui_filter_path(), {}) or {}
    try:
        return float(((d.get("knobs") or {}).get("SNIPER_MAX_RED_HOLD_H") or {}).get("value") or 0)
    except Exception:
        return 0.0


# -- quick actions on a bag -----------------------------------------------------------
def _ui_owner_card(kind: str, pos: dict, mint: str, note: str = "") -> Path:
    """Card to the agent's inbox (workspace/inbox), 'botname - subject_ts' doctrine. Never trades."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tick = _re.sub(r"[^A-Za-z0-9_]", "", str(pos.get("ticker") or mint[:6]))[:16] or "bag"
    pkt = {"type": "owner_review_request" if kind == "review" else "owner_note",
           "from": "owner", "via": "sniper_ui", "to": "agent", "priority": "high", "fired_at": _now_iso(),
           "mint": mint, "ticker": pos.get("ticker"),
           "position": {k: pos.get(k) for k in ("entry_price", "last_price_usd", "amount_sol", "mode",
                                                "armed_protection", "opened_at", "own_launch") if k in pos},
           "note": note or None,
           "ask": ("The owner asks you to review this open bag now: re-read the thesis + live chart, and adjust the "
                   "on-chain SL/TP if warranted (set_protection). Reply with an owner card." if kind == "review"
                   else "Note from the owner about this bag. Read it, act if warranted, reply with an owner card."),
           "reply_to": "owner_inbox/agent - owner_reply_<ticker>_<ts>.md",
           "_doctrine": "From the owner via the Sniper UI. The UI never trades; this is a request, not an order fill."}
    d = _UI_PATHS["root"] / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"owner - owner_{'review' if kind == 'review' else 'note'}_{tick}_{ts}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pkt, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, p)
    _ui_change_log({"file": str(p), "key": f"owner_card:{kind}", "to": pos.get("ticker"), "takes_effect": "the agent's next inbox check"})
    return p


def _ui_quick_view(items):
    from rich.console import Group
    from rich.text import Text
    parts = [Text("Bag Actions   " + _ui_keys(("1-9 / Enter", "Choose Bag"), _UI_SCROLL_HINT, ("Q", "Back")), style="bold")]
    for i, (m, p) in enumerate(items, 1):
        parts.append(Text(f"  {i}. {p.get('ticker', '?')}  entry {p.get('entry_price')}  mode {p.get('mode')}",
                          no_wrap=True, overflow="ellipsis"))
    return Group(*parts)


def _ui_quick_actions(con) -> None:
    from rich.prompt import Confirm, Prompt
    pos = _ui_json(_UI_PATHS["logs"] / "positions.json", {}) or {}
    items = [(m, p) for m, p in (pos.items() if isinstance(pos, dict) else []) if isinstance(p, dict)]
    con.clear()
    if not items:
        from rich.panel import Panel
        _ui_live_loop(con, lambda: Panel("No open positions yet. Bags appear here when the engine opens one.\n\n"
                                         + _ui_keys(("Q", "Back")), title="Bag Actions", border_style=_UI_GREEN),
                      lambda k: None)
        return
    k = _ui_live_loop(con, lambda: _UIScroll("bags", lambda: _ui_quick_view(items)),
                      lambda k: None if _ui_scroll_key("bags", k) else
                      ("exit" if (k.isdigit() or k in ("\r", "\n", "s", "S")) else None))
    if k is None:
        return
    s = Prompt.ask("bag # (blank cancels)", default=k if k.isdigit() else "", console=con)
    if not s.isdigit() or not (1 <= int(s) <= len(items)):
        return
    mint, p = items[int(s) - 1]
    a = Prompt.ask("1 = Ask the agent to review, 2 = Note to the agent (blank cancels)", choices=["1", "2", ""], default="", console=con)
    if not a:
        return
    note = Prompt.ask("note", default="", console=con) if a == "2" else Prompt.ask("optional note", default="", console=con)
    if a == "2" and not note.strip():
        return
    if Confirm.ask(f"Send {'review request' if a == '1' else 'note'} on {p.get('ticker')} to the agent's inbox? (never trades)",
                   default=False, console=con):
        f = _ui_owner_card("review" if a == "1" else "note", p, mint, note.strip())
        _ui_pause(con, f"[{_UI_GREEN}]Written[/] {f}")


# -- files can vanish between glob() and stat()/read (the engine archives inbox packets and
# rotates relay files every few seconds). List-then-read must skip a vanished file, not crash.
def _ui_net_pct_str(r: dict) -> str:
    """Net wallet % (pnl_sol / SOL spent), one decimal - the same basis as the recap. Falls back to price %."""
    try:
        cost = float(r.get("cost_basis_sol") or r.get("amount_sol") or 0)
        if cost > 0 and r.get("pnl_sol") is not None:
            return f"{float(r['pnl_sol']) / cost * 100:+.1f}% net"
        return f"{float(r.get('pnl_pct')):+.1f}%"
    except Exception:
        return "-"


def _ui_mtime(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def _ui_newest(paths) -> list:
    """Paths sorted newest-first, silently dropping any that vanished mid-listing."""
    got = [(m, p) for p in paths for m in (_ui_mtime(p),) if m is not None]
    return [p for _m, p in sorted(got, key=lambda x: x[0], reverse=True)]


def _ui_hhmmss(p) -> str:
    m = _ui_mtime(p)
    return datetime.fromtimestamp(m).strftime("%H:%M:%S  ") if m else "(gone)    "


# -- daily recap ------------------------------------------------------------------------
def _ui_recap() -> dict:
    base = _ui_baseline()
    per = _ui_period_stats(base.get("since"))
    today = _ui_period_stats(_ui_goal_start("daily"))
    t0 = _ui_epoch(base.get("since")) or 0
    trades = [t for t in _ui_closed_trades() if (_ui_epoch(t.get("exit_at") or t.get("entry_at")) or 0) >= t0]
    def _pp(t):
        # 2026-10-14: rank and show the NET wallet result (pnl_sol / SOL spent), the same number
        # the realized-SOL line uses. pnl_pct is the gross PRICE move (exit vs entry price) and
        # leaves out fees/slippage: gork showed +0.19% price but -0.0021 SOL (-2.1%) net.
        try:
            cost = float(t.get("cost_basis_sol") or t.get("amount_sol") or 0)
            if cost > 0 and t.get("pnl_sol") is not None:
                return float(t.get("pnl_sol")) / cost * 100.0
        except Exception:
            pass
        try:
            return float(t.get("pnl_pct"))
        except Exception:
            return None
    ranked = sorted([t for t in trades if _pp(t) is not None], key=_pp)
    fmt = lambda t: f"{t.get('ticker', '?')} {_pp(t):+.1f}% net ({t.get('exit_type') or 'unknown_exit'})" if t else "-"
    sol_usd = _UI_PRICE["sol_usd"]
    return {"at": _now_iso(), "period_start": base.get("since") or "all-time",
            "period_realized_sol": round(per["realized_sol"], 6),
            "period_realized_usd": round(per["realized_sol"] * sol_usd, 2) if sol_usd else None,
            "today_realized_sol": round(today["realized_sol"], 6),
            "best_trade": fmt(ranked[-1] if ranked else None), "worst_trade": fmt(ranked[0] if ranked else None),
            "wins": per["wins"], "losses": per["losses"], "scratches": per["scratches"], "closed": per["trades"],
            "avg_hold_min": {k: (round(v, 1) if v is not None else None) for k, v in per["hold"].items()},
            "goals": [{"kind": g.get("kind"), "target": g.get("target"), "unit": g.get("unit"),
                       "pct": (lambda p: round(p["pct"], 1) if p["pct"] is not None else None)(_ui_goal_progress(g))}
                      for g in _ui_goals()]}


def _ui_write_recap(reason: str) -> dict:
    r = _ui_recap()
    r["reason"] = reason
    p = _UI_PATHS["logs"] / "daily_recaps.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(r, default=str) + "\n")
    li = _UI_PATHS["root"] / "owner_inbox"
    li.mkdir(parents=True, exist_ok=True)
    h = r["avg_hold_min"]
    md = "\n".join([
        "---", "kind: daily_recap", "severity: info", f"dedupe_key: meme_sniper:daily_recap:{r['at'][:10]}",
        "source_skill: sniper-ui", f"summary: today {r['today_realized_sol']:+.4f} SOL, period {r['period_realized_sol']:+.4f} SOL", "---",
        f"# Meme Sniper recap ({reason})", "",
        f"- period since {str(r['period_start'])[:16]}: realized {r['period_realized_sol']:+.4f} SOL"
        + (f" (${r['period_realized_usd']:,.2f})" if r["period_realized_usd"] is not None else ""),
        f"- today: realized {r['today_realized_sol']:+.4f} SOL",
        f"- W/L/S {r['wins']}/{r['losses']}/{r['scratches']} of {r['closed']} closed",
        f"- best {r['best_trade']} | worst {r['worst_trade']}",
        f"- avg hold {_ui_dur(h.get('all'))} (winners {_ui_dur(h.get('win'))} / losers {_ui_dur(h.get('loss'))})",
        "- goals: " + (", ".join(f"{g['kind']} {g['target']} {g['unit']} {g['pct']}%" for g in r["goals"]) or "none"),
        ""])
    (li / f"meme_sniper - daily_recap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md").write_text(md, encoding="utf-8")
    return r


def _ui_recap_view():
    from rich.console import Group
    from rich.text import Text
    c = _UI_STATE.get("recap_view")
    if not c or time.time() - c[0] > 10:
        r = _ui_recap()
        past = []
        for ln in reversed(_ui_tail(_UI_PATHS["logs"] / "daily_recaps.jsonl", 200)):
            try:
                past.append(json.loads(ln))
            except Exception:
                pass
        c = (time.time(), r, past)
        _UI_STATE["recap_view"] = c
    _, r, past = c
    h = r["avg_hold_min"]
    parts = [Text("Recap Now (written on Quit/Stop)   " + _ui_keys(_UI_SCROLL_HINT, ("Q", "Back")), style=f"bold {_UI_GREEN}"),
             Text(f"period since {str(r['period_start'])[:16]}: realized {r['period_realized_sol']:+.4f} SOL"
                  + (f" (${r['period_realized_usd']:,.2f})" if r["period_realized_usd"] is not None else "")),
             Text(f"today: realized {r['today_realized_sol']:+.4f} SOL"),
             Text(f"W/L/S {r['wins']}/{r['losses']}/{r['scratches']} of {r['closed']} closed"),
             Text(f"best {r['best_trade']} | worst {r['worst_trade']}"),
             Text(f"avg hold {_ui_dur(h.get('all'))} (winners {_ui_dur(h.get('win'))} / losers {_ui_dur(h.get('loss'))})"),
             Text("goals: " + (", ".join(f"{g['kind']} {g['target']} {g['unit']} {g['pct']}%" for g in r["goals"]) or "none")),
             Text(""), Text(f"past recaps ({len(past)}, newest first)", style=f"bold {_UI_PURPLE}")]
    for x in past:
        if isinstance(x, dict):
            parts.append(Text(f"{str(x.get('at'))[:16]}  {x.get('reason', '')}  today {_ui_f(x.get('today_realized_sol'), 4)}  "
                              f"period {_ui_f(x.get('period_realized_sol'), 4)}  W/L/S {x.get('wins')}/{x.get('losses')}/"
                              f"{x.get('scratches')}", no_wrap=True, overflow="ellipsis"))
    return Group(*parts)


def _ui_recap_screen(con) -> None:
    _UI_STATE.pop("recap_view", None)
    _ui_live_loop(con, lambda: _UIScroll("recap", _ui_recap_view), lambda k: (_ui_scroll_key("recap", k), None)[1])


def _ui_red_flag(p: dict) -> bool:
    try:
        lim = _UI_STATE.get("red_lim")
        if lim is None or time.time() - _UI_STATE.get("red_lim_at", 0) > 30:
            lim = _ui_red_hold_h(); _UI_STATE["red_lim"], _UI_STATE["red_lim_at"] = lim, time.time()
        if lim <= 0:
            return False
        t0 = _ui_epoch(p.get("opened_at_ts") or p.get("opened_at"))
        return bool(t0) and float(p.get("last_price_usd")) < float(p.get("entry_price")) and \
            (time.time() - t0) / 3600 >= lim
    except Exception:
        return False


def _ui_banner():
    from rich import box
    from rich.align import Align
    from rich.panel import Panel
    from rich.text import Text
    t = Text(justify="center")
    for i, ln in enumerate(_UI_WORDMARK):
        t.append(ln + "\n", style=f"bold {_UI_GREEN if i < 2 else _UI_PURPLE} on {_UI_BG}")
    t.append("v1.0.1  console; engine and sub-bots run under the supervisor\n", style=f"{_UI_PURPLE} on {_UI_BG}")
    t.append(_UI_TAGLINE, style=f"italic {_UI_GREEN} on {_UI_BG}")
    if _ui_paper_on():
        t.append("\n PAPER MODE - simulated trades, no real transactions (bot_logs/paper/) ",
                 style="bold black on yellow")
    return Panel(Align.center(t), style=f"on {_UI_BG}", border_style=_UI_PURPLE, box=box.HEAVY)


def _ui_menu_panel():
    from rich import box
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    t = Table.grid(padding=(0, 2))
    try:
        xs = _ui_x_status()
    except Exception:
        xs = None
    for k, v in _UI_MENU:
        row = Text(v, style="white")
        if v == "Sign in to X" and xs:
            row.append("   " + xs["text"], style=xs["color"])
        t.add_row(Text(k, style=f"bold {_UI_GREEN}"), row)
    last = (_ui_tail(_UI_PATHS["logs"] / "meme_sniper.console.log", 1) or ["(no engine output yet)"])[-1][:110]
    return Panel(t, title="Menu   " + _ui_keys(("1-9", "Open"), ("M", "Mute Alerts")), subtitle=Text(last, style="dim"),
                 border_style=_UI_GREEN, style=f"on {_UI_BG}", box=box.ROUNDED)


def _ui_dashboard_view(env):
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    logs, root = _UI_PATHS["logs"], _UI_PATHS["root"]
    positions = _ui_json(logs / "positions.json", {}) or {}
    positions = positions if isinstance(positions, dict) else {}
    holdings = _ui_json(logs / "holdings.json", {}) or {}
    holdings = holdings if isinstance(holdings, dict) else {}
    own = ((_ui_json(logs / "own_launches.json", {}) or {}).get("launches") or {})
    pnl = _ui_json(logs / "pnl.json", []) or []
    sol_usd, bal = _UI_PRICE["sol_usd"], _UI_PRICE["sol_bal"]
    top = Table.grid(padding=(0, 3))
    top.add_row(Text(f"Wallet {_ui_f(bal, 4)} SOL", style=f"bold {_UI_GREEN}"),
                Text(f"~ {_ui_f((bal or 0) * sol_usd, 2, '$')}" if bal is not None and sol_usd else "~ -"),
                Text(f"SOL {_ui_f(sol_usd, 2, '$')}"), Text(datetime.now().strftime("%H:%M:%S"), style="dim"))
    pt = Table(title="Open Positions", box=box.SIMPLE_HEAD, header_style=f"bold {_UI_PURPLE}", expand=True)
    for c in ("Token", "Entry", "Now", "PnL %", "PnL $", "SL/TP", "Mode"):
        pt.add_column(c)
    for mint, p in list(positions.items())[:15]:
        if not isinstance(p, dict):
            continue
        entry = p.get("entry_price")
        now = _UI_PRICE["prices"].get(mint) or p.get("last_price_usd")
        try:
            pct = (float(now) - float(entry)) / float(entry) * 100
            usd = pct / 100 * float(p.get("amount_sol") or 0) * (sol_usd or 0)
        except Exception:
            pct = usd = None
        ap = p.get("armed_protection") or {}
        armed = ("SL " if ap.get("sl_pct") is not None else "") + ("TP" if ap.get("tp_pct") is not None else "")
        pt.add_row(f"{p.get('ticker', '?')}{' [own]' if p.get('own_launch') else ''}", _ui_f(entry, 8), _ui_f(now, 8),
                   Text(_ui_f(pct, 1, suf="%"), style=_UI_GREEN if (pct or 0) >= 0 else "red"),
                   _ui_f(usd, 2, "$"), armed or "no",
                   Text(str(p.get("mode") or "-") + (" RED>max" if _ui_red_flag(p) else ""),
                        style="bold red" if _ui_red_flag(p) else ""))
    if not positions:
        pt.add_row("No open positions", "", "", "", "", "", "")
    tt = Table(title="Treasury / Holdings", box=box.SIMPLE_HEAD, header_style=f"bold {_UI_PURPLE}", expand=True)
    for c in ("Token", "Class", "Value $", "Tag"):
        tt.add_column(c)
    for mint, h in list(holdings.items())[:10]:
        if isinstance(h, dict):
            tt.add_row(str(h.get("ticker") or mint[:6]), str(h.get("class") or "-"),
                       _ui_f(h.get("est_usd") or h.get("usd_value"), 2, "$"),
                       "own_launch" if (h.get("own_launch") or mint in own) else "")
    for mint, r in own.items():
        if mint not in holdings:
            tt.add_row(str(r.get("ticker") or mint[:6]), str(r.get("status") or "-"), "-", "own_launch")
    if not holdings and not own:
        tt.add_row("Nothing held", "", "", "")
    now_t = time.time()
    if now_t - _UI_STATE.get("stats_at", 0) > 15:
        ledger = _ui_today_rows(logs / "execution_ledger.jsonl")
        _UI_STATE["stats"] = (
            sum(1 for r in ledger if r.get("event") in ("buy", "override_buy")),
            sum(float(r.get("pnl_sol") or 0) for r in ledger if r.get("event") == "sell"),
            sum(float(r.get("pnl_sol") or 0) for r in pnl if isinstance(r, dict)),
            len(_ui_today_rows(logs / "decline_log.jsonl")))
        _UI_STATE["stats_at"] = now_t
    buys, today_pnl, total_pnl, declines = _UI_STATE.get("stats", (0, 0.0, 0.0, 0))
    st = Table.grid(padding=(0, 3))
    st.add_row(Text(f"Today {today_pnl:+.4f} SOL", style=_UI_GREEN if today_pnl >= 0 else "red"),
               Text(f"Total {total_pnl:+.4f} SOL", style=_UI_GREEN if total_pnl >= 0 else "red"),
               Text(f"Buys Today {buys}"), Text(f"Declines Today {declines}"))
    ht = Table(title="Heartbeats", box=box.SIMPLE_HEAD, header_style=f"bold {_UI_PURPLE}", expand=True)
    ht.add_column("Bot"); ht.add_column("Status"); ht.add_column("Age")
    hbs = _ui_heartbeats()
    for name, status, age in hbs[:40]:
        ht.add_row(name, Text(status, style=_ui_hb_color(status, age)), _ui_age_txt(age))
    if not hbs:
        ht.add_row("No heartbeats yet", "", "")
    inbox, owner = root / "inbox", root / "owner_inbox"
    cards = _ui_newest(inbox.glob("*"))[:4] if inbox.exists() else []
    alerts = _ui_newest(owner.glob("*.md"))[:3] if owner.exists() else []
    extra = [Text("Last Cards: " + (", ".join(p.name[:44] for p in cards) or "none"), style="dim"),
             Text("Alerts: " + (", ".join(p.name[:44] for p in alerts) or "none"), style="yellow" if alerts else "dim")]
    if _UI_PRICE["err"]:
        extra.append(Text(_UI_PRICE["err"], style="dim"))
    try:
        ap = _ui_autopsy_panel()
    except Exception:
        ap = Text("autopsy: -", style="dim")
    try:
        hp = _ui_hold_panel(positions)
    except Exception:
        _ui_err("hold panel")
        hp = Text("hold times: -", style="dim")
    try:
        hl = _ui_health_text()
    except Exception:
        hl = Text("health: -", style="dim")
    la = _UI_STATE.get("last_alert")
    if la and time.time() - la[1] < 120:
        extra.insert(0, Text("ALERT: " + la[0][:120], style="bold yellow"))
    if _ui_marker():
        extra.insert(0, Text(_ui_marker(), style="bold yellow"))
    try:
        gp = _ui_goals_panel()
    except Exception:
        _ui_err("goals panel")
        gp = Text("goals: -", style="dim")
    return Group(Panel(top, title="Sniper Dashboard   " + _ui_keys(("Q", "Back"), ("X", "Bags"), ("G", "Goals"), ("A", "Periods"),
                                                     ("R", "Reset Period"), ("C", "Recap"), ("M", "Mute"),
                                                     _UI_SCROLL_HINT),
                       border_style=_UI_GREEN, style=f"on {_UI_BG}"), pt, tt, st, gp, hp, ap, ht, hl, *extra)


def _ui_log_sources():
    logs, root = _UI_PATHS["logs"], _UI_PATHS["root"]
    # Paths match what the code writes: sniper.py gives every child bot_logs/<name>.console.log;
    # security_warden writes security_warden.json, medic_log.json and integrity_log.json; the agent
    # appends bot_alerts.json (forensics skill, FILTER_CLEARED_NO_BUY only).
    # Paper mode: meme_sniper moves TRADES_LOG / EXEC_LEDGER_FILE into bot_logs/paper/ (_PAPER_STATE_NAMES).
    tl = logs / "paper" if _ui_paper_on() else logs
    # json_relay/ is the folder the engine polls (meme_sniper _JSON_RELAY = <drop>/json_relay).
    return [("1", "Sniper Console", "ring"),
            ("2", "Trades" + (" (Paper)" if tl != logs else ""), tl / "trades.log"),
            ("3", "Execution Ledger" + (" (Paper)" if tl != logs else ""), tl / "execution_ledger.jsonl"),
            ("4", "Declines", logs / "decline_log.jsonl"),
            ("5", "Warden Alerts", (logs / "security_warden.json", logs / "medic_log.json",
                                    logs / "integrity_log.json", logs / "bot_alerts.json")),
            ("6", "Owner Inbox", root / "owner_inbox"),
            ("i", "Agent Inbox", ("inbox", root / "inbox")),
            ("r", "JSON Relay", ("relay", root / "json_relay")),
            ("w", "Warden", logs / "security_warden.console.log"),
            ("a", "Autoagent", logs / "agent_autoagent.console.log"),
            ("x", "X Intel", logs / "x_intel.console.log"),
            ("s", "Scraper", logs / "agent_scraper.console.log"),
            ("t", "Tuner", logs / "code_tuner.console.log"),
            ("j", "Janitor", logs / "log_janitor.console.log"),
            ("e", "Learnings", (logs / "learnings_writer.console.log", logs / "learnings_writer.jsonl")),
            ("8", "Trench News", (logs / "trench_news.console.log", logs / "trench_news.jsonl")),
            ("l", "Launcher", logs / "sniper_launcher.log")]


# Friendly empty states: these files are created on first write, so "missing" usually just means "nothing yet".
_UI_EMPTY = {
    "trades.log": "no trades yet, waiting for first trade",
    "execution_ledger.jsonl": "no trades yet, waiting for first trade (buys, sells and exits land here)",
    "decline_log.jsonl": "no buy-gate declines yet (filter skips go to skip_log.json)",
    "security_warden.json": "no warden findings yet",
    "medic_log.json": "no medic actions yet",
    "integrity_log.json": "no integrity events yet (nothing changed or deleted)",
    "bot_alerts.json": "no bot alerts yet",
    "sniper_launcher.log": "launcher has not logged anything yet",
    "learnings_writer.console.log": "learnings writer has not logged anything yet",
    "learnings_writer.jsonl": "no learnings appended yet",
    "trench_news.console.log": "trench news has not logged anything yet",
    "trench_news.jsonl": "no trench news yet (first pass only records a baseline)",
}


def _ui_empty_msg(src: Path) -> str:
    n = src.name
    if n in _UI_EMPTY:
        return f"({_UI_EMPTY[n]})"
    if n.endswith(".console.log"):
        return f"({n[:-12]} has not written output yet; it may not be running)"
    return f"({n}: nothing written yet)"


# JSON Relay filter: only files that belong to Sniper. A relay file counts when
#   (a) its name is one of the relay files the Sniper engine itself reads or writes
#       (_UI_SNIPER_RELAY_NAMES, taken from meme_sniper.py), or it sits in launch_requests/, or
#   (b) its name contains "sniper" or "meme", or
#   (c) its JSON names Sniper in a routing field: from / to / bot / source / target / lane / type
#       contains "sniper" or "meme".
# Other bots' files (perps, flow, pre-sweep acks, scripts) are hidden.
_UI_SNIPER_RELAY_NAMES = frozenset(['agent_signals.json', 'agent_x_actions.json', 'archetype_command.json', 'ca_research_request.json', 'ca_research_response.json', 'chart_request.json', 'chart_response.json', 'deep_research_request.json', 'deep_research_response.json', 'kol_list_proposals.json', 'launch_results.json', 'signals_response.json', 'sniper_discovery_query.json', 'sniper_discovery_query_response.json', 'sniper_meeting.json', 'social_research_request.json', 'social_research_response.json', 'suggestions.json', 'x_thread_handoff.json'])
_UI_RELAY_FIELDS = ("from", "to", "bot", "source", "target", "lane", "type")


def _ui_is_sniper_relay(f) -> bool:
    f = Path(f)
    n = f.name.lower()
    if n in _UI_SNIPER_RELAY_NAMES or f.parent.name == "launch_requests" or "sniper" in n or "meme" in n:
        return True
    d = _ui_json(f, None)
    for it in (d if isinstance(d, list) else [d])[:50]:
        if isinstance(it, dict) and any(w in str(it.get(k) or "").lower()
                                        for k in _UI_RELAY_FIELDS for w in ("sniper", "meme")):
            return True
    return False


def _ui_log_lines(src, n: int) -> list:
    if src == "ring":
        p = _UI_PATHS["logs"] / "meme_sniper.console.log"
        return _ui_tail(p, n) if p.exists() else ["(no engine output yet)"]
    if isinstance(src, tuple) and len(src) == 2 and src[0] == "inbox":   # agent inbox: newest packets
        d = Path(src[1])
        files = _ui_newest(d.glob("*.json")) if d.exists() else []
        if not files:
            return ["(inbox empty: the feed has not queued any packets yet)"]
        out = [f"{len(files)} packet(s) waiting for the agent, newest first", "-" * 40]
        out += [_ui_hhmmss(p) + p.name for p in files[:n]]
        return out[:n]
    if isinstance(src, tuple) and len(src) == 2 and src[0] == "relay":   # json_relay: requests/responses, newest first
        d = Path(src[1])
        _allf = [f for f in d.rglob("*.json") if f.is_file()] if d.exists() else []
        files = _ui_newest(f for f in _allf if _ui_is_sniper_relay(f))
        if not files:
            return ["(JSON relay empty for Sniper: no requests or responses in flight. The engine consumes requests "
                    "within ~5-30 s and acks them to inbox/ (failed) or inbox_results/done/ (ok).)"]
        def _summ(f):
            dd = _ui_json(f, None)
            if isinstance(dd, dict):
                for key in ("requests", "responses", "signals", "proposals"):
                    if isinstance(dd.get(key), list):
                        rows = dd[key]
                        pend = sum(1 for r in rows if isinstance(r, dict) and r.get("status") not in ("done", "failed"))
                        return f"{len(rows)} {key}" + (f", {pend} pending" if key in ("requests", "signals") else "")
                return f"{len(dd)} field(s)"
            if isinstance(dd, list):
                return f"{len(dd)} item(s)"
            return "unreadable / partial write"
        out = [f"{len(files)} Sniper relay file(s), newest first (filtered from {len(_allf)} in json_relay/)", "-" * 40]
        out += [_ui_hhmmss(f) + f"{f.name:<38} {_summ(f)}"
                for f in files]
        out += ["-" * 40, f"== {files[0].name} (newest) =="]
        try:
            txt = json.dumps(_ui_json(files[0], {}), indent=1, ensure_ascii=False, default=str)
            out += txt.splitlines()
        except Exception:
            pass
        return out[:n]
    if isinstance(src, (tuple, list)):          # several files under one tab, newest entries last
        out = []
        for p in src:
            out += [f"== {Path(p).name} =="] + _ui_log_lines(p, max(5, n // len(src)))
        return out
    src = Path(src)
    if src.is_dir():
        files = _ui_newest(src.glob("*.md"))
        if not files:
            return ["(no owner messages yet)"]
        out = ["newest: " + ", ".join(p.name for p in files[:5]), "-" * 40, f"== {files[0].name} =="]
        try:
            out += files[0].read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            pass
        return out[:n]
    if not src.exists():
        return [_ui_empty_msg(src)]
    if src.suffix == ".json":
        d = _ui_json(src, None)
        if isinstance(d, dict):
            for k in ("alerts", "items", "history", "entries"):
                if isinstance(d.get(k), list):
                    d = d[k]; break
        items = d[-n:] if isinstance(d, list) else (list(d.items())[-n:] if isinstance(d, dict) else [])
        return [json.dumps(i, ensure_ascii=False, default=str) for i in items] or [_ui_empty_msg(src)]
    return _ui_tail(src, n) or [_ui_empty_msg(src)]


# -- shared scroll helper (every screen) ------------------------------------------
_UI_SCROLL = {}          # view key -> {"off": top row, "n": total rows, "page": visible rows}
_UI_SCROLL_HELP = "\u2191\u2193 PgUp/PgDn Home/End"


class _UIScroll:
    """Render `inner` at full (virtual) height and show the window starting at the stored top row.
    Top-anchored, so a live-refreshing view keeps its place while scrolled. Render faults are
    caught here (logged), never propagated: UI problems can't touch trading."""

    def __init__(self, key, inner, reserve: int = 0, help_: str = _UI_SCROLL_HELP, quiet: bool = False):
        self.key, self.inner, self.reserve, self.help, self.quiet = key, inner, reserve, help_, quiet

    def __rich_console__(self, console, options):
        from rich.segment import Segment
        from rich.style import Style
        st = _UI_SCROLL.setdefault(self.key, {"off": 0, "n": 0, "page": 10})
        H = options.height or console.size.height
        try:
            inner = self.inner() if callable(self.inner) else self.inner
            lines = console.render_lines(inner, options.update(height=None), pad=False)
        except Exception:
            _ui_err(f"scroll render {self.key}")
            lines = [[Segment("(render error, logged; trading unaffected)")]]
        n = len(lines)
        fits_all = n <= max(1, H - self.reserve) and self.quiet
        page = max(1, H - self.reserve) if fits_all else max(2, H - 1 - self.reserve)
        st["off"] = max(0, min(int(st.get("off") or 0), max(0, n - page)))
        st["n"], st["page"] = n, page
        a = st["off"]
        b = min(n, a + page)
        for i, ln in enumerate(lines[a:b]):
            yield from ln
            if i < b - a - 1 or not fits_all:
                yield Segment.line()
        if fits_all:
            return
        if n > page:
            txt = (f" rows {a + 1}-{b} of {n}  {self.help}" + ("  \u25bc more" if b < n else "")
                   + ("  \u25b2 more" if a > 0 else ""))
        else:
            txt = f" rows 1-{n} of {n}"
        yield Segment(txt[: max(1, options.max_width - 1)], Style(dim=True))


def _ui_scroll_key(key, k) -> bool:
    """Shared key scheme (same as Logs): Up/Down line, PgUp/PgDn page, Home/End. True if consumed."""
    if k not in ("up", "down", "pgup", "pgdn", "home", "end"):
        return False
    st = _UI_SCROLL.setdefault(key, {"off": 0, "n": 0, "page": 10})
    page = max(1, int(st.get("page") or 10) - 1)
    off = int(st.get("off") or 0)
    off = {"up": off - 1, "down": off + 1, "pgup": off - page, "pgdn": off + page, "home": 0, "end": 10 ** 9}[k]
    st["off"] = max(0, min(off, max(0, int(st.get("n") or 0) - int(st.get("page") or 10))))
    return True


def _ui_live_loop(con, render, on_key) -> None:
    from rich.live import Live
    with Live(render(), console=con, refresh_per_second=2, screen=True,
              redirect_stdout=False, redirect_stderr=False) as live:
        while _UI_STATE["active"]:
            k = _ui_getkey(1.0)
            if _ui_back(k):
                return
            if len(k) == 1 and k.isalpha():
                k = k.lower()          # keys are case-insensitive; no key differs by case
            if k and on_key(k) == "exit":
                return k
            live.update(render())


def _ui_dashboard(con) -> None:
    env = _ui_env()
    stop = _ui_threading.Event()

    def _bg():
        while not stop.is_set():
            try:
                pos = _ui_json(_UI_PATHS["logs"] / "positions.json", {}) or {}
                _ui_refresh_prices(list(pos.keys()) if isinstance(pos, dict) else [], env)
            except Exception:
                pass
            stop.wait(5)
    _ui_threading.Thread(target=_bg, daemon=True, name="sniper-ui-prices").start()
    try:
        while _UI_STATE["active"]:
            k = _ui_live_loop(con, lambda: _UIScroll("dash", lambda: _ui_dashboard_view(env)),
                              lambda k: None if _ui_scroll_key("dash", k) else
                              ("exit" if k in ("a", "r", "g", "x", "m", "c") else None))
            if k == "a":
                _ui_archive_screen(con)
            elif k == "r":
                _ui_reset_screen(con)
            elif k in ("c", "C"):
                _ui_recap_screen(con)
            elif k in ("g", "G"):
                _ui_goals_screen(con)
            elif k in ("x", "X"):
                _ui_quick_actions(con)
            elif k in ("m", "M"):
                _ui_toggle_mute()
            else:
                break
    finally:
        stop.set()


_UI_LOG_HISTORY = 5000
_UI_LOGV = {}   # tab -> {"off": lines up from bottom (0 = follow), "q": search, "hit": idx}


def _ui_log_cached(sel: str, src) -> list:
    """Last _UI_LOG_HISTORY lines of the CURRENT tab only (lazy), refreshed every ~2s."""
    c = _UI_STATE.setdefault("logcache", {})
    e = c.get(sel)
    if not e or time.time() - e[0] > 2:
        try:
            lines = _ui_log_lines(src, _UI_LOG_HISTORY)
        except Exception:
            lines = ["(unreadable)"]
        e = (time.time(), lines)
        c[sel] = e
    return e[1]


def _ui_logs_view(sel: str, height: int, width: int):
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text
    srcs = _ui_log_sources()
    tabs = Text()
    for k, name, _ in srcs:
        tabs.append(f" [{k.upper()}] {name} ", style=f"bold black on {_UI_GREEN}" if k == sel else _UI_GREEN)
    src = next(s for k, _, s in srcs if k == sel)
    lines = _ui_log_cached(sel, src)
    v = _UI_LOGV.setdefault(sel, {"off": 0, "q": "", "hit": None})
    n = max(5, height - 8)
    total = len(lines)
    v["off"] = max(0, min(v["off"], max(0, total - n)))
    end = total - v["off"]
    start = max(0, end - n)
    body = Text()
    w = max(20, width - 6)
    q = v["q"].lower()
    for i in range(start, end):
        ln = lines[i][:w]
        style = "black on yellow" if v["hit"] == i else ("bold" if q and q in ln.lower() else "")
        body.append(ln + "\n", style=style)
    status = Text()
    status.append(f" lines {start + 1 if total else 0}-{end} of {total} ", style="dim")
    status.append(" PAUSED " if v["off"] else " LIVE ", style="bold black on yellow" if v["off"] else f"bold black on {_UI_GREEN}")
    if v["q"]:
        status.append(f"  /{v['q']}", style="yellow")
    help_ = _ui_keys(("1-6 I R W A X S T J E L", "Tab"), ("\u2191\u2193", "Line"), ("PgUp/PgDn", "Page"), ("Home/End", "Top / Follow"), ("/", "Search"), ("N", "Next Hit"), ("P", "Prev Hit"), ("Q", "Back"))
    return Group(Panel(tabs, title="Logs", subtitle=Text(help_, style="dim"), border_style=_UI_GREEN), body, status)


def _ui_log_find(sel: str, forward: bool) -> None:
    v = _UI_LOGV.setdefault(sel, {"off": 0, "q": "", "hit": None})
    if not v["q"]:
        return
    lines = _UI_STATE.get("logcache", {}).get(sel, (0, []))[1]
    total = len(lines)
    q = v["q"].lower()
    cur = v["hit"] if v["hit"] is not None else (total - v["off"])
    rng = range(cur + 1, total) if forward else range(cur - 1, -1, -1)
    for i in rng:
        if q in lines[i].lower():
            v["hit"] = i
            v["off"] = max(0, total - i - 5)      # bring it into view
            return
    _UI_STATE["ext_marker"] = (f"/{v['q']}: no more matches", time.time())


def _ui_logs(con) -> None:
    from rich.prompt import Prompt
    sel = {"k": str(_ui_state_load().get("logs_tab") or "1")}
    if sel["k"] not in [s[0] for s in _ui_log_sources()]:
        sel["k"] = "1"

    def _key(k):
        v = _UI_LOGV.setdefault(sel["k"], {"off": 0, "q": "", "hit": None})
        page = max(5, con.size.height - 9)
        if k in [s[0] for s in _ui_log_sources()]:
            sel["k"] = k
            _ui_state_save(logs_tab=k)
        elif k == "up":
            v["off"] += 1
        elif k == "down":
            v["off"] = max(0, v["off"] - 1)
        elif k == "pgup":
            v["off"] += page
        elif k == "pgdn":
            v["off"] = max(0, v["off"] - page)
        elif k == "home":
            v["off"] = 10 ** 9
        elif k == "end":
            v["off"] = 0; v["hit"] = None
        elif k == "n":
            _ui_log_find(sel["k"], forward=True)
        elif k == "p":
            _ui_log_find(sel["k"], forward=False)
        elif k == "/":
            return "exit"
    while _UI_STATE["active"]:
        k = _ui_live_loop(con, lambda: _ui_logs_view(sel["k"], con.size.height, con.size.width), _key)
        if k == "/":
            v = _UI_LOGV.setdefault(sel["k"], {"off": 0, "q": "", "hit": None})
            v["q"] = Prompt.ask("search (blank clears)", default="", console=con).strip()
            v["hit"] = None
            if v["q"]:
                _ui_log_find(sel["k"], forward=False)
        else:
            return


def _ui_launch(con) -> None:
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    env = _ui_env()
    cap = float(env.get("LAUNCH_MAX_DEV_BUY_SOL") or os.environ.get("LAUNCH_MAX_DEV_BUY_SOL") or 0.5)
    con.print(Panel("Guided launch request. Only for a real, useful public GitHub repo. "
                    f"Dev buy cap {cap} SOL. Nothing is written until you confirm. Ctrl+C here stops Sniper, "
                    "so leave a prompt blank + answer no to cancel.", border_style=_UI_PURPLE))
    req = {"id": f"launch-{datetime.now().strftime('%Y%m%d-%H%M%S')}", "action": "launch"}
    import sniper_github as _sg
    req["repo_url"] = ""
    _me = _sg.whoami(check_live=False)
    if not _me["signed_in"]:
        if _me["client_id_set"]:
            if Confirm.ask("Sign in to GitHub? (one time, stays saved; no = type a username)", default=False, console=con):
                _priv = Confirm.ask("Also allow your private repos? (asks GitHub for more access)", default=False, console=con)
                _sg.login(_priv, say=con.print)
                _me = _sg.whoami(check_live=False)
        else:
            con.print("[dim]GitHub sign-in not set up (GITHUB_OAUTH_CLIENT_ID blank). See skill: GitHub sign-in.[/]")
    if _me["signed_in"] and not _me.get("login"):
        _me["signed_in"] = False   # token we can't put a name to = treat as not signed in
    if _me["signed_in"]:
        con.print(f"GitHub: signed in as [bold]{_me['login']}[/] (logout: python bots/sniper_github.py logout)")
        _inc = bool(_me.get("private_repos")) and Confirm.ask("Include your private repos in the list?", default=False, console=con)
        lst = _sg.list_my_repos(_inc)
        gh = _me["login"] if lst["ok"] else ""
        if not lst["ok"]:
            con.print(f"[yellow]Signed-in lookup failed ({lst['reason']}), falling back[/]")
            gh = Prompt.ask("GitHub username (blank = paste a link instead)", default=_me["login"] or "", console=con).strip()
            if gh:
                lst = _sg.list_public_repos(gh)
    else:
        con.print("GitHub: not signed in (optional)")
        gh = Prompt.ask("GitHub username (blank = paste a link instead)", default="", console=con).strip()
        lst = _sg.list_public_repos(gh) if gh else {"ok": False, "reason": "", "repos": []}
    if gh:
        if lst["ok"] and lst["repos"]:
            for i, r in enumerate(lst["repos"], 1):
                con.print(f"  {i}. {r['name']}  \u2605{r['stars']}  {r['description'][:60]}")
            pick = Prompt.ask("Pick a repo number (blank = none)", default="", console=con).strip()
            if pick.isdigit() and 1 <= int(pick) <= len(lst["repos"]):
                req["repo_url"] = lst["repos"][int(pick) - 1]["url"]
        else:
            con.print(f"[yellow]GitHub lookup failed ({lst['reason']}), paste a link instead[/]")
    if not req["repo_url"]:
        link = Prompt.ask("Link your project's GitHub repo (optional, shows buyers there's a real project; blank = launch without one)", default="", console=con).strip()
        if link:
            v = _sg.validate_repo_link(link)
            if v["ok"]:
                req["repo_url"] = v["url"]
            else:
                con.print(f"[yellow]link rejected ({v['reason']}), launching without a repo[/]")
    req["name"] = Prompt.ask("Token name (max 32)", console=con)[:32]
    req["ticker"] = Prompt.ask("Ticker (1-10)", console=con).upper()[:10]
    req["description"] = Prompt.ask("Description", console=con)
    req["image"] = Prompt.ask("Image path or URL", default="examples/placeholder_logo.png", console=con)
    req["website"] = Prompt.ask("Website", default=req["repo_url"], console=con)
    req["twitter"] = Prompt.ask("X link", default="", console=con)
    req["telegram"] = Prompt.ask("Telegram link", default="", console=con)
    while True:
        try:
            dev = float(Prompt.ask("Dev buy SOL", default="0.1", console=con))
        except ValueError:
            continue
        if 0 <= dev <= cap:
            break
        con.print(f"[red]must be between 0 and {cap}[/]")
    req["dev_buy_sol"] = dev
    req["dry_run"] = not Confirm.ask("Send live if the rail is armed?", default=True, console=con)
    req["requested_by"] = "owner_sniper_ui"
    req["confirm"] = True
    con.print_json(json.dumps(req))
    if not Confirm.ask("Write this request?", default=False, console=con):
        con.print("not written"); return
    d = _UI_PATHS["relay"] / "launch_requests"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{req['id']}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(req, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    _ui_sink(f"[ui] launch request written {p.name}")
    con.print(f"[{_UI_GREEN}]written[/] {p}")


def _ui_scraper_flag() -> Path:
    return _UI_PATHS["logs"] / "agent_scraper_pause.flag"


def _ui_scraper_hb() -> dict:
    d = _ui_json(_UI_PATHS["logs"] / "agent_scraper_heartbeat.json", {}) or {}
    return d if isinstance(d, dict) else {}


def _ui_scraper_running() -> bool:
    """Heartbeat written in the last 3 min = the scraper loop is alive."""
    hb = _ui_scraper_hb()
    return bool(hb.get("timestamp")) and _ui_age_s(hb["timestamp"]) < 180


def _ui_scraper_pause(con, timeout_s: float = 180.0, poll_s: float = 2.0):
    """Ask the scraper to park at its safe point (browser closed). Waits for heartbeat 'paused'."""
    f = _ui_scraper_flag()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"by": "owner_ui", "why": "x_sign_in", "at": _now_iso()}), encoding="utf-8")
    if con is not None:
        con.print("[dim]waiting for the scraper to finish its current task and park (browser closed)...[/]")
    end = time.time() + timeout_s
    while time.time() < end:
        hb = _ui_scraper_hb()
        if hb.get("status") == "paused" and _ui_age_s(hb.get("timestamp")) < 30:
            return True, "paused"
        time.sleep(poll_s)
    _ui_scraper_resume()
    return False, ("scraper did not pause in time. Its running code may predate the pause flag "
                   "(it loads it on its next restart), or it is mid-task. Nothing was changed.")


def _ui_scraper_resume() -> None:
    try:
        _ui_scraper_flag().unlink()
    except FileNotFoundError:
        pass
    except Exception:
        _ui_err("scraper resume")


def _ui_x_view(xs):
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text
    return Group(Text(xs["text"], style=f"bold {xs['color']}"),
                 Text(f"profile: {xs['profile']}  {xs['detail']}", style="dim"),
                 Panel("Status is checked first and nothing is paused or opened unless you pick switch / "
                       "sign in. 'Connected (verified)' means the scraper saw a logged-in X page in this "
                       "profile recently; 'Cookie present, unverified' means the cookies exist but that "
                       "was not seen. Sign-in runs `agent_scraper.py --login` in this same profile; if the "
                       "scraper is running it is paused first and resumed after.", border_style=_UI_PURPLE),
                 Text(_ui_keys(*((("Enter / K", "Keep (default)"), ("S", "Switch Account / Re-login"))
                              if xs["state"] in ("ok", "unverified") else (("S / Enter", "Sign In"),)),
                           _UI_SCROLL_HINT, ("Q", "Back")), style="dim"))


def _ui_sign_in_x(con) -> None:
    from rich.panel import Panel
    from rich.prompt import Confirm
    from rich.text import Text
    scraper = _BASE / "sub-bots" / "agent_scraper.py"
    if not scraper.exists():
        con.print("[red]agent_scraper.py not found[/]"); return
    xs = _ui_x_status(force=True)
    connected = xs["state"] in ("ok", "unverified")
    keys_go = ("s", "S") if connected else ("s", "S", "\r", "\n")
    keys_keep = ("k", "K", "\r", "\n") if connected else ()
    k = _ui_live_loop(con, lambda: _UIScroll("xstatus", lambda: _ui_x_view(xs)),
                      lambda k: None if _ui_scroll_key("xstatus", k) else
                      ("exit" if (k in keys_go or k in keys_keep) else None))
    if k is None or k in keys_keep:
        return      # keep: nothing paused, no browser
    paused = False
    if _ui_scraper_running():
        if not Confirm.ask("Scraper is using the X session; pause it to sign in?", default=False, console=con):
            return
        ok, why = _ui_scraper_pause(con)
        if not ok:
            con.print(f"[yellow]{why}[/]"); return
        paused = True
    try:
        if Confirm.ask("Open the X sign-in window?", default=True, console=con):
            import subprocess as _sp
            _sp.call([sys.executable, str(scraper), "--login"], cwd=str(_BASE))
            _ui_x_status(force=True)
    finally:
        if paused:
            _ui_scraper_resume()
            con.print(f"[{_UI_GREEN}]scraper resumed (it picks up the new session on its next task)[/]")


def _ui_wait_any(con) -> None:
    con.print("[dim]press any key for the menu[/]")
    while _UI_STATE["active"] and not _ui_getkey(1.0):
        pass


# -- UI state (last screen) -----------------------------------------------------
def _ui_state_file() -> Path:
    return _UI_PATHS["logs"] / "sniper_ui_state.json"


def _ui_state_load() -> dict:
    d = _ui_json(_ui_state_file(), {}) or {}
    return d if isinstance(d, dict) else {}


def _ui_state_save(**kw) -> None:
    try:
        d = _ui_state_load()
        d.update(kw)
        d["saved_at"] = _now_iso()
        p = _ui_state_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        _ui_err("ui state save")


def _ui_boot_animation(con) -> None:
    from rich.align import Align
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    try:
        with Live(console=con, refresh_per_second=30, screen=True,
                  redirect_stdout=False, redirect_stderr=False) as live:
            w = len(_UI_WORDMARK[0])
            for step in range(0, w + 6, 3):
                t = Text(justify="center")
                for i, ln in enumerate(_UI_WORDMARK):
                    t.append(ln[:step].ljust(w) + "\n", style=f"bold {_UI_GREEN if i < 2 else _UI_PURPLE} on {_UI_BG}")
                bar = int(30 * min(1.0, step / max(1, w)))
                t.append("[" + "#" * bar + "." * (30 - bar) + "]  booting engine\n", style=_UI_PURPLE)
                live.update(Panel(Align.center(t), border_style=_UI_PURPLE, style=f"on {_UI_BG}"))
                time.sleep(0.04)
            time.sleep(0.25)
    except Exception:
        _ui_err("boot animation")


# -- changes log + backups -------------------------------------------------------
def _ui_change_log(rec: dict) -> None:
    try:
        rec = {"ts": _now_iso(), "who": "owner_ui", **rec}
        p = _UI_PATHS["logs"] / "tunables_changes.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        _ui_err("change log")


def _ui_backup_file(p: Path) -> Path:
    import shutil
    d = _UI_PATHS["root"] / "backups" / "owner_ui_edits"
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"{p.name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    shutil.copy2(p, dst)
    return dst


def _ui_atomic_write_text(p: Path, text: str) -> None:
    tmp = p.with_name(p.name + ".owner_ui.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, p)


def _ui_last_changes() -> dict:
    """key -> last owner_ui change record (for 'who changed')."""
    out = {}
    for ln in _ui_tail(_UI_PATHS["logs"] / "tunables_changes.jsonl", 2000):
        try:
            r = json.loads(ln)
            if r.get("key"):
                out[(r.get("file"), r["key"])] = r
        except Exception:
            pass
    return out


# -- external-edit sync + Sniper env allowlist ---------------------------------
class _UIStale(Exception):
    pass


_UI_SIGS: dict = {}


def _ui_sig(p: Path):
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size, hashlib.sha1(p.read_bytes()).hexdigest())
    except Exception:
        return None


def _ui_check_external(paths) -> list:
    """Names of files whose content changed since we last looked (first look just records)."""
    changed = []
    for p in paths:
        p = Path(p)
        sig = _ui_sig(p)
        key = str(p)
        if key in _UI_SIGS and _UI_SIGS[key] != sig:
            changed.append(p.name)
        _UI_SIGS[key] = sig
    if changed:
        _UI_STATE["ext_marker"] = ("changed externally: " + ", ".join(changed) + " (reloaded)", time.time())
    return changed


def _ui_marker() -> str:
    m = _UI_STATE.get("ext_marker")
    return m[0] if m and time.time() - m[1] < 12 else ""


def _ui_guard(p: Path, expect) -> None:
    if expect is not None and _ui_sig(p) != expect:
        _UI_SIGS[str(p)] = _ui_sig(p)
        raise _UIStale(f"{p.name} changed externally while you were editing; reloaded, nothing written")


def _ui_mark_own_write(p: Path) -> None:
    _UI_SIGS[str(p)] = _ui_sig(p)


_UI_ENV_KEY_RE = _re.compile(r"(?:getenv\(|environ\.get\(|environ\[|\b(?:e|env|_env|envs|cfg)\.get\(|_env\w*\()\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']")
_UI_IMPORT_RE = _re.compile(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", _re.M)


def _ui_sniper_env_keys() -> set:
    """Keys meme_sniper.py (and bots/ modules it imports in-process) read. Re-scanned on every open."""
    keys, seen = set(), set()
    todo = [(Path(__file__).resolve(), 0)]
    while todo:
        p, depth = todo.pop()
        if p in seen or not p.exists():
            continue
        seen.add(p)
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        keys.update(_UI_ENV_KEY_RE.findall(src))
        if depth < 2:
            for m in set(_UI_IMPORT_RE.findall(src)):
                q = Path(__file__).resolve().parent / f"{m}.py"
                if q.exists():
                    todo.append((q, depth + 1))
    _UI_STATE["env_scan"] = {"files": sorted(x.name for x in seen), "keys": len(keys)}
    return keys


# -- tunables ----------------------------------------------------------------
_UI_SECRET_RE = _re.compile(r"(PRIVATE|SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|_KEY$|^KEY$|SEED|MNEMONIC|COOKIE|"
                            r"AUTH|BEARER|WEBHOOK|RPC_?(?:URL|ENDPOINT|HTTPS?|WSS?)|_URL$|URL_|CREDENTIAL|SESSION|JWT|SIGNING|KEYPAIR)", _re.I)


def _ui_is_secret(key: str, val: str) -> bool:
    if _UI_SECRET_RE.search(key or ""):
        return True
    v = (val or "").strip()
    if _re.match(r"^(?:https?|wss?)://", v):
        return True
    if len(v) >= 40 and _re.fullmatch(r"[A-Za-z0-9+/=_\-]+", v) and not v.isdigit():
        return True   # looks like a key/token
    return False


def _ui_filter_path() -> Path:
    return _UI_PATHS["filter"]


def _ui_env_path() -> Path:
    p = _UI_PATHS["env"]
    if not p.exists():
        ex = p.parent / ".env.example"
        if ex.exists():
            import shutil as _sh
            _sh.copyfile(ex, p)   # fresh clone: bots/.env starts as a copy of bots/.env.example
    return p


def _ui_env_entries() -> list:
    """Parse bots/.env preserving positions. Returns rows (key, value, line_idx, desc, dup)."""
    p = _ui_env_path()
    try:
        lines = p.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except Exception:
        return []
    rows, seen, comment = {}, {}, []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            comment = []; continue
        if s.startswith("#"):
            comment.append(s.lstrip("# ").strip()); continue
        m = _re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", ln)
        if not m:
            comment = []; continue
        k, raw = m.group(1), m.group(2)
        v = _re.sub(r"\s+#.*$", "", raw).strip().strip('"').strip("'")
        inline = _re.search(r"\s+#\s*(.*)$", raw)
        desc = (inline.group(1) if inline else " ".join(comment[-2:]))[:80]
        seen[k] = seen.get(k, 0) + 1
        rows[k] = (k, v, i, desc, seen[k] > 1)   # last occurrence wins (same as dotenv)
        comment = []
    return list(rows.values())


def _ui_snapshot_overrides() -> dict:
    d = _ui_json(_UI_PATHS["logs"] / "sniper_overrides_snapshot.json", {}) or {}
    o = d.get("overrides") if isinstance(d, dict) else None
    return o if isinstance(o, dict) else {}


_UI_RAIL_KEYS = ("LAUNCH_RAIL_ENABLED", "LAUNCH_RAIL_LIVE", "LAUNCH_MAX_DEV_BUY_SOL")
# Owner wizard keys + learning mode: the engine copies a changed .env value into the
# filter knob of the same name (~30s); the filter row is what the engine uses.
_UI_SEEDED_KEYS = ("SNIPER_BUY_SIZE_SOL", "SNIPER_DEFAULT_SL_PCT", "SNIPER_DEFAULT_TP_PCT", "SNIPER_LEARNING_MODE",
                   "SNIPER_LEARN_REST", "SNIPER_LEARN_COOLDOWN_H", "SNIPER_LEARN_MIN_TRADES", "SNIPER_LEARN_STEP_PCT")


_UI_LLM_CHOICE_KEYS = ("LLM_MAIN", "LLM_FALLBACK")
_UI_LLM = ("grok", "openai", "anthropic", "ollama", "openai_compat")
_UI_LLM_PROVIDER_KEYS = {
    "grok": ("GROK_API_KEY", "XAI_API_KEY", "GROK_TEXT_MODEL", "GROK_VISION_MODEL"),
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_VISION_MODEL", "OPENAI_BASE_URL"),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_VISION_MODEL"),
    "openai_compat": ("OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY", "OPENAI_COMPAT_MODEL", "OPENAI_COMPAT_VISION_MODEL"),
    "ollama": ("OLLAMA_ENABLED", "OLLAMA_MODEL", "OLLAMA_VISION_MODEL", "OLLAMA_CLOUD_ENABLED",
               "OLLAMA_CLOUD_API_KEY", "OLLAMA_CLOUD_MODEL"),
}


def _ui_llm_off_keys(env: dict) -> set:
    """Keys of providers that are not main/fallback (only when LLM_MAIN is set)."""
    m = str(env.get("LLM_MAIN") or "").strip().lower()
    if not m:
        return set()
    f = str(env.get("LLM_FALLBACK", "ollama") or "").strip().lower()
    sel = {m, f}
    return {k for p, ks in _UI_LLM_PROVIDER_KEYS.items() if p not in sel for k in ks}


def _ui_llm_choice_ok(key: str, val) -> bool:
    v = str(val).strip().lower()
    return v in _UI_LLM or (key == "LLM_FALLBACK" and v == "none")


def _ui_on(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _ui_paper_on() -> bool:
    try:
        return any(k == "SNIPER_PAPER_MODE" and _ui_on(v) for k, v, *_ in _ui_env_entries())
    except Exception:
        return False


def _ui_paper_switch_ok(old, new, typed: str = "") -> bool:
    """Paper -> live needs the word LIVE typed; every other change is a normal confirm."""
    if _ui_on(old) and not _ui_on(new):
        return str(typed).strip() == "LIVE"
    return True


def _ui_env_live_label(k: str) -> str:
    if k in _UI_RAIL_KEYS:
        return "launch rail go switch (takes effect on launch_rail restart)"
    if k in _UI_SEEDED_KEYS:
        return "live (~30s: copied into the filter knob of the same name when this value changes)"
    if k == "SNIPER_PAPER_MODE":
        return "next restart (paper/live switch)"
    if k in _UI_LLM_CHOICE_KEYS:
        return "next restart (brain choice; providers not chosen are off)"
    return "next restart"


# -- display map: plain-English label, section and unit per key (bots/settings_labels.json) --
def _ui_labels() -> dict:
    p = Path(__file__).resolve().parent / "settings_labels.json"
    try:
        mt = p.stat().st_mtime
    except Exception:
        return {"keys": {}, "sections": []}
    c = _UI_STATE.get("labels")
    if c and c[0] == mt:
        return c[1]
    d = _ui_json(p, {}) or {}
    d = d if isinstance(d, dict) else {}
    d.setdefault("keys", {}); d.setdefault("sections", [])
    _UI_STATE["labels"] = (mt, d)
    return d


def _ui_label(key: str, meta: dict | None = None) -> dict:
    """{label, section, unit, known}. Unknown keys get a readable fallback and are flagged."""
    e = _ui_labels()["keys"].get(key)
    if e:
        return {**e, "known": True}
    u = "bool" if (meta or {}).get("type") == "bool" else "?"
    return {"label": key.replace("_", " ").lower().capitalize(), "section": "Other", "unit": u, "known": False}


def _ui_num(x, nd=None) -> str:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    if nd is None:
        nd = 0 if f == int(f) else (1 if abs(f) >= 10 else 2 if abs(f) >= 1 else 3)
    txt = f"{f:,.{nd}f}" if abs(f) >= 10000 else f"{f:.{nd}f}"
    return txt


def _ui_fmt_value(value, unit: str, secret: bool = False) -> str:
    """Value with its unit: '15.0 %', '240 min', '1,000,000 USD', '1800 s', On/Off. Secrets stay masked."""
    if secret:
        return str(value)
    if unit == "bool":
        return "On" if _ui_on(value) or value is True else "Off"
    if value is None or value == "":
        return "-"
    if unit in ("text", "secret", "choice", "list", "?"):
        return str(value)
    try:
        float(value)
    except (TypeError, ValueError):
        return str(value)        # e.g. "off" for an optional percent
    if unit == "%":
        return f"{_ui_num(value, 1)} %"
    if unit == "USD":
        return f"{_ui_num(value, 0) if float(value) >= 100 else _ui_num(value)} USD"
    if unit == "SOL":
        return f"{_ui_num(value)} SOL"
    if unit in ("×", "ratio"):
        return f"{_ui_num(value)}" + (" ×" if unit == "×" else "")
    return f"{_ui_num(value)} {unit}"


def _ui_tunable_rows() -> list:
    """Fresh read every call. Row dict: src, key, value, desc, mtime, who, live, auto, secret, meta."""
    rows = []
    last = _ui_last_changes()
    fp = _ui_filter_path()
    data = _ui_json(fp, None)
    if isinstance(data, dict) and isinstance(data.get("knobs"), dict):
        mt = datetime.fromtimestamp(_ui_mtime(fp) or 0).strftime("%m-%d %H:%M") if _ui_mtime(fp) else "-"
        snap = _ui_snapshot_overrides()
        for k, kn in sorted(data["knobs"].items()):
            if not isinstance(kn, dict):
                continue
            hist = kn.get("history") or []
            h = hist[-1] if hist else {}
            who = f"{h.get('by', '-')} {str(h.get('changed_at') or '')[5:16]}".strip() if h else "-"
            rt = (snap.get(k) or {}).get("value") if isinstance(snap.get(k), dict) else None
            auto = "agent tune/meeting"
            if rt is not None and rt != kn.get("value"):
                auto += f"; runtime meeting value {rt}"
            rows.append({"src": "filter", "file": str(fp), "key": k, "value": kn.get("value"),
                         "desc": str(kn.get("description") or "")[:80], "mtime": mt, "who": who,
                         "live": "live (~30s file watcher)", "auto": auto, "secret": False,
                         "editable": bool(kn.get("tunable", True)), "meta": kn})
    ep = _ui_env_path()
    if ep.exists():
        mt = datetime.fromtimestamp(_ui_mtime(ep) or 0).strftime("%m-%d %H:%M") if _ui_mtime(ep) else "-"
        allow = _ui_sniper_env_keys() | set(_UI_RAIL_KEYS) | set(_UI_LLM_CHOICE_KEYS)
        ents = _ui_env_entries()
        off = _ui_llm_off_keys({k: v for k, v, *_ in ents})
        for k, v, idx, desc, dup in ents:
            if k not in allow:
                continue     # another bot's key
            sec = _ui_is_secret(k, v)
            lc = last.get((str(ep), k))
            rows.append({"src": ".env", "file": str(ep), "key": k,
                         "value": ("present" if v else "missing") if sec else v,
                         "desc": ("OFF (not main/fallback) " if k in off else "") + desc
                                 + (" [dup key: last wins]" if dup else ""), "mtime": mt,
                         "who": f"owner_ui {lc['ts'][5:16]}" if lc else "-",
                         "live": _ui_env_live_label(k),
                         "auto": "", "secret": sec and k not in _UI_RAIL_KEYS,
                         "editable": (not sec) or k in _UI_RAIL_KEYS,
                         "meta": {"line": idx}})
    return rows


def _ui_coerce(meta: dict, cur, raw: str):
    """Validate per schema (filter) or by the current value's kind (.env). Returns (ok, value|error)."""
    raw = raw.strip()
    t = (meta or {}).get("type")
    if t is None:
        if isinstance(cur, bool):
            t = "bool"
        elif isinstance(cur, int):
            t = "int"
        elif isinstance(cur, float):
            t = "float"
        elif isinstance(cur, str):
            s = cur.strip().lower()
            if s in ("true", "false", "yes", "no", "on", "off") :
                t = "envbool"
            elif _re.fullmatch(r"-?\d+", s):
                t = "envint"
            elif _re.fullmatch(r"-?\d*\.\d+", s):
                t = "envfloat"
            else:
                t = "str"
        elif isinstance(cur, list):
            t = "list"
    try:
        if t in ("int", "envint"):
            v = int(float(raw)) if t == "int" else int(raw)
        elif t in ("float", "envfloat"):
            v = float(raw)
        elif t == "bool":
            if raw.lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                return False, "expected true/false"
            v = raw.lower() in ("true", "1", "yes", "on")
        elif t == "envbool":
            if raw.lower() not in ("true", "false", "yes", "no", "on", "off", "1", "0"):
                return False, "expected true/false/on/off"
            v = raw
        elif t == "list":
            v = json.loads(raw)
            if not isinstance(v, list):
                return False, "expected a JSON list like [1, 2]"
        else:
            if "\n" in raw or "\r" in raw:
                return False, "no newlines"
            v = raw
    except Exception:
        return False, f"expected {t}"
    for b, op in (("min", lambda a, x: a < x), ("max", lambda a, x: a > x)):
        if (meta or {}).get(b) is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
            if op(float(v), float(meta[b])):
                return False, f"{b} is {meta[b]}"
    return True, v


def _ui_filter_apply(key: str, new_value, expect=None) -> str:
    fp = _ui_filter_path()
    _ui_guard(fp, expect)
    data = _ui_json(fp, None)
    if not isinstance(data, dict) or key not in (data.get("knobs") or {}):
        raise RuntimeError("knob vanished from filter file; nothing written")
    kn = data["knobs"][key]
    old = kn.get("value")
    kn["value"] = new_value
    kn.setdefault("history", []).append({"changed_at": _now_iso(), "from": old, "to": new_value,
                                         "change_type": "value_update", "by": "owner_ui",
                                         "reason": "owner via Sniper UI Settings"})
    try:
        _rotate_knob_history_if_needed(kn, key)
    except Exception:
        pass
    data.setdefault("_meta", {})["last_modified_by"] = "owner_ui"
    data["_meta"]["last_modified_at"] = _now_iso()
    bk = _ui_backup_file(fp)
    _ui_guard(fp, expect)
    _save_json_atomic(fp, data)
    _ui_mark_own_write(fp)
    if fp.resolve() == MEME_SNIPER_FILTER_FILE.resolve():
        _ACTIVE_OVERRIDES[key] = {"value": new_value, "expires_at": kn.get("expires_at"),
                                  "applied_at": _now_iso(), "reason": "owner_ui"}
    _ui_change_log({"file": str(fp), "key": key, "from": old, "to": new_value,
                    "takes_effect": "live", "backup": str(bk)})
    return str(bk)


def _ui_env_apply(key: str, line_idx: int, new_value: str, old_value: str, expect=None) -> str:
    ep = _ui_env_path()
    _ui_guard(ep, expect)
    raw = ep.read_bytes().decode("utf-8-sig", errors="replace")
    nl = "\r\n" if "\r\n" in raw else "\n"
    had_bom = ep.read_bytes()[:3] == b"\xef\xbb\xbf"
    lines = raw.splitlines()          # same indexing as _ui_env_entries, safe with mixed CRLF/LF
    if raw.endswith(("\n", "\r")):
        lines.append("")
    if not 0 <= line_idx < len(lines):
        raise RuntimeError(".env changed under us; nothing written")
    ln = lines[line_idx]
    m = _re.match(r"^(\s*(?:export\s+)?" + _re.escape(key) + r"\s*=\s*)(.*?)(\s+#.*)?$", ln)
    if not m:
        raise RuntimeError(".env changed under us; nothing written")
    q = '"' if (" " in new_value or "#" in new_value) else ""
    lines[line_idx] = f"{m.group(1)}{q}{new_value}{q}{m.group(3) or ''}"
    bk = _ui_backup_file(ep)
    _ui_guard(ep, expect)
    _ui_atomic_write_text(ep, ("\ufeff" if had_bom else "") + nl.join(lines))
    _ui_mark_own_write(ep)
    _ui_change_log({"file": str(ep), "key": key, "from": old_value, "to": new_value,
                    "takes_effect": "next restart", "backup": str(bk)})
    return str(bk)


def _ui_tunables(con) -> None:
    """Settings screen: cursor list (fits the terminal, no wrap) + detail pane with the full wrapped description."""
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
    from rich.text import Text
    v = {"cur": 0, "flt": "", "rows": [], "at": 0.0}

    def _rows():
        if time.time() - v["at"] > 10 or not v["rows"]:
            _ui_check_external([_ui_filter_path(), _ui_env_path(), _ui_set_file()])
            rows = _ui_tunable_rows()
            s = _ui_settings()
            for k, (dflt, desc) in _UI_SET_DEFAULTS.items():
                rows.append({"src": "ui", "file": str(_ui_set_file()), "key": k, "value": s[k], "desc": desc,
                             "mtime": "-", "who": "-", "live": "live", "auto": "", "secret": False,
                             "editable": True, "meta": {"type": "bool"}})
            order = {n: i for i, n in enumerate(_ui_labels().get("sections") or [])}
            for r in rows:
                r["lbl"] = _ui_label(r["key"], r.get("meta"))
            rows.sort(key=lambda r: (order.get(r["lbl"]["section"], 99), r["lbl"]["label"].lower()))
            v["rows"], v["at"] = rows, time.time()
        f = v["flt"].lower()
        return [r for r in v["rows"] if not f or f in r["key"].lower() or f in r["lbl"]["label"].lower()
                or f in r["lbl"]["section"].lower()]

    def _render():
        rows = _rows()
        H, W = con.size.height, con.size.width
        per = max(3, H - 13)
        v["cur"] = max(0, min(v["cur"], len(rows) - 1))
        top = (v["cur"] // per) * per
        t = Table(box=box.SIMPLE_HEAD, header_style=f"bold {_UI_PURPLE}", expand=True, pad_edge=False)
        t.add_column("#", width=4, no_wrap=True)
        t.add_column("Section", ratio=2, no_wrap=True, overflow="ellipsis", style=f"bold {_UI_PURPLE}")
        t.add_column("Setting", ratio=4, no_wrap=True, overflow="ellipsis")
        t.add_column("Value", ratio=2, no_wrap=True, overflow="ellipsis", justify="right")
        t.add_column("Applies", ratio=2, no_wrap=True, overflow="ellipsis")
        t.add_column("Source", width=7, no_wrap=True)
        t.add_column("J", width=2, no_wrap=True)
        last_sec = None
        for i in range(top, min(len(rows), top + per)):
            r = rows[i]
            sel = i == v["cur"]
            lb = r["lbl"]
            eff = "locked" if r["secret"] else ("launch rail restart" if "launch rail" in r["live"] else r["live"].split(" (")[0])
            sec = lb["section"] if lb["section"] != last_sec or i == top else ""
            last_sec = lb["section"]
            t.add_row(str(i + 1), sec, lb["label"] + ("" if lb["known"] else " (no label)"),
                      Text(_ui_fmt_value(r["value"], lb["unit"], r["secret"]), style="dim" if r["secret"] else ""),
                      eff, {"filter": "filter", ".env": ".env", "ui": "console"}.get(r["src"], r["src"]),
                      Text("J", style="yellow") if r["auto"] else "",
                      style=f"bold black on {_UI_GREEN}" if sel else None)
        if not rows:
            t.add_row("-", "", "no match", "", "", "", "")
        r = rows[v["cur"]] if rows else None
        det = Text()
        if r and r["key"] != v.get("dkey"):
            v["dkey"] = r["key"]; _UI_SCROLL.setdefault("setdesc", {})["off"] = 0
        if r:
            lb, m = r["lbl"], r.get("meta") or {}
            det.append(lb["label"], style=f"bold {_UI_GREEN}")
            det.append(f"   key {r['key']}", style="dim")
            if not lb["known"]:
                det.append("  (no display label yet)", style="yellow")
            rng = []
            if m.get("min") is not None or m.get("max") is not None:
                rng.append(f"range {_ui_fmt_value(m.get('min'), lb['unit'])} .. {_ui_fmt_value(m.get('max'), lb['unit'])}")
            if m.get("default") is not None:
                rng.append(f"default {_ui_fmt_value(m.get('default'), lb['unit'])}")
            if lb["unit"] == "?":
                rng.append("unit not determined")
            det.append(("   " + ", ".join(rng) if rng else "") + "\n", style="dim")
            det.append(f"[{r['src']}]  {r['live']}  modified {r['mtime']}  by {r['who']}\n", style="dim")
            if r["auto"]:
                det.append(f"auto-tuned: {r['auto']} (may adjust your value)\n", style="yellow")
            det.append(r["desc"] or "(no description)")
        head = Text(f"Settings  {v['cur'] + 1 if rows else 0}/{len(rows)}  rows {top + 1 if rows else 0}-"
                    f"{min(len(rows), top + per)} of {len(rows)}"
                    + (f"  filter '{v['flt']}'" if v["flt"] else "")
                    + "   " + _ui_keys(("\u2191\u2193", "Select"), ("PgUp/PgDn", "Page"), ("[ ]", "Desc"), ("E / Enter", "Edit"), ("/", "Filter"), ("A", "Alerts"), ("R", "Reload"), ("Q", "Back")),
                    style="bold", no_wrap=True, overflow="ellipsis")
        mk = _ui_marker()
        parts = [head] + ([Text(mk, style="bold yellow", no_wrap=True, overflow="ellipsis")] if mk else []) + \
            [t, Panel(_UIScroll("setdesc", det, help_="[ ] scroll description", quiet=True),
                      border_style=_UI_PURPLE, height=6)]
        return Group(*parts)

    def _key(k):
        rows = _rows()
        per = max(3, con.size.height - 13)
        if k == "up":
            v["cur"] -= 1
        elif k == "down":
            v["cur"] += 1
        elif k in ("n", " ", "pgdn"):
            v["cur"] += per
        elif k in ("p", "pgup"):
            v["cur"] -= per
        elif k == "home":
            v["cur"] = 0
        elif k == "end":
            v["cur"] = len(rows) - 1
        elif k == "r":
            v["at"] = 0
        elif k == "]":
            _ui_scroll_key("setdesc", "down")
        elif k == "[":
            _ui_scroll_key("setdesc", "up")
        elif k in ("e", "\r", "\n", "/", "a"):
            return "exit"
        v["cur"] = max(0, min(v["cur"], max(0, len(rows) - 1)))

    while _UI_STATE["active"]:
        k = _ui_live_loop(con, _render, _key)
        if k is None:
            return
        if k == "/":
            v["flt"] = Prompt.ask("filter (blank = all)", default="", console=con).strip(); v["cur"] = 0
            continue
        if k == "a":
            _ui_alerts_screen(con)
            v["at"] = 0
            continue
        rows = _rows()
        if not rows:
            continue
        r = rows[v["cur"]]
        if not r["editable"]:
            con.print("[yellow]locked: secret or non-tunable, edit it in the file yourself[/]"); time.sleep(1.5); continue
        if r["src"] == "ui":
            nv = not _ui_settings()[r["key"]]
            if Confirm.ask(f"Set {r['key']} -> {nv}?", default=True, console=con):
                _ui_settings_set(r["key"], nv)
            v["at"] = 0
            continue
        sig0 = _ui_sig(Path(r["file"]))
        v["at"] = 0
        fresh = next((x for x in _rows() if x["src"] == r["src"] and x["key"] == r["key"]), None)
        if fresh is None:
            con.print("[red]key vanished, reloaded[/]"); time.sleep(1.5); continue
        meta = fresh["meta"] if r["src"] == "filter" else {}
        lim = f" (min {meta.get('min')}, max {meta.get('max')}, {meta.get('type')})" if meta else ""
        con.print(f"{r['key']} = {fresh['value']}{lim}")
        if r["auto"]:
            con.print(f"[yellow]note: {r['auto']} can adjust this after you[/]")
        raw = Prompt.ask("new value (blank cancels)", default="", console=con)
        if not raw.strip():
            continue
        ok, val = _ui_coerce(meta, fresh["value"], raw)
        if ok and r["key"] in _UI_LLM_CHOICE_KEYS and not _ui_llm_choice_ok(r["key"], val):
            ok, val = False, "pick one of " + "/".join(_UI_LLM) + ("/none" if r["key"] == "LLM_FALLBACK" else "")
        if not ok:
            con.print(f"[red]rejected: {val}[/]"); time.sleep(2); continue
        effect = fresh["live"]
        if r["key"] == "LAUNCH_RAIL_LIVE" and str(val).strip().lower() in ("1", "true", "yes", "on"):
            con.print("[bold red]WARNING: LAUNCH_RAIL_LIVE on means real token launches with real SOL "
                      "(dev buys) once launch_rail restarts and LAUNCH_RAIL_ENABLED is on.[/]")
            if not Confirm.ask("Really arm LIVE launches?", default=False, console=con):
                continue
        if r["key"] == "SNIPER_PAPER_MODE":
            typed = ""
            if _ui_on(fresh["value"]) and not _ui_on(val):
                con.print("[bold red]Leaving PAPER mode: after the restart the bot trades REAL funds.[/]")
                typed = Prompt.ask("Type LIVE to confirm", default="", show_default=False, console=con)
            if not _ui_paper_switch_ok(fresh["value"], val, typed):
                con.print("[yellow]not confirmed; staying in paper mode[/]"); time.sleep(1.5); continue
        if not Confirm.ask(f"Set {r['key']}: {fresh['value']} -> {val}  ({effect})?", default=False, console=con):
            continue
        try:
            if r["src"] == "filter":
                bk = _ui_filter_apply(r["key"], val, expect=sig0)
            else:
                bk = _ui_env_apply(r["key"], fresh["meta"]["line"], str(val), str(fresh["value"]), expect=sig0)
            con.print(f"[{_UI_GREEN}]saved[/] ({effect}); backup {Path(bk).name}")
            _ui_sink(f"[ui] setting {r['key']} -> {val} ({effect})")
        except _UIStale as e:
            _UI_STATE["ext_marker"] = (f"changed externally: {Path(r['file']).name} (reloaded)", time.time())
            con.print(f"[bold yellow]{e}[/]")
        except Exception as e:
            _ui_err("setting write")
            con.print(f"[red]not saved: {e}[/]")
        v["at"] = 0
        time.sleep(1.5)


# -- skills ---------------------------------------------------------------------
_UI_SKILL_DIRS = ("meme-hunter", "ca-intel", "forensics", "sub-skills", "gork-lore")   # v1.0.1: lore shown too (token-lore template moved to templates/token-lore, outside skills/)


def _ui_skill_files() -> list:
    out = []
    base = _UI_PATHS["root"] / "skills"
    for d in _UI_SKILL_DIRS:
        p = base / d
        if not p.exists():
            continue
        for f in sorted(p.rglob("*.md")):
            n = f.name.lower()
            if ".bak" in n or "clobbered" in n or "_archived" in str(f).lower():
                continue
            out.append(f)
    return out


def _ui_skill_change_log(rec: dict) -> None:
    """bot_logs/skills_changes.jsonl: who / when / which skill / how / backup."""
    try:
        rec = {"ts": _now_iso(), "who": "owner_ui", **rec}
        p = _UI_PATHS["logs"] / "skills_changes.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        _ui_err("skills change log")


def _ui_skill_save(f: Path, new_text: str, how: str, expect=None) -> None:
    """Stale-guarded (refuses if the file changed since `expect`), backup per edit, atomic write, logged."""
    _ui_guard(f, expect)
    bk = _ui_backup_file(f)
    _ui_atomic_write_text(f, new_text)
    _ui_mark_own_write(f)
    rec = {"file": str(f), "key": f"skill:{f.parent.name}/{f.name}", "change": how,
           "takes_effect": "next time the skill is read", "backup": str(bk)}
    _ui_change_log(rec)
    _ui_skill_change_log(rec)


def _ui_editor_cmd() -> list:
    import shlex
    ed = (os.environ.get("VISUAL") or os.environ.get("EDITOR") or "").strip()
    if ed:
        return shlex.split(ed, posix=(os.name != "nt"))
    return ["notepad"] if os.name == "nt" else ["nano"]


def _ui_skill_edit_external(con, f: Path, editor=None) -> str:
    """Edit a temp copy in the system editor, then save back through the stale guard.
    Returns saved / nochange / stale / noeditor. On stale your version is kept in backups."""
    import subprocess as _sp
    sig0 = _ui_sig(f)
    before = f.read_bytes()
    tmp_dir = _UI_PATHS["logs"] / "skill_edit_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{f.parent.name}__{f.name}"
    tmp.write_bytes(before)
    cmd = list(editor or _ui_editor_cmd())
    if con is not None:
        con.print(f"[dim]opening {' '.join(cmd)}; save and close it to come back (the skill is saved only then)[/]")
    try:
        _sp.call(cmd + [str(tmp)])
    except (OSError, FileNotFoundError):
        tmp.unlink(missing_ok=True)
        return "noeditor"
    after = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    if after == before:
        return "nochange"
    try:
        _ui_skill_save(f, after.decode("utf-8", errors="replace"), f"edited in {cmd[0]}", expect=sig0)
        return "saved"
    except _UIStale:
        d = _UI_PATHS["root"] / "backups" / "owner_ui_edits"
        d.mkdir(parents=True, exist_ok=True)
        mine = d / f"{f.name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.mine"
        mine.write_bytes(after)
        _UI_STATE["skill_stale_mine"] = (str(mine), after.decode("utf-8", errors="replace"))
        _ui_skill_change_log({"file": str(f), "key": f"skill:{f.parent.name}/{f.name}",
                              "change": "save REFUSED: file changed underneath (yours kept)", "mine": str(mine)})
        return "stale"


def _ui_skill_stale_menu(con, f: Path) -> None:
    """After a refused save: d = diff (current file vs yours), r/Enter = reload (yours stays in backups)."""
    import difflib
    mine_path, mine = _UI_STATE.pop("skill_stale_mine", ("", ""))
    con.print(f"[bold yellow]{f.name} changed while you were editing (agent or another editor). Not saved.[/]")
    con.print(f"[dim]your version is kept at {mine_path}[/]")
    con.print(_ui_keys(("D", "Show Diff"), ("R / Enter", "Reload Current File"), ("Q", "Back")))
    k = _ui_getkey(60.0)
    if k in ("d", "D"):
        cur = f.read_text(encoding="utf-8", errors="replace").splitlines()
        diff = list(difflib.unified_diff(cur, mine.splitlines(), "current file", "your edit", lineterm="", n=1))
        for ln in diff[:max(10, con.size.height - 6)]:
            con.print(ln, markup=False, highlight=False)
        if len(diff) > con.size.height - 6:
            con.print(f"[dim]... {len(diff)} diff lines in total[/]")
        con.print("[dim]press any key[/]")
        _ui_getkey(120.0)


def _ui_skill_view(con, f: Path) -> None:
    from rich.prompt import Confirm, Prompt
    from rich.text import Text
    top = 0
    while _UI_STATE["active"]:
        _ui_check_external([f])
        sig0 = _ui_sig(f)
        raw = f.read_bytes().decode("utf-8", errors="replace")          # re-read every time
        nl = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.split(nl)
        page, top, per = _ui_skill_page(f, lines, top, con.size.height, con.size.width)
        con.clear()
        con.print(page)
        k = _ui_getkey(10.0)
        if _ui_back(k):
            return
        if k in ("n", " ", "pgdn"):
            top += per - 1
        elif k in ("p", "pgup"):
            top -= per - 1
        elif k == "down":
            top += 1
        elif k == "up":
            top -= 1
        elif k == "home":
            top = 0
        elif k == "end":
            top = 10 ** 9
        elif k == "g":
            s = Prompt.ask("line #", default="1", console=con)
            top = int(s) - 1 if s.isdigit() else top
        elif k in ("e", "E", "o"):
            r = _ui_skill_edit_external(con, f)
            if r == "saved":
                con.print(f"[{_UI_GREEN}]saved (backup kept, logged to skills_changes.jsonl), re-read[/]")
            elif r == "nochange":
                con.print("[dim]no change[/]")
            elif r == "stale":
                _ui_skill_stale_menu(con, f)
            else:
                con.print("[yellow]no system editor found; use l to edit a line here[/]")
            time.sleep(1)
        elif k == "l":
            s = Prompt.ask("line # to edit (blank cancels)", default="", console=con)
            if not s.isdigit() or not (1 <= int(s) <= len(lines)):
                continue
            i = int(s) - 1
            con.print(Text("current: " + lines[i]))
            new = Prompt.ask("new text (blank cancels; type <empty> for an empty line)", default="", console=con)
            if not new:
                continue
            new = "" if new == "<empty>" else new
            if Confirm.ask(f"Write line {i + 1}?", default=False, console=con):
                lines[i] = new
                try:
                    _ui_skill_save(f, nl.join(lines), f"line {i + 1} edited inline", expect=sig0)
                    con.print(f"[{_UI_GREEN}]saved, re-read[/]")
                except _UIStale as e:
                    _UI_STATE["ext_marker"] = (f"changed externally: {f.name} (reloaded)", time.time())
                    con.print(f"[bold yellow]{e}[/]")
                time.sleep(1.5)


def _ui_skills_table(files):
    from rich import box
    from rich.table import Table
    t = Table(title="Sniper Skills   " + _ui_keys(("1-9", "Open"), _UI_SCROLL_HINT, ("Q", "Back")), box=box.SIMPLE_HEAD,
              header_style=f"bold {_UI_PURPLE}", expand=True)
    for c in ("#", "Skill", "File", "Size", "Modified"):
        t.add_column(c, no_wrap=True, overflow="ellipsis")
    for i, f in enumerate(files, 1):
        try:
            st = f.stat()
            t.add_row(str(i), f.parent.name, f.name, f"{st.st_size // 1024} KB",
                      datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M"))
        except Exception:
            t.add_row(str(i), f.parent.name, f.name, "-", "-")
    if not files:
        t.add_row("-", "no Sniper skills found", "", "", "")
    return t


def _ui_skill_page(f: Path, lines: list, top: int, H: int, W: int):
    from rich.console import Group
    from rich.text import Text
    per = max(5, H - 4)
    top = max(0, min(top, max(0, len(lines) - per)))
    parts = []
    if _ui_marker():
        parts.append(Text(_ui_marker(), style="bold yellow", no_wrap=True, overflow="ellipsis"))
    parts.append(Text(f"{f.parent.name}/{f.name}  rows {top + 1}-{min(len(lines), top + per)} of {len(lines)}  "
                      f"\u2191\u2193 PgUp/PgDn Home/End  g goto  e edit (system editor)  l edit line  q/esc back",
                      style=f"bold {_UI_GREEN}", no_wrap=True, overflow="ellipsis"))
    w = max(20, W - 7)
    for i in range(top, min(len(lines), top + per)):
        parts.append(Text(f"{i + 1:>5} ", style="dim", no_wrap=True) + Text(lines[i][:w]))
    for p in parts[-(min(len(lines), top + per) - top):] if lines else []:
        p.no_wrap = True; p.overflow = "crop"
    return Group(*parts), top, per


def _ui_skills(con) -> None:
    from rich import box
    from rich.prompt import Prompt
    from rich.table import Table
    while _UI_STATE["active"]:
        files = _ui_skill_files()
        k = _ui_live_loop(con, lambda: _UIScroll("skills", lambda: _ui_skills_table(files)),
                          lambda k: None if _ui_scroll_key("skills", k) else ("exit" if k.isdigit() else None))
        if k is None:
            return
        if k.isdigit():
            s = k if len(files) < 10 else Prompt.ask("skill #", default=k, console=con)
            if s.isdigit() and 1 <= int(s) <= len(files):
                _ui_skill_view(con, files[int(s) - 1])


# -- autopsy panel ----------------------------------------------------------------
def _ui_autopsy_data() -> dict:
    now = time.time()
    if now - _UI_STATE.get("autopsy_at", 0) < 60 and _UI_STATE.get("autopsy"):
        return _UI_STATE["autopsy"]
    logs, root = _UI_PATHS["logs"], _UI_PATHS["root"]
    out = {"verdicts": [], "wl": "-", "miss": "-", "decline": "-", "roast": "-", "report": "-"}
    try:
        ar = _ui_json(logs / "autopsy_reports.json", None)
        ar = ar.get("reports") if isinstance(ar, dict) else ar
        ar = list(ar.values()) if isinstance(ar, dict) else (ar or [])
        ar = [r for r in ar if isinstance(r, dict)]
        if ar:
            w = sum(1 for r in ar if str(r.get("trade_outcome")).lower() in ("win", "profit"))
            l = sum(1 for r in ar if str(r.get("trade_outcome")).lower() in ("loss", "rug"))
            out["wl"] = f"{w}W / {l}L of {len(ar)} closed ({100 * w // max(1, w + l)}% win)"
            out["verdicts"] = [f"{r.get('ticker', '?')} {r.get('trade_outcome', '?')} "
                               f"{_ui_net_pct_str(r)} {r.get('exit_type') or ''}".strip()
                               for r in ar[-3:]][::-1]
    except Exception:
        pass
    for key, fname, field, cut in (("miss", "miss_book.jsonl", "skip_reason", 40),
                                   ("decline", "decline_log.jsonl", "decline_reason", 36)):
        try:
            c = _ui_collections.Counter()
            for ln in _ui_tail(logs / fname, 3000, max_bytes=2 * 1024 * 1024):
                try:
                    r = json.loads(ln)
                    v = r.get(field) if isinstance(r, dict) else None
                    if v:
                        c[str(v)[:cut]] += 1
                except Exception:
                    pass
            if c:
                out[key] = ", ".join(f"{k} x{n}" for k, n in c.most_common(3))
        except Exception:
            pass
    try:
        cands = []
        for d in (root / "inbox", root / "inbox_results" / "done"):
            if d.exists():
                cands += list(d.glob("x_evt_overseer_*.json"))
                cands += list(d.glob("agent_autoagent - overseer_*.json"))
        if cands:
            f = (_ui_newest(cands) or [None])[0]
            j = (_ui_json(f, {}) or {}) if f else {}
            sc = j.get("score_0_to_10")
            out["roast"] = (f"[{sc}/10] " if sc is not None else "") + str(j.get("headline") or "-")[:140]
    except Exception:
        pass
    try:
        p = logs / "autopsy_report.md"
        if p.exists():
            first = next((l.strip("# ").strip() for l in p.read_text(encoding="utf-8", errors="replace").splitlines()
                          if l.strip()), "-")
            out["report"] = f"{first[:70]} ({datetime.fromtimestamp(p.stat().st_mtime).strftime('%m-%d')})"
    except Exception:
        pass
    # 2026-10-14: nothing in the system writes autopsy_report.md, so "report" was always "-".
    # Fall back to the newest autopsy record's map report card (written by the engine on every close).
    if out.get("report") in (None, "-"):
        try:
            ar2 = _ui_json(logs / "autopsy_reports.json", None)
            ar2 = ar2.get("reports") if isinstance(ar2, dict) else ar2
            ar2 = [r for r in (list(ar2.values()) if isinstance(ar2, dict) else (ar2 or [])) if isinstance(r, dict)]
            if ar2:
                r = ar2[-1]; mr = r.get("map_report") or {}
                todo = len(mr.get("_required_from_agent") or []) if not mr.get("lesson_one_liner") else 0
                out["report"] = (f"{r.get('ticker', '?')} map={mr.get('actual_vs_map') or '-'} "
                                 f"exit={mr.get('exit_reason') or r.get('exit_type') or '-'}"
                                 + (f" lesson: {str(mr.get('lesson_one_liner'))[:50]}" if mr.get("lesson_one_liner")
                                    else (f" ({todo} agent fields open)" if todo else ""))
                                 + f" ({str(r.get('exit_at') or r.get('closed_at') or '')[5:10]})")
        except Exception:
            pass
    _UI_STATE["autopsy"], _UI_STATE["autopsy_at"] = out, now
    return out


def _ui_autopsy_panel():
    from rich.panel import Panel
    from rich.table import Table
    a = _ui_autopsy_data()
    t = Table.grid(padding=(0, 1))
    t.add_column(style=f"bold {_UI_PURPLE}"); t.add_column()
    t.add_row("Closed", a["wl"])
    t.add_row("Latest", " | ".join(a["verdicts"]) or "-")
    t.add_row("Top Misses", a["miss"])
    t.add_row("Top Declines", a["decline"])
    t.add_row("Roast", a["roast"])
    t.add_row("Report", a["report"])
    return Panel(t, title="Autopsy (Read-Only)", border_style=_UI_PURPLE)


def _ui_run_screen(con, screen: str) -> None:
    _UI_STATE["last_screen"] = screen
    _ui_state_save(screen=screen)
    try:
        if screen == "dashboard":
            _ui_dashboard(con)
        elif screen == "logs":
            _ui_logs(con)
        elif screen in ("settings", "tunables"):
            _ui_tunables(con)
        elif screen == "skills":
            _ui_skills(con)
    finally:
        if _UI_STATE["active"]:
            _ui_state_save(screen="menu")


def _ui_menu_scroll():
    from rich.console import Group
    return _UIScroll("menu", lambda: Group(_ui_banner(), _ui_menu_panel()), reserve=1)


def _ui_cancel_class():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from cancel_input import CancelInput  # installs q / back / esc = back on every prompt (not Ctrl+C)
        return CancelInput
    except Exception:
        class _Never(Exception):
            pass
        return _Never


def _ui_main() -> None:
    _Cancel = _ui_cancel_class()
    from rich.console import Console
    con = Console(file=sys.__stdout__, highlight=False)
    _UI_STATE["console"] = con
    _ui_boot_animation(con)
    _ui_threading.Thread(target=_ui_alert_loop, daemon=True, name="sniper-ui-alerts").start()
    resume = str(_ui_state_load().get("screen") or "menu")
    if resume == "tunables":          # pre-rename state file
        resume = "settings"
    screens = {"1": "dashboard", "2": "logs", "3": "settings", "4": "skills"}
    while _UI_STATE["active"]:
        try:
            if resume in screens.values():
                s, resume = resume, "menu"
                _ui_run_screen(con, s)
                continue
            con.clear()
            con.print(_ui_menu_scroll())
            _UI_STATE["last_screen"] = "menu"
            k = ""
            while _UI_STATE["active"] and k not in [m[0] for m in _UI_MENU]:
                k = _ui_getkey(5.0)
                if k in ("m", "M") or _ui_scroll_key("menu", k):
                    if k in ("m", "M"):
                        _ui_toggle_mute()
                    k = ""
                if not k:
                    con.clear(); con.print(_ui_menu_scroll())
            if k in screens:
                _ui_run_screen(con, screens[k])
            elif k == "5":
                _ui_launch(con); _ui_wait_any(con)
            elif k == "6":
                _ui_sign_in_x(con); _ui_wait_any(con)
            elif k == "7":
                _ui_state_save(screen="menu")
                try:
                    _ui_write_recap("quit_ui")
                except Exception:
                    _ui_err("recap")
                return
            elif k == "8":
                con.print("[yellow]Stop Sniper? This stops every bot the supervisor started. y / n[/]")
                if _ui_getkey(30.0) in ("y", "Y"):
                    try:
                        _ui_write_recap("stop_sniper")
                    except Exception:
                        _ui_err("recap")
                    con.print("[yellow]stopping Sniper...[/]")
                    if callable(_DROP_HOOKS.get("stop")):
                        _DROP_HOOKS["stop"]()
                    return
        except (_Cancel, EOFError):          # q / back / esc; Ctrl+C keeps its normal stop behaviour
            # backed out of a prompt: nothing saved, bots keep running, back to where we were
            try:
                con.print("[yellow]cancelled, nothing saved. Back.[/]")
                time.sleep(0.8)
            except Exception:
                pass
            last = _UI_STATE.get("last_screen") or "menu"
            resume = last if last in screens.values() else "menu"
        except Exception:
            _ui_err("ui view")
            try:
                con.print("[red]UI error (logged to meme_sniper_ui_errors.log). Back to menu; trading unaffected.[/]")
                time.sleep(2)
            except Exception:
                pass
            _UI_STATE["errors"] = _UI_STATE.get("errors", 0) + 1
            if _UI_STATE["errors"] >= 5:
                _ui_deactivate()
                print("[sniper] UI disabled after repeated errors; engine keeps running.", flush=True)
                return


def _ui_thread_entry() -> None:
    try:
        _ui_main()
    except Exception:
        _ui_err("ui thread")
        _ui_deactivate()


def _ui_start() -> bool:
    if not _ui_should_start():
        return False
    try:
        import rich  # noqa: F401
    except Exception:
        _log("[ui] rich not installed; running without UI")
        return False
    try:
        _ui_activate()
        _UI_STATE["launched_with_ui"] = True
        _ui_threading.Thread(target=_ui_thread_entry, daemon=True, name="sniper-ui").start()
        return True
    except Exception:
        _ui_err("ui start")
        _ui_deactivate()
        return False


def _ui_shutdown(reason: str) -> None:
    """Engine is exiting: hand the screen back and show the last engine lines."""
    if not _UI_STATE.get("active"):
        return
    _ui_deactivate()
    try:
        for ln in list(_UI_RING)[-15:]:
            print(ln)
        print(f"[sniper] engine exited ({reason}); full output in {_ui_console_log()}", flush=True)
    except Exception:
        pass


def _ui_smoke() -> int:
    """Render every view once against WORKSPACE_DIR (temp copies). Never writes live files:
    without WORKSPACE_DIR it refuses to run the edit tests."""
    import shutil
    from rich.console import Console
    ws = (os.environ.get("WORKSPACE_DIR") or "").strip()
    con = Console(file=sys.__stdout__, highlight=False, width=130, height=40)
    if not ws:
        con.print("[red]ui-smoke needs WORKSPACE_DIR (temp) so no live file is touched[/]"); return 2
    r = Path(ws)
    _UI_PATHS.update(root=r, logs=r / "bot_logs", relay=r / "json_relay",
                     filter=r / "bots" / "tuner" / "meme_sniper_filter.json", env=r / "bots" / ".env")
    if not _UI_PATHS["env"].exists() and (r / "bots" / ".env.example").exists():
        shutil.copy(r / "bots" / ".env.example", _UI_PATHS["env"])   # fresh clone: temp .env inside WORKSPACE_DIR only
    _fd = r / "bots" / "tuner" / "meme_sniper_filter.default.json"
    if not _UI_PATHS["filter"].exists() and _fd.exists():
        shutil.copy(_fd, _UI_PATHS["filter"])   # temp filter copy inside WORKSPACE_DIR only
    res = {}
    # never hang: a stuck render or prompt ends the smoke with a FAIL instead of waiting forever
    _wd = _ui_threading.Timer(float(_envv("UI_SMOKE_TIMEOUT_S") or 300),
                              lambda: (print("ui-smoke FAIL: timed out", flush=True), os._exit(3)))
    _wd.daemon = True; _wd.start()
    con.print(_ui_banner()); con.print(_ui_menu_panel())
    con.print(_ui_dashboard_view(_ui_env()))
    for k, name, _ in _ui_log_sources():
        con.print(_ui_logs_view(k, 14, 130))
    _srcs = _ui_log_sources()
    _want = {"security_warden.console.log", "agent_autoagent.console.log", "x_intel.console.log",
             "agent_scraper.console.log", "code_tuner.console.log", "log_janitor.console.log",
             "learnings_writer.console.log", "trench_news.console.log",
             "security_warden.json", "medic_log.json", "integrity_log.json"}
    _have = set()
    for _k, _n, _s in _srcs:
        for _p in (_s if isinstance(_s, (tuple, list)) else [_s]):
            if _p != "ring":
                _have.add(Path(_p).name)
    res["log_sources_ok"] = _want <= _have and len({k for k, *_ in _srcs}) == len(_srcs)
    _tmp_missing = Path(_UI_PATHS["logs"]) / "_smoke_missing"
    res["value_format"] = (_ui_fmt_value(8, "tokens") == "8 tokens" and _ui_fmt_value(15, "%") == "15.0 %"
                           and _ui_fmt_value(240, "min") == "240 min" and _ui_fmt_value(1000000, "USD") == "1,000,000 USD"
                           and _ui_fmt_value(1800, "s") == "1800 s" and _ui_fmt_value("true", "bool") == "On"
                           and _ui_fmt_value(False, "bool") == "Off" and _ui_fmt_value("present", "secret", True) == "present")
    _rows_l = _ui_tunable_rows()
    res["settings_all_labelled"] = all(_ui_label(r["key"], r.get("meta"))["known"] for r in _rows_l if r["src"] == "filter") \
        and all(_ui_label(k)["known"] for k in _UI_SET_DEFAULTS)
    res["log_empty_states"] = (
        "no trades yet" in _ui_log_lines(_tmp_missing / "trades.log", 5)[0]
        and "no trades yet" in _ui_log_lines(_tmp_missing / "execution_ledger.jsonl", 5)[0]
        and "not found" not in " ".join(_ui_log_lines(_tmp_missing / "decline_log.jsonl", 5)
                                        + _ui_log_lines(_tmp_missing / "integrity_log.json", 5))
        and "inbox empty" in _ui_log_lines(("inbox", _tmp_missing / "inbox"), 5)[0]
        and any(k == "i" for k, *_ in _srcs))
    try:
        _rd = _tmp_missing / "json_relay"
        _empty_ok = "JSON relay empty" in _ui_log_lines(("relay", _rd), 5)[0]
        _rd.mkdir(parents=True, exist_ok=True)
        (_rd / "ca_research_request.json").write_text(json.dumps({"requests": [{"request_id": "x", "status": "done"},
                                                                                {"request_id": "y"}]}), encoding="utf-8")
        _ls = _ui_log_lines(("relay", _rd), 40)
        res["relay_tab"] = (_empty_ok and any(k == "r" for k, *_ in _srcs)
                            and any("ca_research_request.json" in l and "1 pending" in l for l in _ls)
                            and any(n == "JSON Relay" for _k, n, _s in _srcs))
    except Exception as _e:
        res["relay_tab"] = False; res["relay_tab_err"] = str(_e)[:120]
    finally:
        import shutil as _sh
        _sh.rmtree(_tmp_missing / "json_relay", ignore_errors=True)
    res["log_tabs_title_case"] = all(n[:1].isupper() or n[:1].isdigit() for _k, n, _s in _srcs)
    _UI_STATE["active"] = True
    _ui_sink("[ui-smoke] console line routed to sink")
    _UI_STATE["active"] = False
    res["sink"] = any("ui-smoke" in l for l in _UI_RING)
    # screens stay until q/back/esc (no timed auto-return), keys case-insensitive, Title Case, one hint style
    try:
        _src = Path(__file__).read_text(encoding="utf-8").split("def _ui_smoke")[0]
        _gk, _seq = globals()["_ui_getkey"], iter(["", "", "", "Q"])
        _calls = {"n": 0}
        def _fake(_t):
            _calls["n"] += 1
            return next(_seq, "q")
        globals()["_ui_getkey"] = _fake
        _act0 = _UI_STATE.get("active"); _UI_STATE["active"] = True
        class _NullCon:
            size = type("S", (), {"height": 40, "width": 120})()
            def clear(self): pass
            def print(self, *a, **k): pass
        try:
            _pos = _UI_PATHS["logs"] / "positions.json"
            _had = _pos.read_bytes() if _pos.exists() else None
            _pos.write_text("{}", encoding="utf-8")
            from rich.console import Console as _C
            import io as _io
            _qc = _C(file=_io.StringIO(), force_terminal=False, width=120)
            _ui_quick_actions(_qc)
        finally:
            globals()["_ui_getkey"] = _gk
            _UI_STATE["active"] = _act0
            if _had is None:
                _pos.unlink(missing_ok=True)
            else:
                _pos.write_bytes(_had)
        res["bags_stay_until_back"] = _calls["n"] >= 4          # idle ticks did not return; only Q did
        res["no_timed_return"] = ("time.sleep(1.5); return" not in _src and "\"no open positions\"); time.sleep" not in _src)
        res["keys_case_insensitive"] = ("k = k.lower()" in _src and '"R", "r"' not in _src and 'k == "N"' not in _src)
        res["title_case"] = not any(t in _src for t in ('title="open positions"', 'title="treasury / holdings"',
                                                         'title="heartbeats"', 'title="profit goals', 'title="hold times',
                                                         'title="autopsy (', 'title="logs"', 'title="menu ('))
        res["hint_style"] = _ui_keys(("Q", "Back"), ("X", "Bags")) == "[Q] Back  [X] Bags"
        res["goals_native_unit"] = (_ui_native_unit() == "SOL" and 'choices=["SOL", "USD"]' not in _src
                                    and "case_sensitive=False" in _src)
    except Exception as _e:
        res["bags_stay_until_back"] = False
        res["ui_nav_err"] = str(_e)[:160]
    rows = _ui_tunable_rows()
    res["tunables_rows"] = len(rows)
    res["secrets_masked"] = all(x["value"] in ("present", "missing") for x in rows if x["secret"])
    res["secret_count"] = sum(1 for x in rows if x["secret"])
    fk = next((x for x in rows if x["src"] == "filter" and x["meta"].get("type") == "int" and x["editable"]), None)
    if fk:
        m = fk["meta"]
        res["reject_out_of_range"] = not _ui_coerce(m, fk["value"], str((m.get("max") or 10 ** 9) + 1))[0]
        newv = m.get("min") if m.get("min") is not None else fk["value"]
        ok, v = _ui_coerce(m, fk["value"], str(newv))
        _ui_filter_apply(fk["key"], v)
        res["filter_write"] = (_ui_json(_ui_filter_path(), {})["knobs"][fk["key"]]["value"] == v)
    ek = next((x for x in rows if x["src"] == ".env" and x["editable"] and _re.fullmatch(r"\d+", str(x["value"]))), None)
    if ek:
        before = _ui_env_path().read_text(encoding="utf-8-sig").splitlines()
        _ui_env_apply(ek["key"], ek["meta"]["line"], str(int(ek["value"]) + 1), str(ek["value"]))
        after = _ui_env_path().read_text(encoding="utf-8-sig").splitlines()
        res["env_write_one_line"] = sum(1 for a, b in zip(before, after) if a != b) == 1 and len(before) == len(after)
    sk = _ui_skill_files()
    res["skills"] = [f"{f.parent.name}/{f.name}" for f in sk]
    if sk:
        f = sk[0]
        t = f.read_text(encoding="utf-8")
        _ui_skill_save(f, t.replace("\n", "\n", 1) + "", "smoke no-op")
        res["skill_write"] = f.read_text(encoding="utf-8") == t
    # allowlist
    allow = _ui_sniper_env_keys()
    env_keys = {k for k, *_ in _ui_env_entries()}
    shown = [x for x in _ui_tunable_rows() if x["src"] == ".env"]
    res["env_allowlist_scanned"] = len(allow)
    res["env_shown"] = len(shown)
    res["env_hidden_other_bots"] = len(env_keys) - len(shown)
    res["env_shown_secret"] = sum(1 for x in shown if x["secret"])
    res["env_shown_nonsecret_keys"] = sorted(x["key"] for x in shown if not x["secret"])
    res["env_only_allowlisted"] = all(x["key"] in allow or x["key"] in _UI_RAIL_KEYS for x in shown)
    res["rail_keys_editable"] = sorted(x["key"] for x in shown if x["key"] in _UI_RAIL_KEYS and x["editable"])
    res["paper_live_confirm"] = (not _ui_paper_switch_ok("1", "0", "")) and _ui_paper_switch_ok("1", "0", "LIVE") \
        and _ui_paper_switch_ok("0", "1", "")
    res["seeded_live_label"] = _ui_env_live_label("SNIPER_BUY_SIZE_SOL").startswith("live") and \
        _ui_env_live_label("SNIPER_PAPER_MODE").startswith("next restart")
    res["ollama_cloud_keys_shown"] = [x["key"] for x in shown if "OLLAMA_CLOUD" in x["key"] or x["key"] == "OLLAMA_API_KEY"]
    # external edit + stale-write refusal (temp copies only)
    for label, p in (("env", _ui_env_path()), ("filter", _ui_filter_path())):
        _ui_check_external([p])
        sig0 = _ui_sig(p)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("\n# external edit (smoke)\n" if label == "env" else " ")
        res[f"{label}_external_detected"] = bool(_ui_check_external([p])) and "changed externally" in _ui_marker()
        before = p.read_bytes()
        try:
            if label == "env":
                e = next(x for x in _ui_tunable_rows() if x["src"] == ".env" and x["editable"])
                _ui_env_apply(e["key"], e["meta"]["line"], str(e["value"]), str(e["value"]), expect=sig0)
            else:
                fk2 = next(x for x in _ui_tunable_rows() if x["src"] == "filter" and x["editable"])
                _ui_filter_apply(fk2["key"], fk2["value"], expect=sig0)
            res[f"{label}_stale_refused"] = False
        except _UIStale:
            res[f"{label}_stale_refused"] = p.read_bytes() == before
    if sk:
        f = sk[-1]
        sig0 = _ui_sig(f)
        f.write_text(f.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        try:
            _ui_skill_save(f, "x", "smoke stale", expect=sig0)
            res["skill_stale_refused"] = False
        except _UIStale:
            res["skill_stale_refused"] = f.read_text(encoding="utf-8") != "x"
        # editor flow: a fake editor script edits the temp copy -> saved, backup + skills_changes.jsonl
        ed = Path(_UI_PATHS["logs"]) / "_smoke_editor.py"
        ed.write_text("import sys\nopen(sys.argv[1], 'a', encoding='utf-8').write('\\nsmoke edit\\n')\n", encoding="utf-8")
        before_log = len(_ui_tail(_UI_PATHS["logs"] / "skills_changes.jsonl", 1000))
        r1 = _ui_skill_edit_external(None, f, editor=[sys.executable, str(ed)])
        res["skill_editor_saved"] = r1 == "saved" and f.read_text(encoding="utf-8").rstrip().endswith("smoke edit") \
            and len(_ui_tail(_UI_PATHS["logs"] / "skills_changes.jsonl", 1000)) == before_log + 1
        # stale: the editor also changes the real file underneath -> refused, external change kept
        ed2 = Path(_UI_PATHS["logs"]) / "_smoke_editor2.py"
        ed2.write_text("import sys\nopen(sys.argv[1], 'a', encoding='utf-8').write('mine')\n"
                       f"open(r'{f}', 'a', encoding='utf-8').write('agent')\n", encoding="utf-8")
        r2 = _ui_skill_edit_external(None, f, editor=[sys.executable, str(ed2)])
        res["skill_editor_stale_refused"] = r2 == "stale" and f.read_text(encoding="utf-8").endswith("agent") \
            and Path(_UI_STATE.pop("skill_stale_mine", ("", ""))[0]).exists()
        res["skill_editor_noeditor"] = _ui_skill_edit_external(None, f, editor=["__no_such_editor__"]) == "noeditor"
    # X status: fake cookie DBs (names + expiry only)
    import sqlite3
    def _mk(prof, rows):
        (prof / "Network").mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(prof / "Network" / "Cookies"))
        c.execute("CREATE TABLE cookies (name TEXT, host_key TEXT, expires_utc INTEGER, encrypted_value BLOB)")
        for n, days in rows:
            c.execute("INSERT INTO cookies VALUES (?,?,?,?)",
                      (n, ".x.com", int((time.time() + days * 86400 + 11644473600) * 1e6), b"x"))
        c.commit(); c.close()
    xb = r / "xprof"
    _mk(xb / "ok", [("auth_token", 30), ("ct0", 30), ("twid", 30)])
    _mk(xb / "old", [("auth_token", -1), ("ct0", -1)])
    (xb / "none").mkdir(parents=True, exist_ok=True)
    got = {}
    for name in ("ok", "old", "none"):
        _UI_PATHS["x_profiles"] = [str(xb / name)]
        got[name] = _ui_x_status(force=True)["state"]
    _UI_PATHS.pop("x_profiles", None)
    res["x_status"] = got
    _ui_threading.Thread(target=lambda: [
        time.sleep(0.5),
        (_UI_PATHS["logs"] / "agent_scraper_heartbeat.json").write_text(
            json.dumps({"timestamp": _now_iso(), "status": "paused" if _ui_scraper_flag().exists() else "idle"}),
            encoding="utf-8")], daemon=True).start()
    (_UI_PATHS["logs"] / "agent_scraper_heartbeat.json").write_text(
        json.dumps({"timestamp": _now_iso(), "status": "idle"}), encoding="utf-8")
    run_ok = _ui_scraper_running()
    pz = _ui_scraper_pause(None, timeout_s=5, poll_s=0.2)
    flag_during = _ui_scraper_flag().exists()
    _ui_scraper_resume()
    res["scraper_pause"] = {"running": run_ok, "paused": pz[0], "flag_during": flag_during,
                            "flag_cleared": not _ui_scraper_flag().exists()}
    (_UI_PATHS["logs"] / "agent_scraper_heartbeat.json").write_text(
        json.dumps({"timestamp": _now_iso(), "status": "idle"}), encoding="utf-8")
    pz2 = _ui_scraper_pause(None, timeout_s=1, poll_s=0.2)
    res["scraper_pause"]["timeout_clears_flag"] = (not pz2[0]) and not _ui_scraper_flag().exists()
    # verified needs a recent logged-in page seen by the scraper in that same profile
    _xs = _ui_x_session()
    _UI_PATHS["x_profiles"] = [str(xb / "ok")]
    try:
        _xs.record(True, "@smoke", {"BROWSER_USER_DATA_DIR": str(xb), "BROWSER_PROFILE_NAME": "ok"})
        got["ok_verified"] = _ui_x_status(force=True)["state"]
        _xs.record(False, "", {"BROWSER_USER_DATA_DIR": str(xb), "BROWSER_PROFILE_NAME": "ok"})
        got["ok_logged_out"] = _ui_x_status(force=True)["state"]
    finally:
        _UI_PATHS.pop("x_profiles", None)
        try:
            _xs.marker_path().unlink()
        except Exception:
            pass
    res["x_status"] = got
    res["x_status_ok"] = got == {"ok": "unverified", "old": "expired", "none": "none",
                                 "ok_verified": "ok", "ok_logged_out": "expired"}
    con.print(_ui_menu_panel())
    # hold times + PnL period archive/reset (temp copies)
    pos = _ui_json(_UI_PATHS["logs"] / "positions.json", {}) or {}
    con.print(_ui_hold_panel(pos if isinstance(pos, dict) else {}))
    hist = [_ui_sig(_UI_PATHS["logs"] / n) for n in ("pnl.json", "autopsy_reports.json")]
    _UI_PRICE["sol_usd"] = _UI_PRICE["sol_usd"] or 150.0
    _ui_goals_save([{"id": "daily", "kind": "daily", "unit": "SOL", "target": 0.5, "set_at": _now_iso()},
                    {"id": "custom", "kind": "custom", "unit": "USD", "target": 1.0, "set_at": _now_iso()}])
    gh = _UI_STATE.setdefault("goal_hist", {})
    p0 = _ui_goal_progress(_ui_goals()[0])
    gh["daily"] = [(time.time() - 900, (p0["cur"] or 0) - 0.1)]
    p1 = _ui_goal_progress(_ui_goals()[0])
    hitg = {"id": "hit", "kind": "custom", "unit": "SOL", "target": 1e-9}
    _UI_PATHS_bak = dict(_UI_PATHS)
    con.print(_ui_goals_panel())
    res["goals"] = {"count": len(_ui_goals()), "rate_up": (p1["rate"] or 0) > 0, "eta": p1["eta_min"] is not None or p1["hit"],
                    "custom_since": _ui_goal_progress(_ui_goals()[1])["since"] == _ui_baseline().get("since"),
                    "hit_logic": _ui_goal_progress(dict(hitg, target=-1e9))["hit"]}
    s1 = _ui_pnl_reset("smoke goals")
    res["goals"]["in_archive"] = bool((s1.get("goals") or {}).get("targets"))
    s2 = _ui_pnl_reset("")
    res["archive_periods"] = len(_ui_archive_rows())
    res["baseline_moved"] = _ui_baseline().get("since") == s2["period_end"] and s2["period_start"] == s1["period_end"]
    res["history_untouched"] = hist == [_ui_sig(_UI_PATHS["logs"] / n) for n in ("pnl.json", "autopsy_reports.json")]
    res["hold_all_min"] = s1["avg_hold_min"]
    con.print(_ui_archive_view()[0])
    import io
    from rich.console import Console as _C
    # Settings screen render: fits terminal, single header per render
    cap = _C(file=io.StringIO(), width=100, height=30, record=True, highlight=False)
    _orig_loop = _ui_live_loop
    shots = []
    def _once(c, render, on_key):
        cap.print(render()); on_key("down"); cap.print(render()); shots.append(1); return None
    globals()["_ui_live_loop"] = _once
    _UI_STATE["active"] = True
    try:
        _ui_tunables(cap)
    finally:
        globals()["_ui_live_loop"] = _orig_loop
        _UI_STATE["active"] = False
    txt = cap.export_text().splitlines()
    res["settings_render"] = {"lines": len(txt), "fits": len(txt) <= 60 and max(len(l) for l in txt) <= 100,
                              "headers": sum(1 for l in txt if l.startswith("Settings ")),
                              "detail_pane": any("auto-tuned" in l or "[filter]" in l or "[.env]" in l for l in txt)}
    # alerts (beep/toast stubbed)
    fired = []
    _ob, _ot = _ui_beep, _ui_toast
    globals()["_ui_beep"] = lambda k: fired.append(("beep", k))
    globals()["_ui_toast"] = lambda t, b: (fired.append(("toast", t)) or True)
    _UI_STATE["active"] = True
    try:
        _ui_alert_scan(first=True)
        with open(_UI_PATHS["logs"] / "execution_ledger.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "sell", "ticker": "TST", "exit_reason": "sl_hit", "pnl_sol": -0.01}) + "\n")
        (r / "owner_inbox").mkdir(parents=True, exist_ok=True)
        (r / "owner_inbox" / "security_warden - smoke_alert.md").write_text("x", encoding="utf-8")
        _ui_alert_scan(); time.sleep(0.5)
        n1 = len(fired)
        _ui_settings_set("MUTED", True)
        with open(_UI_PATHS["logs"] / "execution_ledger.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "sell", "ticker": "TS2", "exit_reason": "tp_hit"}) + "\n")
        _ui_alert_scan(); time.sleep(0.5)
        res["alerts"] = {"fired_sltp_and_warden": n1 >= 2, "muted_silent": len(fired) == n1}
        _ui_settings_set("MUTED", False)
    finally:
        globals()["_ui_beep"], globals()["_ui_toast"] = _ob, _ot
        _UI_STATE["active"] = False
    # owner card + recap
    oc = _ui_owner_card("review", {"ticker": "TST", "entry_price": 1, "mode": "hold"}, "MintXYZ", "check it")
    ocd = json.loads(oc.read_text(encoding="utf-8"))
    res["owner_card"] = {"path_ok": oc.parent == r / "inbox" and oc.name.startswith("owner - owner_review_TST_"),
                         "type": ocd["type"], "from": ocd["from"]}
    rc = _ui_write_recap("smoke")
    res["recap"] = {"jsonl": (_UI_PATHS["logs"] / "daily_recaps.jsonl").exists(),
                    "card": any((r / "owner_inbox").glob("meme_sniper - daily_recap_*.md")), "keys": len(rc)}
    # health line + red-hold (engine pass, temp paths, inbox writer stubbed)
    con.print(_ui_health_text())
    pp = r / "rh_positions.json"
    pp.write_text(json.dumps({"M1": {"ticker": "RED", "entry_price": 1.0, "last_price_usd": 0.5,
                                     "opened_at_ts": time.time() - 10 * 3600},
                              "M2": {"ticker": "GRN", "entry_price": 1.0, "last_price_usd": 2.0,
                                     "opened_at_ts": time.time() - 10 * 3600}}), encoding="utf-8")
    cards = []
    _ow = write_inbox_packet_generic
    globals()["write_inbox_packet_generic"] = lambda pkt, **kw: cards.append(pkt) or Path("x")
    _ACTIVE_OVERRIDES["SNIPER_MAX_RED_HOLD_H"] = {"value": 4}
    try:
        n_a = _red_hold_review_pass(pp, r / "rh_state.json")
        n_b = _red_hold_review_pass(pp, r / "rh_state.json")
    finally:
        globals()["write_inbox_packet_generic"] = _ow
        _ACTIVE_OVERRIDES.pop("SNIPER_MAX_RED_HOLD_H", None)
    res["red_hold"] = {"first_pass_cards": n_a, "dedup_second": n_b, "only_red": [c["ticker"] for c in cards],
                       "knob_in_schema": "SNIPER_MAX_RED_HOLD_H" in TUNABLE_PARAMS}
    rl = _UI_PATHS["logs"] / "trades.log"
    rl.write_text("\n".join(f"line {i} {'needle' if i == 4321 else ''}" for i in range(6000)), encoding="utf-8")
    _UI_STATE.pop("logcache", None)
    con.print(_ui_logs_view("2", 20, 120))
    v = _UI_LOGV["2"]
    loaded = len(_UI_STATE["logcache"]["2"][1])
    v["off"] = 100
    pv = _ui_logs_view("2", 20, 120)
    v["q"] = "needle"; v["hit"] = None
    _ui_log_find("2", forward=False)
    res["logs_scrollback"] = {"loaded": loaded, "paused": v["off"] > 0,
                              "search_hit": _UI_STATE["logcache"]["2"][1][v["hit"]].startswith("line 4321")}
    v["off"] = 0
    con.print(_ui_autopsy_panel())
    # scrolling on a small 80x24 terminal, every screen
    from rich.console import Group as _G
    def _small():
        return _C(file=io.StringIO(), width=80, height=24, record=True, highlight=False)
    def _shot(key, fn, reserve=0):
        c = _small(); c.print(_UIScroll(key, fn, reserve=reserve)); return c.export_text().splitlines()
    fake_bags = [(f"M{i}", {"ticker": f"T{i}", "entry_price": 1, "mode": "hold"}) for i in range(60)]
    views = {"menu": (lambda: _G(_ui_banner(), _ui_menu_panel()), 1),
             "dash": (lambda: _ui_dashboard_view(_ui_env()), 0),
             "archive": (lambda: _ui_archive_view(0, 10 ** 6)[0], 0),
             "goals": (_ui_goals_view, 0),
             "bags": (lambda: _ui_quick_view(fake_bags), 0),
             "skills": (lambda: _ui_skills_table(_ui_skill_files() * 12), 0),
             "xstatus": (lambda: _ui_x_view(_ui_x_status(force=True)), 0),
             "recap": (_ui_recap_view, 0)}
    small = {}
    for key, (fn, rsv) in views.items():
        _UI_SCROLL.pop(key, None)
        t0 = _shot(key, fn, rsv)
        st = dict(_UI_SCROLL[key])
        long_ = st["n"] > st["page"]
        _ui_scroll_key(key, "pgdn"); _shot(key, fn, rsv); o1 = _UI_SCROLL[key]["off"]
        _ui_scroll_key(key, "down"); _shot(key, fn, rsv); o2 = _UI_SCROLL[key]["off"]
        _shot(key, fn, rsv); stable = _UI_SCROLL[key]["off"] == o2          # live refresh keeps the place
        _ui_scroll_key(key, "end"); te = _shot(key, fn, rsv); oe = _UI_SCROLL[key]["off"]
        _ui_scroll_key(key, "up"); _shot(key, fn, rsv); ou = _UI_SCROLL[key]["off"]
        _ui_scroll_key(key, "home"); _shot(key, fn, rsv); oh = _UI_SCROLL[key]["off"]
        small[key] = {"rows": st["n"],
                      "fits": len(t0) <= 24 - rsv and len(te) <= 24 - rsv and max(len(x) for x in t0 + te) <= 80,
                      "indicator": any(" rows " in x for x in t0),
                      "scrolls": (not long_) or (o1 > 0 and o2 == o1 + 1 and oe == st["n"] - st["page"] and ou == oe - 1),
                      "stable": stable, "home": oh == 0}
    small["_long_screens"] = sorted(k for k in views if small[k]["rows"] > _UI_SCROLL[k]["page"])
    # Settings at 80x24: list cursor + description pane
    s_shots = []
    def _once2(c, render, on_key):
        a = _small(); a.print(render()); s_shots.append(a.export_text().splitlines())
        on_key("pgdn"); on_key("down"); on_key("]")
        b = _small(); b.print(render()); s_shots.append(b.export_text().splitlines())
        on_key("end"); b2 = _small(); b2.print(render()); s_shots.append(b2.export_text().splitlines())
        return None
    globals()["_ui_live_loop"] = _once2
    _UI_STATE["active"] = True
    try:
        _ui_tunables(_small())
    finally:
        globals()["_ui_live_loop"] = _orig_loop
        _UI_STATE["active"] = False
    small["settings"] = {"fits": all(len(x) <= 24 and max(len(y) for y in x) <= 80 for x in s_shots),
                         "indicator": all(any(y.startswith("Settings ") and " rows " in y for y in x) for x in s_shots),
                         "moved": s_shots[0][0] != s_shots[1][0] != s_shots[2][0]}
    if sk:
        ls = (sk[0].read_text(encoding="utf-8", errors="replace").splitlines() or [""]) * 5
        c = _small(); pg, tp, per = _ui_skill_page(sk[0], ls, 10, 24, 80); c.print(pg)
        tx = c.export_text().splitlines()
        small["skill_viewer"] = {"fits": len(tx) <= 24 and max(len(x) for x in tx) <= 80,
                                 "indicator": " rows 11-" in tx[0] or any(" rows 11-" in x for x in tx[:2])}
    c = _small(); c.print(_ui_logs_view("2", 24, 80)); tx = c.export_text().splitlines()
    small["logs"] = {"fits": len(tx) <= 24 and max(len(x) for x in tx) <= 80}
    res["scroll_80x24"] = small
    _ui_state_save(screen="tunables")
    res["state_resume"] = _ui_state_load().get("screen") == "tunables"
    res["change_log_lines"] = len(_ui_tail(_UI_PATHS["logs"] / "tunables_changes.jsonl", 100))
    con.print(f"ui-smoke: {json.dumps(res)}")
    _wd.cancel()
    ok = all(res.get(_k) for _k in ("bags_stay_until_back", "no_timed_return", "keys_case_insensitive", "title_case", "hint_style", "goals_native_unit", "relay_tab", "log_tabs_title_case")) and res["paper_live_confirm"] and res["seeded_live_label"] and res["sink"] and res["log_sources_ok"] and res["log_empty_states"] and res["value_format"] and res["settings_all_labelled"] and res["secrets_masked"] and res.get("filter_write", True) and \
        res.get("reject_out_of_range", True) and res.get("env_write_one_line", True) and res["state_resume"] and \
        res["env_only_allowlisted"] and res["env_stale_refused"] and res["filter_stale_refused"] and \
        res["env_external_detected"] and res["filter_external_detected"] and res.get("skill_stale_refused", True) and \
        res.get("skill_editor_saved", True) and res.get("skill_editor_stale_refused", True) and res.get("skill_editor_noeditor", True) and \
        res["x_status_ok"] and res["archive_periods"] == 2 and res["baseline_moved"] and res["history_untouched"] and \
        res["logs_scrollback"]["loaded"] == 5000 and res["logs_scrollback"]["search_hit"] and \
        all(res["scraper_pause"].values()) and all(res["goals"].values()) and \
        res["settings_render"]["fits"] and res["settings_render"]["headers"] == 2 and all(res["alerts"].values()) and \
        res["owner_card"]["path_ok"] and res["recap"]["jsonl"] and res["recap"]["card"] and \
        res["red_hold"]["first_pass_cards"] == 1 and res["red_hold"]["dedup_second"] == 0 and \
        all(all(x.values()) for k_, x in res["scroll_80x24"].items() if isinstance(x, dict))
    con.print("ui-smoke " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1




def _ui_health_text():
    _drop_health_refresh()
    return _ui_health_text_core()


def run(stop_hook=None) -> None:
    """Open the console in this terminal. Returns on Quit (7) or after Stop (8)."""
    if stop_hook:
        _DROP_HOOKS["stop"] = stop_hook
    _ui_activate()
    try:
        _ui_main()
    finally:
        _ui_deactivate()


if __name__ == "__main__":
    if "--ui-smoke" in sys.argv:
        sys.exit(_ui_smoke())
    run()
