#!/usr/bin/env python3
"""sniper.py: one entry point for Meme Sniper.

    pip install -r requirements.txt
    python bots/sniper.py

Menu: start everything, setup wizard, sign in to X, live dashboard, launch a token, exit.
meme_sniper.py stays the engine; this file only launches, configures and watches.
The dashboard reads state files only and never places trades.

Flags (optional): --start  --dashboard  --wizard  --launch  --console  --no-ui  --smoke  --ui-smoke  --help
"""
from __future__ import annotations

import json
import os

def _envv(key, default=None):
    """os.getenv, but a blank value (KEY= in .env) counts as unset and returns the default."""
    v = os.environ.get(key)
    return default if v is None or not str(v).strip() else v

import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("Meme Sniper needs `rich`. Run:  pip install -r requirements.txt")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cancel_input import CancelInput, choose  # noqa: E402  (q / back / esc at any prompt = back; Ctrl+C = stop)

VERSION = "v1.0.1"
TAGLINE = "Snipe, build, launch, all from one repo."
GREEN, PURPLE, BG = "#39FF14", "#8A2BE2", "#000000"

# ── paths ────────────────────────────────────────────────────────────────────
BOTS = Path(__file__).resolve().parent
SUB = BOTS / "sub-bots"
ENV_FILE = BOTS / ".env"
ENV_EXAMPLE = BOTS / ".env.example"


def _root() -> Path:
    v = (os.environ.get("WORKSPACE_DIR") or "").strip()
    if not v and ENV_FILE.exists():
        for ln in ENV_FILE.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if ln.strip().startswith("WORKSPACE_DIR="):
                v = ln.split("=", 1)[1].strip().strip('"').strip("'")
    return Path(v).expanduser().resolve() if v else BOTS.parent


ROOT = _root()
BOT_LOGS = ROOT / "bot_logs"
JSON_RELAY = ROOT / "json_relay"
LAUNCH_REQ_DIR = JSON_RELAY / "launch_requests"
SETUP_JSON_CANDIDATES = (ROOT / "setup.json", BOTS / "setup.json")
LAUNCHER_LOG = BOT_LOGS / "sniper_launcher.log"
LAUNCHER_HB = BOT_LOGS / "sniper_launcher_heartbeat.json"
ENGINE_HB = BOT_LOGS / "meme_sniper_heartbeat.json"

COMPONENTS = [  # (name, script path)
    ("meme_sniper", BOTS / "meme_sniper.py"),
    ("security_warden", SUB / "security_warden.py"),
    ("agent_autoagent", SUB / "agent_autoagent.py"),
    ("x_intel", SUB / "x_intel.py"),
    ("agent_scraper", SUB / "agent_scraper.py"),
    ("code_tuner", SUB / "code_tuner.py"),
    ("log_janitor", SUB / "log_janitor.py"),
    ("learnings_writer", SUB / "learnings_writer.py"),
]
OWNER_COMMANDS_COMPONENT = ("owner_commands", SUB / "owner_commands.py")   # started only when OWNER_COMMANDS != off
OWNER_COMMANDS_CHOICES = ("off", "telegram", "file")

# wizard fields: (key, prompt, secret, default)
WIZARD_FIELDS = [
    ("HOT_WALLET_PRIVATE_KEY", "Trading wallet private key (base58)", True, None),
    ("HOT_WALLET_ADDRESS", "Trading wallet address", False, None),
    ("LEDGER_ADDRESS", "Cold wallet address for profit sweeps (optional; blank = sweeps off)", False, ""),
    ("RPC_URL", "Solana RPC URL (Helius or other)", True, None),
    ("HELIUS_API_KEY", "Helius API key (optional if RPC_URL already ends in ?api-key=...; used by the warden and launch rail)", True, ""),
    ("HELIUS_DAILY_CREDIT_CAP", "Helius plan (sets the daily credit cap: free 30000 / developer 300000 / business 3000000 / custom / 0 = off)", False, "30000"),
    ("GROK_API_KEY", "Grok (xAI) API key (recommended brain; Enter skips if you run Ollama only)", True, None),
    ("GROK_TEXT_MODEL", "Grok text model (recommended: grok-4.7)", False, "grok-4.7"),
    ("OLLAMA_ENABLED", "Use local Ollama as fallback/brain? (true/false)", False, "false"),
    ("OLLAMA_MODEL", "Local Ollama text model (recommended: qwen3:14b-q4_K_M)", False, "qwen3:14b-q4_K_M"),
    ("OLLAMA_VISION_MODEL", "Local Ollama vision model (recommended: qwen2.5vl:7b)", False, "qwen2.5vl:7b"),
    ("OLLAMA_CLOUD_ENABLED", "Use Ollama cloud (needs your own key; off by default) (true/false)", False, "false"),
    ("OLLAMA_CLOUD_API_KEY", "Ollama cloud API key (optional, Enter skips)", True, ""),
    ("OLLAMA_CLOUD_MODEL", "Ollama cloud model (recommended: deepseek-v4-pro:cloud)", False, "deepseek-v4-pro:cloud"),
    ("LLM_PROVIDER_ORDER", "Legacy brain order (only used while LLM_MAIN is unset), comma list of grok/openai/anthropic/ollama/openai_compat", False, "grok,ollama"),
    ("OPENAI_API_KEY", "OpenAI API key (optional, Enter skips)", True, ""),
    ("OPENAI_MODEL", "OpenAI model (pick a current one; blank = OpenAI off)", False, ""),
    ("ANTHROPIC_API_KEY", "Anthropic (Claude) API key (optional, Enter skips)", True, ""),
    ("ANTHROPIC_MODEL", "Claude model (pick a current one; blank = Claude off)", False, ""),
    ("OPENAI_COMPAT_BASE_URL", "OpenAI-compatible endpoint base URL, e.g. https://host/v1 (optional)", False, ""),
    ("OPENAI_COMPAT_API_KEY", "OpenAI-compatible endpoint key (optional)", True, ""),
    ("OPENAI_COMPAT_MODEL", "OpenAI-compatible model name (optional)", False, ""),
    ("SNIPER_BUY_SIZE_SOL", "Base buy size in SOL (also the base entry cap; hard caps still apply)", False, "0.1"),
    ("SNIPER_DEFAULT_SL_PCT", "Default stop-loss % armed on each new position unless the agent sets one (0 = off)", False, "25"),
    ("SNIPER_DEFAULT_TP_PCT", "Default take-profit % armed on each new position unless the agent sets one (0 = off)", False, "100"),
    ("LAUNCH_RAIL_LIVE", "Launch tokens live on-chain (LAUNCH_RAIL_LIVE)?", False, "0"),
    ("LAUNCH_RAIL_ENABLED", "Turn on the launch rail at all (master switch; off = no token launches, not even dry runs)?", False, "false"),
    ("LAUNCH_MAX_DEV_BUY_SOL", "Max dev buy per token launch (SOL)", False, "0.5"),
    ("DAILY_LOSS_STOP_SOL", "Daily loss stop: realized SOL loss in one day that stops new buys (0 = off)", False, "0.5"),
    ("DAILY_BUY_CAP", "Daily buy cap: most buys per day (0 = off)", False, "10"),
    ("MINT_COOLDOWN_HOURS", "Same-token cooldown: hours before it may buy the same token again after a stop-loss", False, "72"),
    ("LOSS_STREAK_PAUSE", "Loss-streak pause: losses in a row that pause buys for a while (0 = off)", False, "3"),
    ("MAX_OPEN_POSITIONS", "Max open positions at once (0 = off)", False, "3"),
    ("TRADING_HOURS", "Trading hours, e.g. 09:00-23:00 (blank = always)", False, ""),
    ("TRADING_TZ", "Timezone for trading hours (e.g. America/New_York, Europe/London)", False, "America/New_York"),
    ("PINATA_JWT", "Pinata JWT for token image/metadata uploads (needed for live launches; Enter skips)", True, ""),
    ("OWN_LAUNCH_MODE", "Own-launch mode (hold / flip)", False, "hold"),
    ("OWN_LAUNCH_TREASURY_PCT", "Own-launch treasury % (never sold)", False, "50"),
    ("TELEGRAM_TOKEN", "Telegram bot token from @BotFather (optional, Enter skips)", True, ""),
    ("TELEGRAM_CHAT_ID", "Telegram chat ID for alerts (optional, Enter skips)", False, ""),
    ("ALERT_CHANNELS", "Alert Channels, comma list of telegram / discord / email / ntfy, or off (blank = telegram if its token + chat are set)", False, ""),
    ("DISCORD_WEBHOOK_URL", "Discord Webhook URL (Server Settings > Integrations > Webhooks)", True, ""),
    ("SMTP_HOST", "SMTP Host, e.g. smtp.gmail.com", False, ""),
    ("SMTP_PORT", "SMTP Port (587 = STARTTLS, 465 = SSL)", False, "587"),
    ("SMTP_USER", "SMTP Username (blank = no login)", False, ""),
    ("SMTP_PASS", "SMTP Password (Gmail: an app password)", True, ""),
    ("SMTP_FROM", "Email From Address (blank = SMTP Username)", False, ""),
    ("ALERT_EMAIL_TO", "Email To Address (where alerts go)", False, ""),
    ("ALERT_EMAIL_MIN_INTERVAL_S", "Email Minimum Interval in seconds (extra alerts inside it are counted, not emailed)", False, "60"),
    ("NTFY_TOPIC", "Ntfy Topic (pick a long unguessable name)", False, ""),
    ("NTFY_URL", "Ntfy Server URL", False, "https://ntfy.sh"),
    ("NTFY_TOKEN", "Ntfy Access Token (only for protected topics; Enter skips)", True, ""),
    ("OWNER_COMMANDS", "Owner Commands: Off, Telegram (A Separate Command Bot) Or File (Drop A Text File In owner_commands/)", False, "off"),
    ("OWNER_COMMANDS_TG_TOKEN", "Owner Commands Bot Token (A Second @BotFather Bot, Never The Alert Bot)", True, ""),
    ("OWNER_COMMANDS_TG_CHAT_ID", "Owner Commands Chat ID (Blank = Telegram Chat ID)", False, ""),
    ("OWNER_ROAST_COOLDOWN_S", "Owner Roast Cooldown In Seconds", False, "900"),
    ("OWNER_ROAST_TARGETING", "Roast Whoever Made The Trades (On: Your Own Trades Roast You, The Agent's Roast The Agent; Off: Always Roast The Agent)", False, "on"),
    ("X_NOTIFY_TELEGRAM_TOKEN", "Backup alert bot token (optional): a second Telegram bot the warden sends alerts through. Use it if another app or agent already polls your main bot (Telegram allows one poller per bot). Enter = use the main token; alerts go to the same chat", True, ""),
]
REQUIRED_KEYS = ("HOT_WALLET_PRIVATE_KEY", "RPC_URL", "GROK_API_KEY")   # GROK_API_KEY, or an Ollama brain
LAUNCH_LIVE_WARNING = (
    "LAUNCH RAIL: off-chain is the default. With LAUNCH_RAIL_LIVE=1 the agent can create tokens on pump.fun, "
    "buy the dev bag (up to LAUNCH_MAX_DEV_BUY_SOL), burn and claim creator fees with real SOL from the "
    "trading wallet, without asking first, unless rules/rules.md says to ask. "
    "Answer no (the default) to keep launches off-chain (LAUNCH_RAIL_LIVE=0).")

