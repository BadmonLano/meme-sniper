"""Offline smoke: meme_sniper brain routing + gates with mocked OpenAI-only and Claude-only configs.
Pulls the real routing functions out of meme_sniper.py (no engine import, no network).
python bots/test_sniper_routing.py"""
import ast, asyncio, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "sub-bots"))
import httpx
import llm_providers as L

HITS = []


def handler(req):
    b = json.loads(req.content or b"{}")
    HITS.append(req.url.host)
    if req.url.path.endswith("/chat/completions"):
        c = b["messages"][-1]["content"]
        img = isinstance(c, list) and any(x.get("type") == "image_url" for x in c)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":1}' + ("img" if img else "")}}]})
    if req.url.path.endswith("/messages"):
        img = any(x.get("type") == "image" for x in b["messages"][0]["content"])
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"ok":1}' + ("img" if img else "")}]})
    return httpx.Response(500)


_real = L.generate
async def _mocked(name, prompt, **kw):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as cl:
        kw["client"] = cl
        return await _real(name, prompt, **kw)
L.generate = _mocked

src = open(os.path.join(HERE, "meme_sniper.py"), encoding="utf-8").read()
want = {"_llm_split", "_brain_ready", "grok_generate", "grok_generate_with_image"}
nodes = [n for n in ast.parse(src).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in want]
assert {n.name for n in nodes} == want, {n.name for n in nodes}
GROK_CALLS = []
async def _grok_text(*a, **k):      # mirrors the real xAI call: no key -> None, no HTTP
    if not ns.get("GROK_API_KEY"):
        return None
    GROK_CALLS.append("t"); return "grok"
async def _grok_img(*a, **k):
    if not ns.get("GROK_API_KEY"):
        return None
    GROK_CALLS.append("i"); return "grok"
ns = {"_llmp": L, "Optional": __import__("typing").Optional, "_LAST_TEXT_LLM_SOURCE": "",
      "_log": lambda *a, **k: None, "_grok_generate_xai": _grok_text,
      "_grok_generate_with_image_xai": _grok_img}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "meme_sniper_routing", "exec"), ns)


def env(**kv):
    for k in list(os.environ):
        if k.split("_")[0] in ("GROK", "XAI", "OPENAI", "ANTHROPIC", "OLLAMA", "LLM", "VISION"):
            os.environ.pop(k)
    os.environ.update(kv)
    ns["GROK_API_KEY"] = kv.get("GROK_API_KEY", "")


async def main():
    img = os.path.join(tempfile.mkdtemp(), "c.png")
    open(img, "wb").write(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    fails = []
    def chk(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # OpenAI-only, no LLM_PROVIDER_ORDER set (default grok,ollama)
    env(OPENAI_API_KEY="k", OPENAI_MODEL="m-test")
    HITS.clear(); GROK_CALLS.clear()
    chk("openai: text gate open", ns["_brain_ready"]())
    chk("openai: vision gate open", ns["_brain_ready"](vision=True))
    t = await ns["grok_generate"]("p", format_json=True)
    chk("openai: text routed", t == '{"ok":1}' and HITS == ["api.openai.com"] and not GROK_CALLS)
    chk("openai: source label", str(ns["_LAST_TEXT_LLM_SOURCE"]).startswith("openai"))
    HITS.clear()
    t = await ns["grok_generate_with_image"]("p", [img])
    chk("openai: vision routed", t == '{"ok":1}img' and HITS == ["api.openai.com"])

    # Claude-only
    env(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m-test")
    HITS.clear(); GROK_CALLS.clear()
    chk("claude: text gate open", ns["_brain_ready"]())
    chk("claude: vision gate open", ns["_brain_ready"](vision=True))
    t = await ns["grok_generate"]("p")
    chk("claude: text routed", t == '{"ok":1}' and HITS == ["api.anthropic.com"] and not GROK_CALLS)
    HITS.clear()
    t = await ns["grok_generate_with_image"]("p", [img])
    chk("claude: vision routed", t == '{"ok":1}img' and HITS == ["api.anthropic.com"])

    # Grok-only: unchanged (Grok path only, no other HTTP)
    env(GROK_API_KEY="k")
    HITS.clear(); GROK_CALLS.clear()
    chk("grok: gate open", ns["_brain_ready"]() and ns["_brain_ready"](vision=True))
    t = await ns["grok_generate"]("p")
    chk("grok: grok path only", t == "grok" and GROK_CALLS == ["t"] and not HITS)
    chk("grok: order unchanged", L.brain_order() == ["grok", "ollama"])

    # Nothing configured / Ollama only: cloud gates closed
    env()
    chk("none: gate closed", not ns["_brain_ready"]() and not ns["_brain_ready"](vision=True))
    env(OLLAMA_ENABLED="true")
    chk("ollama-only: cloud gate closed (Ollama path is the caller's fallback)", not ns["_brain_ready"]())
    chk("ollama-only: any_configured incl. ollama", L.any_configured(include_ollama=True))

    # Explicit order respected
    env(OPENAI_API_KEY="k", OPENAI_MODEL="m", ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m", LLM_PROVIDER_ORDER="anthropic,ollama")
    HITS.clear()
    await ns["grok_generate"]("p")
    chk("order: anthropic first", HITS[:1] == ["api.anthropic.com"])
    print("ALL PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0

sys.exit(asyncio.run(main()))
