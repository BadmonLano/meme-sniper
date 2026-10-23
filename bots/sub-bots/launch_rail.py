#!/usr/bin/env python3
"""
launch_rail.py: the Sniper launch rail (Pump.fun via PumpPortal).

When an agent ships something real and useful, the rail checks the repo, uploads metadata
that links the repo, builds the pump.fun create transaction (PumpPortal local API),
signs it with the mint keypair and the creator wallet, and sends it when the setup config arms live mode.
The agent decides each launch; there is no human confirm step.

SAFETY
  * Ships off-chain: LAUNCH_RAIL_LIVE defaults to 0 (dry runs only). Set LAUNCH_RAIL_LIVE=1 to go live.
  * Live is setup config, not an approval: LAUNCH_RAIL_ENABLED on (env or launch_rail_config.json)
    + env LAUNCH_RAIL_LIVE=1, and dev buy <= the cap (LAUNCH_MAX_DEV_BUY_SOL, default 0.5). Then every agent request
    sends live unless it asks for --dry-run / "dry_run": true. --confirm is accepted and ignored.
  * Secrets are read by NAME from env and never printed.
  * Every attempt is appended to bot_logs/launch_rail_log.jsonl.

Docs checked 2026-10-13 (pumpportal.fun/creation, /creator-fee):
  * pump.fun/api/ipfs is deprecated. PumpPortal now says to upload metadata to IPFS via Pinata
    (PINATA_JWT, https://uploads.pinata.cloud/v3/files). Legacy endpoint kept as --ipfs pumpfun.
  * Create: POST https://pumpportal.fun/api/trade-local, JSON {publicKey, action:"create",
    tokenMetadata{name,symbol,uri}, mint:<mint pubkey>, denominatedInSol:"true", amount,
    slippage, priorityFee, pool:"pump"}. It returns raw VersionedTransaction bytes, which are
    signed with [mint, creator].
  * Fees: action "collectCreatorFee" (pump claims all at once, so no mint is needed).

CLI
  python launch_rail.py check-repo <github url>
  python launch_rail.py launch --request req.json [--no-upload] [--throwaway] [--force] [--dry-run]
  python launch_rail.py scan-requests            # process bot_logs/launch_requests/*.json (dry-run)
  python launch_rail.py burn --mint <mint> --amount-raw N   # own-launch dev-bag burn (same gates)
  python launch_rail.py claim-fees [--dry-run]   # stub, same config gates
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import os

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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import base58
import httpx
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

ENV_FILE_LOADED: Optional[str] = None


def load_env(path: Optional[str] = None) -> Optional[str]:
    """Load secrets from an env file: --env / LAUNCH_ENV_FILE, else the .env next to this file.
    Values are never printed; returns the path that was loaded (or None)."""
    global ENV_FILE_LOADED
    p = Path(path or os.getenv("LAUNCH_ENV_FILE") or Path(WS_BOTS, ".env"))
    if p.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(p, override=bool(path))
            ENV_FILE_LOADED = str(p)
        except Exception as e:
            print(f"[launch_rail] env load failed for {p.name}: {type(e).__name__}")
    return ENV_FILE_LOADED


load_env()

BASE = Path(WS_BOTS)
BOT_LOGS = Path(WS_BOT_LOGS)
REQUESTS_DIR = BOT_LOGS / "launch_requests"
LOG_FILE = BOT_LOGS / "launch_rail_log.jsonl"
KEYS_DIR = BOT_LOGS / "launch_keys"          # git-ignored; mint keypairs for recovery
CONFIG_FILE = BOT_LOGS / "launch_rail_config.json"
JSON_RELAY = Path(WS_JSON_RELAY)
RELAY_REQUEST_FILE = JSON_RELAY / "launch_requests.json"      # one request, or {"requests": [...]}
RELAY_REQUEST_DIR = JSON_RELAY / "launch_requests"            # or one file per request
RELAY_RESULTS_FILE = JSON_RELAY / "launch_results.json"       # {"results": {id: result}}
SEEN_FILE = BOT_LOGS / "launch_rail_seen.json"                # idempotency: ids ever processed

PUMPPORTAL_LOCAL = "https://pumpportal.fun/api/trade-local"
PINATA_UPLOAD = "https://uploads.pinata.cloud/v3/files"
PUMPFUN_IPFS_LEGACY = "https://pump.fun/api/ipfs"
GITHUB_API = "https://api.github.com"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"

DEFAULT_CONFIG = {
    "LAUNCH_RAIL_ENABLED": False,       # master switch: ships OFF (set LAUNCH_RAIL_ENABLED=1 to turn on)
    "max_dev_buy_sol": 0.5,             # cap; raise via config or --max-dev-buy
    "default_slippage": 10,
    "default_priority_fee": 0.0005,
    "repo_min_score": 60,
    "repo_max_days_since_push": 90,
    "hooks": {"telegram": False, "agent_inbox": False},
}
EST_CREATE_RENT_SOL = 0.02   # rough: mint + bonding curve + metadata accounts (estimate)


# ----------------------------------------------------------------- utils
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paper_mode() -> bool:
    """SNIPER_PAPER_MODE=1: every launch is a dry run and send() refuses."""
    return (os.getenv("SNIPER_PAPER_MODE") or "0").strip().lower() in ("1", "true", "yes", "on")


def _rail_live_env() -> bool:
    """LAUNCH_RAIL_LIVE ships off: unset counts as 0 (simulate only). Set LAUNCH_RAIL_LIVE=1 to go live.
    Paper mode (SNIPER_PAPER_MODE=1) always simulates."""
    if _paper_mode():
        return False
    return (os.getenv("LAUNCH_RAIL_LIVE") or "0").strip() == "1"


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            print(f"[launch_rail] config unreadable ({e}); using defaults (rail OFF)")
    env = os.getenv("LAUNCH_RAIL_ENABLED")
    if env is not None:
        cfg["LAUNCH_RAIL_ENABLED"] = env.strip().lower() in ("1", "true", "yes", "on")
    return cfg


def log_attempt(entry: dict) -> None:
    BOT_LOGS.mkdir(parents=True, exist_ok=True)
    entry = {"ts": _now(), **entry}
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def rpc_url() -> str:
    if os.getenv("RPC_URL"):
        return os.environ["RPC_URL"]
    if os.getenv("HELIUS_API_KEY"):
        return f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
    return PUBLIC_RPC


def _redact_url(u: str) -> str:
    return u.split("?")[0] + ("?<redacted>" if "?" in u else "")


def load_keypair_from_secret(secret: str) -> Keypair:
    s = secret.strip()
    if s.startswith("["):
        return Keypair.from_bytes(bytes(json.loads(s)[:64]))
    raw = base58.b58decode(s)
    return Keypair.from_bytes(raw) if len(raw) == 64 else Keypair.from_seed(raw)


def load_creator(throwaway: bool, keyfile: Optional[str]) -> tuple[Keypair, str]:
    """Return (keypair, source description). Never prints secret material."""
    if throwaway:
        return Keypair(), "throwaway (generated, unfunded)"
    if keyfile:
        return Keypair.from_bytes(bytes(json.loads(Path(keyfile).read_text())[:64])), f"file {Path(keyfile).name}"
    for name in ("LAUNCH_WALLET_PRIVATE_KEY", "HOT_WALLET_PRIVATE_KEY", "PRIVATE_KEY"):
        if os.getenv(name):
            return load_keypair_from_secret(os.environ[name]), f"env {name}"
    raise SystemExit("No creator wallet: set LAUNCH_WALLET_PRIVATE_KEY or HOT_WALLET_PRIVATE_KEY, or use --throwaway")


# ----------------------------------------------------------------- b. repo gate
def check_repo(url: str, cfg: Optional[dict] = None) -> dict:
    """'Real and useful' gate. Returns {score, passed, reasons, facts}."""
    cfg = cfg or load_config()
    reasons, facts, score = [], {}, 0
    u = url.strip().rstrip("/").removesuffix(".git")
    parts = u.replace("https://", "").replace("http://", "").split("/")
    if len(parts) < 3 or parts[0].lower() != "github.com":
        return {"score": 0, "passed": False, "reasons": ["not a github.com/<owner>/<repo> URL"], "facts": {}}
    owner, repo = parts[1], parts[2]
    hdr = {"Accept": "application/vnd.github+json", "User-Agent": "sniper-launch-rail"}
    if os.getenv("GITHUB_TOKEN"):
        hdr["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with httpx.Client(timeout=20, headers=hdr) as c:
        r = c.get(f"{GITHUB_API}/repos/{owner}/{repo}")
        if r.status_code != 200:
            return {"score": 0, "passed": False, "reasons": [f"repo not found/public (HTTP {r.status_code})"], "facts": {}}
        d = r.json()
        facts.update(full_name=d["full_name"], private=d["private"], fork=d["fork"], archived=d["archived"],
                     stars=d["stargazers_count"], pushed_at=d["pushed_at"], language=d.get("language"),
                     size_kb=d.get("size"), default_branch=d["default_branch"])
        if d["private"]:
            reasons.append("FAIL private repo")
        else:
            score += 15; reasons.append("ok public")
        if d["archived"]:
            reasons.append("FAIL archived")
        else:
            score += 10; reasons.append("ok not archived")
        own_commits = None
        if d["fork"]:
            # fork: require the fork to be ahead of its parent with its own commits
            p = d.get("parent") or {}
            try:
                cmp = c.get(f"{GITHUB_API}/repos/{owner}/{repo}/compare/"
                            f"{p['owner']['login']}:{p['default_branch']}...{owner}:{d['default_branch']}").json()
                own_commits = cmp.get("ahead_by", 0)
            except Exception:
                own_commits = 0
            facts["fork_ahead_by"] = own_commits
            if own_commits and own_commits >= 3:
                score += 10; reasons.append(f"ok fork with {own_commits} own commits")
            else:
                reasons.append("FAIL fork-only clone (no meaningful own commits)")
        else:
            score += 20; reasons.append("ok original repo (not a fork)")
        rm = c.get(f"{GITHUB_API}/repos/{owner}/{repo}/readme")
        if rm.status_code == 200 and rm.json().get("size", 0) > 200:
            score += 15; reasons.append("ok README present")
        else:
            reasons.append("FAIL no meaningful README")
        tree = c.get(f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{d['default_branch']}?recursive=1")
        code_ext = {".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".sol", ".java", ".c", ".cpp", ".cs",
                    ".rb", ".php", ".swift", ".kt", ".html", ".css", ".sh", ".lua", ".dart", ".vue", ".svelte"}
        n_code = 0
        if tree.status_code == 200:
            n_code = sum(1 for t in tree.json().get("tree", [])
                         if t["type"] == "blob" and Path(t["path"]).suffix.lower() in code_ext)
        facts["code_files"] = n_code
        if n_code >= 3:
            score += 20; reasons.append(f"ok {n_code} code files")
        elif n_code:
            score += 8; reasons.append(f"weak only {n_code} code file(s)")
        else:
            reasons.append("FAIL no code files")
        try:
            pushed = datetime.fromisoformat(d["pushed_at"].replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - pushed).days
        except Exception:
            days = 9999
        facts["days_since_push"] = days
        if days <= cfg["repo_max_days_since_push"]:
            score += 20; reasons.append(f"ok pushed {days}d ago")
        else:
            reasons.append(f"FAIL stale: last push {days}d ago")
    hard_fail = any(x.startswith("FAIL") for x in reasons)
    passed = score >= cfg["repo_min_score"] and not hard_fail
    return {"score": score, "passed": passed, "reasons": reasons, "facts": facts, "repo": f"https://github.com/{owner}/{repo}"}


# ----------------------------------------------------------------- c. metadata
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_IMAGE_MAX_BYTES = 15_000_000
_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"RIFF")


def _image_bytes(src: str) -> tuple[bytes, str, str]:
    if src.startswith("http"):
        r = httpx.get(src, timeout=30, follow_redirects=True); r.raise_for_status()
        name = src.split("/")[-1].split("?")[0] or "image.png"
        return r.content, name, r.headers.get("content-type", "image/png")
    p = Path(src)
    # a local image is uploaded publicly to IPFS: only real image files, never .env/keys/other files
    if p.suffix.lower() not in _IMAGE_EXTS:
        raise SystemExit(f"image must be a {'/'.join(sorted(_IMAGE_EXTS))} file or an http(s) URL")
    if not p.is_file() or p.stat().st_size > _IMAGE_MAX_BYTES:
        raise SystemExit(f"image not found or larger than {_IMAGE_MAX_BYTES // 1_000_000} MB: {p.name}")
    data = p.read_bytes()
    if not any(data.startswith(m) for m in _IMAGE_MAGIC) or (data.startswith(b"RIFF") and data[8:12] != b"WEBP"):
        raise SystemExit(f"image is not a PNG/JPEG/GIF/WEBP file: {p.name}")
    return data, p.name, mimetypes.guess_type(p.name)[0] or "image/png"


def build_metadata(req: dict) -> dict:
    desc = req.get("description", "").strip()
    repo = req.get("repo_url") or ""
    if repo and repo not in desc:
        desc = (desc + f"\n\nBuilt on: {repo}").strip()
    return {"name": req["name"], "symbol": req["ticker"], "description": desc,
            "twitter": req.get("twitter", ""), "telegram": req.get("telegram", ""),
            "website": req.get("website") or repo, "showName": "true"}


def upload_metadata(req: dict, meta: dict, mode: str) -> dict:
    """mode: 'mock' | 'pinata' | 'pumpfun'. Returns {uri, image, mode}."""
    if mode == "mock":
        return {"uri": "https://ipfs.io/ipfs/MOCK_METADATA_CID", "image": "https://ipfs.io/ipfs/MOCK_IMAGE_CID", "mode": "mock"}
    img, fname, ctype = _image_bytes(req["image"])
    if mode == "pumpfun":   # legacy; PumpPortal says this endpoint is no longer supported
        r = httpx.post(PUMPFUN_IPFS_LEGACY, data=meta, files={"file": (fname, img, ctype)}, timeout=60)
        r.raise_for_status()
        j = r.json()
        return {"uri": j["metadataUri"], "image": j.get("metadata", {}).get("image"), "mode": "pumpfun"}
    jwt, _ = _pinata_jwt()
    if not jwt:
        raise SystemExit("PINATA_JWT not set (needed for IPFS upload); use --no-upload for a dry run")
    h = {"Authorization": f"Bearer {jwt}"}
    r = httpx.post(PINATA_UPLOAD, headers=h, data={"network": "public"}, files={"file": (fname, img, ctype)}, timeout=60)
    r.raise_for_status()
    image = f"https://ipfs.io/ipfs/{r.json()['data']['cid']}"
    body = {k: meta[k] for k in ("name", "symbol", "description", "twitter", "telegram", "website")}
    body["image"] = image
    r2 = httpx.post(PINATA_UPLOAD, headers=h, data={"network": "public"},
                    files={"file": ("metadata.json", json.dumps(body).encode(), "application/json")}, timeout=60)
    r2.raise_for_status()
    return {"uri": f"https://ipfs.io/ipfs/{r2.json()['data']['cid']}", "image": image, "mode": "pinata"}


def _pinata_jwt() -> tuple[Optional[str], Optional[str]]:
    """JWT by name: PINATA_JWT, else the lowercase pinata_secret_token some setups use."""
    for name in ("PINATA_JWT", "pinata_secret_token"):
        if os.getenv(name):
            return os.environ[name], name
    return None, None


def pinata_test_auth() -> dict:
    out = {}
    jwt, name = _pinata_jwt()
    if jwt:
        r = httpx.get("https://api.pinata.cloud/data/testAuthentication",
                      headers={"Authorization": f"Bearer {jwt}"}, timeout=20)
        out["jwt"] = {"var": name, "ok": r.status_code == 200, "http": r.status_code}
    if os.getenv("pinata_api_key") and os.getenv("pinata_api_secret"):
        r = httpx.get("https://api.pinata.cloud/data/testAuthentication",
                      headers={"pinata_api_key": os.environ["pinata_api_key"],
                               "pinata_secret_api_key": os.environ["pinata_api_secret"]}, timeout=20)
        out["api_key"] = {"var": "pinata_api_key/pinata_api_secret", "ok": r.status_code == 200, "http": r.status_code}
    out["ok"] = bool(out.get("jwt", {}).get("ok"))
    if not out["ok"]:
        out["note"] = "uploads use the v3 Files API, which needs a valid JWT (PINATA_JWT)"
    return out


# ----------------------------------------------------------------- d. create tx
def build_create_tx(creator: Keypair, mint: Keypair, meta: dict, uri: str, dev_buy: float,
                    slippage: float, priority_fee: float) -> bytes:
    payload = {"publicKey": str(creator.pubkey()), "action": "create",
               "tokenMetadata": {"name": meta["name"], "symbol": meta["symbol"], "uri": uri},
               "mint": str(mint.pubkey()), "denominatedInSol": "true", "amount": dev_buy,
               "slippage": slippage, "priorityFee": priority_fee, "pool": "pump"}
    r = httpx.post(PUMPPORTAL_LOCAL, json=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"PumpPortal trade-local HTTP {r.status_code}: {r.text[:300]}")
    return r.content


def sign_tx(raw: bytes, signers: list[Keypair]) -> VersionedTransaction:
    msg = VersionedTransaction.from_bytes(raw).message
    return VersionedTransaction(msg, signers)


def _rpc_urls() -> list[str]:
    urls = [rpc_url()]
    if os.getenv("RPC_URL_FALLBACK"):
        urls.append(os.environ["RPC_URL_FALLBACK"])
    if PUBLIC_RPC not in urls:
        urls.append(PUBLIC_RPC)
    return urls


def _rpc(method: str, params: list) -> dict:
    """JSON-RPC with fallback across RPC_URL -> RPC_URL_FALLBACK -> public. Never logs URLs/keys."""
    last = None
    for i, u in enumerate(_rpc_urls()):
        try:
            r = httpx.post(u, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
            j = r.json()
            if i:
                j["_rpc_used"] = "public" if u == PUBLIC_RPC else "RPC_URL_FALLBACK"
                j["_rpc_note"] = last
            return j
        except Exception as e:
            last = f"rpc#{i} {type(e).__name__}" + (f" HTTP {r.status_code}" if 'r' in locals() else "")
            if method == "sendTransaction":
                break   # never re-broadcast a send through another RPC automatically
    return {"error": last}


def simulate(tx: VersionedTransaction) -> dict:
    enc = base64.b64encode(bytes(tx)).decode()
    j = _rpc("simulateTransaction", [enc, {"encoding": "base64", "sigVerify": False,
                                            "replaceRecentBlockhash": True, "commitment": "processed"}])
    if "error" in j:
        return {"ok": False, "rpc_error": j["error"]}
    v = j["result"]["value"]
    return {"rpc": j.get("_rpc_used", "primary"), "rpc_note": j.get("_rpc_note"), "ok": v.get("err") is None, "err": v.get("err"), "units": v.get("unitsConsumed"),
            "logs_tail": (v.get("logs") or [])[-6:]}


def send(tx: VersionedTransaction) -> str:
    if _paper_mode():
        raise RuntimeError("SNIPER_PAPER_MODE is on: launch_rail never sends in paper mode")
    enc = base64.b64encode(bytes(tx)).decode()
    j = _rpc("sendTransaction", [enc, {"encoding": "base64", "skipPreflight": False,
                                        "preflightCommitment": "confirmed", "maxRetries": 3}])
    if "error" in j:
        raise RuntimeError(f"sendTransaction failed: {j['error']}")
    return j["result"]


def balance_sol(pubkey: str) -> Optional[float]:
    try:
        return _rpc("getBalance", [pubkey])["result"]["value"] / 1e9
    except Exception:
        return None


def save_mint_key(mint: Keypair) -> Path:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    gi = KEYS_DIR / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n!.gitignore\n")
    p = KEYS_DIR / f"{mint.pubkey()}.json"
    p.write_text(json.dumps(list(bytes(mint))))
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return p


# ----------------------------------------------------------------- g. hooks / fees
def wallet_token_balance(owner: str, mint: str) -> Optional[dict]:
    """Token balance of `mint` held by `owner` via the rail's RPC helper. None on failure."""
    try:
        j = _rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
        accts = ((j.get("result") or {}).get("value")) or []
        raw, dec = 0, None
        for a in accts:
            ta = a["account"]["data"]["parsed"]["info"]["tokenAmount"]
            raw += int(ta["amount"]); dec = int(ta["decimals"])
        if dec is None:
            return {"raw": 0, "decimals": None, "ui": 0.0}
        return {"raw": raw, "decimals": dec, "ui": raw / (10 ** dec)}
    except Exception:
        return None


