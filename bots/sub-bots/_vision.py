"""_vision.py — Shared vision pipeline for all Sniper ecosystem bots.

(Public build: history trimmed; see TIMELINE.md.)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os

def _envv(key, default=None):
    """os.getenv, but a blank value (KEY= in .env) counts as unset and returns the default."""
    v = os.environ.get(key)
    return default if v is None or not str(v).strip() else v

import sys

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

from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx


# ─── config (from env) ───
OLLAMA_URL              = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_VISION_MODEL     = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:7b")
OLLAMA_VISION_TIMEOUT   = float(_envv("OLLAMA_VISION_TIMEOUT", "180"))

GROK_API_KEY            = os.getenv("GROK_API_KEY", "") or os.getenv("XAI_API_KEY", "")
GROK_API_BASE           = os.getenv("GROK_API_BASE", "https://api.x.ai/v1")
GROK_VISION_MODEL       = os.getenv("GROK_VISION_MODEL", "auto").strip() or "auto"
GROK_MODELS_CACHE_FILE  = Path(os.getenv(
    "GROK_MODELS_CACHE_FILE",
    str(Path(WS_BOT_LOGS) / "grok_brain_models.json")
))
_GROK_VISION_LASTKNOWN  = ["grok-4.7", "grok-4.6", "grok-4.5"]
_GROK_VISION_MAX_TRIES  = int(_envv("GROK_VISION_MAX_TRIES", "3"))


def grok_vision_models() -> list[str]:
    """Ordered vision candidates. Every main grok-N.N model takes images."""
    auto: list[str] = []
    try:
        d = json.loads(GROK_MODELS_CACHE_FILE.read_text(encoding="utf-8")) or {}
        auto = [m for m in (d.get("main_models") or []) if isinstance(m, str) and m]
        if not auto:
            r = d.get("roles") or {}
            auto = [r.get(k) for k in ("analyst", "narrative", "judge") if r.get(k)]
    except Exception:
        pass
    auto = auto or list(_GROK_VISION_LASTKNOWN)
    out: list[str] = []
    if GROK_VISION_MODEL.lower() != "auto":
        out.append(GROK_VISION_MODEL)
    for m in auto:
        if m not in out:
            out.append(m)
    return out[:max(1, _GROK_VISION_MAX_TRIES)]
GROK_VISION_TIMEOUT     = float(_envv("GROK_VISION_TIMEOUT", "60"))
# 2026-10-14: which layer runs first. Comma list of grok / ollama; the next one is
# the fallback. Default keeps the old local-first order.
VISION_PROVIDER_ORDER   = [p.strip().lower() for p in
                           os.getenv("VISION_PROVIDER_ORDER", "grok,ollama").split(",")
                           if p.strip().lower() in ("grok", "ollama", "openai", "anthropic", "claude",
                                                    "openai_compat", "compat", "custom")] or ["grok", "ollama"]
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import llm_providers as _llmp
except Exception:
    _llmp = None

# Cache location — defaults to bot_logs in standard workspace, env-overridable
DEFAULT_CACHE_FILE = Path(os.getenv(
    "VISION_CACHE_FILE",
    str(Path(WS_BOT_LOGS) / "vision_cache.json")
))

# Concurrency: vision is heavy on local GPU, throttle to 1 at a time
_OLLAMA_VISION_SEMAPHORE = asyncio.Semaphore(int(_envv("OLLAMA_VISION_CONCURRENCY", "1")))


# ─── primitives ───
def _now_iso() -> str:
    return datetime.now().isoformat()


def _now_ts() -> float:
    return datetime.now().timestamp()


def _log(msg: str, prefix: str = "vision") -> None:
    """Lightweight logger. Bots should override by passing _log= if they want their own."""
    line = f"[{_now_iso()}] [{prefix}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass


def _save_json_atomic(path: Path, data) -> None:
    """Atomic JSON write via temp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _detect_mime(b: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if b[:2] == b"\xff\xd8":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"  # safe default


# ─── cache ───
def _vision_cache_get(key: str, *, max_age_seconds: int, cache_file: Path) -> Optional[str]:
    try:
        if not cache_file.exists():
            return None
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if not isinstance(cache, dict):
            return None
        entry = cache.get(key)
        if not isinstance(entry, dict):
            return None
        cached_at_ts = entry.get("cached_at_ts", 0)
        if (_now_ts() - cached_at_ts) > max_age_seconds:
            return None
        return entry.get("description")
    except Exception:
        return None


def _vision_cache_set(key: str, description: str, *, source: str, cache_file: Path) -> None:
    try:
        cache = {}
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                if not isinstance(cache, dict):
                    cache = {}
            except Exception:
                cache = {}
        
        cache[key] = {
            "description": description,
            "cached_at": _now_iso(),
            "cached_at_ts": _now_ts(),
            "source": source,
        }
        
        # Bound: keep last 1000 by cached_at_ts
        if len(cache) > 1000:
            sorted_keys = sorted(cache.keys(), key=lambda k: cache[k].get("cached_at_ts", 0), reverse=True)
            cache = {k: cache[k] for k in sorted_keys[:1000]}
        
        _save_json_atomic(cache_file, cache)
    except Exception as e:
        _log(f"cache set failed: {e}")


# ─── Ollama vision ───
async def _vision_describe_via_ollama(
    prompt: str,
    image_bytes_list: list[bytes],
    *,
    max_tokens: int = 600,
) -> Optional[str]:
    """Local Ollama vision call using OLLAMA_VISION_MODEL (default qwen2.5vl:7b)."""
    images_b64 = [base64.b64encode(b).decode() for b in image_bytes_list]
    
    async with _OLLAMA_VISION_SEMAPHORE:
        try:
            timeout_client = httpx.AsyncClient(timeout=OLLAMA_VISION_TIMEOUT)
            try:
                payload = {
                    "model": OLLAMA_VISION_MODEL,
                    "prompt": prompt,
                    "images": images_b64,
                    "stream": False,
                    "options": {"temperature": 0.4, "num_predict": max_tokens},
                }
                r = await timeout_client.post(f"{OLLAMA_URL}/api/generate", json=payload)
                if r.status_code != 200:
                    _log(f"ollama ({OLLAMA_VISION_MODEL}) returned {r.status_code}: {r.text[:200]}")
                    return None
                data = r.json()
                return (data.get("response") or "").strip()
            finally:
                await timeout_client.aclose()
        except httpx.TimeoutException:
            _log(f"ollama ({OLLAMA_VISION_MODEL}) timeout after {OLLAMA_VISION_TIMEOUT}s")
            return None
        except Exception as e:
            _log(f"ollama vision error: {e}")
            return None


# ─── Grok vision (fallback) ───
async def _vision_describe_via_grok(
    prompt: str,
    image_bytes_list: list[bytes],
    *,
    max_tokens: int = 600,
) -> Optional[str]:
    """
    Grok-4 vision fallback. Sends inline base64-encoded images via data URI scheme.
    xAI API is OpenAI-compatible at https://api.x.ai/v1/chat/completions.
    """
    if not GROK_API_KEY:
        return None
    
    content_blocks: list[dict] = [{"type": "text", "text": prompt}]
    for b in image_bytes_list:
        b64 = base64.b64encode(b).decode()
        mime = _detect_mime(b)
        content_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })
    
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }
    for model in grok_vision_models():
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content_blocks}],
            "max_tokens": max_tokens,
            "temperature": 0.4,
        }
        out = await _grok_vision_once(model, payload, headers)
        if out:
            return out
    return None