def _win_utf8() -> None:
    """Windows consoles (PowerShell, cmd): switch to UTF-8 so the banner and tables render."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # Turn on VT processing BEFORE the rich Console is created. Without it rich sees a
    # legacy console, falls back to 16 colours, and the half-block logo turns into blocks.
    try:
        import ctypes
        k = ctypes.windll.kernel32
        for std in (-11, -12):
            h = k.GetStdHandle(std)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass


_win_utf8()
console = Console(highlight=False)


def log(msg: str) -> None:
    try:
        BOT_LOGS.mkdir(parents=True, exist_ok=True)
        with open(LAUNCHER_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(p: Path, default=None):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ── env helpers ──────────────────────────────────────────────────────────────
def read_env(path: Path = ENV_FILE) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                v = "" if v.strip().startswith("#") else re.sub(r"\s+#.*$", "", v).strip().strip('"').strip("'")
                out[k.strip()] = v
    return out


try:
    sys.path.insert(0, str(BOTS / "sub-bots"))
    import llm_providers as _llmp  # noqa: E402  (pure choice helpers; no network at import)
except Exception:
    _llmp = None
LLM_CHOICES = ("grok", "openai", "anthropic", "ollama", "openai_compat")
# per provider: (key, required?) rows the wizard shows when that provider is main or fallback
PROVIDER_ROWS = {
    "grok": (("GROK_API_KEY", True), ("GROK_TEXT_MODEL", False)),
    "openai": (("OPENAI_API_KEY", True), ("OPENAI_MODEL", True)),
    "anthropic": (("ANTHROPIC_API_KEY", True), ("ANTHROPIC_MODEL", True)),
    "openai_compat": (("OPENAI_COMPAT_BASE_URL", True), ("OPENAI_COMPAT_MODEL", True), ("OPENAI_COMPAT_API_KEY", False)),
    "ollama": (("OLLAMA_MODEL", False), ("OLLAMA_VISION_MODEL", False), ("OLLAMA_CLOUD_ENABLED", False)),
}
OLLAMA_CLOUD_ROWS = (("OLLAMA_CLOUD_API_KEY", True), ("OLLAMA_CLOUD_MODEL", False))


def llm_choice(env: dict):
    """(main, fallback) when LLM_MAIN is set, else None (legacy LLM_PROVIDER_ORDER)."""
    if _llmp is not None:
        return _llmp.choice(env)
    m = str(env.get("LLM_MAIN") or "").strip().lower()
    if not m:
        return None
    f = str(env.get("LLM_FALLBACK", "ollama") or "").strip().lower()
    return (m if m in LLM_CHOICES else "grok"), (f if f in LLM_CHOICES and f != m else "")


def provider_ready(p: str, env: dict) -> bool:
    g = lambda k: str(env.get(k) or "").strip()
    if p == "grok":
        return bool(g("GROK_API_KEY") or g("XAI_API_KEY"))
    if p == "openai":
        return bool(g("OPENAI_API_KEY") and g("OPENAI_MODEL"))
    if p == "anthropic":
        return bool(g("ANTHROPIC_API_KEY") and g("ANTHROPIC_MODEL"))
    if p == "openai_compat":
        return bool(g("OPENAI_COMPAT_BASE_URL") and g("OPENAI_COMPAT_MODEL"))
    if p == "ollama":
        return True     # local; selecting it turns it on
    return False


def selected_providers(env: dict) -> list:
    """Providers that will run: [main, fallback] when chosen; legacy: the order plus configured extras."""
    c = llm_choice(env)
    if c:
        return [p for p in c if p]
    order = []
    for p in str(env.get("LLM_PROVIDER_ORDER") or "grok,ollama").lower().split(","):
        p = {"xai": "grok", "claude": "anthropic", "compat": "openai_compat"}.get(p.strip(), p.strip())
        if p in LLM_CHOICES and p not in order:
            order.append(p)
    if "ollama" in order and not _on(env.get("OLLAMA_ENABLED")) and not (
            _on(env.get("OLLAMA_CLOUD_ENABLED")) and env.get("OLLAMA_CLOUD_API_KEY")):
        order.remove("ollama")
    extra = [p for p in LLM_CHOICES if p not in order and p != "ollama" and provider_ready(p, env)]
    return order + extra


def env_complete(env: dict) -> bool:
    c = llm_choice(env)
    if c:
        if not any(provider_ready(p, env) for p in c if p):
            return False
        return all(env.get(k) for k in REQUIRED_KEYS if k != "GROK_API_KEY")
    ollama = str(env.get("OLLAMA_ENABLED", "")).lower() in ("true", "1", "yes") or \
        (str(env.get("OLLAMA_CLOUD_ENABLED", "")).lower() in ("true", "1", "yes") and env.get("OLLAMA_CLOUD_API_KEY"))
    other = (env.get("OPENAI_API_KEY") and env.get("OPENAI_MODEL")) or \
        (env.get("ANTHROPIC_API_KEY") and env.get("ANTHROPIC_MODEL")) or \
        (env.get("OPENAI_COMPAT_BASE_URL") and env.get("OPENAI_COMPAT_MODEL"))
    if not (env.get("GROK_API_KEY") or env.get("XAI_API_KEY") or ollama or other):
        return False
    return all(env.get(k) for k in REQUIRED_KEYS if k != "GROK_API_KEY")


def write_env(values: dict, path: Path = ENV_FILE, template: Path = ENV_EXAMPLE) -> Path:
    """Set keys in an env file: replace existing lines, append the rest. Values are never printed."""
    if path.exists():
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    elif template.exists():
        lines = template.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    else:
        lines = []
    done = set()
    out = []
    for ln in lines:
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=(.*)$", ln)
        if m:
            cm = re.search(r"\s+#.*$", m.group(2))
            if cm and not m.group(2).strip().startswith(("'", '"')):
                out.append("# " + cm.group(0).strip().lstrip("#").strip())   # comment moved to its own line
                ln = f"{m.group(1)}={m.group(2)[:cm.start()].strip()}"
            if m.group(1) in values:
                ln = f"{m.group(1)}={values[m.group(1)]}"
                done.add(m.group(1))
        out.append(ln)
    lines = out
    _lbl = {k: l for k, l, _s, _d in WIZARD_FIELDS + EXTRA_FIELDS}
    extra = []
    for k, v in values.items():
        if k not in done:
            if k in _lbl:
                extra.append("# " + _lbl[k])   # comment on its own line (python-dotenv reads inline # as the value)
            extra.append(f"{k}={v}")
    if extra:
        lines += ["", "# --- set by the sniper.py setup wizard ---"] + extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def setup_json_path():
    for p in SETUP_JSON_CANDIDATES:
        if p.exists():
            return p
    return None


def _on(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


PAPER_WARNING = ("PAPER mode: the full pipeline runs (feed, filters, rug checks, decisions, exits) but buys and "
                 "sells are simulated at real quotes with estimated slippage and fees. No transaction is sent and "
                 "launches are dry runs. Paper results live in bot_logs/paper/. Live trading stays the default.")


def paper_mode_answer(cur: dict, answers: dict | None) -> str:
    """Explicit opt-in (defaults to No). Leaving paper for live needs the word LIVE typed."""
    was = _on(cur.get("SNIPER_PAPER_MODE"))
    if answers is not None:
        want = _on(answers.get("SNIPER_PAPER_MODE", "1" if was else "0"))
        if was and not want and str(answers.get("SNIPER_CONFIRM_LIVE", "")).strip() != "LIVE":
            return "1"
        return "1" if want else "0"
    console.print(Panel(PAPER_WARNING, border_style="yellow", title="Paper Mode"))
    want = Confirm.ask("Run in PAPER mode (simulated, no real transactions)?", default=False)
    if was and not want:
        if Prompt.ask("Switching back to LIVE trading with real funds. Type LIVE to confirm",
                      default="", show_default=False).strip() != "LIVE":
            console.print("[yellow]not confirmed; staying in paper mode[/]")
            return "1"
    return "1" if want else "0"


def apply_setup_json() -> bool:
    """Agent override: setup.json {"env": {...}} is written into .env, no questions asked.
    Exception: paper -> live needs "SNIPER_CONFIRM_LIVE": "LIVE" alongside (owner's explicit OK)."""
    p = setup_json_path()
    if not p:
        return False
    data = _read_json(p, {}) or {}
    env = data.get("env") if isinstance(data.get("env"), dict) else {}
    if "SNIPER_PAPER_MODE" in env and _on(read_env().get("SNIPER_PAPER_MODE")) and not _on(env["SNIPER_PAPER_MODE"]) \
            and str(env.get("SNIPER_CONFIRM_LIVE", "")).strip() != "LIVE":
        env = {k: v for k, v in env.items() if k != "SNIPER_PAPER_MODE"}
        log("setup.json asked to leave paper mode without SNIPER_CONFIRM_LIVE=LIVE; staying in paper")
    env.pop("SNIPER_CONFIRM_LIVE", None)
    if env or not ENV_FILE.exists():   # agent path also creates bots/.env from bots/.env.example
        write_env({k: str(v) for k, v in env.items()})
    log(f"configured by agent ({p.name}, {len(env)} keys)")
    try:   # setup.json holds secrets: remove it once applied (values now live in bots/.env)
        p.unlink()
        log(f"deleted {p.name} after applying (secrets now only in bots/.env)")
    except OSError as e:
        log(f"could not delete {p.name} ({type(e).__name__}); delete it by hand")
    console.print(f"[{GREEN}]configured by agent[/] ({p.name}, file deleted after applying)")
    return True


# ── banner ───────────────────────────────────────────────────────────────────
WORDMARK = [
    "█▄ ▄█ █▀▀ █▄ ▄█ █▀▀   █▀▀ █▄  █ █ █▀█ █▀▀ █▀█",
    "█ ▀ █ █▀▀ █ ▀ █ █▀▀   ▀▀█ █ ▀▄█ █ █▀▀ █▀▀ █▀▄",
    "▀   ▀ ▀▀▀ ▀   ▀ ▀▀▀   ▀▀▀ ▀   ▀ ▀ ▀   ▀▀▀ ▀ ▀",
]


def _unicode_ok() -> bool:
    enc = (getattr(console, "encoding", "") or "").lower()
    return "utf" in enc


_LOGO_CACHE: dict = {}


def _logo_width() -> int:
    """Columns for the logo: 40 on a roomy terminal, 28 on a small one."""
    try:
        w, h = console.size.width, console.size.height
    except Exception:
        return 28
    return 40 if (w >= 90 and h >= 40) else 28


def _logo_art(width: int | None = None):
    """Half-block render of assets/meme_sniper_logo.png (one cell = two square pixels, truecolour).
    None if PIL/unicode/file missing or the terminal has no colour."""
    if not _unicode_ok() or console.color_system in (None, "standard", "windows"):
        return None
    width = width or _logo_width()
    if width in _LOGO_CACHE:
        return _LOGO_CACHE[width]
    p = ROOT / "assets" / "meme_sniper_logo.png"
    try:
        from PIL import Image
        src = Image.open(p)
        if src.mode in ("RGBA", "LA", "P"):
            src = src.convert("RGBA")
            bg = Image.new("RGBA", src.size, (0, 0, 0, 255))
            bg.alpha_composite(src)
            src = bg
        im = src.convert("RGB")
    except Exception:
        return None
    h = max(2, int(im.height * width / im.width / 2) * 2)
    im = im.resize((width, h), Image.LANCZOS)
    t = Text()
    for y in range(0, h, 2):
        for x in range(width):
            top, bot = im.getpixel((x, y)), im.getpixel((x, y + 1))
            t.append("▀", style=f"rgb({top[0]},{top[1]},{top[2]}) on rgb({bot[0]},{bot[1]},{bot[2]})")
        t.append("\n")
    _LOGO_CACHE[width] = t
    return t


def banner(show_logo: bool = True) -> Panel:
    t = Text(justify="center")
    if _unicode_ok():
        for i, ln in enumerate(WORDMARK):
            t.append(ln + "\n", style=f"bold {GREEN if i < 2 else PURPLE} on {BG}")
    else:
        t.append("M E M E   S N I P E R\n", style=f"bold {GREEN} on {BG}")
    t.append(f"{VERSION}\n", style=f"{PURPLE} on {BG}")
    t.append(TAGLINE, style=f"italic {GREEN} on {BG}")
    art = _logo_art() if show_logo else None
    body = Group(Align.center(art), Align.center(t)) if art is not None else Align.center(t)
    return Panel(body, style=f"on {BG}", border_style=PURPLE, box=box.HEAVY if _unicode_ok() else box.ASCII)


MENU = [("1", "Start Sniper (+ console)"), ("2", "Setup wizard"), ("3", "Sign in to X"),
        ("4", "Live dashboard"), ("5", "Launch a token"),
        ("6", "Console only (dashboard, logs, settings, skills, alerts)"), ("7", "Exit")]


def menu_panel() -> Panel:
    t = Table.grid(padding=(0, 2))
    for k, v in MENU:
        t.add_row(Text(k, style=f"bold {GREEN}"), Text(v, style="white"))
    try:
        miss = setup_missing(read_env())
        line = Text("setup: complete", style=GREEN) if not miss else \
            Text(f"setup: {len(miss)} missing ({', '.join(miss)}) - press 2", style="bold red")
    except Exception:
        line = Text("setup: unknown", style="yellow")
    return Panel(t, title="Menu", subtitle=line, border_style=GREEN, style=f"on {BG}",
                 box=box.ROUNDED if _unicode_ok() else box.ASCII)


# ── wizard ───────────────────────────────────────────────────────────────────
# ── wizard status ──
EXTRA_FIELDS = [   # (key, prompt, secret, default): asked as yes/no or extra keys, shown in the status table
    ("LLM_MAIN", "Main brain", False, "grok"),
    ("LLM_FALLBACK", "Fallback brain (none = no fallback)", False, "ollama"),
    ("X_BEARER_TOKEN", "X API bearer token (optional; or use menu 3, Sign in to X)", True, ""),
    ("SNIPER_LEARN_REST", "Let the system learn the rest (with learning mode on, also tune the other filters)?", False, "true"),
    ("SNIPER_LEARNING_MODE", "Turn on LEARNING mode (starts small, adjusts size and SL/TP from its own closed trades)?", False, "0"),
    ("SNIPER_PAPER_MODE", "Run in PAPER mode (simulated, no real transactions)?", False, "0"),
]
YESNO_KEYS = ("LAUNCH_RAIL_LIVE", "LAUNCH_RAIL_ENABLED", "SNIPER_LEARN_REST", "SNIPER_LEARNING_MODE", "SNIPER_PAPER_MODE",
              "OLLAMA_ENABLED", "OLLAMA_CLOUD_ENABLED")
AREAS = [
    ("Wallet", ("HOT_WALLET_PRIVATE_KEY", "HOT_WALLET_ADDRESS", "LEDGER_ADDRESS")),
    ("RPC", ("RPC_URL", "HELIUS_API_KEY", "HELIUS_DAILY_CREDIT_CAP")),
    ("Brain / LLM", None),       # dynamic: main + fallback, then only the selected providers' rows
    ("Alerts", "ALERTS"),        # dynamic: ALERT_CHANNELS, then the selected channels' rows
    ("Owner Commands", "OWNER_COMMANDS"),   # dynamic: the mode, then the Telegram rows only when it is telegram
    ("Pinata", ("PINATA_JWT",)),
    ("X", ("X_BEARER_TOKEN",)),
    ("Trading values", ("SNIPER_BUY_SIZE_SOL", "SNIPER_DEFAULT_SL_PCT", "SNIPER_DEFAULT_TP_PCT",
                        "LAUNCH_MAX_DEV_BUY_SOL", "OWN_LAUNCH_MODE", "OWN_LAUNCH_TREASURY_PCT")),
    ("Safety caps", ("DAILY_LOSS_STOP_SOL", "DAILY_BUY_CAP", "MINT_COOLDOWN_HOURS", "LOSS_STREAK_PAUSE",
                     "MAX_OPEN_POSITIONS", "TRADING_HOURS", "TRADING_TZ")),
    ("Modes", ("LAUNCH_RAIL_ENABLED", "LAUNCH_RAIL_LIVE", "SNIPER_PAPER_MODE", "SNIPER_LEARNING_MODE", "SNIPER_LEARN_REST")),
]
# blank is a valid answer here (blank = the built-in default / always), so "fill only what is missing" skips them
# once they have been seen; SNIPER_WIZARD_SAFETY=0 hides the Safety caps questions (kill switch)
BLANK_OK = ("TRADING_HOURS",)
IMPORTANT = ("HOT_WALLET_PRIVATE_KEY", "HOT_WALLET_ADDRESS", "RPC_URL", "PINATA_JWT")   # Telegram no longer required (2026-10-15)
X_KEYS = ("X_BEARER_TOKEN", "X_INTEL_TOKEN", "BROWSER_USER_DATA_DIR")


def _fields() -> dict:
    return {k: (k, lbl, sec, d) for k, lbl, sec, d in WIZARD_FIELDS + EXTRA_FIELDS}


def _brain_ok(env: dict) -> bool:
    return env_complete({**env, "HOT_WALLET_PRIVATE_KEY": "x", "RPC_URL": "x"})


def setup_missing(env: dict) -> list:
    """Short names of what a boot needs and is missing (never values)."""
    miss = [k for k in IMPORTANT if not str(env.get(k) or "").strip()]
    am = _alerts()
    if am is not None:
        for ch in am.channels(env):
            if am.missing(ch, env):
                miss.append(f"alerts: {am.CHANNELS[ch][0]}")
    if not _brain_ok(env):
        miss.append("brain/LLM key")
    if not str(env.get("X_BEARER_TOKEN") or "").strip():
        try:
            xst, _ = x_status_line(env)
        except Exception:
            xst = "missing"
        if xst not in ("verified", "unverified"):
            miss.append("X login")
    return miss


def _brain_rows(env: dict) -> list:
    """[(key or None, label, required, off_status)] for the Brain area. key None = info row (not editable)."""
    rows = [("LLM_MAIN", "LLM_MAIN", True, None), ("LLM_FALLBACK", "LLM_FALLBACK", False, None)]
    sel = selected_providers(env)
    for p in LLM_CHOICES:
        if p in sel:
            for k, req in PROVIDER_ROWS[p]:
                rows.append((k, k, req, None))
            if p == "ollama" and _on(env.get("OLLAMA_CLOUD_ENABLED")):
                rows += [(k, k, req, None) for k, req in OLLAMA_CLOUD_ROWS]
    for p in LLM_CHOICES:
        if p not in sel:
            keyset = any(str(env.get(k) or "").strip() for k, _ in PROVIDER_ROWS[p]
                         if not k.endswith(("_MODEL", "_ENABLED")))
            rows.append((None, p, False, "off (key set)" if keyset else "off"))
    return rows


def _alerts():
    """bots/sub-bots/alerts.py, or None."""
    try:
        sys.path.insert(0, str(SUB))
        import alerts as _a
        return _a
    except Exception:
        return None


def _alert_rows(env: dict) -> list:
    """Alerts area: the channel list first, then each SELECTED channel's keys (required ones
    marked), then one info row per channel that is off, and iMessage noted for later."""
    am = _alerts()
    rows = [("ALERT_CHANNELS", "ALERT_CHANNELS", False, None)]
    if am is None:
        return rows + [(k, k, False, None) for k in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "X_NOTIFY_TELEGRAM_TOKEN")]
    sel = am.channels(env)
    for st in am.status(env):
        ch = st["channel"]
        if ch in sel:
            req = am.CHANNELS[ch][1]
            rows += [(k, k, k in req, None) for k in st["keys"]
                     if k not in ("SMTP_STARTTLS",)]
        else:
            rows.append((None, st["label"], False, st["status"].lower()))
    return rows