def write_own_launch_note(result: dict, inbox_dir, request: Optional[dict] = None) -> Path:
    """Write a clean own_launch note for the agent inbox (empire doctrine: 'botname - subject_ts.json').
    Whitelisted public fields only: never the mint key file, simulation data or any secret."""
    inbox_dir = Path(inbox_dir); inbox_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    mint = str(result.get("mint") or "")
    ticker = str(result.get("ticker") or "") or mint[:8] or "unk"
    safe_t = "".join(c for c in ticker if c.isalnum() or c == "_")[:16] or "unk"
    wallet = (result.get("creator") or {}).get("pubkey") if isinstance(result.get("creator"), dict) else None
    dev_buy = result.get("dev_buy_sol")
    req = request or result.get("request") or {}
    dev_tokens = result.get("dev_buy_tokens")
    if dev_tokens is None and wallet and mint:
        bal = wallet_token_balance(wallet, mint)
        dev_tokens = bal.get("ui") if bal else None
    note = {
        "_type": "own_launch",
        "lane": "queue",
        "generated_at": now.isoformat(timespec="seconds"),
        "headline": f"own launch: {result.get('name')} (${ticker}) - dev buy {dev_buy} SOL",
        "event": "own_launch",
        "mode": result.get("mode"),
        "mint": mint,
        "ticker": ticker,
        "name": result.get("name"),
        "dev_buy_sol": dev_buy,
        "dev_buy_tokens": dev_tokens,
        "holding_note": "the dev buy is the holding",
        "wallet": wallet,
        "signature": result.get("signature"),
        "pump_url": result.get("pump_url"),
        "solscan": result.get("solscan"),
        "repo_url": result.get("repo_url"),
        "website": req.get("website") or result.get("website") or None,
        "twitter": req.get("twitter") or result.get("twitter") or None,
        "telegram": req.get("telegram") or result.get("telegram") or None,
        "suggested_actions": ["set_holding_thesis", "classify_holding", "harvest_holding", "promote_holding"],
        "ask": "one line: hold dev bag / skim / burn / promote to managed",
    }
    path = inbox_dir / f"meme_sniper - own_launch_{safe_t}_{mint[:8] or 'unk'}_{now.strftime('%Y%m%d_%H%M%S')}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(note, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


