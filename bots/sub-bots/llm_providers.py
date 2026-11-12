"""llm_providers.py: one small, provider-agnostic LLM layer (plain httpx, no SDKs).

Providers: grok (default, recommended), openai, anthropic, ollama (local, optional cloud),
openai_compat (any OpenAI-compatible endpoint with a custom base URL).
Choice: LLM_MAIN (one of the providers) and LLM_FALLBACK (one of them, or none). Defaults in the
template: main=grok, fallback=ollama. When LLM_MAIN is set it wins: the text and vision order is
[main, fallback] and every other provider is OFF even if its key is set (apply_choice() also drops
their keys from this process so no direct call can reach them; the .env file is never changed).
Legacy: with LLM_MAIN unset, LLM_PROVIDER_ORDER (text) and VISION_PROVIDER_ORDER (images), comma
lists, default "grok,ollama", work as before. A provider with no key/model set is skipped.
Ollama cloud stays an opt-in tier under ollama (OLLAMA_CLOUD_ENABLED + key).

Env (all optional except what your chosen provider needs):
  grok          GROK_API_KEY (or XAI_API_KEY), GROK_TEXT_MODEL (grok-4.7), GROK_VISION_MODEL, GROK_API_BASE
  openai        OPENAI_API_KEY, OPENAI_MODEL, OPENAI_VISION_MODEL (defaults to OPENAI_MODEL), OPENAI_BASE_URL
  anthropic     ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_VISION_MODEL (defaults to ANTHROPIC_MODEL)
  openai_compat OPENAI_COMPAT_BASE_URL, OPENAI_COMPAT_API_KEY, OPENAI_COMPAT_MODEL, OPENAI_COMPAT_VISION_MODEL
  ollama        OLLAMA_ENABLED, OLLAMA_URL, OLLAMA_MODEL, OLLAMA_VISION_MODEL;
                OLLAMA_CLOUD_ENABLED, OLLAMA_CLOUD_URL, OLLAMA_CLOUD_API_KEY, OLLAMA_CLOUD_MODEL
Model names for openai / anthropic / openai_compat ship blank on purpose: pick a current one.
Never logs keys.
"""
from __future__ import annotations

import base64
import mimetypes
import os
from typing import Optional

import httpx

PROVIDERS = ("grok", "openai", "anthropic", "ollama", "openai_compat")


def _e(k: str, d: str = "") -> str:
    return (os.getenv(k) or d).strip()


def _on(k: str) -> bool:
    return _e(k, "false").lower() in ("1", "true", "yes", "on")


_ALIAS = {"xai": "grok", "claude": "anthropic", "compat": "openai_compat", "custom": "openai_compat",
          "openai-compat": "openai_compat", "local": "ollama"}
