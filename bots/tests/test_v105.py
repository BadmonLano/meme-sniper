"""v1.0.5 celeb_post cards + x_celeb_watch. No network: fake X API + fake enrich."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sub-bots"))
import celeb_card as cc      # noqa: E402
import x_celeb_watch as xw   # noqa: E402

CA = "Gjd3JUbNG2C3n5Ww98SfPxyWaqvDk2BkiKongGwEpump"   # FLOYD (public)


def resp(followers=6_800_000, verified=True, text=f"hello @fomo {CA}", tid="2110070647737155629"):
    return {"data": [{"id": tid, "author_id": "u1", "text": text, "created_at": "2026-10-13T18:10:20Z"}],
            "includes": {"users": [{"id": "u1", "username": "FloydMayweather", "verified": verified,
                                    "public_metrics": {"followers_count": followers}}]}}


def test_find_cas():
    assert cc.find_cas(f"buy {CA} now https://x.com/a") == [CA]
    assert cc.find_cas("no address here") == []


def test_posts_filter_celeb_only():
    assert len(xw.posts_from_response(resp())) == 1
    assert xw.posts_from_response(resp(followers=1000)) == []
    assert xw.posts_from_response(resp(verified=False)) == []
    assert xw.posts_from_response(resp(text="gm")) == []


def _run(tmp_path, monkeypatch, get, enrich=None):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("CELEB_WATCH_HANDLES", "")
    async def no_enrich(p, c):
        return None, None
    st = {"seen": {}}
    n = asyncio.run(xw.cycle("t", st, get=get, enrich=enrich or no_enrich, now=1760378000))
    return n, st


def test_cycle_emits_once_and_dedupes(tmp_path, monkeypatch):
    get = lambda path, params, tok: resp() if "search" in path else {"data": {"id": "x"}}
    n, st = _run(tmp_path, monkeypatch, get)
    assert n == 1
    card = cc.load_cards(tmp_path / "json_relay")[0]
    assert card["schema"] == "celeb_post_card/1" and card["decision"] == "agent"
    assert card["celeb_post"]["handle"] == "FloydMayweather" and card["ca"] == CA
    assert card["context"]["funding_cluster"] == "unknown" and card["context"]["creator_sold"] is None
    n2 = asyncio.run(xw.cycle("t", st, get=get, enrich=lambda p, c: asyncio.sleep(0, (None, None)), now=1760378100))
    assert n2 == 0


def test_cycle_enriched_floyd_veto(tmp_path, monkeypatch):
    async def enrich(p, c):
        return ({"creator": "FuJB", "creator_balance_pct": 0.0},
                {"enter": False, "veto": True, "wait": False,
                 "reason": "veto: creator funded pre-launch by fan-out wallet busy… (5 wallets in one tx)"})
    get = lambda path, params, tok: resp() if "search" in path else {"data": {"id": "x"}}
    _run(tmp_path, monkeypatch, get, enrich)
    ctx = cc.load_cards(tmp_path / "json_relay")[0]["context"]
    assert ctx["funding_cluster"] == "fanout_funder" and ctx["creator_sold"] is True


def test_rate_limit_and_errors_fail_safe(tmp_path, monkeypatch):
    def rl(path, params, tok):
        raise xw.RateLimited(1760379000)
    n, st = _run(tmp_path, monkeypatch, rl)
    assert n == 0 and st["next_ok_ts"] == 1760379000
    assert asyncio.run(xw.cycle("t", st, get=rl, now=1760378500)) == 0     # still waiting
    def boom(path, params, tok):
        raise RuntimeError("x down")
    n, _ = _run(tmp_path, monkeypatch, boom)
    assert n == 0 and cc.load_cards(tmp_path / "json_relay") == []


def test_deleted_flag_and_shill_history(tmp_path):
    rd = tmp_path / "json_relay"
    p = {"handle": "FloydMayweather", "followers": 1, "verified": True, "post_id": "1", "posted_ts": 1}
    cc.emit_card(rd, cc.build_card(p, "AAA", []))
    c2 = cc.build_card({**p, "post_id": "2"}, "BBB", cc.load_cards(rd))
    assert c2["context"]["shill_history"]["prior_cards"] == 1
    assert cc.mark_deleted(rd, "1") == 1
    assert cc.load_cards(rd)[0]["context"]["post_deleted"] is True