async def _grok_vision_once(model: str, payload: dict, headers: dict) -> Optional[str]:
    try:
        timeout_client = httpx.AsyncClient(timeout=GROK_VISION_TIMEOUT)
        try:
            r = await timeout_client.post(
                f"{GROK_API_BASE}/chat/completions",
                json=payload,
                headers=headers,
            )
            if r.status_code != 200:
                _log(f"grok vision {model} returned {r.status_code}: {r.text[:300]}")
                return None
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                _log(f"grok vision returned no choices: {str(data)[:200]}")
                return None
            msg = choices[0].get("message") or {}
            content = msg.get("content") or ""
            return content.strip() if isinstance(content, str) else None
        finally:
            await timeout_client.aclose()
    except httpx.TimeoutException:
        _log(f"grok vision {model} timeout after {GROK_VISION_TIMEOUT}s")
        return None
    except Exception as e:
        _log(f"grok vision {model} error: {e}")
        return None


# ─── public API ───
async def vision_describe(
    prompt: str,
    *,
    image_paths: Optional[list[str]] = None,
    image_urls: Optional[list[str]] = None,
    max_tokens: int = 600,
    cache_ttl_seconds: int = 60 * 60 * 24,  # 24h default; chart_vision overrides to 5min
    skip_cache: bool = False,
    cache_file: Optional[Path] = None,
) -> Optional[str]:
    """
    Three-layer vision pipeline (cache → local Ollama → Grok fallback).
    
    Inputs accept EITHER local file paths OR remote URLs (or both).
    URLs are downloaded once, hashed, used for both Ollama and cache key.
    
    Returns:
        str  — the description text
        None — both layers failed (logged; caller should handle)
    """
    image_paths = image_paths or []
    image_urls = image_urls or []
    cache_file = cache_file or DEFAULT_CACHE_FILE
    
    if not image_paths and not image_urls:
        _log("no images provided")
        return None
    
    # Resolve all images to bytes
    image_bytes_list: list[bytes] = []
    
    for p in image_paths:
        try:
            with open(p, "rb") as f:
                image_bytes_list.append(f.read())
        except Exception as e:
            _log(f"failed to load image {p}: {e}")
    
    if image_urls:
        url_client = httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            for url in image_urls:
                try:
                    r = await url_client.get(url)
                    if r.status_code == 200:
                        image_bytes_list.append(r.content)
                    else:
                        _log(f"failed to fetch {url} ({r.status_code})")
                except Exception as e:
                    _log(f"error fetching {url}: {e}")
        finally:
            await url_client.aclose()
    
    if not image_bytes_list:
        _log("no usable image bytes after fetch")
        return None
    
    # Cache key: prompt + sorted hashes (so order-insensitive within a single call)
    hasher = hashlib.sha256()
    hasher.update(prompt.encode("utf-8"))
    for b in image_bytes_list:
        hasher.update(hashlib.sha256(b).digest())
    cache_key = hasher.hexdigest()[:32]
    
    if not skip_cache:
        cached = _vision_cache_get(cache_key, max_age_seconds=cache_ttl_seconds, cache_file=cache_file)
        if cached:
            _log(f"cache HIT key={cache_key[:8]}")
            return cached
    
    # Provider order is a setting (VISION_PROVIDER_ORDER); first non-empty answer wins.
    result, source = None, None
    for prov in (_llmp.brain_order("VISION_PROVIDER_ORDER", vision=True) if _llmp else VISION_PROVIDER_ORDER):
        if prov == "grok":
            if not GROK_API_KEY:
                _log("grok skipped: no GROK_API_KEY")
                continue
            result = await _vision_describe_via_grok(prompt, image_bytes_list, max_tokens=max_tokens)
        elif prov == "ollama":
            result = await _vision_describe_via_ollama(prompt, image_bytes_list, max_tokens=max_tokens)
        elif _llmp:
            _t, _src = await _llmp.generate(prov, prompt, max_tokens=max_tokens, images=list(image_bytes_list or []))
            result = _t or None
            if not result:
                _log(f"{prov}: {_src}")
        if result and result.strip():
            source = prov
            break
        _log(f"{prov} failed/empty, trying next provider")
    
    if result and result.strip():
        try:
            _vision_cache_set(cache_key, result, source=source, cache_file=cache_file)
        except Exception as e:
            _log(f"cache write failed: {e}")
        _log(f"ok via {source}, key={cache_key[:8]} len={len(result)}")
        return result
    
    _log(f"BOTH layers failed key={cache_key[:8]}")
    return None