def owner_commands_mode(env: dict) -> str:
    m = str(env.get("OWNER_COMMANDS") or "off").strip().lower()
    return m if m in OWNER_COMMANDS_CHOICES else "off"


def _owner_cmd_rows(env: dict) -> list:
    """Owner Commands area: the mode, then the command-bot rows only in telegram mode."""
    rows = [("OWNER_COMMANDS", "OWNER_COMMANDS", False, None)]
    if owner_commands_mode(env) == "telegram":
        rows += [("OWNER_COMMANDS_TG_TOKEN", "OWNER_COMMANDS_TG_TOKEN", True, None),
                 ("OWNER_COMMANDS_TG_CHAT_ID", "OWNER_COMMANDS_TG_CHAT_ID", False, None)]
    if owner_commands_mode(env) != "off":
        rows.append(("OWNER_ROAST_COOLDOWN_S", "OWNER_ROAST_COOLDOWN_S", False, None))
        rows.append(("OWNER_ROAST_TARGETING", "OWNER_ROAST_TARGETING", False, None))
    return rows


def owner_commands_answer(cur: dict) -> str | None:
    """Pick OWNER_COMMANDS (off / telegram / file). Esc, q or back keeps the current value."""
    now = owner_commands_mode(cur)
    console.print(Panel("Owner Commands. Ask the agent for /roast, /recap or /autopsy on demand.\n"
                        "Off: nothing runs.  Telegram: a SEPARATE command bot reads only your chat "
                        "(never the alert bot).  File: drop a .txt into owner_commands/ (any OS, no Telegram).",
                        border_style=PURPLE, title="Owner Commands"))
    v = choose(console, "Owner Commands", list(OWNER_COMMANDS_CHOICES), now)
    return None if v == now else v


def _area_rows(env: dict) -> list:
    """[(area, key or None, label, required, off_status)] in display order."""
    out = []
    for area, keys in AREAS:
        if keys is None:
            out += [(area, k, lbl, req, off) for k, lbl, req, off in _brain_rows(env)]
        elif keys == "ALERTS":
            out += [(area, k, lbl, req, off) for k, lbl, req, off in _alert_rows(env)]
        elif keys == "OWNER_COMMANDS":
            out += [(area, k, lbl, req, off) for k, lbl, req, off in _owner_cmd_rows(env)]
        else:
            if area == "Safety caps" and str(os.environ.get("SNIPER_WIZARD_SAFETY", "1")).strip().lower() in ("0", "false", "off", "no"):
                continue
            out += [(area, k, k, k in IMPORTANT, None) for k in keys]
    return out


# Helius plan -> daily credit cap (about 1/30 of the monthly credits, so one bad day
# cannot burn the month). 0 = no cap. Unset = Free (the engine falls back to 30000).
HELIUS_PLANS = (("free", "Free", 30000, "$0, 1M credits/month"),
                ("developer", "Developer", 300000, "$49, 10M credits/month"),
                ("business", "Business", 3000000, "$499, 100M credits/month"))
HELIUS_FREE_CAP = 30000
HELIUS_CAP_KEY = "HELIUS_DAILY_CREDIT_CAP"


def helius_cap_label(env: dict) -> str:
    v = str(env.get(HELIUS_CAP_KEY) or "").strip()
    if not v:
        return f"free plan cap {HELIUS_FREE_CAP:,}/day (default)"
    try:
        n = int(float(v))
    except ValueError:
        return "invalid (engine uses the free cap)"
    if n <= 0:
        return "off (no cap)"
    for _k, name, cap, _d in HELIUS_PLANS:
        if n == cap:
            return f"{name} ({cap:,}/day)"
    return f"custom ({n:,}/day)"


def helius_plan_answer(cur: dict) -> str | None:
    """Ask which Helius plan the user is on; returns the daily cap, or None to keep the current one."""
    now = str(cur.get(HELIUS_CAP_KEY) or "").strip()
    console.print("[dim]Helius bills in credits. The bot meters its own Helius calls and slows background "
                  "reads near a daily cap so one bad day cannot burn the month. Sniper uses about "
                  "0.15M-1.05M credits/month (more when scanning 24/7); with Perps about 0.2M-1.4M. "
                  "Not on Helius? Pick free.[/]")
    for i, (_k, name, cap, desc) in enumerate(HELIUS_PLANS, 1):
        console.print(f"  {i}. {name} [dim]({desc}) -> {cap:,}/day[/]")
    console.print(f"  {len(HELIUS_PLANS) + 1}. custom [dim](your own daily number)[/]")
    console.print(f"  {len(HELIUS_PLANS) + 2}. none [dim](0 = no cap, not recommended)[/]")
    opts = [k for k, *_ in HELIUS_PLANS] + ["custom", "none"]
    try:
        n_now = int(float(now)) if now else HELIUS_FREE_CAP
    except ValueError:
        n_now = HELIUS_FREE_CAP
    dflt = "none" if n_now <= 0 else next((k for k, _n, c, _d in HELIUS_PLANS if c == n_now), "custom")
    while True:
        pick = (Prompt.ask(f"Which Helius plan are you on? [dim]({' / '.join(opts)} or 1-{len(opts)})[/]",
                           default=dflt) or dflt).strip().lower()
        if pick.isdigit() and 1 <= int(pick) <= len(opts):
            pick = opts[int(pick) - 1]
        if pick not in opts:
            console.print("[yellow]Pick one of the listed plans.[/]")
            continue
        if pick == "custom":
            while True:
                v = Prompt.ask("Daily credit cap (whole number above 0)", default=str(n_now) if n_now > 0 else "")
                v = (v or "").replace(",", "").replace("_", "").strip()
                if v.isdigit() and int(v) > 0:
                    break
                console.print("[yellow]Enter a whole number above 0 (pick none for no cap).[/]")
            val = str(int(v))
        elif pick == "none":
            console.print("[bold red]Warning: no cap means nothing stops a bug, a busy market or a leaked key "
                          "from using your whole monthly Helius credits (or running up overage).[/]")
            if not Confirm.ask("Really run with no daily cap?", default=False):
                continue
            val = "0"
        else:
            val = str(next(c for k, _n, c, _d in HELIUS_PLANS if k == pick))
        return None if val == now else val


def _labels() -> dict:
    d = _read_json(BOTS / "settings_labels.json", {}) or {}
    return d.get("keys", {}) if isinstance(d, dict) else {}


def wizard_status_table(env: dict) -> Table:
    """Status per area. Secrets and values are never shown: Set / Missing / on-off for modes.
    Provider names for main/fallback are shown (they are not secrets)."""
    t = Table(box=box.SIMPLE_HEAD, header_style=f"bold {PURPLE}", expand=False)
    for c in ("area", "#", "setting", "status", "key"):
        t.add_column(c, style="dim" if c == "key" else None)
    f = _fields()
    L = _labels()
    _add = t.add_row

    def _row(a, n, lab, st):     # label first, raw key dimmed at the end
        key = lab.plain if isinstance(lab, Text) else str(lab)
        e = L.get(key)
        shown = Text(e["label"], style=lab.style if isinstance(lab, Text) else "") if e else lab
        _add(a, n, shown, st, key if e else "")
    t.add_row = _row
    n = 0
    last = None
    choice = llm_choice(env)
    for area, k, label, req, off in _area_rows(env):
        first = area != last
        last = area
        if True:
            if k is None:
                t.add_row(Text(area if first else "", style=f"bold {GREEN}"), "", Text(label, style="dim"),
                          Text(off, style="dim"))
                continue
            n += 1
            v = str(env.get(k) or "").strip()
            if k in ("LLM_MAIN", "LLM_FALLBACK"):
                if choice:
                    name = choice[0] if k == "LLM_MAIN" else (choice[1] or "none")
                    ready = name == "none" or provider_ready(name, env)
                    st = Text(name + ("" if ready else " (needs key/model)"),
                              style=f"bold {GREEN}" if ready else "bold red")
                else:
                    st = Text("not chosen (legacy order: " + ",".join(selected_providers(env)) + ")"
                              if k == "LLM_MAIN" else "not chosen", style="bold yellow")
                t.add_row(Text(area if first else "", style=f"bold {GREEN}"), str(n), label, st)
                continue
            if k == HELIUS_CAP_KEY:
                lab_ = helius_cap_label(env)
                st = Text(lab_, style=f"bold {GREEN}" if v and not lab_.startswith("off") else
                          ("bold yellow" if v else "dim"))
                t.add_row(Text(area if first else "", style=f"bold {GREEN}"), str(n), label, st)
                continue
            if k in YESNO_KEYS:
                d = f.get(k, (k, "", False, ""))[3] or "0"
                on = _on(v if v else d)
                st = Text(("on" if on else "off") + ("" if v else " (default)"), style=GREEN if v else "dim")
            elif v:
                st = Text("Set", style=f"bold {GREEN}")
            elif req:
                st = Text("Missing", style="bold red")
            else:
                d = f.get(k, (k, "", False, ""))[3]
                st = Text(f"default" if d else "not set (optional)", style="dim")
            t.add_row(Text(area if first else "", style=f"bold {GREEN}"), str(n), label, st)
    return t


def _status_keys(env: dict | None = None) -> list:
    return [k for _, k, _, _, _ in _area_rows(env or {}) if k]


def _missing_keys(env: dict) -> list:
    """Editable keys that are unset (main/fallback count as unset until chosen)."""
    return [k for k in _status_keys(env) if not str(env.get(k) or "").strip() and k not in BLANK_OK]


def _ask_field(key: str, cur: dict) -> str | None:
    """One field. Enter keeps the current value (returns None). 'clear' blanks it explicitly."""
    f = _fields().get(key, (key, key, False, ""))
    _, label, secret, default = f
    if key == "LAUNCH_RAIL_LIVE":
        console.print(Panel(LAUNCH_LIVE_WARNING, border_style="red", title="Token Launches"))
        on = str(cur.get(key) or default).strip().lower() not in ("0", "false", "no", "off")
        return "1" if Confirm.ask(label, default=on) else "0"
    if key == "SNIPER_PAPER_MODE":
        return paper_mode_answer(cur, None)
    if key == "ALERT_CHANNELS":
        return alert_channels_answer(cur)
    if key == "OWNER_COMMANDS":
        return owner_commands_answer(cur)
    if key == HELIUS_CAP_KEY:
        return helius_plan_answer(cur)
    if key in ("LLM_MAIN", "LLM_FALLBACK"):
        c = llm_choice(cur)
        now = (c[0] if key == "LLM_MAIN" else (c[1] or "none")) if c else ""
        opts = list(LLM_CHOICES) if key == "LLM_MAIN" else \
            [p for p in LLM_CHOICES if p != (c[0] if c else str(cur.get("LLM_MAIN") or "grok"))] + ["none"]
        dflt = now if now in opts else (default if default in opts else opts[0])
        v = Prompt.ask(f"{label} [dim](others are OFF even if a key is set)[/]", choices=opts, default=dflt)
        return None if v == now else v
    if key in YESNO_KEYS:
        on = _on(cur.get(key) or default)
        yes = Confirm.ask(label, default=on)
        return ("true" if yes else "false") if key in ("SNIPER_LEARN_REST", "OLLAMA_ENABLED", "OLLAMA_CLOUD_ENABLED", "LAUNCH_RAIL_ENABLED") \
            else ("1" if yes else "0")
    has = bool(str(cur.get(key) or "").strip())
    hint = "[dim](set; Enter keeps, 'clear' blanks)[/]" if has else \
        ("[dim](missing; Enter uses the default)[/]" if default and not secret else "[dim](missing; Enter skips)[/]")
    if secret:
        v = Prompt.ask(f"{label} {hint}", password=True, default="", show_default=False)
    else:
        v = Prompt.ask(f"{label} {hint}", default=cur.get(key) or default or "", show_default=True)
    v = (v or "").strip()
    if v.lower() == "clear":
        return "" if has and Confirm.ask(f"Really clear {key}?", default=False) else None
    if not v or v == str(cur.get(key) or ""):
        return None
    return v


