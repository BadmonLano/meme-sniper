"""Mocked-HTTP smoke for llm_providers.py (no network). python bots/test_llm_providers.py"""
import asyncio, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sub-bots"))
import httpx
import llm_providers as L

SEEN = []


def handler(req: httpx.Request) -> httpx.Response:
    body = json.loads(req.content or b"{}")
    SEEN.append((req.url.host, req.url.path, body.get("model"), "authorization" in req.headers or "x-api-key" in req.headers))
    img = False
    if req.url.path.endswith("/chat/completions"):
        c = body["messages"][-1]["content"]
        img = isinstance(c, list) and any(x.get("type") == "image_url" for x in c)
        return httpx.Response(200, json={"choices": [{"message": {"content": f"ok{'-img' if img else ''}"}}]})
    if req.url.path.endswith("/messages"):
        img = any(x.get("type") == "image" for x in body["messages"][0]["content"])
        assert req.headers.get("anthropic-version")
        return httpx.Response(200, json={"content": [{"type": "text", "text": f"ok{'-img' if img else ''}"}]})
    if req.url.path.endswith("/api/generate"):
        return httpx.Response(200, json={"response": f"ok{'-img' if body.get('images') else ''}"})
    return httpx.Response(404)


def clear():
    for k in list(os.environ):
        if k.split("_")[0] in ("GROK", "XAI", "OPENAI", "ANTHROPIC", "OLLAMA", "LLM", "VISION"):
            os.environ.pop(k)


async def main() -> int:
    res = {}
    cl = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    png = tempfile.NamedTemporaryFile(suffix=".png", delete=False); png.write(b"\x89PNG\r\n\x1a\n0000"); png.close()
    clear(); os.environ["GROK_API_KEY"] = "x" * 8
    res["default_order"] = L.order()
    res["only_grok_configured"] = [p for p in L.order() if L.configured(p)] == ["grok"]
    res["grok_text"] = await L.generate("grok", "hi", client=cl)
    res["grok_vision"] = await L.generate("grok", "hi", images=[png.name], client=cl)
    os.environ.update(OPENAI_API_KEY="k" * 8)
    res["openai_blank_model_skipped"] = not L.configured("openai")
    os.environ.update(OPENAI_MODEL="test-model")
    res["openai_text"] = await L.generate("openai", "hi", client=cl)
    res["openai_vision"] = await L.generate("openai", "hi", images=[b"\x89PNG\r\n\x1a\n00"], client=cl)
    os.environ.update(ANTHROPIC_API_KEY="a" * 8, ANTHROPIC_MODEL="test-model")
    res["anthropic_text"] = await L.generate("anthropic", "hi", system="s", client=cl)
    res["anthropic_vision"] = await L.generate("anthropic", "hi", images=[png.name], client=cl)
    os.environ.update(OPENAI_COMPAT_BASE_URL="http://compat.local/v1", OPENAI_COMPAT_MODEL="m")
    res["compat_text_no_key"] = await L.generate("openai_compat", "hi", client=cl)
    res["ollama_off_skipped"] = not L.configured("ollama")
    os.environ.update(OLLAMA_ENABLED="true")
    res["ollama_local"] = await L.generate("ollama", "hi", client=cl)
    res["ollama_vision"] = await L.generate("ollama", "hi", images=[png.name], client=cl)
    os.environ.update(OLLAMA_ENABLED="false", OLLAMA_CLOUD_ENABLED="true", OLLAMA_CLOUD_API_KEY="c" * 8)
    res["ollama_cloud"] = await L.generate("ollama", "hi", client=cl)
    os.environ["LLM_PROVIDER_ORDER"] = "claude,openai,compat,grok"
    res["order_aliases"] = L.order()
    res["chain_first"] = await L.generate_chain("hi", client=cl)
    await cl.aclose()
    hosts = sorted({h for h, *_ in SEEN})
    ok = (res["default_order"] == ["grok", "ollama"] and res["only_grok_configured"]
          and res["grok_text"][0] == "ok" and res["grok_vision"][0] == "ok-img"
          and res["openai_blank_model_skipped"] and res["openai_text"][0] == "ok" and res["openai_vision"][0] == "ok-img"
          and res["anthropic_text"][0] == "ok" and res["anthropic_vision"][0] == "ok-img"
          and res["compat_text_no_key"][0] == "ok" and res["ollama_off_skipped"]
          and res["ollama_local"][0] == "ok" and res["ollama_vision"][0] == "ok-img" and res["ollama_cloud"][0] == "ok"
          and res["order_aliases"] == ["anthropic", "openai", "openai_compat", "grok"]
          and res["chain_first"][1].startswith("anthropic:"))
    print(json.dumps({"hosts": hosts, **{k: (v if not isinstance(v, tuple) else list(v)) for k, v in res.items()}}))
    print("llm-providers smoke " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