async def vision_smoke_test() -> dict:
    """Sprint 28.7 update — 2-phase smoke test:

    Phase A: /api/tags lookup → confirms model is pulled (fast, <1s)
    Phase B: /api/generate inference probe with 30s timeout
    → success means model loaded and works
    → timeout means model is COLD-LOADING (not a failure;
    first real call will warm it within its own budget)

    Sprint 28.7 PNG fix — uses 32x32 PNG (1024 pixels, above Grok's 512-pixel
    minimum). The previous 16x16 PNG (256 pixels) was rejected by Grok with
    HTTP 400 'minimum of 512 pixels'.

    Returns:
    {
    "ollama_model": "qwen2.5vl:7b",
    "grok_model": os.getenv("GROK_VISION_MODEL", "grok-4.7"),
    "ollama_registry_ok": bool,    # model pulled?
    "ollama_inference_ok": bool,   # model loads + responds within 30s?
    "ollama_status": "ready" | "cold_loading" | "not_pulled" | "daemon_down",
    "grok_ok": bool,
    "grok_response": "...",
    "tested_at": "..."
    }
    """
    BLACK_PNG_256_B64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAIAAADTED8xAAAA1UlEQVR42u3BMQEAAADCoPVP7WUL"
        "oAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAACAGwEtAAGey8LtAAAAAElFTkSuQmCC"
    )
    img_bytes = base64.b64decode(BLACK_PNG_256_B64)
    SMOKE_PROMPT = "Describe the dominant color in one word."
    
    result: dict = {
        "ollama_model": OLLAMA_VISION_MODEL,
        "grok_model": (grok_vision_models() or ["?"])[0],
        "ollama_registry_ok": False,
        "ollama_inference_ok": False,
        "ollama_status": "unknown",
        # Backwards-compat: callers checking ollama_ok still work — true if
        # either registry presence or inference passes.
        "ollama_ok": False,
        "grok_ok": False,
        "tested_at": _now_iso(),
    }
    
    # ─── Phase A: Ollama registry check (model pulled?) ───
    try:
        registry_client = httpx.AsyncClient(timeout=10)
        try:
            r = await registry_client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code != 200:
                result["ollama_status"] = "daemon_down"
                _log(f"smoke: ollama daemon unreachable ({r.status_code})")
            else:
                tags = r.json().get("models", []) or []
                model_names = [m.get("name", "") for m in tags]
                # Model match: tolerate ":latest" suffix variants
                vision_model_base = OLLAMA_VISION_MODEL.split(":")[0]
                has_model = any(
                    name == OLLAMA_VISION_MODEL or
                    name.startswith(f"{OLLAMA_VISION_MODEL}:") or
                    name.startswith(f"{vision_model_base}:")
                    for name in model_names
                )
                result["ollama_registry_ok"] = has_model
                if not has_model:
                    result["ollama_status"] = "not_pulled"
                    _log(f"smoke: ollama model {OLLAMA_VISION_MODEL} NOT PULLED — found: {model_names[:5]}")
                else:
                    _log(f"smoke: ollama registry OK — {OLLAMA_VISION_MODEL} present")
        finally:
            await registry_client.aclose()
    except httpx.TimeoutException:
        result["ollama_status"] = "daemon_down"
        _log(f"smoke: ollama /api/tags timeout — daemon may be down")
    except Exception as e:
        result["ollama_status"] = "daemon_down"
        _log(f"smoke: ollama /api/tags exception: {e}")
    
    # ─── Phase B: Ollama inference probe (only if registry passed) ───
    if result["ollama_registry_ok"]:
        SMOKE_TIMEOUT = 30
        
        images_b64 = [base64.b64encode(img_bytes).decode()]
        
        try:
            probe_client = httpx.AsyncClient(timeout=SMOKE_TIMEOUT)
            try:
                payload = {
                    "model": OLLAMA_VISION_MODEL,
                    "prompt": SMOKE_PROMPT,
                    "images": images_b64,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 20},
                }
                r = await probe_client.post(f"{OLLAMA_URL}/api/generate", json=payload)
                if r.status_code == 200:
                    response_text = (r.json().get("response") or "").strip()
                    if response_text:
                        result["ollama_inference_ok"] = True
                        result["ollama_status"] = "ready"
                        result["ollama_response"] = response_text[:80]
                        _log(f"smoke: ollama inference OK — '{response_text[:60]}'")
                    else:
                        # 200 OK with empty response — VRAM thrash
                        result["ollama_status"] = "cold_loading"
                        _log(f"smoke: ollama returned empty response — likely cold-loading or VRAM contention")
                else:
                    result["ollama_status"] = "cold_loading"
                    _log(f"smoke: ollama probe returned {r.status_code} — treating as cold-loading")
            finally:
                await probe_client.aclose()
        except httpx.TimeoutException:
            result["ollama_status"] = "cold_loading"
            _log(f"smoke: ollama inference timeout after {SMOKE_TIMEOUT}s — model is cold-loading, will warm on first real call")
        except Exception as e:
            result["ollama_status"] = "cold_loading"
            _log(f"smoke: ollama probe exception: {e} — treating as cold-loading")
    
    # Backwards-compat: ollama_ok is true if registry OR inference passed.
    # "Cold loading" still counts as OK because the first real call will warm it.
    result["ollama_ok"] = result["ollama_registry_ok"]
    
    # ─── Grok smoke test ───
    if GROK_API_KEY:
        try:
            grok_resp = await _vision_describe_via_grok(SMOKE_PROMPT, [img_bytes], max_tokens=20)
            if grok_resp:
                result["grok_ok"] = True
                result["grok_response"] = grok_resp[:80]
                _log(f"smoke: grok ({grok_vision_models()}) OK — '{grok_resp[:60]}'")
            else:
                _log(f"smoke: grok ({grok_vision_models()}) FAILED")
        except Exception as e:
            _log(f"smoke: grok exception: {e}")
    else:
        _log("smoke: grok skipped (no GROK_API_KEY)")
    
    return result