def _wizard_interactive(out_path: Path) -> Path | None:
    cur = read_env(out_path)
    console.print(Panel("Setup wizard. Secrets are typed hidden and never shown. Enter keeps a value, "
                        "'clear' blanks one, q / back / esc goes back without saving. Ctrl+C stops the launcher.", border_style=PURPLE))
    console.print(wizard_status_table(cur))
    miss = setup_missing(cur)
    console.print(Text("setup: complete" if not miss else f"setup: {len(miss)} missing: {', '.join(miss)}",
                       style=GREEN if not miss else "bold red"))
    console.print("1 fill only what is missing   2 edit one item   3 go through everything")
    mode = choose(console, "choose", ["1", "2", "3"], "1")
    keys = _status_keys(cur)
    if mode == "1":
        todo = _missing_keys(cur)
        if not todo:
            console.print(f"[{GREEN}]nothing missing[/]")
            return out_path
    elif mode == "2":
        n = Prompt.ask("item number(s), comma separated", default="")
        idx = [int(x) for x in n.replace(" ", "").split(",") if x.isdigit()]
        todo = [keys[i - 1] for i in idx if 1 <= i <= len(keys)]
    else:
        todo = list(keys)
    vals: dict = {}
    done: set = set()
    while todo:
        k = todo.pop(0)
        if k in done:
            continue
        done.add(k)
        v = _ask_field(k, {**cur, **vals})
        if v is not None:
            vals[k] = v
        if k == "OWNER_COMMANDS" and v is not None:
            merged = {**cur, **vals}
            todo += [x for _a, x, _l, _r, _o in _area_rows(merged)
                     if x and x != "OWNER_COMMANDS" and _a == "Owner Commands" and x not in done and x not in todo
                     and (mode == "3" or not str(merged.get(x) or "").strip())]
        if k == "ALERT_CHANNELS" and v is not None:
            # queue the newly selected channels' keys (status rows for the rest)
            merged = {**cur, **vals}
            todo += [x for _a, x, _l, _r, _o in _area_rows(merged)
                     if x and x != "ALERT_CHANNELS" and _a == "Alerts" and x not in done and x not in todo
                     and (mode == "3" or not str(merged.get(x) or "").strip())]
        if k in ("LLM_MAIN", "LLM_FALLBACK", "OLLAMA_CLOUD_ENABLED"):
            # the brain rows depend on the choice: queue what the new selection needs
            merged = {**cur, **vals}
            if k == "LLM_MAIN" and "LLM_FALLBACK" not in done and "LLM_FALLBACK" not in todo \
                    and not str(cur.get("LLM_FALLBACK") or "").strip():
                todo.insert(0, "LLM_FALLBACK")
            new = _status_keys(merged) if mode == "3" else _missing_keys(merged)
            todo += [x for x in new if x not in done and x not in todo
                     and (mode != "2" or x in [r for r, _ in sum(PROVIDER_ROWS.values(), ())] + [r for r, _ in OLLAMA_CLOUD_ROWS])]
    if any(k in vals for k in ("LLM_MAIN", "LLM_FALLBACK")):
        c = llm_choice({**cur, **vals})
        if c:
            want = "true" if "ollama" in c else "false"
            if str(cur.get("OLLAMA_ENABLED") or "").strip().lower() != want:
                vals["OLLAMA_ENABLED"] = want    # keep the file consistent with the choice
    if not vals:
        console.print("[dim]no changes[/]")
    else:
        console.print("changes: " + ", ".join(f"{k} ({'cleared' if v == '' else 'set'})" for k, v in vals.items()))
        if not Confirm.ask(f"Save {len(vals)} change(s) to {out_path.name}?", default=True):
            console.print("[yellow]not saved[/]")
            return None
        write_env(vals, out_path)
        log(f"wizard wrote {len(vals)} keys to {out_path.name}")
        console.print(f"[{GREEN}]saved[/] {len(vals)} setting(s) to {out_path} (values hidden)")
    am = _alerts()
    alert_keys = {"ALERT_CHANNELS", "X_NOTIFY_TELEGRAM_TOKEN"} | (am._all_keys() if am else set())
    after = read_env(out_path)
    if (any(k in vals for k in alert_keys) or mode == "3") and am is not None and am.channels(after):
        alerts_step(after, ask_first=True)
    if mode == "3" or not (ROOT / "rules" / "rules.md").exists():
        owner_rules_step(None, interactive=True, root=ROOT)
    if str(os.environ.get("SNIPER_WIZARD_REMINDER", "1")).strip().lower() not in ("0", "false", "off", "no"):
        console.print(Panel("Next: set up your inbox checks. Ask your SI agent to schedule the prompts in automations/ "
                            "(sniper_lane every 10 min, misc_lane 15, warden_lane 20, morning_brief daily, nightly "
                            "self-eval). README Quick start step 8.", border_style=PURPLE, title="Inbox checks"))
    return out_path


def wizard(out_path: Path = ENV_FILE, answers: dict | None = None) -> Path | None:
    """Status first, then fill missing / edit one / everything. `answers` makes it non-interactive (tests).
    Interactive: nothing is written until the final confirm; q / back / esc cancels (Ctrl+C = stop)."""
    if answers is None:
        try:
            return _wizard_interactive(out_path)
        except CancelInput:
            console.print("[yellow]wizard cancelled, nothing saved[/]")
            return None
    console.print(Panel("Setup wizard. Secrets are typed hidden and never shown. "
                        "Leave a field blank to keep its current value.", border_style=PURPLE))
    cur = read_env(out_path)
    vals = {}
    for key, label, secret, default in WIZARD_FIELDS:
        if key == "LAUNCH_RAIL_LIVE":   # explicit yes/no, defaults to off-chain, loud warning first
            if answers is not None:
                v = str(answers.get(key, default))
            else:
                console.print(Panel(LAUNCH_LIVE_WARNING, border_style="red", title="Token Launches"))
                on = str(cur.get(key) or default).strip().lower() not in ("0", "false", "no", "off")
                v = "1" if Confirm.ask(label, default=on) else "0"
            vals[key] = v
            continue
        if key == HELIUS_CAP_KEY and answers is not None and key not in answers and str(cur.get(key) or "").strip():
            continue   # keep the plan already in .env; no plan given + none set -> Free cap below
        if answers is not None:
            v = answers.get(key, default or "")
        else:
            shown = "set" if cur.get(key) else "empty"
            if secret:
                v = Prompt.ask(f"{label} [dim]({shown})[/]", password=True, default="", show_default=False)
            else:
                v = Prompt.ask(label, default=cur.get(key) or default or "")
        if v:
            vals[key] = v.strip()
    learn = answers.get("SNIPER_LEARN_REST", "true") if answers is not None else \
        ("true" if Confirm.ask("Let the system learn the rest?", default=True) else "false")
    vals["SNIPER_LEARN_REST"] = learn
    lm = answers.get("SNIPER_LEARNING_MODE", "0") if answers is not None else \
        ("1" if Confirm.ask("Turn on LEARNING mode (starts small, adjusts size and SL/TP from its own "
                            "closed trades in small logged steps)?", default=False) else "0")
    vals["SNIPER_LEARNING_MODE"] = str(lm)
    vals["SNIPER_PAPER_MODE"] = paper_mode_answer(cur, answers)
    write_env(vals, out_path)
    owner_rules_step(answers.get("_rules") if answers is not None else None,
                     interactive=answers is None, root=out_path.parent if answers is not None else ROOT)
    log(f"wizard wrote {len(vals)} keys to {out_path.name}")
    console.print(f"[{GREEN}]saved[/] {len(vals)} settings to {out_path} (values hidden)")
    return out_path


RULES_SECTIONS = [
    ("max_size", "Max size", "Largest buy in SOL, or % of wallet per trade (e.g. 0.25 SOL / 10%)"),
    ("no_trade_hours", "No-trade hours", "Local hours or days you never trade (e.g. 00:00-07:00, weekends)"),
    ("banned", "Banned tokens / categories", "CAs, tickers or categories never to buy (e.g. political, AI agents)"),
    ("loss_limits", "Loss limits", "Daily / weekly loss that stops trading (e.g. -1 SOL per day)"),
    ("exits", "Exits", "Your own SL/TP or hold rules (e.g. always peel 50% at 2x)"),
    ("other", "Other", "Anything else the agent must always or never do"),
]


def rules_template(values: dict | None = None) -> str:
    v = values or {}
    out = ["# Owner trading rules", "",
           "The agent reads this file before every trade decision. These rules override skill defaults.",
           "The bot's hard safety gates (wallet floor, rug checks, size caps) still apply.",
           "Leave a section empty if it does not apply.", ""]
    for key, title, hint in RULES_SECTIONS:
        out += [f"## {title}", f"<!-- {hint} -->", (v.get(key) or "").strip(), ""]
    return "\n".join(out).rstrip() + "\n"


def owner_rules_step(values: dict | None = None, interactive: bool = True, root: Path = ROOT) -> Path:
    """Ask for personal trading rules; write rules/rules.md (template when none). Never overwrites
    an existing file unless the owner says so."""
    p = Path(root) / "rules" / "rules.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    if interactive:
        if p.exists() and not Confirm.ask(f"{p} exists. Update your trading rules now?", default=False):
            return p
        vals = {}
        if Confirm.ask("Do you have personal trading rules (max size, no-trade hours, banned tokens, loss limits)?",
                       default=False):
            for key, title, hint in RULES_SECTIONS:
                vals[key] = Prompt.ask(f"{title} [dim]({hint}; Enter skips)[/]", default="", show_default=False)
        p.write_text(rules_template(vals), encoding="utf-8")
    elif values is not None or not p.exists():
        p.write_text(rules_template(values), encoding="utf-8")
    log(f"owner rules at {p} ({'filled' if values or interactive else 'template'})")
    return p


# ── supervisor ───────────────────────────────────────────────────────────────
SNIPER_RELOAD_EXIT_CODE = 75   # meme_sniper.py exits with this on a live-update reload


class Child:
    def __init__(self, name: str, script: Path):
        self.name, self.script = name, script
        self.proc = None
        self.restarts = 0
        self.started = 0.0
        self.next_start = 0.0
        self.state = "pending"
        self.log = None

    def start(self) -> None:
        if not self.script.exists():
            self.state = "missing"; return
        BOT_LOGS.mkdir(parents=True, exist_ok=True)
        self.log = open(BOT_LOGS / f"{self.name}.console.log", "a", encoding="utf-8")
        self.log.write(f"\n==== start {_now_iso()} (restart #{self.restarts}) ====\n"); self.log.flush()
        # SNIPER_SUPERVISED: the engine exits with 75 on a live-update and this launcher
        # restarts it (no os.execv, so never an orphaned second engine).
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", SNIPER_SUPERVISED="1")
        self.proc = subprocess.Popen([sys.executable, str(self.script)], cwd=str(self.script.parent),
                                     stdout=self.log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)
        self.started = time.time(); self.state = "running"
        log(f"started {self.name} pid={self.proc.pid}")

    def poll(self) -> None:
        if self.state == "missing":
            return
        if self.proc and self.proc.poll() is None:
            return
        if self.proc is not None:
            rc = self.proc.returncode
            log(f"{self.name} exited rc={rc}")
            self.proc = None
            if self.log:
                self.log.close(); self.log = None
            if rc == SNIPER_RELOAD_EXIT_CODE:
                # 2026-10-16: live-update reload, not a crash: restart now, no backoff.
                log(f"{self.name} live-update reload - restarting on the new code")
                self.state = "reloading"
                self.next_start = 0.0
                self.start()
                return
            if time.time() - self.started > 300:
                self.restarts = 0       # it ran a while; reset the backoff
            self.restarts += 1
            self.next_start = time.time() + min(60, 5 * self.restarts)
            self.state = f"crashed rc={rc}"
        if time.time() >= self.next_start:
            self.start()

    def stop(self, timeout: float = 20.0) -> None:
        p = self.proc
        if not p or p.poll() is not None:
            return
        try:
            if os.name != "nt":
                p.send_signal(signal.SIGINT)
        except Exception:
            pass
        try:
            p.wait(timeout=timeout)
        except Exception:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        if self.log:
            self.log.close(); self.log = None
        self.state = "stopped"


def _status_table(children) -> Table:
    t = Table(box=box.SIMPLE, show_header=True, header_style=f"bold {PURPLE}", expand=False)
    for c in ("component", "state", "pid", "up", "restarts"):
        t.add_column(c)
    for c in children:
        alive = c.proc is not None and c.proc.poll() is None
        color = GREEN if alive else ("yellow" if c.state.startswith("crashed") else "red")
        up = f"{int(time.time() - c.started)}s" if alive else "-"
        t.add_row(c.name, Text(c.state, style=color), str(c.proc.pid) if alive else "-", up, str(c.restarts))
    return t


def write_stop_reason(reason: str = "user_stopped") -> None:
    hb = _read_json(LAUNCHER_HB, {}) or {}
    hb.update({"stop_reason": reason, "stopped_at": _now_iso()})
    _write_json(LAUNCHER_HB, hb)
    eng = _read_json(ENGINE_HB, None)
    if isinstance(eng, dict) and not eng.get("stop_reason"):
        eng.update({"stop_reason": reason, "stopped_at": _now_iso()})
        _write_json(ENGINE_HB, eng)
    log(f"stop_reason {reason}")