# secrets / endpoints that make a provider callable; dropped from os.environ when it is not selected
PROVIDER_KEYS = {
    "grok": ("GROK_API_KEY", "XAI_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai_compat": ("OPENAI_COMPAT_API_KEY", "OPENAI_COMPAT_BASE_URL"),
}


def _norm(p) -> str:
    p = str(p or "").strip().lower().replace("-", "_")
    return _ALIAS.get(p, p)


def choice(env=None):
    """(main, fallback) from LLM_MAIN / LLM_FALLBACK, or None when LLM_MAIN is unset (legacy order).
    fallback is '' for none. Unknown names: main falls back to grok, fallback to none."""
    env = os.environ if env is None else env
    m = _norm(env.get("LLM_MAIN"))
    if not m:
        return None
    if m not in PROVIDERS:
        m = "grok"
    f = _norm(env.get("LLM_FALLBACK", "ollama") if "LLM_FALLBACK" in env else "ollama")
    if f in ("", "none", "off", "0", "false", "no") or f not in PROVIDERS or f == m:
        f = ""
    return m, f


def selected(env=None) -> list:
    """Providers allowed to run: [main, fallback] when chosen, else every provider (legacy)."""
    c = choice(env)
    if not c:
        return list(PROVIDERS)
    return [p for p in c if p]


def apply_choice(env=None) -> Optional[list]:
    """Make LLM_MAIN / LLM_FALLBACK authoritative for this process (call right after load_dotenv).
    Sets LLM_PROVIDER_ORDER / VISION_PROVIDER_ORDER to [main, fallback], turns Ollama on only when
    it is selected (cloud stays opt-in), and removes the keys of unselected providers from the
    process env. Never writes the .env file. Returns the selection, or None in legacy mode."""
    env = os.environ if env is None else env
    c = choice(env)
    if not c:
        return None
    sel = [p for p in c if p]
    env["LLM_PROVIDER_ORDER"] = ",".join(sel)
    env["VISION_PROVIDER_ORDER"] = ",".join(sel)
    if "ollama" in sel:
        env["OLLAMA_ENABLED"] = "true"
    else:
        env["OLLAMA_ENABLED"] = "false"
        env["OLLAMA_CLOUD_ENABLED"] = "false"
    for p, keys in PROVIDER_KEYS.items():
        if p not in sel:
            for k in keys:
                env.pop(k, None)
    return sel


def order(var: str = "LLM_PROVIDER_ORDER", default: str = "grok,ollama") -> list:
    if choice() and var in ("LLM_PROVIDER_ORDER", "VISION_PROVIDER_ORDER"):
        return selected()
    out = []
    for p in _e(var, default).lower().split(","):
        p = _norm(p)
        if p in PROVIDERS and p not in out:
            out.append(p)
    return out or ["grok", "ollama"]


def cfg(name: str, vision: bool = False) -> dict:
    """Resolved settings for one provider; {} when it is not configured or not selected."""
    if name not in selected():
        return {}
    if name == "grok":
        key = _e("GROK_API_KEY") or _e("XAI_API_KEY")
        m = _e("GROK_VISION_MODEL", "grok-4.7") if vision else _e("GROK_TEXT_MODEL", "grok-4.7")
        if m == "auto":
            m = "grok-4.7"
        return {"kind": "openai", "base": _e("GROK_API_BASE", "https://api.x.ai/v1"), "key": key, "model": m} if key else {}
    if name == "openai":
        key, m = _e("OPENAI_API_KEY"), (_e("OPENAI_VISION_MODEL") or _e("OPENAI_MODEL")) if vision else _e("OPENAI_MODEL")
        return {"kind": "openai", "base": _e("OPENAI_BASE_URL", "https://api.openai.com/v1"), "key": key, "model": m} if key and m else {}
    if name == "openai_compat":
        base = _e("OPENAI_COMPAT_BASE_URL").rstrip("/")
        m = (_e("OPENAI_COMPAT_VISION_MODEL") or _e("OPENAI_COMPAT_MODEL")) if vision else _e("OPENAI_COMPAT_MODEL")
        return {"kind": "openai", "base": base, "key": _e("OPENAI_COMPAT_API_KEY"), "model": m} if base and m else {}
    if name == "anthropic":
        key = _e("ANTHROPIC_API_KEY")
        m = (_e("ANTHROPIC_VISION_MODEL") or _e("ANTHROPIC_MODEL")) if vision else _e("ANTHROPIC_MODEL")
        return {"kind": "anthropic", "base": _e("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"), "key": key, "model": m} if key and m else {}
    if name == "ollama":
        tiers = []
        if _on("OLLAMA_ENABLED"):
            tiers.append({"base": _e("OLLAMA_URL", "http://localhost:11434").rstrip("/"), "key": "",
                          "model": _e("OLLAMA_VISION_MODEL", "qwen2.5vl:7b") if vision else _e("OLLAMA_MODEL", "qwen3:14b-q4_K_M")})
        if _on("OLLAMA_CLOUD_ENABLED") and _e("OLLAMA_CLOUD_API_KEY") and not vision:
            tiers.append({"base": _e("OLLAMA_CLOUD_URL", "https://ollama.com").rstrip("/"), "key": _e("OLLAMA_CLOUD_API_KEY"),
                          "model": _e("OLLAMA_CLOUD_MODEL", "deepseek-v4-pro:cloud")})
        return {"kind": "ollama", "tiers": tiers} if tiers else {}
    return {}


def configured(name: str, vision: bool = False) -> bool:
    return bool(cfg(name, vision))


def brain_order(var: str = "LLM_PROVIDER_ORDER", vision: bool = False) -> list:
    """order(var) plus any configured provider the order left out, slotted before 'ollama'.
    So an owner who only sets OPENAI_* / ANTHROPIC_* / OPENAI_COMPAT_* gets a brain without
    touching LLM_PROVIDER_ORDER. Only-Grok setups: unchanged."""
    o = order(var)
    if choice():
        return o          # explicit main/fallback: nothing else is slotted in
    extra = [p for p in PROVIDERS if p not in o and p != "ollama" and configured(p, vision)]
    if not extra:
        return o
    i = o.index("ollama") if "ollama" in o else len(o)
    return o[:i] + extra + o[i:]


def any_configured(vision: bool = False, var: Optional[str] = None, include_ollama: bool = False,
                   skip: tuple = ()) -> bool:
    """True when at least one provider in the (brain) order is usable for text (or images)."""
    var = var or ("VISION_PROVIDER_ORDER" if vision else "LLM_PROVIDER_ORDER")
    return any(configured(p, vision) for p in brain_order(var, vision)
               if p not in skip and (include_ollama or p != "ollama"))


def _img_b64(p):
    """p = file path or raw bytes."""
    if isinstance(p, (bytes, bytearray)):
        b = bytes(p)
        mt = "image/jpeg" if b[:3] == b"\xff\xd8\xff" else ("image/webp" if b[8:12] == b"WEBP" else "image/png")
        return base64.b64encode(b).decode("ascii"), mt
    with open(p, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return data, (mimetypes.guess_type(p)[0] or "image/png")


async def generate(name: str, prompt: str, *, max_tokens: int = 800, temperature: float = 0.3,
                   json_mode: bool = False, system: Optional[str] = None, images: Optional[list] = None,
                   timeout: float = 60.0, client: Optional[httpx.AsyncClient] = None):
    """Returns (text, model) or ("", reason). Never raises. images = file paths or raw bytes."""
    c = cfg(name, vision=bool(images))
    if not c:
        return "", f"{name} not configured"
    own = client is None
    cl = client or httpx.AsyncClient(timeout=timeout)
    try:
        imgs = [_img_b64(p) for p in (images or []) if isinstance(p, (bytes, bytearray)) or (p and os.path.exists(p))]
        if images and not imgs:
            return "", "no readable images"
        if c["kind"] == "openai":
            content = prompt if not imgs else [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{b}"}} for b, mt in imgs]
            msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
            body = {"model": c["model"], "messages": msgs, "max_tokens": int(max_tokens), "temperature": temperature}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            h = {"Content-Type": "application/json"}
            if c["key"]:
                h["Authorization"] = f"Bearer {c['key']}"
            r = await cl.post(f"{c['base'].rstrip('/')}/chat/completions", headers=h, json=body)
            if r.status_code != 200:
                return "", f"{name} HTTP {r.status_code}"
            t = ((((r.json().get("choices") or [{}])[0]).get("message") or {}).get("content") or "")
            if isinstance(t, list):
                t = "".join(x.get("text", "") for x in t if isinstance(x, dict))
            t = str(t).strip()
            return (t, f"{name}:{c['model']}") if t else ("", f"{name} empty")
        if c["kind"] == "anthropic":
            content = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": b}} for b, mt in imgs]
            content.append({"type": "text", "text": prompt + ("\nReply with JSON only." if json_mode else "")})
            body = {"model": c["model"], "max_tokens": int(max_tokens), "temperature": temperature,
                    "messages": [{"role": "user", "content": content}]}
            if system:
                body["system"] = system
            r = await cl.post(f"{c['base'].rstrip('/')}/messages", json=body,
                              headers={"x-api-key": c["key"], "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"})
            if r.status_code != 200:
                return "", f"{name} HTTP {r.status_code}"
            t = "".join(b.get("text", "") for b in (r.json().get("content") or []) if b.get("type") == "text").strip()
            return (t, f"{name}:{c['model']}") if t else ("", f"{name} empty")
        if c["kind"] == "ollama":
            last = "ollama failed"
            for tier in c["tiers"]:
                body = {"model": tier["model"], "prompt": (system + "\n\n" + prompt) if system else prompt,
                        "stream": False, "options": {"num_predict": int(max_tokens), "temperature": temperature}}
                if json_mode:
                    body["format"] = "json"
                if imgs:
                    body["images"] = [b for b, _ in imgs]
                h = {"Authorization": f"Bearer {tier['key']}"} if tier["key"] else {}
                try:
                    r = await cl.post(f"{tier['base']}/api/generate", json=body, headers=h)
                except Exception as e:
                    last = f"ollama {type(e).__name__}"; continue
                if r.status_code == 200:
                    t = (r.json().get("response") or "").strip()
                    if t:
                        return t, f"ollama:{tier['model']}"
                last = f"ollama HTTP {r.status_code}"
            return "", last
        return "", "unknown kind"
    except Exception as e:
        return "", f"{name} {type(e).__name__}"
    finally:
        if own:
            await cl.aclose()


async def generate_chain(prompt: str, *, providers: Optional[list] = None, skip: tuple = (), **kw):
    """First non-empty answer along the order. Returns (text, model) or ("", reasons)."""
    why = []
    for p in (providers or order()):
        if p in skip:
            continue
        t, m = await generate(p, prompt, **kw)
        if t:
            return t, m
        why.append(m)
    return "", "; ".join(why) or "no provider configured"