_ALERTS_MOD = None


def _alerts_mod():
    """bots/sub-bots/alerts.py (2026-10-15 pluggable alerts). None = fall back to direct Telegram."""
    global _ALERTS_MOD
    if _ALERTS_MOD is None:
        try:
            import importlib.util as _ilu
            _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alerts.py")
            _spec = _ilu.spec_from_file_location("ms_alerts", _p)
            _m = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_m)
            _ALERTS_MOD = _m
        except Exception:
            _ALERTS_MOD = False
    return _ALERTS_MOD or None


def run_hooks(cfg: dict, result: dict) -> list[str]:
    done = []
    hooks = cfg.get("hooks", {})
    text = (f"Launched {result['name']} (${result['ticker']}) | {result['pump_url']} " + (f" | repo {result['repo_url']}" if result.get('repo_url') else ""))
    _am = _alerts_mod() if (hooks.get("telegram") or hooks.get("alerts")) else None
    if _am is not None:
        # 2026-10-15: through the alert dispatcher (every ALERT_CHANNELS channel); Telegram
        # payload unchanged (bare chat_id + text). Errors are logged without the token.
        _res = _am.send_sync(text, source="launch_rail", tg_plain=True)
        done += [c if s == "sent" else f"{c}_failed:{s}" for c, s in _res.items()]
    elif hooks.get("telegram") and os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        try:
            httpx.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
                       json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text}, timeout=15)
            done.append("telegram")
        except Exception as e:
            done.append(f"telegram_failed:{type(e).__name__}")   # never str(e): the URL carries the token
    if hooks.get("agent_inbox"):
        try:
            p = write_own_launch_note(result, BASE.parent / "inbox")
            done.append(f"agent_inbox:{p.name}")
        except Exception as e:
            done.append(f"agent_inbox_failed:{type(e).__name__}")
    return done


