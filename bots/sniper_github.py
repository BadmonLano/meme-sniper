"""sniper_github.py - GitHub helper imported by meme_sniper.py (not a standalone bot).

Pieces:
  1. Repo attacher   resolve_repo(req): github_user -> pick public repo; fallback pasted link; else no repo.
  2. Contributions   suggestion files / PRs -> review queue -> reviewer inbox note -> approve/reject.
                     Approve = credit + version bump + changelog + release plan. NO auto-merge, NO auto-pull.
  3. Repo uploader   folder -> staging copy + MIT LICENSE + blank .env.example + .gitignore + scans.
Nothing here pushes, commits, tags or creates repos unless `publish ... --owner-ok` is run by hand.
Secrets are never printed. GITHUB_TOKEN is used only if set, only as a header.
"""
from __future__ import annotations
import json, os, re, shutil, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path
try:
    from dotenv import load_dotenv; load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

WS = Path(os.getenv("WORKSPACE_DIR") or Path(__file__).resolve().parent.parent)
RELAY = WS / "json_relay"
LOGS = Path(os.getenv("SNIPER_LOGS_DIR") or (WS / "bot_logs"))
REVIEWER_INBOX = WS / "inbox"   # the reviewing agent's inbox
REVIEW = LOGS / "repo_review"
SUGGEST_IN = RELAY / "repo_suggestions"
DECISIONS_IN = RELAY / "repo_decisions"
AGENT_INBOX = RELAY / "agent_inbox"
DROPS = WS / "repo_drops"
UPLOADS = LOGS / "repo_uploads"
CFG_FILE = LOGS / "sniper_github_config.json"
API = "https://api.github.com"
_GH_RE = re.compile(r"^https?://(www\.)?github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})/?(\.git)?$")

DEFAULT_CFG = {
    "suggest_daily_cap": 3,                 # per wallet OR github account per day
    "our_owner": "",                        # OUR GitHub owner/org for publish plans
    "denylist_paths": [                     # uploader blocks these (case-insensitive substring of rel path)
        "bot_logs", "wallets", "keypair", "id.json", ".ssh", "memory/", "owner_inbox",
        "backups/", "_staging",                 # add your own private folders in sniper_github_config.json
    ],
    "default_topics": ["solana", "si-agents", "trading-bot", "open-source", "bentayga-empire"],
    "license_holder": "Bentayga Empire LLC",
}