def _ui_wanted() -> bool:
    if "--no-ui" in sys.argv or (os.environ.get("SNIPER_UI") or "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    return bool(sys.stdin and sys.stdin.isatty())


def open_console(stop_hook=None) -> bool:
    """bots/sniper_ui.py: dashboard, logs, settings, skills, goals, alerts, bag actions, health, recap."""
    try:
        sys.path.insert(0, str(BOTS))
        import sniper_ui
    except Exception as e:
        console.print(f"[yellow]console unavailable ({type(e).__name__}); using the status view[/]")
        log(f"console import failed: {e}")
        return False
    try:
        sniper_ui.run(stop_hook=stop_hook)
    except Exception as e:
        log(f"console error: {e}")
        console.print("[red]console error (logged); bots keep running[/]")
    return True


def start_all() -> None:
    only = [s.strip() for s in (os.environ.get("SNIPER_COMPONENTS") or "").split(",") if s.strip()]
    comps = list(COMPONENTS)
    try:
        if owner_commands_mode(read_env()) != "off":
            comps.append(OWNER_COMMANDS_COMPONENT)      # optional; off by default
    except Exception:
        pass
    children = [Child(n, p) for n, p in comps if not only or n in only]
    _write_json(LAUNCHER_HB, {"started_at": _now_iso(), "pid": os.getpid(),
                              "components": [c.name for c in children]})
    log("start: " + ", ".join(c.name for c in children))
    halt = threading.Event()
    stopped = threading.Event()

    def _supervise():
        while not halt.is_set():
            for c in children:
                c.poll()
            hb = _read_json(LAUNCHER_HB, {}) or {}
            hb["last_update"] = _now_iso()
            hb["states"] = {c.name: c.state for c in children}
            _write_json(LAUNCHER_HB, hb)
            halt.wait(2)

    def _stop_all():
        if stopped.is_set():
            return
        stopped.set(); halt.set()
        console.print(f"[{PURPLE}]stopping all components...[/]")
        threads = [threading.Thread(target=c.stop) for c in children]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        write_stop_reason("user_stopped")
        console.print(f"[{GREEN}]all stopped[/]")

    sup = threading.Thread(target=_supervise, daemon=True, name="supervisor")
    sup.start()
    try:
        if _ui_wanted():
            open_console(stop_hook=_stop_all)      # Quit (7) falls through to the status view
        if stopped.is_set():
            return
        with Live(Panel(_status_table(children), title="Running   [Ctrl+C] Stop All", border_style=GREEN),
                  console=console, refresh_per_second=1) as live:
            while not stopped.is_set():
                live.update(Panel(_status_table(children), title="Running   [Ctrl+C] Stop All", border_style=GREEN))
                time.sleep(2)
    except KeyboardInterrupt:
        _stop_all()


# ── sign in to X ─────────────────────────────────────────────────────────────
def alert_channels_answer(cur: dict) -> str | None:
    """Pick ALERT_CHANNELS. Status first; q / back / esc keeps the current value."""
    am = _alerts()
    if am is None:
        v = Prompt.ask("Alert Channels (comma list)", default=str(cur.get("ALERT_CHANNELS") or ""))
        return v.strip() or None
    console.print(alerts_status_table(cur))
    now = ",".join(am.channels(cur)) or "off"
    names = list(am.CHANNELS)
    console.print(f"[dim]Pick any of {', '.join(names)} (comma separated), or 'off'. Enter keeps '{now}'. "
                  "iMessage comes with the Mac version.[/]")
    while True:
        v = Prompt.ask("Alert Channels", default=now).strip().lower()
        if v in ("q", "back", "esc", "\x1b"):
            raise CancelInput()
        picked = [x.strip() for x in v.replace(";", ",").split(",") if x.strip()]
        bad = [x for x in picked if x not in names + ["off", "none"]]
        if bad:
            console.print(f"[red]unknown: {', '.join(bad)}[/] (imessage = Mac version, later)")
            continue
        out = "off" if (not picked or "off" in picked or "none" in picked) else ",".join(dict.fromkeys(picked))
        return None if out == now else out


def alerts_status_table(env: dict) -> Table:
    """Status-first table of alert channels. Never shows a value."""
    am = _alerts()
    t = Table(box=box.SIMPLE_HEAD, header_style=f"bold {PURPLE}", expand=False)
    for c in ("Status", "#", "Channel", "Needs"):
        t.add_column(c)
    if am is None:
        t.add_row(Text("Unavailable", style="red"), "", "alerts.py missing", "")
        return t
    for i, st in enumerate(am.status(env), 1):
        style = (f"bold {GREEN}" if st["on"] and st["configured"] else "bold red" if st["on"] else "dim")
        t.add_row(Text(st["status"], style=style), str(i), st["label"],
                  ", ".join(st["missing"]) if st["missing"] else ("-" if st["keys"] else st.get("note", "")))
    return t


def alerts_step(env: dict | None = None, ask_first: bool = False, opener=None) -> dict:
    """Wizard / Settings step: status first, then a test message per channel. q / esc goes back."""
    am = _alerts()
    env = read_env() if env is None else env
    if am is None:
        console.print("[red]alerts.py missing[/]"); return {}
    console.print(Panel("Alerts. Status first; send a test message per channel. q / back / esc goes back.",
                        border_style=PURPLE, title="Alerts"))
    console.print(alerts_status_table(env))
    if ask_first and not Confirm.ask("Send a test message now?", default=True):
        return {}
    rows = am.status(env)
    done = {}
    while True:
        v = Prompt.ask("Test which channel # (a = all on channels, q = back)", default="q").strip().lower()
        if v in ("q", "back", "esc", "\x1b", ""):
            return done
        if v == "a":
            pick = [r["channel"] for r in rows if r["on"]]
        elif v.isdigit() and 1 <= int(v) <= len(rows):
            pick = [rows[int(v) - 1]["channel"]]
        else:
            console.print("[red]pick a number, a, or q[/]"); continue
        for ch in pick:
            if ch not in am.CHANNELS:
                console.print("[dim]iMessage comes with the Mac version.[/]"); continue
            if am.missing(ch, env):
                console.print(f"[yellow]{am.CHANNELS[ch][0]}: needs {', '.join(am.missing(ch, env))}[/]"); continue
            res = am.test(ch, env_override=env, opener=opener)
            for k, st in res.items():
                lab = am.CHANNELS.get(k, ("Telegram, Backup Alert Bot",))[0] if k in am.CHANNELS else "Telegram, Backup Alert Bot"
                console.print(f"Test, {lab}: " + (f"[{GREEN}]sent[/]" if st == "sent" else f"[red]{st}[/]"))
                for code, hint in am.HINTS.items():
                    if code in st:
                        console.print(f"[dim]{hint}[/]")
            done.update(res)
            log("alerts test: " + ", ".join(f"{k}={'sent' if v2 == 'sent' else 'error'}" for k, v2 in res.items()))


def telegram_test(env: dict | None = None, opener=None) -> dict:
    """Send one test message to TELEGRAM_CHAT_ID through the main bot and, if set, the backup alert bot.
    Returns {"main": sent|error..., "backup": ...}. Never prints or logs a token."""
    import urllib.parse
    import urllib.request
    env = read_env() if env is None else env
    chat = str(env.get("TELEGRAM_CHAT_ID") or "").strip()
    bots = {"main": str(env.get("TELEGRAM_TOKEN") or "").strip(),
            "backup": str(env.get("X_NOTIFY_TELEGRAM_TOKEN") or "").strip()}
    out = {}
    if not chat or not bots["main"]:
        console.print("[yellow]Telegram test: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must both be set[/]")
        return {"main": "missing"}
    opener = opener or urllib.request.urlopen
    for name, tok in bots.items():
        if not tok:
            continue
        text = f"Meme Sniper test message ({name} bot). If you see this, alerts reach this chat."
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        try:
            with opener(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=15) as r:
                j = json.loads(r.read().decode("utf-8", "replace") or "{}")
            out[name] = "sent" if j.get("ok") else f"error: {str(j.get('description') or 'not ok')[:80]}"
        except Exception as e:
            code = getattr(e, "code", None)
            out[name] = f"error: HTTP {code}" if code else f"error: {type(e).__name__}"
    for name, st in out.items():
        label = "main bot" if name == "main" else "backup alert bot"
        console.print(f"Telegram test, {label}: " + (f"[{GREEN}]sent[/]" if st == "sent" else f"[red]{st}[/]"))
        if st.startswith("error: HTTP 401"):
            console.print("[dim]401 = the token is wrong[/]")
        elif st.startswith("error: HTTP 400") or "chat not found" in st:
            console.print("[dim]400 / chat not found = wrong chat ID, or you have not sent your bot a message yet[/]")
        elif st.startswith("error: HTTP 403"):
            console.print("[dim]403 = the bot is not in that chat or was blocked[/]")
    log("telegram test: " + ", ".join(f"{k}={'sent' if v == 'sent' else 'error'}" for k, v in out.items()))
    return out


def _x_session():
    try:
        sys.path.insert(0, str(SUB))
        import x_session
        return x_session
    except Exception:
        return None


def x_status_line(env: dict | None = None) -> tuple:
    """(state, text). Same profile and logic as the scraper and the console (x_session.py)."""
    xs = _x_session()
    if xs is None:
        return "missing", "X: status unavailable (x_session.py missing)"
    st = xs.status(read_env() if env is None else env)
    return st["state"], "X: " + xs.describe(st)


def sign_in_x() -> None:
    """Verify first. Keep (default) does nothing: no pause, no browser. Only switch / sign in opens it."""
    xs = _x_session()
    if xs is None:
        console.print("[red]x_session.py not found[/]"); return
    scraper = SUB / "agent_scraper.py"
    if not scraper.exists():
        console.print("[red]agent_scraper.py not found[/]"); return
    env = read_env()
    st = xs.status(env)
    col = {"verified": GREEN, "unverified": "yellow", "expired": "yellow"}.get(st["state"], "red")
    console.print(Text("X: " + xs.describe(st), style=f"bold {col}"))
    console.print(f"[dim]profile: {st['profile']}\n{st['detail']}[/]")
    if st["state"] in ("verified", "unverified"):
        console.print("1 Keep (default)   2 Switch account / re-login")
        if choose(console, "choose", ["1", "2"], "1") == "1":
            console.print("[dim]kept; nothing paused, no browser opened[/]")
            return
    elif not Confirm.ask("Sign in to X now (opens a browser window)?", default=True):
        return
    paused = False
    if xs.scraper_running():
        if not Confirm.ask("The scraper is using this X session; pause it while you sign in?", default=True):
            return
        console.print("[dim]waiting for the scraper to park (browser closed)...[/]")
        ok, why = xs.pause_scraper()
        if not ok:
            console.print(f"[yellow]{why}[/]"); return
        paused = True
    try:
        try:
            import playwright  # noqa: F401
        except ImportError:
            console.print("[yellow]installing playwright...[/]")
            subprocess.call([sys.executable, "-m", "pip", "install", "playwright"])
        console.print("[dim]making sure Playwright Chromium is installed...[/]")
        subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
        console.print(f"[{GREEN}]opening the scraper's profile ({st['profile']}). Sign in, then press Enter in this window.[/]")
        subprocess.call([sys.executable, str(scraper), "--login"], cwd=str(SUB))
        log("x login flow ran")
    finally:
        if paused:
            xs.resume_scraper()
            console.print(f"[{GREEN}]scraper resumed[/]")
    st = xs.status(read_env())
    console.print(Text("X now: " + xs.describe(st), style="bold " + (GREEN if st["state"] == "verified" else "yellow")))


# ── dashboard ────────────────────────────────────────────────────────────────
SOL_MINT = "So11111111111111111111111111111111111111112"
_PRICE = {"at": 0.0, "prices": {}, "sol_usd": None, "sol_bal": None, "bal_at": 0.0, "err": None}
DEX_MIN_INTERVAL_S = float(_envv("DASH_DEX_MIN_INTERVAL_S", "30"))   # 1 batched call per interval
RPC_MIN_INTERVAL_S = float(_envv("DASH_RPC_MIN_INTERVAL_S", "120"))   # dashboard balance refresh (was 30s; HELIUS_AUDIT)


def _http_json(url: str, payload=None, timeout: float = 10.0):
    import urllib.request
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "meme-sniper-dashboard",
                                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _refresh_prices(mints: list, env: dict) -> None:
    """Background refresh: one DexScreener batch (<=30 mints incl. SOL) and one getBalance."""
    now = time.time()
    if now - _PRICE["at"] >= DEX_MIN_INTERVAL_S:
        _PRICE["at"] = now
        try:
            want = [SOL_MINT] + [m for m in mints if m][:29]
            j = _http_json("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(want))
            best = {}
            for p in (j or {}).get("pairs") or []:
                m = (p.get("baseToken") or {}).get("address")
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                if m and (m not in best or liq > best[m][1]):
                    best[m] = (float(p.get("priceUsd") or 0), liq)
            _PRICE["prices"].update({m: v[0] for m, v in best.items()})
            _PRICE["sol_usd"] = _PRICE["prices"].get(SOL_MINT) or _PRICE["sol_usd"]
            _PRICE["err"] = None
        except Exception as e:
            _PRICE["err"] = f"prices: {type(e).__name__}"
    addr = env.get("HOT_WALLET_ADDRESS")
    if addr and now - _PRICE["bal_at"] >= RPC_MIN_INTERVAL_S:
        _PRICE["bal_at"] = now
        try:
            rpc = env.get("RPC_URL") or "https://api.mainnet-beta.solana.com"
            j = _http_json(rpc, {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]})
            _PRICE["sol_bal"] = j["result"]["value"] / 1e9
        except Exception as e:
            _PRICE["err"] = f"balance: {type(e).__name__}"


def _today_rows(path: Path, keys=("at", "ts", "timestamp", "logged_at", "declined_at")) -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                stamp = next((str(r.get(k)) for k in keys if r.get(k)), "")
                if stamp.startswith(today) or (stamp.replace(".", "").isdigit() and
                                               datetime.fromtimestamp(float(stamp)).strftime("%Y-%m-%d") == today):
                    out.append(r)
    except Exception:
        pass
    return out


def _f(v, nd=4, pre="", suf=""):
    try:
        return f"{pre}{float(v):,.{nd}f}{suf}"
    except (TypeError, ValueError):
        return "-"


def _heartbeats() -> list:
    rows = []
    eng = _read_json(ENGINE_HB, {}) or {}
    for name, r in ((eng.get("components") or {}) if isinstance(eng, dict) else {}).items():
        rows.append((f"meme_sniper.{name}", str((r or {}).get("status") or "?"), (r or {}).get("last_update")))
    for p in sorted(BOT_LOGS.glob("*heartbeat*.json")) if BOT_LOGS.exists() else []:
        if p == ENGINE_HB:
            continue
        rows.append((p.stem.replace("_heartbeat", ""), "file", datetime.fromtimestamp(p.stat().st_mtime).isoformat()))
    return rows


def _hb_color(status: str, stamp) -> str:
    try:
        age = time.time() - datetime.fromisoformat(str(stamp)).timestamp()
    except Exception:
        age = 1e9
    if status in ("stale", "error", "dead") or age > 1800:
        return "red"
    if age > 600 or status in ("starting", "degraded"):
        return "yellow"
    return GREEN


def dashboard_view(env: dict) -> Group:
    paper = _on((env or {}).get("SNIPER_PAPER_MODE"))
    logs = BOT_LOGS / "paper" if paper else BOT_LOGS
    positions = _read_json(logs / "positions.json", {}) or {}
    positions = positions if isinstance(positions, dict) else {}
    holdings = _read_json(logs / "holdings.json", {}) or {}
    holdings = holdings if isinstance(holdings, dict) else {}
    own = ((_read_json(logs / "own_launches.json", {}) or {}).get("launches") or {})
    pnl = _read_json(logs / "pnl.json", []) or []
    sol_usd = _PRICE["sol_usd"]
    # top line
    bal = _PRICE["sol_bal"]
    if paper:
        bal = (_read_json(logs / "paper_wallet.json", {}) or {}).get("sol", bal)
    top = Table.grid(padding=(0, 3))
    if paper:
        top.add_row(Text(" PAPER MODE - simulated trades, no real transactions (bot_logs/paper/) ",
                         style="bold black on yellow"))
    top.add_row(Text(f"wallet {_f(bal, 4)} SOL", style=f"bold {GREEN}"),
                Text(f"~ {_f((bal or 0) * sol_usd, 2, '$')}" if bal is not None and sol_usd else "~ -"),
                Text(f"SOL {_f(sol_usd, 2, '$')}"),
                Text(datetime.now().strftime("%H:%M:%S"), style="dim"))
    # positions
    pt = Table(title="Open Positions", box=box.SIMPLE_HEAD, header_style=f"bold {PURPLE}", expand=True)
    for c in ("token", "entry", "now", "PnL %", "PnL $", "SL/TP", "mode"):
        pt.add_column(c)
    for mint, p in list(positions.items())[:20]:
        if not isinstance(p, dict):
            continue
        entry = p.get("entry_price")
        now = _PRICE["prices"].get(mint) or p.get("last_price_usd")
        try:
            pct = (float(now) - float(entry)) / float(entry) * 100
            usd = pct / 100 * float(p.get("amount_sol") or 0) * (sol_usd or 0)
        except Exception:
            pct = usd = None
        ap = p.get("armed_protection") or {}
        armed = ("SL " if ap.get("sl_pct") is not None else "") + ("TP" if ap.get("tp_pct") is not None else "")
        tag = " [own]" if p.get("own_launch") else ""
        pt.add_row(f"{p.get('ticker', '?')}{tag}", _f(entry, 8), _f(now, 8),
                   Text(_f(pct, 1, suf="%"), style=GREEN if (pct or 0) >= 0 else "red"),
                   _f(usd, 2, "$"), armed or "no", str(p.get("mode") or "-"))
    if not positions:
        pt.add_row("no open positions", "", "", "", "", "", "")
    # treasury
    tt = Table(title="Treasury / Holdings", box=box.SIMPLE_HEAD, header_style=f"bold {PURPLE}", expand=True)
    for c in ("token", "class", "value $", "tag"):
        tt.add_column(c)
    for mint, h in list(holdings.items())[:12]:
        if not isinstance(h, dict):
            continue
        tt.add_row(str(h.get("ticker") or mint[:6]), str(h.get("class") or "-"),
                   _f(h.get("est_usd") or h.get("usd_value"), 2, "$"),
                   "own_launch" if (h.get("own_launch") or mint in own) else "")
    for mint, r in own.items():
        if mint not in holdings:
            tt.add_row(str(r.get("ticker") or mint[:6]), str(r.get("status") or "-"), "-", "own_launch")
    if not holdings and not own:
        tt.add_row("nothing held", "", "", "")
    # pnl + activity
    ledger = _today_rows(BOT_LOGS / "execution_ledger.jsonl")
    buys = sum(1 for r in ledger if r.get("event") in ("buy", "override_buy"))
    today_pnl = sum(float(r.get("pnl_sol") or 0) for r in ledger if r.get("event") == "sell")
    total_pnl = sum(float(r.get("pnl_sol") or 0) for r in pnl if isinstance(r, dict))
    declines = len(_today_rows(BOT_LOGS / "decline_log.jsonl"))
    st = Table.grid(padding=(0, 3))
    st.add_row(Text(f"today {today_pnl:+.4f} SOL", style=GREEN if today_pnl >= 0 else "red"),
               Text(f"total {total_pnl:+.4f} SOL", style=GREEN if total_pnl >= 0 else "red"),
               Text(f"buys today {buys}"), Text(f"declines today {declines}"))
    # heartbeats
    ht = Table(title="Components", box=box.SIMPLE_HEAD, header_style=f"bold {PURPLE}", expand=True)
    ht.add_column("component"); ht.add_column("status"); ht.add_column("last")
    for name, status, stamp in _heartbeats()[:16]:
        ht.add_row(name, Text(status, style=_hb_color(status, stamp)), str(stamp or "-")[11:19])
    if not _heartbeats():
        ht.add_row("no heartbeats yet", "", "")
    # cards + alerts
    cards = sorted((ROOT / "inbox").glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:5] \
        if (ROOT / "inbox").exists() else []
    alerts = sorted((ROOT / "owner_inbox").glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:3] \
        if (ROOT / "owner_inbox").exists() else []
    ct = Text("last cards: " + (", ".join(p.name[:48] for p in cards) or "none"), style="dim")
    at = Text("alerts: " + (", ".join(p.name[:48] for p in alerts) or "none"),
              style="yellow" if alerts else "dim")
    eng = _read_json(ENGINE_HB, {}) or {}
    extra = [Text(f"engine stop_reason: {eng.get('stop_reason')}", style="yellow")] if isinstance(eng, dict) and eng.get("stop_reason") else []
    if _PRICE["err"]:
        extra.append(Text(_PRICE["err"], style="dim"))
    return Group(Panel(top, title="Meme Sniper Dashboard (Read-Only)   [Q] Back  [Esc] Back",
                       border_style=GREEN, style=f"on {BG}"), pt, tt, st, ht, ct, at, *extra)


def _back_pressed() -> bool:
    """Non-blocking: q / esc (or a 'q' / 'back' line on non-Windows) pressed?"""
    try:
        if os.name == "nt":
            import msvcrt
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch in ("q", "Q", "\x1b", "b", "B"):
                    return True
            return False
        import select
        if sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.readline().strip().lower() in ("q", "back", "esc", "b")
    except KeyboardInterrupt:
        raise
    except Exception:
        pass
    return False


def dashboard(once: bool = False) -> None:
    env = read_env()

    def _bg():
        while not stop.is_set():
            pos = _read_json(BOT_LOGS / "positions.json", {}) or {}
            try:
                _refresh_prices(list(pos.keys()) if isinstance(pos, dict) else [], env)
            except Exception:
                pass
            stop.wait(5)

    stop = threading.Event()
    if once:
        console.print(dashboard_view(env)); return
    threading.Thread(target=_bg, daemon=True).start()
    try:
        with Live(dashboard_view(env), console=console, refresh_per_second=0.5, screen=False) as live:
            while True:
                for _ in range(20):
                    if _back_pressed():
                        return
                    time.sleep(0.2)
                live.update(dashboard_view(env))
    finally:
        stop.set()      # Ctrl+C is not caught here: it keeps its normal stop behaviour


# ── launch a token ───────────────────────────────────────────────────────────
def guided_launch() -> None:
    env = read_env()
    cap = float(env.get("LAUNCH_MAX_DEV_BUY_SOL") or os.environ.get("LAUNCH_MAX_DEV_BUY_SOL") or 0.5)
    console.print(Panel("Guided launch request. Only for a real, useful public GitHub repo. "
                        f"Dev buy cap {cap} SOL. The rail checks the repo before anything is sent.",
                        border_style=PURPLE))
    req = {"id": f"launch-{datetime.now().strftime('%Y%m%d-%H%M%S')}", "action": "launch"}
    req["repo_url"] = Prompt.ask("Link your project's GitHub repo (optional, shows buyers there's a real project; blank = launch without one)", default="")
    req["name"] = Prompt.ask("Token name (max 32)")[:32]
    req["ticker"] = Prompt.ask("Ticker (1-10)").upper()[:10]
    req["description"] = Prompt.ask("Description")
    req["image"] = Prompt.ask("Image path or URL", default="examples/placeholder_logo.png")
    req["website"] = Prompt.ask("Website", default=req["repo_url"])
    req["twitter"] = Prompt.ask("X link", default="")
    req["telegram"] = Prompt.ask("Telegram link", default="")
    while True:
        try:
            dev = float(Prompt.ask("Dev buy SOL", default="0.1"))
        except ValueError:
            continue
        if 0 <= dev <= cap:
            break
        console.print(f"[red]must be between 0 and {cap}[/]")
    req["dev_buy_sol"] = dev
    req["dry_run"] = not Confirm.ask("Send live if the rail is armed?", default=True)
    req["requested_by"] = "user"
    console.print_json(json.dumps(req))
    if not Confirm.ask("Write this request?", default=False):
        console.print("not written"); return
    LAUNCH_REQ_DIR.mkdir(parents=True, exist_ok=True)
    p = LAUNCH_REQ_DIR / f"{req['id']}.json"
    _write_json(p, req)
    log(f"launch request written {p.name}")
    console.print(f"[{GREEN}]written[/] {p}. Results land in {JSON_RELAY / 'launch_results.json'}.")


# ── main ─────────────────────────────────────────────────────────────────────
def first_run_check() -> None:
    if apply_setup_json():
        return
    env = read_env()
    if env_complete(env):
        log("configured by agent (complete .env)")
        return
    if not sys.stdin.isatty():
        console.print("[yellow].env is incomplete and there is no terminal for the wizard. "
                      "Add setup.json or fill bots/.env. Helius daily cap: "
                      f"{helius_cap_label(env)} (set HELIUS_DAILY_CREDIT_CAP for your plan).[/]")
        log("first run: incomplete .env, no tty, wizard skipped")
        return
    console.print("[yellow]No complete .env yet, opening the setup wizard.[/]")
    try:
        wizard()
    except (EOFError, CancelInput):   # Ctrl+C is not back: it stops the launcher
        console.print("[yellow]wizard cancelled[/]")


_SMOKE_ENGINE = r'''
import asyncio, json, os, sys, re
from pathlib import Path
ws = Path(os.environ["WORKSPACE_DIR"])
sys.path.insert(0, str(ws / "bots"))
import meme_sniper as ms
res = {}
src = (ws / "bots" / "meme_sniper.py").read_text(encoding="utf-8")
# every sendTransaction in the engine goes through helius_rpc (the paper guard)
sends = [l for l in src.splitlines() if '"sendTransaction"' in l and not l.strip().startswith("#")]
res["sends_via_helius_rpc"] = all(("helius_rpc(" in l) or ("method ==" in l) or ("_PAPER_BLOCKED" in l)
                                  or l.strip().startswith(('"sendTransaction"', "eps =")) for l in sends)
res["paper_mode"] = ms.PAPER_MODE
calls = []
real = ms.helius_rpc
async def spy(method, params, **k):
    calls.append(method)
    return await real(method, params, **k)
ms.helius_rpc = spy
class NoNet:
    async def post(self, *a, **k): raise AssertionError("network post in paper swap")
async def nonet(): return NoNet()
ms._get_dex_client = nonet
async def dec(m): return 6
ms.get_mint_decimals = dec
async def main():
    r = await real("sendTransaction", ["AAAA", {}])
    res["send_refused"] = r is None and ms._PAPER_BLOCKED_SENDS["n"] == 1
    w0 = ms._paper_wallet_load()["sol"]
    q = {"inputMint": ms._PAPER_SOL_MINT, "outputMint": "Mint1111pump", "inAmount": "100000000", "outAmount": "5000000"}
    b = await ms.jupiter_swap_execute(q, priority_fee_lamports=10000, track_meta={"mint": "Mint1111pump"})
    bal = await ms.get_wallet_token_balances()
    s = await ms.jupiter_swap_execute({"inputMint": "Mint1111pump", "outputMint": ms._PAPER_SOL_MINT,
                                       "inAmount": str(int(bal[0]["amount_raw"])), "outAmount": "90000000"},
                                      priority_fee_lamports=10000, track_meta={"mint": "Mint1111pump"})
    w1 = await ms._wallet_sol_balance()
    res["paper_buy_sell"] = b.get("paper") and s.get("paper") and b["tx_signature"].startswith("PAPER-") and w1 < w0
    res["no_send_called"] = "sendTransaction" not in calls
    res["paper_files"] = ms.PAPER_TRADES_LOG.exists() and ms.POSITIONS_FILE.parent.name == "paper"
asyncio.run(main())
sys.path.insert(0, str(ws / "bots" / "sub-bots"))
import launch_rail
res["launch_dry"] = launch_rail._rail_live_env() is False
try:
    launch_rail.send(None); res["launch_send_refused"] = False
except RuntimeError as e:
    res["launch_send_refused"] = "PAPER" in str(e)
# wizard keys + learning
ms.ensure_filter_file_initialized(); ms.reload_active_overrides_from_filter_file()
res["unset_unchanged"] = ms._base_size_cap() == ms.SIZE_CAP_BASE_SOL and ms._size_tier_factor() == 1.0
(ws / "bots" / ".env").write_text("SNIPER_BUY_SIZE_SOL=0.2\nSNIPER_DEFAULT_SL_PCT=25\nSNIPER_LEARNING_MODE=1\n", encoding="utf-8")
seeded = ms._seed_wizard_knobs_from_env(force=True)
res["env_seeded"] = set(seeded) == {"SNIPER_BUY_SIZE_SOL", "SNIPER_DEFAULT_SL_PCT", "SNIPER_LEARNING_MODE"} \
    and ms._base_size_cap() == 0.2 and ms._tier_cap("SIZE_CAP_TIER1_SOL", 2.0) == 0.4
ms.apply_filter_change("SNIPER_BUY_SIZE_SOL", 0.3, by="agent", reason="smoke")
res["agent_edit_kept"] = ms._seed_wizard_knobs_from_env() == [] and ms._base_size_cap() == 0.3
ms.apply_filter_change("SNIPER_LEARN_REST", False, by="smoke", reason="smoke")
r0 = ms._learning_step()          # start: records started_at, waits for trades
res["learning_waits"] = r0["status"].startswith("waiting_for_trades")
from datetime import datetime as _dt, timedelta as _td
_later = (_dt.now() + _td(seconds=90)).isoformat(timespec="seconds")
rows = [{"closed_at": _later, "amount_sol": 0.1, "pnl_pct": 30, "pnl_sol": 0.03, "exit_type": "agent_armed_take_profit"}
        for _ in range(12)]
ms.AUTOPSY_REPORTS_FILE.write_text(json.dumps(rows), encoding="utf-8")
r1 = ms._learning_step(force=True)
res["r1"] = r1["status"]
size = ms._owner_buy_size_sol()
k = json.loads(ms.MEME_SNIPER_FILTER_FILE.read_text(encoding="utf-8"))["knobs"]["SNIPER_BUY_SIZE_SOL"]
res["learning_bounded"] = r1["status"] == "step" and 0.3 < size <= 0.33 + 1e-9 and k["history"][-1]["by"] == "learning_mode" \
    and bool(k["history"][-1]["reason"]) and ms.LEARNING_LOG.exists()
r2 = ms._learning_step()
res["learning_rests"] = r2["status"] == "resting"
(ws / "rules" / "rules.md").write_text("## Max size\n0.31 SOL\n", encoding="utf-8")
ms._OWNER_RULES_CACHE["mtime"] = None
ms.LEARNING_STATE_FILE.write_text("{}", encoding="utf-8")
ms._learning_step(force=True)
res["rules_cap"] = ms._owner_buy_size_sol() <= 0.31
ms.apply_filter_change("SNIPER_LEARNING_MODE", False, by="smoke", reason="smoke")
keep = ms._owner_buy_size_sol()
res["off_keeps_values"] = ms._learning_step(force=True)["status"] == "off" and ms._owner_buy_size_sol() == keep
print("ENGINE_SMOKE " + json.dumps(res))
'''


def _smoke_paper_learning() -> bool:
    """Paper mode + wizard keys + learning, on a throwaway copy of the bots (no network sends possible)."""
    import shutil, subprocess, tempfile
    ws = Path(tempfile.mkdtemp(prefix="sniper_smoke_ws_"))
    try:
        shutil.copytree(BOTS, ws / "bots", ignore=shutil.ignore_patterns("__pycache__", ".env", "tuner", "*.log"))
        (ws / "rules").mkdir(exist_ok=True)
        (ws / "bots" / ".env").write_text("", encoding="utf-8")
        envv = {k: v for k, v in os.environ.items() if not k.startswith(("SNIPER_", "LAUNCH_", "HOT_WALLET", "RPC_"))}
        envv.update(WORKSPACE_DIR=str(ws), SNIPER_PAPER_MODE="1", SNIPER_PAPER_START_SOL="1.0",
                    RPC_URL="http://127.0.0.1:9", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-c", _SMOKE_ENGINE], cwd=str(ws), env=envv,
                           capture_output=True, text=True, timeout=240)
        line = next((l for l in r.stdout.splitlines() if l.startswith("ENGINE_SMOKE ")), None)
        if not line:
            console.print(f"[red]engine smoke produced no result (rc={r.returncode}): {(r.stderr or r.stdout)[-600:]}[/]")
            return False
        res = json.loads(line[len("ENGINE_SMOKE "):])
        res.pop("r1", None) if res.get("learning_bounded") else None
        ok = all(v is True for v in res.values())
        console.print(f"smoke: paper+learning {json.dumps(res)} -> {'OK' if ok else 'FAIL'}")
        # wizard: paper defaults off; leaving paper needs LIVE typed
        w = paper_mode_answer({}, {}) == "0" and paper_mode_answer({"SNIPER_PAPER_MODE": "1"}, {"SNIPER_PAPER_MODE": "0"}) == "1" \
            and paper_mode_answer({"SNIPER_PAPER_MODE": "1"}, {"SNIPER_PAPER_MODE": "0", "SNIPER_CONFIRM_LIVE": "LIVE"}) == "0"
        console.print(f"smoke: paper wizard opt-in/confirm -> {'OK' if w else 'FAIL'}")
        return ok and w
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def _smoke_llm_choice() -> bool:
    """LLM_MAIN / LLM_FALLBACK: unselected providers are never called (mocked HTTP, no network);
    legacy order unchanged when LLM_MAIN is unset."""
    import asyncio
    import httpx
    if _llmp is None:
        console.print("[red]llm_providers not importable[/]"); return False
    saved = dict(os.environ)
    res = {}
    hits = []

    def handler(req):
        hits.append(req.url.host)
        if "anthropic" in req.url.host:
            return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    try:
        for k in list(os.environ):
            if k.startswith(("LLM_", "VISION_PROVIDER", "GROK_", "XAI_", "OPENAI_", "ANTHROPIC_", "OLLAMA_")):
                os.environ.pop(k)
        os.environ.update(GROK_API_KEY="g" * 8, OPENAI_API_KEY="o" * 8, OPENAI_MODEL="m",
                          ANTHROPIC_API_KEY="a" * 8, ANTHROPIC_MODEL="m")
        res["legacy_order"] = _llmp.brain_order() == ["grok", "openai", "anthropic", "ollama"]
        os.environ.update(LLM_MAIN="openai", LLM_FALLBACK="none")
        res["order"] = _llmp.brain_order() == ["openai"] and _llmp.order("VISION_PROVIDER_ORDER") == ["openai"]
        res["cfg_off"] = not _llmp.cfg("grok") and not _llmp.cfg("anthropic") and bool(_llmp.cfg("openai"))
        res["any_configured"] = _llmp.any_configured() and not _llmp.any_configured(skip=("openai",))

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                for p in _llmp.PROVIDERS:
                    await _llmp.generate(p, "hi", client=c)
        asyncio.run(run())
        res["only_main_called"] = hits == ["api.openai.com"]
        sel = _llmp.apply_choice()
        res["apply"] = sel == ["openai"] and "GROK_API_KEY" not in os.environ and \
            "ANTHROPIC_API_KEY" not in os.environ and os.environ.get("OLLAMA_ENABLED") == "false" and \
            os.environ.get("LLM_PROVIDER_ORDER") == "openai"
        os.environ.update(GROK_API_KEY="g" * 8, LLM_MAIN="grok")
        os.environ.pop("LLM_FALLBACK", None)
        sel = _llmp.apply_choice()
        res["default_fallback_ollama"] = sel == ["grok", "ollama"] and os.environ.get("OLLAMA_ENABLED") == "true"
        res["env_complete"] = env_complete({"LLM_MAIN": "anthropic", "LLM_FALLBACK": "none", "GROK_API_KEY": "x",
                                            "HOT_WALLET_PRIVATE_KEY": "x", "RPC_URL": "x"}) is False
    except Exception as e:
        res["error"] = str(e)[:120]
    finally:
        os.environ.clear(); os.environ.update(saved)
    ok = all(v is True for v in res.values())
    console.print(f"smoke: llm main/fallback {json.dumps(res)} -> {'OK' if ok else 'FAIL'}")
    return ok


def _smoke_alerts() -> bool:
    """Alert dispatcher: channel selection, per-caller Telegram payloads (unchanged), backup bot,
    Discord webhook / ntfy / email transports, email throttle, and NO secret in bot_logs/alerts.log."""
    import io, tempfile
    am = _alerts()
    if am is None:
        console.print("[red]smoke alerts: alerts.py missing[/]"); return False
    calls = []

    class _R(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, timeout=15):
        calls.append((req.full_url, dict(req.header_items()), req.data))
        return _R(b'{"ok": true}')

    sent_mail = []

    class _S:
        def __init__(self, h, p): self.h, self.p = h, p
        def starttls(self, context=None): pass
        def login(self, u, pw): pass
        def send_message(self, m): sent_mail.append(m)
        def quit(self): pass

    secrets = {"TELEGRAM_TOKEN": "111:MAINSECRET", "X_NOTIFY_TELEGRAM_TOKEN": "222:BACKUPSECRET",
               "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/HOOKSECRET",
               "SMTP_PASS": "MAILSECRET", "NTFY_TOKEN": "NTFYSECRET"}
    env = {**secrets, "TELEGRAM_CHAT_ID": "42", "SMTP_HOST": "smtp.example", "SMTP_USER": "u@example",
           "ALERT_EMAIL_TO": "me@example", "NTFY_TOPIC": "sniper-topic-x", "ALERT_EMAIL_MIN_INTERVAL_S": "60"}
    old_root = am._ROOT
    tmp = Path(tempfile.mkdtemp())
    am._ROOT = tmp
    ok = True
    try:
        ok &= am.channels({"TELEGRAM_TOKEN": "x", "TELEGRAM_CHAT_ID": "1"}) == ["telegram"]      # blank = old behaviour
        ok &= am.channels({}) == [] and am.channels({**env, "ALERT_CHANNELS": "off"}) == []
        ok &= am.channels({"ALERT_CHANNELS": "ntfy, discord,imessage,bogus"}) == ["ntfy", "discord"]
        r = am.send_sync("<b>fill</b> X", source="engine", silent=True, only=["telegram"], env_override=env, opener=fake)
        j = json.loads(calls[-1][2])
        ok &= r == {"telegram": "sent"} and "MAINSECRET" in calls[-1][0] and "parse_mode" not in j \
            and j["disable_notification"] is True and j["disable_web_page_preview"] is True and j["chat_id"] == "42"
        am.send_sync("warden", source="warden", html=True, telegram_token=env["X_NOTIFY_TELEGRAM_TOKEN"],
                     only=["telegram"], env_override=env, opener=fake)
        ok &= "BACKUPSECRET" in calls[-1][0] and json.loads(calls[-1][2]).get("parse_mode") == "HTML"
        am.send_sync("launch", source="launch_rail", tg_plain=True, only=["telegram"], env_override=env, opener=fake)
        ok &= set(json.loads(calls[-1][2])) == {"chat_id", "text"}
        am.send_sync("<b>hi</b> &amp; bye", source="t", only=["discord"], env_override=env, opener=fake)
        ok &= json.loads(calls[-1][2]) == {"content": "hi & bye"}
        am.send_sync("<b>push</b>", source="t", silent=True, only=["ntfy"], env_override=env, opener=fake)
        ok &= calls[-1][0].endswith("/sniper-topic-x") and calls[-1][2] == b"push" \
            and calls[-1][1].get("Priority") == "low" and calls[-1][1].get("Authorization") == "Bearer NTFYSECRET"
        am._EMAIL_STATE.update(last=0.0, suppressed=0)
        r1 = am.send_sync("mail one", source="t", only=["email"], env_override=env, smtp_factory=_S)
        r2 = am.send_sync("mail two", source="t", only=["email"], env_override=env, smtp_factory=_S)
        ok &= r1 == {"email": "sent"} and r2 == {"email": "throttled"} and len(sent_mail) == 1
        def boom(req, timeout=15):
            raise RuntimeError("https://api.telegram.org/bot111:MAINSECRET/sendMessage failed")
        r = am.send_sync("x", source="t", only=["telegram"], env_override=env, opener=boom)
        ok &= r["telegram"] == "failed: RuntimeError"
        r = am.send_sync("x", source="t", only=["discord"], env_override={"ALERT_CHANNELS": "discord"}, opener=fake)
        ok &= r["discord"].startswith("failed: missing")
        t = am.test("telegram", env_override=env, opener=fake)
        ok &= t == {"telegram": "sent", "telegram_backup": "sent"}
        logtxt = (tmp / "bot_logs" / "alerts.log").read_text(encoding="utf-8")
        leak = [k for k, v in secrets.items() if v in logtxt or v.split("/")[-1] in logtxt] + \
            [x for x in ("42 |", "me@example") if x in logtxt]
        ok &= not leak and "| telegram | sent |" in logtxt and "| email | throttled |" in logtxt
        st = {x["channel"]: x["status"] for x in am.status({**env, "ALERT_CHANNELS": "telegram,discord"})}
        ok &= st["telegram"] == "On" and st["discord"] == "On" and st["email"] == "Off (Configured)" \
            and st["imessage"].startswith("Later")
        ok &= bool(alerts_status_table(env).row_count)
        miss = setup_missing({"HOT_WALLET_PRIVATE_KEY": "x", "HOT_WALLET_ADDRESS": "x", "RPC_URL": "x",
                              "PINATA_JWT": "x", "ALERT_CHANNELS": "discord"})
        ok &= "TELEGRAM_TOKEN" not in miss and any(m.startswith("alerts: Discord Webhook") for m in miss)
    except Exception as e:
        console.print(f"[red]smoke alerts error: {type(e).__name__}: {e}[/]")
        ok = False
    finally:
        am._ROOT = old_root
    console.print(f"smoke alerts: {'ok' if ok else 'FAIL'}")
    return bool(ok)


def _smoke_telegram_test() -> bool:
    """Mocked HTTP: main + backup bots each get one sendMessage to the same chat; tokens never printed."""
    import io as _io
    calls = []

    class _R(_io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, timeout=0):
        calls.append((req.full_url, req.data))
        return _R(b'{"ok": true}')
    env = {"TELEGRAM_TOKEN": "111:MAINSECRET", "TELEGRAM_CHAT_ID": "42", "X_NOTIFY_TELEGRAM_TOKEN": "222:BACKUPSECRET"}
    rec = Console(file=_io.StringIO(), width=120, color_system=None)
    global console
    old, console = console, rec
    try:
        r1 = telegram_test(env, opener=fake)
        r2 = telegram_test({k: v for k, v in env.items() if k != "X_NOTIFY_TELEGRAM_TOKEN"}, opener=fake)
        r3 = telegram_test({"TELEGRAM_TOKEN": "x"}, opener=fake)
    finally:
        console = old
    out = rec.file.getvalue()
    res = {"both_sent": r1 == {"main": "sent", "backup": "sent"}, "main_only": r2 == {"main": "sent"},
           "missing_chat": r3 == {"main": "missing"}, "calls": len(calls) == 3,
           "same_chat": all(b"chat_id=42" in d for _, d in calls),
           "no_token_printed": "SECRET" not in out}
    ok = all(res.values())
    console.print(f"smoke: telegram test {json.dumps(res)} -> {'OK' if ok else 'FAIL'}")
    return ok


def _smoke_labels() -> bool:
    """Every filter knob, template key, wizard key and console setting has a label, section and a known unit."""
    L = _labels()
    want = set()
    fj = _read_json(BOTS / "tuner" / "meme_sniper_filter.json", {}) or \
        _read_json(BOTS / "tuner" / "meme_sniper_filter.default.json", {}) or {}
    want |= set((fj.get("knobs") or {}).keys())
    for ln in (BOTS / ".env.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", ln)
        if m:
            want.add(m.group(1))
    want |= {k for k, *_ in WIZARD_FIELDS + EXTRA_FIELDS}
    want |= {"ALERT_SOUND", "ALERT_TOAST", "ALERT_GOAL_HIT", "ALERT_SL_TP", "ALERT_WARDEN", "MUTED",
             "SNIPER_LEARN_COOLDOWN_H", "SNIPER_LEARN_MIN_TRADES", "SNIPER_LEARN_STEP_PCT"}
    missing = sorted(k for k in want if k not in L or not L[k].get("label") or not L[k].get("section"))
    unknown_unit = sorted(k for k in want if k in L and L[k].get("unit") in (None, "", "?"))
    ok = not missing and not unknown_unit
    console.print(f"smoke: labels {len(want)} keys, missing={missing[:8]} unit_unknown={unknown_unit[:8]} -> {'OK' if ok else 'FAIL'}")
    return ok


def _smoke_owner_commands() -> bool:
    """OWNER_COMMANDS defaults off, its rows follow the mode, the launcher adds it only when on,
    and Esc / q / back at the mode prompt keeps the old value."""
    import cancel_input as _ci
    ok = owner_commands_mode({}) == "off" and owner_commands_mode({"OWNER_COMMANDS": "TELEGRAM"}) == "telegram"
    ok &= owner_commands_mode({"OWNER_COMMANDS": "bogus"}) == "off"
    ok &= [k for k, *_ in _owner_cmd_rows({})] == ["OWNER_COMMANDS"]
    ok &= "OWNER_COMMANDS_TG_TOKEN" in [k for k, *_ in _owner_cmd_rows({"OWNER_COMMANDS": "telegram"})]
    ok &= "OWNER_COMMANDS_TG_TOKEN" not in [k for k, *_ in _owner_cmd_rows({"OWNER_COMMANDS": "file"})]
    ok &= "OWNER_COMMANDS" in _status_keys({})
    ok &= OWNER_COMMANDS_COMPONENT[0] not in [n for n, _ in COMPONENTS] and OWNER_COMMANDS_COMPONENT[1].exists()
    lbl = _fields()["OWNER_COMMANDS"][1]
    ok &= lbl.split(":")[0] == "Owner Commands"
    import rich.console as _rc
    old, orig_input = _ci.FORCE_PROMPT, _rc.Console.input
    _ci.FORCE_PROMPT = True
    try:
        for word in ("q", "back", "esc", "\x1b"):
            _rc.Console.input = lambda self, *a, _w=word, **k: _w
            try:
                owner_commands_answer({"OWNER_COMMANDS": "file"})
                ok = False                  # must raise CancelInput (back, nothing saved)
            except CancelInput:
                pass
        _rc.Console.input = lambda self, *a, **k: "telegram"
        ok &= owner_commands_answer({"OWNER_COMMANDS": "off"}) == "telegram"
        _rc.Console.input = lambda self, *a, **k: ""
        ok &= owner_commands_answer({"OWNER_COMMANDS": "file"}) is None     # Enter keeps the value
    finally:
        _ci.FORCE_PROMPT, _rc.Console.input = old, orig_input
    console.print(f"smoke: owner commands -> {'OK' if ok else 'FAIL'}")
    return bool(ok)


def _smoke_cancel_and_status() -> bool:
    """Cancel paths (q / back / esc) never save; Ctrl+C is not swallowed and saves nothing; status shows no values."""
    import io
    import tempfile
    import rich.console as _rc
    import cancel_input as _ci
    _ci.FORCE_PROMPT = True
    res = {}
    for word in ("q", "back", "\x1b"):
        try:
            Prompt.ask("x", stream=io.StringIO(word + "\n")); res[f"prompt_{word!r}"] = False
        except CancelInput:
            res[f"prompt_{word!r}"] = True
    try:
        Confirm.ask("x", stream=io.StringIO("q\n")); res["confirm_q"] = False
    except CancelInput:
        res["confirm_q"] = True
    res["normal_answer"] = Prompt.ask("x", stream=io.StringIO("abc\n")) == "abc"
    tmp = Path(tempfile.mkdtemp()) / ".env"
    tmp.write_text("HOT_WALLET_PRIVATE_KEY=SECRETVALUE123\nRPC_URL=https://secret.example/abc\n", encoding="utf-8")
    before = tmp.read_bytes()
    orig_input = _rc.Console.input
    for name, script in (("cancel_q", ["1", "q"]), ("ctrl_c_not_back", ["1", KeyboardInterrupt]),
                         ("cancel_at_save", ["3"])):
        it = iter(script)

        def fake(self, prompt="", *a, _it=it, **k):
            if "Save " in str(getattr(prompt, "plain", prompt)):
                return "q"
            v = next(_it, "")
            if v is KeyboardInterrupt:
                raise KeyboardInterrupt
            return v
        _rc.Console.input = fake
        try:
            r = wizard(tmp)
            res[name] = (r is None and tmp.read_bytes() == before) if name != "ctrl_c_not_back" else "swallowed"
        except KeyboardInterrupt:
            res[name] = name == "ctrl_c_not_back" and tmp.read_bytes() == before
        except Exception as e:
            res[name] = f"error {e}"
        finally:
            _rc.Console.input = orig_input
    # Enter everywhere + confirm save: a set key is never blanked
    it = iter(["3"] + [""] * 400)
    _rc.Console.input = lambda self, *a, _it=it, **k: next(_it, "")
    try:
        wizard(tmp)
    finally:
        _rc.Console.input = orig_input
    after = read_env(tmp)
    res["enter_keeps_set"] = after.get("HOT_WALLET_PRIVATE_KEY") == "SECRETVALUE123" and \
        after.get("RPC_URL") == "https://secret.example/abc"
    c = Console(file=io.StringIO(), width=120, color_system=None)
    c.print(wizard_status_table(read_env(tmp)))
    out = c.file.getvalue()
    res["status_no_values"] = "SECRETVALUE123" not in out and "secret.example" not in out and "Set" in out and "Missing" in out
    # provider choice: main/fallback rows first, unselected providers grey "off", never red
    penv = {"LLM_MAIN": "openai", "LLM_FALLBACK": "none", "OPENAI_API_KEY": "SKOPENAI999", "OPENAI_MODEL": "m",
            "GROK_API_KEY": "XAIKEY999", "ANTHROPIC_API_KEY": "ANTKEY999"}
    c = Console(file=io.StringIO(), width=140, color_system=None)
    c.print(wizard_status_table(penv))
    pout = c.file.getvalue()
    brain = [ln for ln in pout.splitlines() if "LLM_MAIN" in ln or "grok" in ln or "anthropic" in ln or "ANTHROPIC" in ln]
    res["brain_rows"] = ("LLM_MAIN" in pout and "LLM_FALLBACK" in pout and "off (key set)" in pout
                         and "ANTHROPIC_API_KEY" not in pout and "GROK_API_KEY" not in pout
                         and "OPENAI_API_KEY" in pout and "999" not in pout
                         and not any("Missing" in ln for ln in brain))
    res["brain_status_keys"] = _status_keys(penv)[:2] == [] or "GROK_API_KEY" not in _status_keys(penv)
    res["missing_names"] = "HOT_WALLET_ADDRESS" in setup_missing(read_env(tmp)) and "HOT_WALLET_PRIVATE_KEY" not in setup_missing(read_env(tmp))
    lc = _logo_art.__wrapped__ if hasattr(_logo_art, "__wrapped__") else None
    try:
        from PIL import Image
        im = Image.open(ROOT / "assets" / "meme_sniper_logo.png")
        res["logo_source_rgb"] = im.mode in ("RGB", "RGBA") and min(im.size) >= 512
    except Exception:
        res["logo_source_rgb"] = False
    ok = all(v is True for v in res.values())
    console.print(f"smoke: cancel+status {json.dumps(res)} -> {'OK' if ok else 'FAIL'}")
    return ok


def smoke() -> int:
    """Render banner, menu, empty dashboard; dry-write the wizard to a temp file."""
    import tempfile
    console.print(banner()); console.print(menu_panel())
    dashboard(once=True)
    tmp = Path(tempfile.mkdtemp()) / ".env"
    wizard(tmp, answers={"HOT_WALLET_PRIVATE_KEY": "x" * 10, "RPC_URL": "https://example.invalid",
                         "GROK_API_KEY": "k" * 8})
    env = read_env(tmp)
    ok = env_complete(env) and env.get("OWN_LAUNCH_MODE") == "hold"
    ok = ok and "TELEGRAM_TOKEN" in [k for k, *_ in WIZARD_FIELDS]
    wk = [k for k, *_ in WIZARD_FIELDS]
    ok = ok and all(k in wk for k in ("PINATA_JWT", "HELIUS_API_KEY", "LEDGER_ADDRESS", "LAUNCH_RAIL_LIVE"))
    ok = ok and env.get("LAUNCH_RAIL_LIVE") == "0"          # default stays off-chain
    ok = ok and env.get("HELIUS_DAILY_CREDIT_CAP") == str(HELIUS_FREE_CAP)   # no plan given -> Free cap
    rt = tmp.parent / "ws"
    rp = owner_rules_step({"max_size": "0.25 SOL", "banned": "political"}, interactive=False, root=rt)
    rtxt = rp.read_text(encoding="utf-8")
    ok = ok and "## Max size" in rtxt and "0.25 SOL" in rtxt and "## Loss limits" in rtxt
    ok = ok and env_complete({"HOT_WALLET_PRIVATE_KEY": "x", "RPC_URL": "y", "ANTHROPIC_API_KEY": "a", "ANTHROPIC_MODEL": "m"})
    ok = ok and not env_complete({"HOT_WALLET_PRIVATE_KEY": "x", "RPC_URL": "y", "OPENAI_API_KEY": "a"})
    console.print(f"smoke: rules file {'OK' if '0.25 SOL' in rtxt else 'FAIL'}, provider env check done")
    try:
        sys.path.insert(0, str(BOTS)); import sniper_ui  # noqa: F401  (import check; full test: sniper_ui.py --ui-smoke)
    except Exception as e:
        ok = False; console.print(f"[red]sniper_ui import failed: {e}[/]")
    try:  # chain plug-in point: registry loads solana by default, engine NOT imported
        import chains
        from chains.base import REQUIRED_METHODS
        ad = chains.load_adapters({})
        cok = list(ad) == ["solana"] and all(callable(getattr(ad["solana"], m, None)) for m in REQUIRED_METHODS)
        cok = cok and chains.load_adapters({"CHAIN_ADAPTERS": "solana,base"}).keys() == {"solana"}
        cok = cok and "meme_sniper" not in sys.modules
        ok = ok and cok
        console.print(f"smoke: chains adapters={list(ad)} -> {'OK' if cok else 'FAIL'}")
    except Exception as e:
        ok = False; console.print(f"[red]chains check failed: {e}[/]")
    try:      # convert_mode flip -> hold -> flip (keeps agent levels, clears hold rules, armed SL/TP in sync, no moonbag)
        sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
        import test_convert_mode as _tcm
        _cm = _tcm.run(str(Path(__file__).resolve().parent / "meme_sniper.py"))
        _cm_ok = all(v for k, v in _cm.items() if not k.endswith("_err"))
        ok = ok and _cm_ok
        console.print(f"smoke: convert_mode flip->hold->flip {sum(1 for v in _cm.values() if v is True)}/{len(_cm)} -> {'OK' if _cm_ok else 'FAIL ' + str([k for k, v in _cm.items() if not v])}")
    except Exception as _e:
        ok = False
        console.print(f"smoke: convert_mode test error {_e} -> FAIL")
    try:      # agent_status.json builder + request_id echo on every confirmation
        import test_agent_status as _tas
        _as = _tas.run(str(Path(__file__).resolve().parent / "meme_sniper.py"))
        _as_ok = all(_as.values())
        ok = ok and _as_ok
        console.print(f"smoke: agent_status + request_id echo {sum(1 for v in _as.values() if v)}/{len(_as)} -> "
                      f"{'OK' if _as_ok else 'FAIL ' + str([k for k, v in _as.items() if not v])}")
    except Exception as _e:
        ok = False
        console.print(f"smoke: agent_status test error {_e} -> FAIL")
    try:      # skill <-> code path drift: every json_relay/, bot_logs/, inbox path a skill names exists in code
        import tempfile as _tf
        import skill_path_drift as _spd
        _dr = _spd.check(Path(__file__).resolve().parent.parent)
        _neg = Path(_tf.mkdtemp())
        (_neg / "skills").mkdir(); (_neg / "bots").mkdir()
        (_neg / "skills" / "x.md").write_text("write json_relay/no_such_lane.json", encoding="utf-8")
        (_neg / "bots" / "a.py").write_text("X = 1\n", encoding="utf-8")
        _neg_ok = "json_relay/no_such_lane.json" in _spd.check(_neg)["missing"]
        _dr_ok = not _dr["missing"] and not _dr["allowlist_stale"] and _neg_ok
        ok = ok and _dr_ok
        console.print(f"smoke: skill path drift checked={_dr['checked']} agent_owned={_dr['agent_owned']} "
                      f"missing={list(_dr['missing'])[:5]} stale={_dr['allowlist_stale'][:3]} detects_drift={_neg_ok} -> "
                      f"{'OK' if _dr_ok else 'FAIL'}")
    except Exception as _e:
        ok = False
        console.print(f"smoke: skill path drift error {_e} -> FAIL")
    try:
        ok = _smoke_telegram_test() and ok
        ok = _smoke_alerts() and ok
    except Exception as e:
        ok = False; console.print(f"[red]telegram smoke failed: {e}[/]")
    try:
        ok = _smoke_labels() and ok
    except Exception as e:
        ok = False; console.print(f"[red]labels smoke failed: {e}[/]")
    try:
        lok = _smoke_llm_choice()
    except Exception as e:
        lok = False; console.print(f"[red]llm choice smoke failed: {e}[/]")
    ok = ok and lok
    try:
        cok2 = _smoke_cancel_and_status()
    except Exception as e:
        cok2 = False; console.print(f"[red]cancel/status smoke failed: {e}[/]")
    ok = ok and cok2
    try:
        ook = _smoke_owner_commands()
    except Exception as e:
        ook = False; console.print(f"[red]owner commands smoke failed: {e}[/]")
    ok = ok and ook
    try:
        pok = _smoke_paper_learning()
    except Exception as e:
        pok = False; console.print(f"[red]paper/learning smoke failed: {e}[/]")
    ok = ok and pok
    try:
        import tempfile as _tf2
        import import_closure as _ic
        _ir = _ic.check(Path(__file__).resolve().parent.parent)
        _neg2 = Path(_tf2.mkdtemp()); (_neg2 / "bots").mkdir()
        (_neg2 / "bots" / "a.py").write_text("import no_such_live_module\n", encoding="utf-8")
        _neg2_ok = any(m == "no_such_live_module" for _, _, m in _ic.check(_neg2)["unresolved"])
        _ic_ok = not _ir["unresolved"] and _neg2_ok
        ok = ok and _ic_ok
        console.print(f"smoke: imports closed-world files={_ir['checked']} unresolved={_ir['unresolved'][:5]} "
                      f"detects_missing={_neg2_ok} -> {'OK' if _ic_ok else 'FAIL'}")
    except Exception as _e:
        ok = False
        console.print(f"smoke: imports closed-world error {_e} -> FAIL")
    console.print(f"smoke: wizard keys={len(env)} complete={env_complete(env)} -> {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


KNOWN_FLAGS = {"--start", "--dashboard", "--wizard", "--launch", "--console", "--no-ui", "--smoke", "--ui-smoke",
               "--telegram-test", "--help", "-h"}

HELP_TEXT = f"""Meme Sniper {VERSION}

usage: python bots/sniper.py [option]     (no option = menu)

  --start          start Sniper and its helpers, then the console
  --dashboard      live dashboard (read-only)
  --wizard         setup wizard (writes bots/.env)
  --launch         guided token launch (dry run unless LAUNCH_RAIL_LIVE=1)
  --console        console only (dashboard, logs, settings, skills, alerts)
  --no-ui          with --start: no console, just the bots
  --smoke          quick self-check, changes nothing
  --ui-smoke       render every console view against a temp copy (your files are never touched)
  --telegram-test  send a test alert to your alert channels
  --help, -h       this text
"""


def _ui_smoke_temp() -> int:
    """--ui-smoke without WORKSPACE_DIR: run it against a throwaway copy of this folder, then delete the copy.
    The copy gets its own .env from .env.example, so your bots/.env and tracked files never change."""
    import shutil, tempfile
    if (os.environ.get("WORKSPACE_DIR") or "").strip():
        sys.path.insert(0, str(BOTS)); import sniper_ui
        return sniper_ui._ui_smoke()
    src = BOTS.parent
    tmp = Path(tempfile.mkdtemp(prefix="sniper_ui_smoke_"))
    ws = tmp / "ws"
    skip = shutil.ignore_patterns(".git", ".venv", "venv", "__pycache__", ".env", "bot_logs", "*.pyc")
    shutil.copytree(src, ws, ignore=skip)
    (ws / "bot_logs").mkdir(exist_ok=True)
    if (ws / "bots" / ".env.example").exists():
        shutil.copy(ws / "bots" / ".env.example", ws / "bots" / ".env")
    env = {**os.environ, "WORKSPACE_DIR": str(ws), "PYTHONIOENCODING": os.environ.get("PYTHONIOENCODING", "utf-8")}
    import subprocess
    try:
        return subprocess.call([sys.executable, str(ws / "bots" / "sniper_ui.py"), "--ui-smoke"], env=env, cwd=str(ws))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    if os.name == "nt":
        os.system("")   # enable ANSI on older Windows consoles
    a = set(sys.argv[1:])
    if "--smoke" in a:
        return smoke()
    if "--help" in a or "-h" in a:
        print(HELP_TEXT); return 0
    if "--ui-smoke" in a:   # runs against a temp copy unless WORKSPACE_DIR is set
        return _ui_smoke_temp()
    unknown = sorted(x for x in a if x.startswith("--") and x not in KNOWN_FLAGS)
    if unknown:
        console.print(f"[yellow]unknown option(s): {' '.join(unknown)}[/] (known: {' '.join(sorted(KNOWN_FLAGS))})")
        return 2
    if "--telegram-test" in a:
        r = telegram_test()
        return 0 if r and all(v == "sent" for v in r.values()) else 1
    console.print(banner())
    first_run_check()
    if "--start" in a:
        start_all(); return 0
    if "--dashboard" in a:
        dashboard(); return 0
    if "--wizard" in a:
        wizard(); return 0
    if "--launch" in a:
        guided_launch(); return 0
    if "--console" in a:
        open_console(); return 0
    if not sys.stdin.isatty():   # no terminal: never block on the menu prompt
        console.print("[yellow]No terminal for the menu. Use a flag: --start, --dashboard, --wizard, --launch, "
                      "--console, --smoke or --ui-smoke.[/]")
        log("menu skipped: no tty")
        return 2
    while True:
        console.print(menu_panel())
        try:
            c = choose(console, "choose (q = exit)", [k for k, _ in MENU], "4")
        except (KeyboardInterrupt, EOFError, CancelInput):
            c = "7"
        if c == "7":
            write_stop_reason("user_stopped")
            console.print(f"[{PURPLE}]bye[/]")
            return 0
        try:
            if c == "1":
                start_all()
            elif c == "2":
                wizard()
            elif c == "3":
                sign_in_x()
            elif c == "4":
                dashboard()
            elif c == "5":
                guided_launch()
            elif c == "6":
                open_console()
        except CancelInput:
            console.print("[yellow]back to the menu (nothing saved)[/]")


if __name__ == "__main__":
    sys.exit(main())