def claim_creator_fees(creator: Keypair, priority_fee: float, live: bool) -> dict:
    """PumpPortal collectCreatorFee (pump claims all creator fees at once). Same gates as launch."""
    r = httpx.post(PUMPPORTAL_LOCAL, data={"publicKey": str(creator.pubkey()), "action": "collectCreatorFee",
                                           "priorityFee": priority_fee}, timeout=30)
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    tx = sign_tx(r.content, [creator])
    if not live:
        return {"ok": True, "mode": "dry-run", "simulation": simulate(tx)}
    return {"ok": True, "mode": "live", "signature": send(tx)}


# ----------------------------------------------------------------- own-launch dev-bag burn
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def burn_ix_data(amount_raw: int) -> bytes:
    """SPL Token / Token-2022 `Burn` (instruction 8): u8 tag + u64 LE amount."""
    if amount_raw <= 0:
        raise ValueError("burn amount must be > 0")
    return bytes([8]) + int(amount_raw).to_bytes(8, "little")


def burn_dev_bag(owner: Keypair, mint: str, amount_raw: int, live: bool) -> dict:
    """Burn `amount_raw` of `mint` from the owner's token account. Dry-run simulates only.
    Lock / vesting is NOT supported (no reliable program in the current deps)."""
    from solders.pubkey import Pubkey
    from solders.instruction import Instruction, AccountMeta
    from solders.message import MessageV0
    from solders.hash import Hash
    j = _rpc("getTokenAccountsByOwner", [str(owner.pubkey()), {"mint": mint}, {"encoding": "jsonParsed"}])
    accts = ((j.get("result") or {}).get("value")) or []
    if not accts:
        return {"ok": False, "mode": "live" if live else "dry-run", "error": "no token account for mint"}
    best = max(accts, key=lambda a: int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]))
    held = int(best["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
    program = best["account"]["owner"]
    if program not in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
        return {"ok": False, "error": f"unknown token program {program}"}
    amount_raw = min(int(amount_raw), held)
    ix = Instruction(Pubkey.from_string(program), burn_ix_data(amount_raw), [
        AccountMeta(Pubkey.from_string(best["pubkey"]), is_signer=False, is_writable=True),
        AccountMeta(Pubkey.from_string(mint), is_signer=False, is_writable=True),
        AccountMeta(owner.pubkey(), is_signer=True, is_writable=False)])
    bh = _rpc("getLatestBlockhash", [{"commitment": "confirmed"}])
    blockhash = Hash.from_string(bh["result"]["value"]["blockhash"])
    tx = VersionedTransaction(MessageV0.try_compile(owner.pubkey(), [ix], [], blockhash), [owner])
    out = {"mint": mint, "amount_raw": amount_raw, "held_raw": held, "program": program}
    if not live:
        sim = simulate(tx)
        return {"ok": bool(sim.get("ok")), "mode": "dry-run", "simulation": sim, **out}
    return {"ok": True, "mode": "live", "signature": send(tx), **out}


# ----------------------------------------------------------------- orchestration
REQUIRED = ("name", "ticker", "description", "image")


def validate_request(req: dict) -> None:
    missing = [k for k in REQUIRED if not req.get(k)]
    if missing:
        raise SystemExit(f"launch request missing: {missing}")
    if not (1 <= len(req["ticker"]) <= 10):
        raise SystemExit("ticker must be 1-10 chars")
    if not re.fullmatch(r"[A-Za-z0-9$_\-]{1,10}", str(req["ticker"])):
        raise SystemExit("ticker may only use letters, digits, $, _ and - (it also names files)")
    if len(req["name"]) > 32:
        raise SystemExit("name max 32 chars")


def _dev_buy_cap(cli: Optional[float], cfg: dict) -> float:
    """Dev-buy cap. Precedence: --max-dev-buy, env LAUNCH_MAX_DEV_BUY_SOL, config max_dev_buy_sol, 0.5."""
    if cli is not None:
        return float(cli)
    env = (os.getenv("LAUNCH_MAX_DEV_BUY_SOL") or "").strip()
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    try:
        return float(cfg.get("max_dev_buy_sol", 0.5))
    except (TypeError, ValueError):
        return 0.5


def launch(req: dict, *, no_upload=False, ipfs="pinata", throwaway=False, keyfile=None, force=False,
           confirm=True, max_dev_buy: Optional[float] = None, no_build=False, dry_run=False) -> dict:
    # `confirm` is kept for old callers and ignored: the agent is the decider. Only dry_run or
    # the setup config (LAUNCH_RAIL_ENABLED + LAUNCH_RAIL_LIVE) keep a request off-chain.
    cfg = load_config()
    validate_request(req)
    dev_buy = float(req.get("dev_buy_sol", 0.0))
    slippage = float(req.get("slippage", cfg["default_slippage"]))
    prio = float(req.get("priority_fee", cfg["default_priority_fee"]))
    cap = _dev_buy_cap(max_dev_buy, cfg)
    want_live = (not dry_run) and _rail_live_env()
    blockers = []
    if dry_run:
        blockers.append("dry_run requested")
    if not cfg["LAUNCH_RAIL_ENABLED"]:
        blockers.append("LAUNCH_RAIL_ENABLED is off")
    if _paper_mode():
        blockers.append("SNIPER_PAPER_MODE is on (launch simulated)")
    elif not _rail_live_env():
        blockers.append("env LAUNCH_RAIL_LIVE != 1")
    if dev_buy > cap:
        blockers.append(f"dev buy {dev_buy} > cap {cap}")
    if want_live and throwaway:
        blockers.append("throwaway creator cannot launch live")
    live = want_live and not blockers
    out: dict[str, Any] = {"mode": "LIVE" if live else "dry-run", "name": req["name"], "ticker": req["ticker"],
                           "repo_url": req.get("repo_url") or "", "dev_buy_sol": dev_buy, "cap_sol": cap, "blockers": blockers}
    # b. repo gate
    if not req.get("repo_url") and os.getenv("LAUNCH_ALLOW_NO_REPO", "1") != "0":
        rc = {"score": None, "passed": True, "reasons": ["no repo attached: gate skipped (LAUNCH_ALLOW_NO_REPO)"], "facts": {}}
    else:
        rc = check_repo(req.get("repo_url") or "", cfg)
    out["repo_check"] = rc
    if not rc["passed"] and not force:
        out["status"] = "blocked_repo_gate"
        log_attempt(out); return out
    if any("cap" in b for b in blockers):
        out["status"] = "blocked_dev_buy_cap"
        log_attempt(out); return out
    creator, src = load_creator(throwaway, keyfile)
    out["creator"] = {"pubkey": str(creator.pubkey()), "source": src, "balance_sol": balance_sol(str(creator.pubkey()))}
    mint = Keypair()
    out["mint"] = str(mint.pubkey())
    # c. metadata
    meta = build_metadata(req)
    out["metadata"] = meta
    up = upload_metadata(req, meta, "mock" if no_upload else ipfs)
    out["metadata_uri"] = up["uri"]; out["ipfs_mode"] = up["mode"]
    out["cost_estimate_sol"] = round(dev_buy + prio + EST_CREATE_RENT_SOL + dev_buy * 0.01, 6)
    out["cost_note"] = "dev buy + priority fee + ~0.02 rent (estimate) + ~1% trade fee on dev buy"
    if no_build:
        out["status"] = "dry_run_no_build"; log_attempt(out); return out
    # d. build + sign
    raw = build_create_tx(creator, mint, meta, up["uri"], dev_buy, slippage, prio)
    tx = sign_tx(raw, [mint, creator])
    out["tx_bytes"] = len(bytes(tx))
    out["signers"] = [str(k) for k in tx.message.account_keys[: tx.message.header.num_required_signatures]]
    out["simulation"] = simulate(tx)
    if not live:
        out["status"] = "dry_run_ok" if out["simulation"].get("ok") else "dry_run_built_sim_failed"
        log_attempt(out); return out
    # live
    keyp = save_mint_key(mint)
    out["mint_key_file"] = str(keyp)
    print(f"[launch_rail] WARNING: mint keypair saved to {keyp}. Keep it private; never commit it.")
    sig = send(tx)
    out.update(status="sent", signature=sig, pump_url=f"https://pump.fun/coin/{mint.pubkey()}",
               solscan=f"https://solscan.io/tx/{sig}")
    out["request"] = {k: req.get(k) for k in ("website", "twitter", "telegram")}
    out["hooks"] = run_hooks(cfg, out)
    log_attempt(out)
    return out


# ----------------------------------------------------------------- relay
RELAY_FIELDS = {"id": str, "action": str, "repo_url": str, "name": str, "ticker": str, "description": str,
                "image": str, "website": str, "twitter": str, "telegram": str, "dev_buy_sol": (int, float),
                "slippage": (int, float), "priority_fee": (int, float), "confirm": bool, "dry_run": bool, "requested_by": str}
RELAY_REQUIRED = ("id", "action", "name", "ticker", "description", "image", "dev_buy_sol", "requested_by")


def validate_relay_request(r: Any) -> list[str]:
    errs = []
    if not isinstance(r, dict):
        return ["request must be a JSON object"]
    for k in RELAY_REQUIRED:
        if r.get(k) in (None, ""):
            errs.append(f"missing {k}")
    for k, t in RELAY_FIELDS.items():
        if k in r and r[k] is not None and r[k] != "" and not isinstance(r[k], t):
            errs.append(f"{k} wrong type")
    if r.get("action") not in (None, "launch"):
        errs.append("action must be 'launch'")
    unknown = set(r) - set(RELAY_FIELDS)
    if unknown:
        errs.append(f"unknown fields {sorted(unknown)}")
    return errs


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json_atomic(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, p)


def _archive(p: Path) -> None:
    """Mark a processed request file without ever colliding (Windows rename can't overwrite)."""
    try:
        os.replace(p, p.with_name(f"{p.name}.processed_{int(time.time()*1000)}"))
    except Exception:
        pass


def _collect_relay_requests() -> list[tuple[dict, Optional[Path]]]:
    out = []
    if RELAY_REQUEST_FILE.exists():
        d = _read_json(RELAY_REQUEST_FILE, None)
        items = d.get("requests", [d]) if isinstance(d, dict) else (d if isinstance(d, list) else [])
        out += [(x, None) for x in items]
    if RELAY_REQUEST_DIR.is_dir():
        for p in sorted(RELAY_REQUEST_DIR.glob("*.json")):
            out.append((_read_json(p, {"_unreadable": p.name}), p))
    return out


def process_relay(*, no_upload: Optional[bool] = None, ipfs: str = "pinata") -> list[dict]:
    """Poll the launch relay once. Each new id is processed exactly once (launch_rail_seen.json).
    Live when the rail is enabled and LAUNCH_RAIL_LIVE=1 (setup config), unless the request sets dry_run:true."""
    if no_upload is None:
        no_upload = os.getenv("LAUNCH_RAIL_NO_UPLOAD") == "1"
    seen = _read_json(SEEN_FILE, {})
    results = _read_json(RELAY_RESULTS_FILE, {"results": {}})
    results.setdefault("results", {})
    done = []
    for req, path in _collect_relay_requests():
        rid = str(req.get("id", "")) if isinstance(req, dict) else ""
        if rid and rid in seen:
            if path:
                _archive(path)
            continue
        errs = validate_relay_request(req)
        if errs:
            res = {"id": rid or None, "status": "rejected_schema", "errors": errs, "ts": _now()}
        else:
            seen[rid] = _now(); _write_json_atomic(SEEN_FILE, seen)   # mark BEFORE launching: never twice
            try:
                res = launch(req, no_upload=no_upload, ipfs=ipfs, dry_run=bool(req.get("dry_run")))
            except SystemExit as e:
                res = {"status": "error", "error": str(e)}
            except Exception as e:
                res = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            res = {"id": rid, "requested_by": req.get("requested_by"), "ts": _now(),
                   **{k: res.get(k) for k in ("status", "mode", "blockers", "mint", "pump_url", "signature",
                                              "solscan", "metadata_uri", "cost_estimate_sol", "error", "dev_buy_sol", "ticker", "name")},
                   "repo_score": (res.get("repo_check") or {}).get("score"),
                   "repo_reasons": (res.get("repo_check") or {}).get("reasons"),
                   "simulation": res.get("simulation"),
                   "creator": {k: (res.get("creator") or {}).get(k) for k in ("pubkey", "source", "balance_sol")},
                   "metadata": res.get("metadata"),
                   "why_not_live": None if res.get("mode") == "LIVE" else (
                       res.get("blockers") or (["request dry_run is true"] if req.get("dry_run") else []))}
        log_attempt({"relay": True, **res})
        if rid:
            results["results"][rid] = res
        _write_json_atomic(RELAY_RESULTS_FILE, results)
        if path:
            _archive(path)
        done.append(res)
    if RELAY_REQUEST_FILE.exists() and done:
        _archive(RELAY_REQUEST_FILE)
    return done


def _print(o: dict) -> None:
    print(json.dumps(o, indent=2, default=str))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="launch_rail")
    ap.add_argument("--env", help="env file to load (default: LAUNCH_ENV_FILE or .env next to this file)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check-repo"); s.add_argument("url")
    s = sub.add_parser("launch")
    s.add_argument("--request", required=True)
    for f in ("--no-upload", "--throwaway", "--force", "--confirm", "--no-build", "--dry-run"):
        s.add_argument(f, action="store_true")
    s.add_argument("--ipfs", choices=["pinata", "pumpfun"], default="pinata")
    s.add_argument("--keyfile"); s.add_argument("--max-dev-buy", type=float)
    s = sub.add_parser("scan-requests"); s.add_argument("--no-upload", action="store_true"); s.add_argument("--throwaway", action="store_true")
    s = sub.add_parser("relay-once"); s.add_argument("--no-upload", action="store_true")
    s.add_argument("--ipfs", choices=["pinata", "pumpfun"], default="pinata")
    s = sub.add_parser("pinata-auth")
    s = sub.add_parser("burn"); s.add_argument("--mint", required=True); s.add_argument("--amount-raw", type=int, required=True)
    s.add_argument("--confirm", action="store_true"); s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("claim-fees"); s.add_argument("--confirm", action="store_true"); s.add_argument("--dry-run", action="store_true"); s.add_argument("--throwaway", action="store_true")
    s.add_argument("--priority-fee", type=float, default=0.000001)
    a = ap.parse_args(argv)
    if a.env:
        load_env(a.env)
    if a.cmd == "relay-once":
        _print({"processed": process_relay(no_upload=a.no_upload, ipfs=a.ipfs)}); return 0
    if a.cmd == "pinata-auth":
        _print(pinata_test_auth()); return 0
    if a.cmd == "check-repo":
        r = check_repo(a.url); _print(r); return 0 if r["passed"] else 2
    if a.cmd == "launch":
        req = json.loads(Path(a.request).read_text(encoding="utf-8"))
        r = launch(req, no_upload=a.no_upload, ipfs=a.ipfs, throwaway=a.throwaway, keyfile=a.keyfile,
                   force=a.force, max_dev_buy=a.max_dev_buy, no_build=a.no_build, dry_run=a.dry_run)
        _print(r); return 0 if not str(r.get("status", "")).startswith("blocked") else 2
    if a.cmd == "scan-requests":   # legacy bot_logs drop folder: always dry-run (use the json_relay for agent launches)
        REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
        for p in sorted(REQUESTS_DIR.glob("*.json")):
            r = launch(json.loads(p.read_text(encoding="utf-8")), no_upload=a.no_upload, throwaway=a.throwaway, dry_run=True)
            _archive(p); _print(r)
        return 0
    if a.cmd == "burn":
        cfg = load_config()
        live = (not a.dry_run) and cfg["LAUNCH_RAIL_ENABLED"] and _rail_live_env()
        creator, _ = load_creator(False, None)
        r = burn_dev_bag(creator, a.mint, a.amount_raw, live)
        log_attempt({"burn": True, **{k: v for k, v in r.items() if k != "simulation"}})
        _print(r); return 0 if r.get("ok") else 2
    if a.cmd == "claim-fees":
        cfg = load_config()
        live = (not a.dry_run) and cfg["LAUNCH_RAIL_ENABLED"] and _rail_live_env() and not a.throwaway
        creator, _ = load_creator(a.throwaway, None)
        _print(claim_creator_fees(creator, a.priority_fee, live)); return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