def cfg() -> dict:
    c = dict(DEFAULT_CFG)
    try:
        c.update(json.loads(CFG_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    if os.getenv("SNIPER_SUGGEST_DAILY_CAP"):
        c["suggest_daily_cap"] = int(os.environ["SNIPER_SUGGEST_DAILY_CAP"])
    return c


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _wjson(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, p)
    return p


def _rjson(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _append(p: Path, row: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _safe(s, n=40) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(s or ""))[:n] or "x"


# ------------------------------------------------------------------ 1. GitHub read API
def _gh_get(path: str, timeout=15):
    """GET public API. Returns (status, json|None). Token used only if present; never logged."""
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": "sniper-github"})
    tok = auth_token() or os.getenv("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


# ------------------------------------------------------------------ 0. GitHub sign-in (OAuth Device Flow)
# User gets a short code, opens github.com/login/device, approves. No passwords ever touch Sniper.
# Token lives in Windows Credential Manager (keyring) or, if keyring is missing, a user-only file
# under bot_logs (ACL locked to the current user). The token is never printed or logged.
AUTH_META = LOGS / "github_auth.json"          # non-secret: login, scopes, storage, signed_in_at
AUTH_FILE = LOGS / "github_auth.token"         # fallback store only
KR_SERVICE, KR_USER = "sniper_github", "oauth_token"
SETUP_HELP = (
    "GitHub sign-in isn't set up yet (GITHUB_OAUTH_CLIENT_ID is blank in .env).\n"
    "One-time setup by the bot owner:\n"
    "  1. Open https://github.com/settings/developers -> OAuth Apps -> New OAuth App.\n"
    "  2. Name: Sniper. Homepage URL: your repo or site. Callback URL: same URL (not used).\n"
    "  3. Tick 'Enable Device Flow', click Register.\n"
    "  4. Copy the Client ID (it is public, no secret needed) into .env: GITHUB_OAUTH_CLIENT_ID=...\n"
    "Until then Sniper works as before: type a username or paste a repo link.")


def _kr():
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def _lock_file(path: Path) -> None:
    if os.name == "nt":
        import subprocess
        u = os.environ.get("USERNAME", "")
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{u}:(R,W)"],
                       capture_output=True, check=False)
    else:
        os.chmod(path, 0o600)


def _store_token(tok: str) -> str:
    kr = _kr()
    if kr:
        try:
            kr.set_password(KR_SERVICE, KR_USER, tok)
            return "windows_credential_manager" if os.name == "nt" else "keyring"
        except Exception:
            pass
    LOGS.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(tok, encoding="utf-8")
    _lock_file(AUTH_FILE)
    return "user_only_file"


_TOK_CACHE: dict = {}


def auth_token() -> str | None:
    if os.getenv("SNIPER_GH_NO_LOGIN") == "1":
        return None
    if "t" in _TOK_CACHE:
        return _TOK_CACHE["t"]
    tok = None
    kr = _kr()
    if kr:
        try:
            tok = kr.get_password(KR_SERVICE, KR_USER)
        except Exception:
            tok = None
    if not tok and AUTH_FILE.exists():
        tok = AUTH_FILE.read_text(encoding="utf-8").strip() or None
    _TOK_CACHE["t"] = tok
    return tok


def _post_form(url: str, data: dict, timeout=15) -> dict:
    import urllib.parse
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Accept": "application/json", "User-Agent": "sniper-github"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return {"error": f"http_{e.code}"}
    except Exception as e:
        return {"error": f"network: {type(e).__name__}"}


def login(private: bool = False, say=print, open_browser: bool = True, public: bool = False) -> dict:
    """Device Flow. Default scope '' = read public data only. private=True asks for 'repo' (needed to list
    your own private repos; GitHub has no read-only private scope)."""
    cid = (os.getenv("GITHUB_OAUTH_CLIENT_ID") or "").strip()
    if not cid:
        say(SETUP_HELP)
        return {"ok": False, "reason": "no_client_id", "fallback": "username_or_link"}
    # default read-only; public=True asks for public_repo (create/push PUBLIC repos only); private=True asks for repo
    scope = "repo" if private else ("public_repo" if public else "")
    d = _post_form("https://github.com/login/device/code", {"client_id": cid, "scope": scope})
    if "device_code" not in d:
        say(f"GitHub sign-in couldn't start ({d.get('error', 'unknown')}). Check Device Flow is enabled on the OAuth App.")
        return {"ok": False, "reason": d.get("error", "device_code_failed")}
    say(f"Open {d['verification_uri']} and enter code:  {d['user_code']}")
    say("Waiting for you to approve (Ctrl+C to cancel)...")
    if open_browser:
        try:
            import webbrowser; webbrowser.open(d["verification_uri"])
        except Exception:
            pass
    interval, deadline = int(d.get("interval", 5)), time.time() + int(d.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(interval)
        t = _post_form("https://github.com/login/oauth/access_token",
                       {"client_id": cid, "device_code": d["device_code"],
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        err = t.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval = int(t.get("interval", interval + 5)); continue
        if err:
            say({"expired_token": "Code expired. Run login again.",
                 "access_denied": "You cancelled on GitHub. Nothing saved."}.get(err, f"Sign-in failed ({err})."))
            return {"ok": False, "reason": err}
        tok = t.get("access_token")
        if not tok:
            return {"ok": False, "reason": "no_token"}
        where = _store_token(tok)
        _TOK_CACHE["t"] = tok
        st, me = _gh_get("/user")
        user = (me or {}).get("login", "") if st == 200 else ""
        _wjson(AUTH_META, {"login": user, "scopes": t.get("scope", ""), "private_repos": bool(private),
                           "storage": where, "signed_in_at": _now()})
        say(f"Signed in to GitHub as {user or '?'}. Saved securely ({where}). You stay signed in until you log out.")
        return {"ok": True, "login": user, "storage": where, "scopes": t.get("scope", "")}
    say("Timed out waiting for approval. Run login again.")
    return {"ok": False, "reason": "timeout"}


def logout(say=print) -> dict:
    removed = []
    kr = _kr()
    if kr:
        try:
            kr.delete_password(KR_SERVICE, KR_USER); removed.append("credential_manager")
        except Exception:
            pass
    if AUTH_FILE.exists():
        AUTH_FILE.unlink(); removed.append("file")
    if AUTH_META.exists():
        AUTH_META.unlink()
    _TOK_CACHE.clear()
    say("Signed out on this PC. To fully revoke Sniper's access, open "
        "https://github.com/settings/applications -> Authorized OAuth Apps -> Sniper -> Revoke.")
    return {"ok": True, "removed": removed}


def whoami(check_live: bool = True) -> dict:
    meta = _rjson(AUTH_META, {}) or {}
    has = bool(auth_token())
    out = {"signed_in": has, "login": meta.get("login", ""), "scopes": meta.get("scopes", ""),
           "private_repos": meta.get("private_repos", False), "storage": meta.get("storage", ""),
           "signed_in_at": meta.get("signed_in_at", ""),
           "client_id_set": bool((os.getenv("GITHUB_OAUTH_CLIENT_ID") or "").strip())}
    if has and not out["login"] and not check_live:   # login missing from cache: look it up once and save it
        st, me = _gh_get("/user")
        if st == 200 and (me or {}).get("login"):
            out["login"] = me["login"]
            meta.update(login=me["login"])
            try:
                _wjson(AUTH_META, meta)
            except Exception:
                pass
    if has and check_live:
        st, me = _gh_get("/user")
        out["token_valid"] = st == 200
        if st == 200:
            out["login"] = me.get("login", out["login"])
        elif st == 401:
            out["note"] = "Saved sign-in was revoked or expired. Run logout, then login."
    return out


def list_my_repos(include_private: bool = False, limit=30) -> dict:
    """Signed-in user's own repos. Private ones only if include_private and the token has 'repo' scope."""
    if not auth_token():
        return {"ok": False, "reason": "not_signed_in", "repos": []}
    vis = "all" if include_private else "public"
    st, j = _gh_get(f"/user/repos?affiliation=owner&visibility={vis}&sort=pushed&per_page={limit}")
    if st in (403, 429):
        return {"ok": False, "reason": "rate_limited", "repos": []}
    if st != 200 or not isinstance(j, list):
        return {"ok": False, "reason": f"api_http_{st}", "repos": []}
    repos = [{"name": r.get("name"), "url": r.get("html_url"), "description": r.get("description") or "",
              "stars": r.get("stargazers_count", 0), "fork": r.get("fork"), "pushed_at": r.get("pushed_at"),
              "private": bool(r.get("private"))}
             for r in j if include_private or not r.get("private")]
    return {"ok": True, "reason": "ok", "repos": repos}


def gh_cli_status() -> dict:
    """Status only: is the real GitHub CLI installed / logged in. Never reads or prints tokens."""
    import subprocess
    exe = shutil.which("gh")
    if not exe:
        return {"installed": False}
    try:
        v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        real = "github.com/cli" in (v.stdout + v.stderr) or (v.stdout.startswith("gh version"))
        if not real:
            return {"installed": False, "note": f"'{exe}' is not the GitHub CLI (likely the npm 'gh' package)"}
        a = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=15)
        return {"installed": True, "logged_in": a.returncode == 0}
    except Exception as e:
        return {"installed": True, "error": type(e).__name__}


def list_public_repos(user: str, limit=30) -> dict:
    user = (user or "").strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", user):
        return {"ok": False, "reason": "bad_username", "repos": []}
    st, j = _gh_get(f"/users/{user}/repos?type=owner&sort=pushed&per_page={limit}")
    if st == 403 or st == 429:
        return {"ok": False, "reason": "rate_limited", "repos": []}
    if st != 200 or not isinstance(j, list):
        return {"ok": False, "reason": f"api_http_{st}", "repos": []}
    repos = [{"name": r.get("name"), "url": r.get("html_url"), "description": r.get("description") or "",
              "stars": r.get("stargazers_count", 0), "fork": r.get("fork"), "pushed_at": r.get("pushed_at")}
             for r in j if not r.get("private")]
    return {"ok": True, "reason": "ok", "repos": repos}


def validate_repo_link(url: str) -> dict:
    m = _GH_RE.match((url or "").strip())
    if not m:
        return {"ok": False, "reason": "not_github_repo_url"}
    owner, name = m.group(2), m.group(3).removesuffix(".git")
    st, j = _gh_get(f"/repos/{owner}/{name}")
    if st == 200 and isinstance(j, dict) and not j.get("private"):
        return {"ok": True, "url": j.get("html_url"), "description": j.get("description") or "",
                "stars": j.get("stargazers_count", 0), "reason": "resolved"}
    if st in (403, 429, 0):   # can't verify right now: keep the well-formed link, flag it
        return {"ok": True, "url": f"https://github.com/{owner}/{name}", "description": "", "stars": None,
                "reason": "unverified_api_unavailable"}
    return {"ok": False, "reason": f"repo_not_found_http_{st}"}


def resolve_repo(req: dict, chooser=None) -> dict:
    """Attach a repo to a launch request. Never blocks a launch.
    Order: github_user (+ repo_pick name/index or chooser) -> pasted repo_url -> no repo.
    Returns {"source", "repo_url", "repo_description", "repo_stars", "notes"}; mutates nothing."""
    notes = []
    user = req.get("github_user") or req.get("github_username")
    if user:
        lst = list_public_repos(user)
        if lst["ok"] and lst["repos"]:
            pick = None
            want = req.get("repo_pick")
            if want is not None:
                for i, r in enumerate(lst["repos"], 1):
                    if str(want) == str(i) or str(want).lower() == str(r["name"]).lower():
                        pick = r; break
            if pick is None and chooser:
                pick = chooser(lst["repos"])
            if pick is None and len(lst["repos"]) == 1:
                pick = lst["repos"][0]
            if pick:
                return {"source": "github_user", "repo_url": pick["url"], "repo_description": pick["description"],
                        "repo_stars": pick["stars"], "notes": notes}
            notes.append("github_user given but no repo picked")
        else:
            notes.append(f"github_user lookup failed: {lst['reason']}")
    if req.get("repo_url"):
        v = validate_repo_link(req["repo_url"])
        if v["ok"]:
            return {"source": "pasted_link", "repo_url": v["url"], "repo_description": v["description"],
                    "repo_stars": v["stars"], "notes": notes + [v["reason"]]}
        notes.append(f"pasted link rejected: {v['reason']}")
    return {"source": "none", "repo_url": "", "repo_description": "", "repo_stars": None,
            "notes": notes + ["launch proceeds without a repo"]}


# ------------------------------------------------------------------ 2. contributions
def invite_agent(agent: str, repo_url: str, ticker: str = "") -> Path | None:
    """Drop an invite in the launching agent's inbox. the reviewer's is workspace/inbox."""
    if not repo_url:
        return None
    agent = _safe(agent or "agent")
    d = REVIEWER_INBOX if agent.lower().startswith(os.getenv("SNIPER_REVIEWER", "reviewer").lower()) else AGENT_INBOX / agent
    body = (f"# Want to improve this repo?\n\nRepo: {repo_url}\n\n"
            "If you see a fix or upgrade, send it one of two ways:\n"
            f"1. Open a pull request on {repo_url}\n"
            f"2. Write a JSON file to json_relay/repo_suggestions/ with: "
            '{"repo": "<url>", "github_user": "<you>", "wallet": "<your wallet>", "title": "...", '
            '"body": "what and why", "pr_url": "<optional>", "patch": "<optional unified diff>"}\n\n'
            f"Limit: {cfg()['suggest_daily_cap']} suggestions per wallet/GitHub account per day.\n"
            "Every suggestion is reviewed by the owner's agent. Nothing merges automatically. Your own copy/fork is never "
            "changed by us; pull our updates only when you choose.\n")
    p = d / f"meme_sniper - repo_invite_{_safe(ticker or 'repo', 16)}_{_ts()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _rate_ok(wallet: str, gh: str) -> bool:
    cap = int(cfg()["suggest_daily_cap"])
    day = datetime.now().strftime("%Y-%m-%d")
    n = 0
    for line in (REVIEW / "intake.jsonl").read_text(encoding="utf-8").splitlines() if (REVIEW / "intake.jsonl").exists() else []:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("day") == day and r.get("accepted") and (
                (wallet and r.get("wallet") == wallet) or (gh and r.get("github_user") == gh)):
            n += 1
    return n < cap


def _reviewer_note(item: dict) -> Path:
    p = REVIEWER_INBOX / f"meme_sniper - repo_suggestion_{item['id']}_{_ts()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"# Repo suggestion to review: {item['id']}\n\n"
        f"- Repo: {item.get('repo')}\n- From: GitHub `{item.get('github_user') or '?'}`, wallet "
        f"`{item.get('wallet') or '?'}`\n- Kind: {item['kind']}\n- PR: {item.get('pr_url') or 'none'}\n"
        f"- Title: {item.get('title')}\n\n{(item.get('body') or '')[:3000]}\n\n"
        f"Patch attached: {'yes, see queue file' if item.get('patch') else 'no'}\n"
        f"Queue file: bots/bot_logs/repo_review/queue/{item['id']}.json\n\n"
        "## Decide\nWrite `json_relay/repo_decisions/" + item["id"] + ".json` with\n"
        '`{"decision": "approve" | "reject", "by": "reviewer", "reason": "...", "bump": "minor" | "patch" | "major"}`\n'
        f"or run `python bots/sniper_github.py review approve|reject {item['id']} --by reviewer --reason \"...\"`.\n"
        "Approve only records credit, bumps the version and prepares a release. Nothing is pushed until the owner OKs it.\n",
        encoding="utf-8")
    return p



def _agent_memo(kind, ok, summary, **kw):
    """Loop closure memo in inbox/ (agent_memo.py; AGENT_MEMOS=0 = off). Never raises."""
    try:
        import sys as _s, os as _o
        _d = _o.path.dirname(_o.path.abspath(__file__))
        for _c in (_d, _o.path.join(_d, "sub-bots")):
            if _c not in _s.path:
                _s.path.insert(0, _c)
        import agent_memo as _am
        return _am.write(kind, ok, summary, **kw)
    except Exception:
        return None


def intake_suggestions() -> list[dict]:
    """Move suggestion files from json_relay/repo_suggestions into the review queue."""
    out = []
    if not SUGGEST_IN.is_dir():
        return out
    for f in sorted(SUGGEST_IN.glob("*.json")):
        s = _rjson(f, None)
        dest = SUGGEST_IN / "processed"
        dest.mkdir(exist_ok=True)
        if not isinstance(s, dict):
            _agent_memo("repo_suggestion", False, f"repo suggestion {f.name} unreadable, moved to processed/",
                        request_id=f.stem, source="sniper_github", reason="not a JSON object")
            shutil.move(str(f), str(dest / f.name)); continue
        _it = enqueue(s, kind="pr" if s.get("pr_url") else "suggestion_file", source_file=f.name)
        out.append(_it)
        _agent_memo("repo_suggestion", _it.get("status") == "queued",
                    f"repo suggestion '{_it.get('title') or f.stem}': {_it.get('status')} as {_it.get('id')}",
                    request_id=s.get("id") or f.stem, source="sniper_github", status=str(_it.get("status")),
                    reason=_it.get("note") or "", detail={"queue_id": _it.get("id")})
        shutil.move(str(f), str(dest / f.name))
    return out


def enqueue(s: dict, kind: str, source_file: str = "") -> dict:
    wallet, gh = str(s.get("wallet") or "")[:64], str(s.get("github_user") or "")[:39]
    iid = f"sg_{_ts()}_{_safe(gh or wallet or 'anon', 12)}_{os.urandom(2).hex()}"
    accepted = _rate_ok(wallet, gh)
    _append(REVIEW / "intake.jsonl", {"id": iid, "day": datetime.now().strftime("%Y-%m-%d"), "wallet": wallet,
                                      "github_user": gh, "accepted": accepted, "at": _now()})
    item = {"id": iid, "kind": kind, "status": "queued" if accepted else "rejected_rate_limit",
            "repo": s.get("repo"), "github_user": gh, "wallet": wallet, "title": str(s.get("title") or "")[:200],
            "body": str(s.get("body") or "")[:8000], "pr_url": s.get("pr_url"), "patch": s.get("patch"),
            "source_file": source_file, "received_at": _now()}
    if not accepted:
        item["note"] = f"Over the daily cap ({cfg()['suggest_daily_cap']}/day per wallet or GitHub account). Try tomorrow."
        _wjson(REVIEW / "rejected" / f"{iid}.json", item)
        return item
    _wjson(REVIEW / "queue" / f"{iid}.json", item)
    item["reviewer_note"] = str(_reviewer_note(item))
    return item


def scan_prs(repo: str) -> list[dict]:
    """Read-only: enqueue open PRs on OUR repo that aren't queued yet."""
    m = _GH_RE.match(repo if repo.startswith("http") else f"https://github.com/{repo}")
    if not m:
        return []
    owner, name = m.group(2), m.group(3)
    st, j = _gh_get(f"/repos/{owner}/{name}/pulls?state=open&per_page=50")
    if st != 200 or not isinstance(j, list):
        return []
    seen = _rjson(REVIEW / "prs_seen.json", {}) or {}
    out = []
    for pr in j:
        url = pr.get("html_url")
        if url in seen:
            continue
        out.append(enqueue({"repo": f"https://github.com/{owner}/{name}", "github_user": (pr.get("user") or {}).get("login"),
                            "title": pr.get("title"), "body": pr.get("body"), "pr_url": url}, kind="pr"))
        seen[url] = _now()
    _wjson(REVIEW / "prs_seen.json", seen)
    return out


def _bump(v: str, how: str) -> str:
    nums = [int(x) for x in re.findall(r"\d+", v or "1.0")] + [0, 0]
    ma, mi, pa = nums[0], nums[1], nums[2]
    if how == "major":
        return f"v{ma + 1}.0"
    if how == "patch":
        return f"v{ma}.{mi}.{pa + 1}"
    return f"v{ma}.{mi + 1}"


def decide(iid: str, decision: str, by: str = "reviewer", reason: str = "", bump: str = "minor") -> dict:
    qp = REVIEW / "queue" / f"{iid}.json"
    item = _rjson(qp, None)
    if not item:
        return {"ok": False, "error": "not_in_queue"}
    item.update(decided_by=by, decided_at=_now(), reason=reason)
    if decision != "approve":
        item["status"] = "rejected"
        _wjson(REVIEW / "rejected" / f"{iid}.json", item); qp.unlink()
        return {"ok": True, "status": "rejected"}
    repo = item.get("repo") or "unknown"
    vers = _rjson(REVIEW / "versions.json", {}) or {}
    prev = vers.get(repo, "v1.0")
    new = _bump(prev, bump)
    vers[repo] = new
    _wjson(REVIEW / "versions.json", vers)
    credit = {"id": iid, "repo": repo, "version": new, "github_user": item.get("github_user"),
              "title": item.get("title"), "pr_url": item.get("pr_url"), "at": _now()}
    _append(REVIEW / "credits.jsonl", credit)
    rel = REVIEW / "releases" / _safe(repo.split("github.com/")[-1].replace("/", "__"), 80)
    rel.mkdir(parents=True, exist_ok=True)
    who = f"@{item['github_user']}" if item.get("github_user") else "a community builder"
    with (rel / "CHANGELOG_pending.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## {new} ({datetime.now():%Y-%m-%d})\n- {item.get('title')} (thanks {who}"
                f"{', ' + item['pr_url'] if item.get('pr_url') else ''})\n")
    shout = f"{new} is out. {item.get('title')}. Shoutout {who} for the contribution. {repo}"
    plan = {"id": iid, "repo": repo, "from_version": prev, "tag": new, "status": "awaiting_owner_ok",
            "apply": ("merge PR " + item["pr_url"]) if item.get("pr_url") else
                     ("apply patch from queue file" if item.get("patch") else "manual edit per suggestion body"),
            "commands_after_ok": [f"git tag {new}", f"git push origin {new}",
                                  f"gh release create {new} --notes-file CHANGELOG_pending.md"],
            "x_shoutout_draft": shout, "prepared_at": _now()}
    _wjson(rel / f"release_plan_{new}.json", plan)
    item.update(status="approved", version=new, release_plan=str(rel / f"release_plan_{new}.json"))
    _wjson(REVIEW / "approved" / f"{iid}.json", item); qp.unlink()
    note = REVIEWER_INBOX / f"meme_sniper - repo_approved_{iid}_{_ts()}.md"
    note.write_text(f"# Approved {iid} -> {new}\n\nRepo: {repo}\nCredit: {who}\n"
                    f"Release plan: {plan['apply']}; tag {new} prepared, NOT pushed. Waiting on the owner's OK.\n\n"
                    f"## Drafted X shoutout (not posted)\n{shout}\n", encoding="utf-8")
    return {"ok": True, "status": "approved", "version": new, "plan": plan}


def process_decisions() -> list[dict]:
    out = []
    if not DECISIONS_IN.is_dir():
        return out
    for f in sorted(DECISIONS_IN.glob("*.json")):
        d = _rjson(f, {}) or {}
        r = decide(f.stem, str(d.get("decision", "")).lower(), d.get("by", "reviewer"), d.get("reason", ""),
                   d.get("bump", "minor"))
        out.append({"id": f.stem, **r})
        _dok = not (r.get("error") or str(r.get("status") or "").startswith(("error", "unknown", "not_found", "invalid")))
        _agent_memo("repo_decision", _dok, f"repo decision {f.stem}: {d.get('decision')} -> {r.get('status') or r.get('error')}",
                    request_id=f.stem, source="sniper_github", status=str(r.get("status")),
                    reason=str(r.get("error") or r.get("why") or ""))
        (DECISIONS_IN / "processed").mkdir(exist_ok=True)
        shutil.move(str(f), str(DECISIONS_IN / "processed" / f.name))
    return out


def tick() -> dict:
    """Called from meme_sniper's loop. Local files only, no network writes."""
    return {"intake": intake_suggestions(), "decisions": process_decisions()}


# ------------------------------------------------------------------ 3. uploader
_SECRET_RES = [re.compile(p) for p in (
    r"ghp_[A-Za-z0-9]{30,}", r"github_pat_[A-Za-z0-9_]{40,}", r"xai-[A-Za-z0-9]{20,}", r"sk-[A-Za-z0-9_-]{20,}",
    r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"xox[baprs]-[A-Za-z0-9-]{10,}",
    r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b",                                        # telegram bot token
    r"(?i)(api[_-]?key|secret|token|password|private[_-]?key)\s*[=:]\s*['\"]?[A-Za-z0-9_\-/+]{16,}",
    r"\[\s*\d{1,3}(\s*,\s*\d{1,3}){63}\s*\]",                                 # solana keypair array
)]
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def scan_folder(src: Path) -> dict:
    deny = [d.lower() for d in cfg()["denylist_paths"]]
    secrets, private = [], []
    for p in src.rglob("*"):
        if any(part in _SKIP_DIRS for part in p.parts) or not p.is_file():
            continue
        rel = p.relative_to(src).as_posix()
        low = rel.lower()
        hit = next((d for d in deny if d in low), None)
        if hit:
            private.append({"file": rel, "rule": hit}); continue
        if p.name == ".env" or (p.name.startswith(".env") and p.name != ".env.example"):
            secrets.append({"file": rel, "rule": "env_file"}); continue
        if p.stat().st_size > 2_000_000:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(txt.splitlines(), 1):
            for rx in _SECRET_RES:
                if rx.search(line):
                    secrets.append({"file": rel, "line": i, "rule": rx.pattern[:30]}); break  # never the value
    return {"secrets": secrets, "private_paths": private}


def _env_keys(src: Path) -> list[str]:
    keys = set()
    for name in (".env", ".env.example"):
        f = src / name
        if f.exists():
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=", line)
                if m:
                    keys.add(m.group(1))        # names only, values never read out
    for f in src.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in f.parts):
            continue
        try:
            keys.update(re.findall(r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
                                   f.read_text(encoding="utf-8", errors="ignore")))
        except Exception:
            pass
    return sorted(keys)


def prepare_upload(src: str | Path, name: str = "", topics: list[str] | None = None) -> dict:
    """Copy folder to staging, add LICENSE/.env.example/.gitignore/README topics, scan. Never pushes."""
    src = Path(src).resolve()
    if not src.is_dir():
        return {"status": "error", "error": "folder not found"}
    c = cfg()
    name = _safe(name or src.name.replace(" ", "-"), 100)
    scan = scan_folder(src)
    out = UPLOADS / name
    man = {"name": name, "source": str(src), "staging": str(out), "prepared_at": _now(),
           "topics": topics or c["default_topics"], "scan": scan}
    if scan["secrets"] or scan["private_paths"]:
        man["status"] = "blocked"
        man["why"] = "secrets or private paths found; fix the source folder and re-run (values not shown)"
        _wjson(UPLOADS / f"{name}.manifest.json", man)
        return man
    if out.exists():
        shutil.move(str(out), str(UPLOADS / f"_archived_{name}_{_ts()}"))
    shutil.copytree(src, out, ignore=shutil.ignore_patterns(*_SKIP_DIRS, ".env"))
    (out / "LICENSE").write_text(MIT.format(year=datetime.now().year, holder=c["license_holder"]), encoding="utf-8")
    (out / ".env.example").write_text("".join(f"{k}=\n" for k in _env_keys(src)) or "# no env vars\n", encoding="utf-8")
    gi = out / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    for need in (".env", "*.env.local", "__pycache__/", "bot_logs/", "*.keypair.json"):
        if need not in lines:
            lines.append(need)
    gi.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rd = out / "README.md"
    if not rd.exists():
        rd.write_text(f"# {name}\n\nTODO: what it does, demo GIF, quick start.\n\n"
                      f"Topics: {', '.join(man['topics'])}\n\nMIT, {c['license_holder']}.\n", encoding="utf-8")
    rescan = scan_folder(out)
    man["scan_staging"] = rescan
    man["status"] = "blocked" if (rescan["secrets"] or rescan["private_paths"]) else "ready_awaiting_owner_ok"
    owner = c.get("our_owner") or "<owner>"
    man["commands_after_ok"] = [f"cd \"{out}\"", "git init -b main", "git add -A", "git commit -m \"initial drop\"",
                                f"gh repo create {owner}/{name} --public --source . --push"
                                + (f" --description \"{c.get('repo_description')}\"" if c.get("repo_description") else ""),
                                f"gh repo edit {owner}/{name} " + " ".join(f"--add-topic {t}" for t in man["topics"])]
    _wjson(UPLOADS / f"{name}.manifest.json", man)
    return man


def watch_drops() -> list[dict]:
    """Prepare any new folder in workspace/repo_drops (done once per folder mtime)."""
    DROPS.mkdir(parents=True, exist_ok=True)
    seen = _rjson(UPLOADS / "drops_seen.json", {}) or {}
    out = []
    for d in DROPS.iterdir():
        if d.is_dir() and not d.name.startswith("_"):
            key = f"{d.name}:{int(d.stat().st_mtime)}"
            if key in seen.values():
                continue
            m = prepare_upload(d)
            seen[d.name] = key
            out.append({"name": m.get("name"), "status": m.get("status")})
            REVIEWER_INBOX.mkdir(exist_ok=True)
            (REVIEWER_INBOX / f"meme_sniper - repo_upload_{_safe(d.name, 30)}_{_ts()}.md").write_text(
                f"# Repo upload prepared: {m.get('name')}\n\nStatus: {m.get('status')}\n"
                f"Manifest: bots/bot_logs/repo_uploads/{m.get('name')}.manifest.json\n"
                "Nothing pushed. The owner runs `python bots/sniper_github.py publish-upload <name> --owner-ok` after OK.\n",
                encoding="utf-8")
    _wjson(UPLOADS / "drops_seen.json", seen)
    return out


def token_scopes():
    """Scopes on the saved token (from GitHub's X-OAuth-Scopes header). None = no token / unreachable."""
    tok = auth_token()
    if not tok:
        return None
    try:
        import urllib.request
        req = urllib.request.Request("https://api.github.com/user", headers={
            "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": "sniper-github"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return [x.strip() for x in (r.headers.get("X-OAuth-Scopes") or "").split(",") if x.strip()]
    except Exception:
        return None


WRITE_HINT = ("Your GitHub sign-in is read-only, so it can't create or push repos. "
              "Sign in with write access for public repos:  python bots/sniper_github.py login --public")


def publish(commands: list[str], owner_ok: bool, cwd: Path | None = None) -> dict:
    if not owner_ok or os.getenv("SNIPER_GH_PUSH_OK") != "1":
        _agent_memo("publish", True, f"publish dry run: {len(commands)} command(s) not run (needs --owner-ok AND SNIPER_GH_PUSH_OK=1)",
                    source="sniper_github", status="dry_run")
        return {"status": "dry_run", "would_run": commands,
                "gate": "needs --owner-ok AND env SNIPER_GH_PUSH_OK=1"}
    _sc = token_scopes()
    if _sc is not None and not ({"public_repo", "repo"} & set(_sc)):
        _agent_memo("publish", False, "publish blocked: GitHub token is read-only", source="sniper_github",
                    status="blocked", reason="token_lacks_write; run login --public")
        return {"status": "blocked", "why": "token_lacks_write", "hint": WRITE_HINT}
    import subprocess
    ran = []
    for c in commands:
        if c.startswith("cd "):
            cwd = Path(c[3:].strip().strip('"')); continue
        r = subprocess.run(c, shell=True, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
        ran.append({"cmd": c, "rc": r.returncode})
        if r.returncode:
            break
    _bad = [x for x in ran if x["rc"]]
    _agent_memo("publish", not _bad, f"publish ran {len(ran)} command(s)" + (f", failed at: {_bad[0]['cmd'][:80]}" if _bad else ", all ok"),
                source="sniper_github", status="ran", reason=(f"rc={_bad[0]['rc']}" if _bad else ""))
    return {"status": "ran", "ran": ran}


MIT = """MIT License

Copyright (c) {year} {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="sniper_github")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("repos"); s.add_argument("user")
    s = sub.add_parser("resolve"); s.add_argument("--user", default=""); s.add_argument("--pick", default=None); s.add_argument("--url", default="")
    sub.add_parser("tick")
    s = sub.add_parser("login"); s.add_argument("--private", action="store_true", help="also allow your private repos (full repo access)")
    s.add_argument("--public", action="store_true", help="write access to PUBLIC repos only (needed to publish a drop)")
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("logout"); sub.add_parser("whoami"); sub.add_parser("status"); sub.add_parser("gh-cli")
    s = sub.add_parser("my-repos"); s.add_argument("--private", action="store_true")
    s = sub.add_parser("scan-prs"); s.add_argument("repo")
    s = sub.add_parser("review"); s.add_argument("decision", choices=["approve", "reject"]); s.add_argument("id")
    s.add_argument("--by", default="reviewer"); s.add_argument("--reason", default=""); s.add_argument("--bump", default="minor")
    sub.add_parser("queue")
    s = sub.add_parser("upload"); s.add_argument("folder"); s.add_argument("--name", default="")
    sub.add_parser("watch-drops")
    s = sub.add_parser("publish-upload"); s.add_argument("name"); s.add_argument("--owner-ok", action="store_true")
    s = sub.add_parser("publish-release"); s.add_argument("plan"); s.add_argument("--owner-ok", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "repos": r = list_public_repos(a.user)
    elif a.cmd == "resolve": r = resolve_repo({"github_user": a.user, "repo_pick": a.pick, "repo_url": a.url})
    elif a.cmd == "tick": r = tick()
    elif a.cmd == "login": r = login(a.private, open_browser=not a.no_browser, public=a.public)
    elif a.cmd == "logout": r = logout()
    elif a.cmd in ("whoami", "status"): r = whoami()
    elif a.cmd == "gh-cli": r = gh_cli_status()
    elif a.cmd == "my-repos": r = list_my_repos(a.private)
    elif a.cmd == "scan-prs": r = scan_prs(a.repo)
    elif a.cmd == "review": r = decide(a.id, a.decision, a.by, a.reason, a.bump)
    elif a.cmd == "queue": r = [p.stem for p in (REVIEW / "queue").glob("*.json")]
    elif a.cmd == "upload": r = prepare_upload(a.folder, a.name)
    elif a.cmd == "watch-drops": r = watch_drops()
    elif a.cmd == "publish-upload":
        m = _rjson(UPLOADS / f"{a.name}.manifest.json", {}) or {}
        r = publish(m.get("commands_after_ok", []), a.owner_ok and m.get("status") == "ready_awaiting_owner_ok")
    else:
        p = _rjson(Path(a.plan), {}) or {}
        r = publish(p.get("commands_after_ok", []), a.owner_ok)
    print(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    _cli(sys.argv[1:])
