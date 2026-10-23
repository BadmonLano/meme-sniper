<p align="center"><img src="assets/meme_sniper_logo.png" alt="Meme Sniper" width="320"></p>

# Meme Sniper

**Solana meme sniper run by your SI agent: scans, rug-checks, buys and sells, plus a gated launch rail with GitHub repo attach. Live trading with safety caps, launch rail off by default. Python, MIT.**

Your agent's trench crew. Meme Sniper scans every new Solana memecoin, rug-checks it, buys, manages and sells, and can launch your own token through a gated launch rail with a real GitHub repo attached. An SI agent runs it for you; you set the wallet, sizes and rules once, and get pinged about what happens.

No hype, no ticker. Just the code.

---

## Works with

Sniper can be run by Grok Bot, Muse, or an agent from any of the larger SI companies: any SI agent that can read and write files and run Python works. No official partnership or endorsement is implied.

## Contents

- [Works with](#works-with)
- [What Sniper is](#what-sniper-is)
- [Read this first: safety defaults](#read-this-first-safety-defaults)
- [Safety caps and your settings](#safety-caps-and-your-settings)
- [Self-updates and fixes (policy)](#self-updates-and-fixes-policy)
- [GitHub basics (new to GitHub? start here)](#github-basics-new-to-github-start-here)
- [What's in this folder](#whats-in-this-folder)
- [Quick start](#quick-start)
- [Windows, Mac and Linux](#windows-mac-and-linux)
- [GitHub sign-in setup](#github-sign-in-setup)
- [Messaging / notifications setup](#messaging--notifications-setup)
- [How the inbox works](#how-the-inbox-works)
- [Contributing](#contributing)
- [Versions and releases](#versions-and-releases)
- [Updating](#updating)
- [License](#license)

---

## What Sniper is

Four pieces that work together:

1. **The sniper** (`bots/meme_sniper.py`). Scores every new Solana launch, runs rug checks, buys, and manages each position with stop loss, take profit and trailing stops. Writes what it sees as small JSON "packets" to an inbox for your agent.
2. **The launch rail** (`bots/sub-bots/launch_rail.py`). Launches a token for you, with a dev-buy cap (default 0.5 SOL) and a repo gate: the launch must point at a real public GitHub repo. **Off by default** (see below). Full details: [`docs/LAUNCH_RAIL.md`](docs/LAUNCH_RAIL.md).
3. **GitHub sign-in and repo attach** (`bots/sniper_github.py`). Sign in once with GitHub's device code, list your repos, and attach one to a launch.
4. **Contribution review and uploader** (also `bots/sniper_github.py`). Scans pull requests and suggestion files from other people, queues them for **you** to review, and packages and publishes your own uploads and releases. Nothing auto-merges.

Around those: an SI "brain" (Grok, OpenAI, Claude, any OpenAI-compatible endpoint, or local Ollama), alerts to your phone, a console dashboard, nightly self-review, and skill files in `skills/` that teach your agent how to trade.

**Who it's for:** people who run an SI agent that can read files, run Python and keep a loop going, and who understand Solana memecoins and their risks.

## Read this first: safety defaults

| Setting | Default | What it means |
|---|---|---|
| `SNIPER_PAPER_MODE` | **off (0)** | **Trading is live from the first start.** It signs real buys and sells. Set `SNIPER_PAPER_MODE=1` to simulate at real quotes and send nothing. Your agent asks you paper or live on first run. |
| `LAUNCH_RAIL_ENABLED` | **off (false)** | The launch rail does nothing until you turn it on. |
| `LAUNCH_RAIL_LIVE` | **off (0)** | Even with the rail on, launches are dry runs until you set this to `1`. Both must be on for a real on-chain launch. |
| `LAUNCH_MAX_DEV_BUY_SOL` | 0.5 | Hard cap on the dev buy for a launch. |
| `bots/.env` | ignored by git | Your keys live here. **Never commit it, zip it or paste it anywhere.** Only `.env.example` (blank) is in the repo. |

Honest notes:
- Use a **burner hot wallet** holding only what you can afford to lose. Never your main wallet.
- **What wallet access means:** the private key in `bots/.env` lets the bot sign **any** transaction from that wallet, not just trades: it could move or spend everything in it. So use a burner, keep the balance small, and sweep profits out (`LEDGER_ADDRESS`).
- **Agent buys need a working RPC.** Without a reachable `RPC_URL` (or `HELIUS_API_KEY`) buy signals are refused, not queued.
- Most memecoins go to zero and many are scams. The gates here reduce risk; they don't remove it. Bugs, RPC outages and bad model output can lose money.
- Once set up, your agent acts on its own (buys, sells, launches if armed). Alerts are notify-only; nothing waits for your OK. Your safety is in the switches above, so set them deliberately.
- MIT license, no warranty. You're responsible for every transaction it sends.

## Safety caps and your settings

These are on by default. Every one is a line in `bots/.env`; leave it blank to keep the default, set `0` to switch a number off.

| Setting | Default | In plain English |
|---|---|---|
| `DAILY_LOSS_STOP_SOL` | 0.5 | Stop buying for the rest of the day (US Eastern) once you have lost this much SOL on closed trades. |
| `DAILY_BUY_CAP` | 10 | At most this many buys per day. |
| `BUY_AUTHORITY_GATE` | true | Refuse any token whose dev can still freeze your tokens or mint more. If that can't be checked, it refuses too (`BUY_AUTHORITY_FAIL_CLOSED`). |
| `MAX_PUMP_5M_PCT` | 50 | Don't chase: skip a token already up more than this % in the last 5 minutes. |
| `RUG_FAIL_CLOSED` | true | If 4 or more rug-check sources can't be reached (`RUG_FAIL_CLOSED_MIN_ERRORS`), treat the token as unsafe instead of "unknown". |
| `CANDIDATE_FLOOR` | true | Hide a token from your agent's inbox unless it has at least `CANDIDATE_MIN_LIQ_USD` (10,000) of liquidity, no fake-volume flag and no bundled launch. |
| `TRADING_HOURS` / `TRADING_TZ` | blank (always) / America/New_York | Only surface and buy tokens in this window, e.g. `09:00-23:00`. Overnight windows like `22:00-02:00` work. Selling and stops always run. `TRADING_HOURS_GATES_SCAN=false` keeps scanning outside the window but still blocks buys. |
| `LOSS_STREAK_PAUSE` | 3 | After this many losing trades in a row, pause buys for `LOSS_STREAK_PAUSE_HOURS` (2). |
| `SIZE_HALVE_AFTER_LOSSES` | 2 | After this many losses in a row, buys are half size until a winner. |
| `MAX_OPEN_POSITIONS` | 3 | Never hold more than this many tokens at once. |
| `MINT_COOLDOWN_HOURS` | 72 | After a stop-loss on a token, don't buy that same token again for this many hours. |
| `SECOND_WIND_V2` | true | "Second wind" pings (a token that dumped, built a base and is waking up) use the real price history peak, need a 1-3 hour base where volume dried up and came back, skip tokens more than 80% off their peak (`SECOND_WIND_MAX_OFF_PEAK_PCT`), check holders and bundles, and include a plan: entry zone, stop under the base low, target the old peak. Pings are watch-only, never auto-buys. |
| `SECOND_WIND_SCORE` | true | Grades every second-wind ping at +1h, +6h and +24h into `bot_logs/second_wind_scores.jsonl`, so you can see if they actually work. |
| `SIGNAL_RECHECK` | true | Right before any agent or manual buy, take a fresh price/liquidity snapshot. Refuse if liquidity is under `SIGNAL_RECHECK_MIN_LIQ_USD` (10,000), if the market cap moved more than `SIGNAL_RECHECK_MAX_DRIFT_PCT` (50%) since the signal, or if the rug check fails. For the drift check, put `mcap_at_signal` (the market cap you saw, in USD) in the buy signal; without it the bot uses `mcap`, `expected_mcap` or the scan's market cap. A refusal lands in `inbox/` as `signal_rejected` with a one-line summary. |
| `PEAK_SANITY` | true | Throws out junk "missed runner" numbers (over `PEAK_SANITY_MAX_X`, 1000x) so the lessons aren't built on bad data. |

**First run: the setup wizard and your agent ask you.** The wizard asks most of these (see [What the setup wizard asks](#what-the-setup-wizard-asks)); before it trades, your agent should confirm and write the answers into `bots/.env`: paper or live (default **live**), launch rail on or off (default **off**), buy size, daily loss stop, daily buy cap, stop loss / trailing stop, same-token cooldown, loss-streak pause, max open positions, and trading hours plus time zone. Press Enter on any question to keep the default.

## Self-updates and fixes (policy)

Plain English rules for any agent running this drop:

- **Your agent may fix or upgrade its own local copy** when it spots a bug or a better way. Before it changes anything it must: (1) back up the file it is about to edit, (2) test the change in paper mode (`SNIPER_PAPER_MODE=1`) first, and (3) tell you, its owner, what changed and why.
- **Fixes for everyone go back as suggestions, not pushes.** If the fix would help other users, the agent sends it to the upstream repo as a suggestion through the review queue (`bots/sniper_github.py`). The maintainer's agent reviews it. Nothing is ever auto-merged.
- **Your copy never auto-pulls.** Upstream changes only reach your copy when you choose to update.
- **Safety caps only loosen with your OK.** The daily loss stop, daily buy cap, fail-closed rug checks, mint/freeze authority gate and max 5-minute pump gate can be tightened by the agent at any time, but loosened or switched off only after you say yes.

## GitHub basics (new to GitHub? start here)

- **Repo (repository):** a project folder that lives on GitHub, with its full history. This page is one.
- **Download ZIP:** green **Code** button → **Download ZIP**. Gets you a copy with no account and no Git needed.
- **Clone:** same as downloading, but with Git (`git clone <url>`), so you can pull updates later with `git pull`.
- **Star:** a bookmark and a thumbs-up. Find your stars under your profile → **Stars**.
- **Watch:** the **Watch** button picks what you get notified about. **Custom → Releases** pings you only when a new version ships. Notifications show in the bell icon (top right) and by email if you allow it in [notification settings](https://github.com/settings/notifications).
- **Fork:** your own copy of the repo under your account. You can change it freely. It does **not** update itself when the original changes (see [Versions and releases](#versions-and-releases)).
- **Pull request (PR):** "here's a change I made in my fork, please consider adding it." The owner reviews and decides.
- **Issue:** a bug report or question. **Issues** tab → **New issue**.
- **Release:** a named, tested version (like `v1.0.1`) with notes and a downloadable zip. Right side of the repo page → **Releases**.

## What's in this folder

| Path | What it is |
|---|---|
| `bots/sniper.py` | **Start here.** One launcher: start everything, setup wizard, X sign-in, dashboard, launch a token. |
| `bots/meme_sniper.py` | The trading engine. |
| `bots/sniper_ui.py` | Console dashboard (reads state files, never trades). |
| `bots/sniper_github.py` | GitHub sign-in, repos, PR/suggestion review queue, uploads and releases. |
| `bots/sub-bots/` | Helpers: launch rail, alerts, X intel, security warden, model providers, etc. |
| `bots/chains/` | Chain plug-ins. Solana is the only live one. |
| `bots/.env.example` | Every setting, blank, with comments. Copy to `bots/.env`. |
| `bots/examples/` | Sample launch requests (dry-run test included). |
| `skills/` | Skill files your agent reads to make decisions. |
| `automations/` | Inbox-check prompts for your agent to schedule: sniper lane, warden lane, misc lane, morning brief (see Quick start step 8). |
| `rules/` | Your personal trading rules (`rules.example.md` to start). |
| `learnings/` | Lessons the nightly review writes down. |
| `inbox/` | Agent inbox: new cards, rejected signals, reviews, for your SI agent to read. |
| `owner_inbox/` | Owner cards: alerts and recaps meant for you. |
| `json_relay/`, `owner_commands/`, `inbox_results/` | Requests, your commands and finished work (see [How the inbox works](#how-the-inbox-works)). |
| `bots/tuner/meme_sniper_filter.default.json` | Shipped filter defaults. First run copies it to `meme_sniper_filter.json` (git-ignored), which the bot tunes, so `git pull` stays clean. |
| `VERSION` | The release version. |
| `bot_logs/` | Runtime state and logs (git ignores the contents). |
| `docs/` | Deep dives: `LAUNCH_RAIL.md`, `DEPENDENCY_MAP.md`. |
| `SETUP.md` | The full step-by-step setup. Your agent should read all of it. |
| `CONTRIBUTING.md`, `SECURITY.md`, `TIMELINE.md`, `LICENSE` | How to help, how to report a hole, change history, license. |

## Quick start

1. **Install Python 3.12+** from [python.org](https://www.python.org/downloads/). On Windows tick **Add python.exe to PATH**.
2. **Get the code:** green **Code** button → **Download ZIP** and unzip it, or `git clone https://github.com/BadmonLano/meme-sniper.git` then `cd meme-sniper`.
3. **Open a terminal in that folder** and install:
   ```
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
   Mac/Linux: make a virtual environment first, then install inside it:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
4. **Make your settings file:** copy `bots/.env.example` to `bots/.env`.
   - Windows: `copy bots\.env.example bots\.env`
   - Mac/Linux: `cp bots/.env.example bots/.env`
5. **Fill in `bots/.env`** in a text editor: burner wallet (`HOT_WALLET_PRIVATE_KEY`, `HOT_WALLET_ADDRESS`), RPC (`RPC_URL` / `HELIUS_API_KEY`), one brain (`LLM_MAIN` plus that provider's key), and **`SNIPER_PAPER_MODE=1` for your first run**.
6. **Run it:** `python bots/sniper.py` (Mac/Linux: `python3 bots/sniper.py`). Pick **2 Setup wizard** first, then **1 Start Sniper**. `--help` lists the options.
7. **Point your agent at `SETUP.md`** so it finishes setup (rules, skills, automations, alerts).
8. **Set up your inbox checks.** Sniper only writes files; nothing gets decided until your agent checks them. Ask your agent to create one recurring task per prompt below, pasting the prompt file's text as the task (Grok Bot: a routine; Muse or other SI agents: a scheduled task, cron job or heartbeat with the file's text as the prompt). Replace `{AGENT_NAME}` / `{USER}` first, then run each once by hand and check `bot_logs/inbox_cron_audit.log`.

| Prompt | Suggested frequency | Watches for |
|---|---|---|
| `automations/sniper_lane.automation.md` | every 10 min | `inbox/meme_sniper - *` and `trench_news - *`: token cards, second-wind pings, digests, boot summaries, signal answers (incl. `signal_rejected`); arms SL/TP on open bags |
| `automations/warden_lane.automation.md` | every 20 min | `inbox/security_warden - *`: wallet moves, Sniper down / zero buys, integrity, medic |
| `automations/misc_lane.automation.md` | every 15 min | everything else in `inbox/` (x_intel, code_tuner, autoagent, log_janitor, launch_rail, owner cards, repo_watch) |
| `automations/morning_brief.automation.md` | once each morning | reads logs and done packets, sends you one brief |
| `learnings/nightly_self_eval.automation.md` | once a night | reviews the day's trades and writes lessons |

Offset the start minutes so no two checks start in the same minute. Details: `automations/README.md` and SETUP.md section 11.

Quick checks: `python bots/sniper.py --smoke`, `python bots/sniper.py --ui-smoke` (runs on a temp copy) and `python bots/sub-bots/launch_rail.py --help`.

### Menus

Launcher (`python bots/sniper.py`): **1** Start Sniper (+ console), **2** Setup wizard, **3** Sign in to X, **4** Live dashboard, **5** Launch a token, **6** Console only, **7** Exit.

Console (opens with 1 or 6): **1** Live dashboard, **2** Logs, **3** Settings, **4** Skills, **5** Launch a token, **6** Sign in to X, **7** Quit UI (engine keeps trading), **8** Stop Sniper. Skills are under **6 Console → 4 Skills** (all skill folders, including `gork-lore` and `_templates`).

### What the setup wizard asks

Wallet (key, address, optional cold wallet), RPC (URL, Helius key, Helius plan), the brain (main + fallback and their keys/models), alert channels, owner commands, Pinata, X token, trading values (buy size, default SL/TP, dev-buy cap, own-launch mode and treasury %), **Safety caps** (daily loss stop 0.5 SOL, daily buy cap 10, same-token cooldown 72h, loss-streak pause 3, max open positions 3, trading hours blank = always, timezone America/New_York), and modes (**launch rail on/off, default off**, launch live on-chain default no, paper, learning). Enter takes the default shown. Answers go to `bots/.env`, each comment on its own line. `SNIPER_WIZARD_SAFETY=0` hides the Safety caps questions.

## Windows, Mac and Linux

The same Python files run on all three. Built and tested on Windows 10/11; macOS and Linux should work but are less tested.

| Thing | Windows | Mac / Linux |
|---|---|---|
| Python command | `python` | usually `python3` (and `pip3`) |
| Paths in docs | `bots\.env` | `bots/.env` |
| Terminal | Windows Terminal recommended | Terminal / iTerm |
| GitHub token storage | Windows Credential Manager (via `keyring`) | macOS Keychain or Linux Secret Service (via `keyring`) |
| File locks | `msvcrt` | `fcntl` (picked automatically) |

Windows-only bits in the code, all guarded so they're skipped elsewhere:
- `bots/sniper.py`: sets the console to UTF-8 with `ctypes.windll` (Windows only).
- `bots/sniper.py`, `bots/sniper_ui.py`, `bots/cancel_input.py`: single-key input via `msvcrt`; on Mac/Linux the menus fall back to typed input.
- `bots/sub-bots/agent_scraper.py`: cleans up its own stray Chrome via PowerShell on Windows only; on Mac/Linux close a stuck scraper browser yourself.
- `bots/sniper_ui.py`: `CREATE_NO_WINDOW` subprocess flag (ignored off Windows).

No `winreg`, scheduled tasks or hard-coded drive paths. Keep the computer awake: trading pauses when it sleeps (Mac: `caffeinate -i python3 bots/sniper.py`).

## GitHub sign-in setup

Optional. Needed only to list your repos, attach one to a launch, review contributions, or publish uploads.

1. Go to [GitHub → Settings → Developer settings → OAuth Apps](https://github.com/settings/developers) → **New OAuth App**.
2. Name: anything (e.g. `Sniper`). Homepage URL and Callback URL: your GitHub profile URL (the callback isn't used).
3. Tick **Enable Device Flow**. Register.
4. If shown, **untick "Expire user access tokens"**. Sniper doesn't refresh tokens yet, so expiring tokens log you out every 8 hours.
5. Copy the **Client ID** (not a secret) into `bots/.env`:
   ```
   GITHUB_OAUTH_CLIENT_ID=your_client_id
   ```
   You do **not** need a client secret.
6. Sign in:
   ```
   python bots/sniper_github.py login
   ```
   Open the link, type the code, approve. Then check with `status` and `my-repos`.

The token is stored in your OS password store (Credential Manager / Keychain / Secret Service). If `keyring` is unavailable it falls back to a user-only file in `bot_logs/`. `python bots/sniper_github.py logout` removes it. Default scope is read-only public access.

Other commands: `repos`, `resolve`, `scan-prs`, `review`, `queue`, `upload`, `watch-drops`, `publish-upload`, `publish-release`. Run any with `--help`.

## Messaging / notifications setup

All optional. Pick channels with a comma list in `bots/.env`, e.g. `ALERT_CHANNELS=telegram,ntfy`. Leave it blank for none. Every setting has a comment in `.env.example`, and the setup wizard (`python bots/sniper.py` → wizard) can do this for you and send a test.

**Telegram**
1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Send your new bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
3. Set `TELEGRAM_TOKEN=` and `TELEGRAM_CHAT_ID=`, and add `telegram` to `ALERT_CHANNELS`.

**Discord**
1. Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL.
2. Set `DISCORD_WEBHOOK_URL=` and add `discord`. Treat the URL like a password.

**Email (SMTP)**
1. Set `SMTP_HOST`, `SMTP_PORT` (587 = STARTTLS, 465 = SSL), `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `ALERT_EMAIL_TO`. Gmail: `smtp.gmail.com` with an [app password](https://myaccount.google.com/apppasswords).
2. Add `email`. `ALERT_EMAIL_MIN_INTERVAL_S` stops it flooding your inbox.

**ntfy (free phone push, iPhone and Android)**
1. Install the ntfy app, subscribe to a long random topic name.
2. Set `NTFY_TOPIC=` (and `NTFY_URL` / `NTFY_TOKEN` if self-hosted or protected). Add `ntfy`.

**Owner commands (talk back to it, off by default)**
Ask for `/roast`, `/recap` or `/autopsy [ticker|last]` by Telegram through a separate command bot (`OWNER_COMMANDS`, `OWNER_COMMANDS_TG_TOKEN`, `OWNER_COMMANDS_TG_CHAT_ID`) or by dropping a text file in `owner_commands/`. Replies land in your alert channels and `inbox_results/owner_replies/`. See SETUP.md section 6.5.

**iMessage on Mac (optional, community recipe)**
Sniper has no built-in iMessage channel yet (`imessage` in `ALERT_CHANNELS` is ignored and logged as planned). If you're on a Mac signed into Messages, your agent can forward alerts itself with:
```
osascript -e 'tell application "Messages" to send "Sniper: test alert" to buddy "+15555550123"'
```
Run it once by hand first (macOS asks for permission). This is outside Sniper's code and unsupported; ntfy is the easier phone option.

## How the inbox works

Sniper and your agent talk through plain files, so any agent that can read and write files works:

- **Bots → agent:** packets land in `inbox/` and `json_relay/` (new cards, rejected signals, positions, launch requests). Cards meant for you (alerts, recaps) go to `owner_inbox/`.
- **Agent → bots:** the agent writes decisions and launch requests back into `json_relay/` (e.g. `json_relay/launch_requests/*.json`).
- **Done work:** results go to `inbox_results/` and move to `inbox_results/done/`.
- **You → agent:** text files in `owner_commands/`.
- Each request is processed once (tracked in `bot_logs/`), so nothing fires twice.

The `automations/` files are ready-made loops telling your agent how often to read these. Details in SETUP.md sections 6 and 11.

## Contributing

Ideas and fixes are welcome. Everything is reviewed by the repo owner. **Nothing is auto-merged.**

- **Pull request:** **Fork** → change it in your fork → **Contribute → Open pull request**. Keep it small, say what and why, run the tests (`python bots/sniper.py --smoke` and the `test_*.py` files).
- **Suggestion file:** no Git needed. Open an issue, or attach a short markdown file describing the change.
- **Security holes:** don't open a public issue. See [`SECURITY.md`](SECURITY.md).
- **Never** include keys, wallets, `.env` files or logs in a PR.

Full guide: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Versions and releases

- Versions look like `v1.0.1` (the trading engine inside keeps its own number, v14.3). Each one is a **Release** with notes on what changed (history in [`TIMELINE.md`](TIMELINE.md)).
- **Forks and downloads don't auto-update.** You update when you want:
  - ZIP: download the new release, copy your `bots/.env`, `rules/rules.md` and `learnings/` across.
  - Git clone: `git pull`.
  - Fork: on your fork's page click **Sync fork**.
- To hear about new versions: **Watch → Custom → Releases**.
- Read the release notes before updating; new settings appear in `.env.example`.

## Updating

- Git: `git pull` in the folder.
- ZIP: download the new release zip and unzip it over the old folder (or next to it and copy your files across).
- Your `bots/.env` and `bot_logs/` are kept either way (git ignores them, and the zip doesn't contain them). The live filter file is ignored too, so `git pull` doesn't conflict with what the bot tuned.
- Check `.env.example` and the release notes for new settings.

## License

[MIT](LICENSE) © 2026 Bentayga Empire LLC. Use it, change it, share it; keep the license notice. No warranty.

---

More from Bentayga: [JOS (@JOSYSTEMS)](https://x.com/JOSYSTEMS) · [theflowcycle.com](https://theflowcycle.com)
