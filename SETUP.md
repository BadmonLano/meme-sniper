# SETUP

**Who this is for:** the agent setting Meme Sniper up for its owner. "You" is the agent; "the owner" is the human whose wallet and rules these are. Read this once, top to bottom, before the first start. The skills ship as tested defaults; change them only with the owner (section 8).

> **Ask these first, in this order (wizard menu 2 does the same):**
> 1. **Agent autonomy (`AGENT_MODE`).** `suggest` (default, preselected): the agent proposes every buy and sell and the bot waits for the owner's `/approve <id>` (owner commands) or `python bots/approve.py <id>`; unanswered suggestions expire after `AGENT_MODE_APPROVAL_TTL_MIN` (60). `auto`: **warning** - the agent buys and sells on its own inside the caps with no per-trade sign-off. The wizard makes the owner type `AUTO`; `setup.json` needs `"AGENT_CONFIRM_AUTO": "AUTO"`. Never pick auto for the owner.
> 2. **Active hours (`ACTIVE_HOURS` + `ACTIVE_TZ`).** Default `00:00-23:59` (always on), `America/New_York`. The loop runs 24/7 either way; the window only gates new buys and new cards, exits always run. See "Always on" below.
> 3. **Paper or live (`SNIPER_PAPER_MODE`).** Paper is the default for new setups (`bots/.env.example` ships `SNIPER_PAPER_MODE=1`): every trade is simulated at real quotes, nothing is signed or sent, and no wallet private key is needed. **Live keys are opt-in**: only after the owner chooses live does the wizard ask for the burner wallet's private key, with a warning, and leaving paper needs `LIVE` typed (section 4.2). Token launches stay off-chain (`LAUNCH_RAIL_LIVE=0`) until the owner sets `LAUNCH_RAIL_LIVE=1`. Make sure the owner uses a burner wallet and understands the warning in the README before going live.

> **The owner runs setup once by hand.** Start `python bots/sniper.py` and use the setup wizard (menu 2) and **Sign in to X** (menu 3) at least once: X sign-in needs a human at the browser window (2FA, captcha). After that, you (the agent) can fill or change the rest through `setup.json` or the Settings screen. If `bots/.env` is missing, the wizard, `setup.json`, the Settings screen and token refresh all create it from `bots/.env.example`.

## Always on: loop, cadence and active hours

Meme Sniper is a **loop meant to run continuously**: the bot runs 24/7 on its cadence and your agent runs the lanes in `automations/` on theirs. It is not a one-shot script.

- **Keep it running:** use an always-on hosted agent (best), or auto-start on boot on your own PC: Windows Task Scheduler "At log on" running `python bots/sniper.py --start`, macOS a `launchd` agent, Linux a `systemd --user` service or `@reboot` cron. Have the agent's lane jobs saved as recurring automations so they survive restarts.
- **Active hours (tunable, `bots/.env`):** `ACTIVE_HOURS` (default `00:00-23:59` = always on; e.g. `09:00-23:00`, overnight `22:00-02:00`, several windows `09:00-12:00,18:00-23:00`), `ACTIVE_TZ` (default `America/New_York`), `ACTIVE_DAYS` (blank = every day; e.g. `mon-fri`). Outside the window the loop idles on new buys and new inbox cards (declined with reason `outside_active_hours`), never cuts off an order mid-send, keeps sells, stop-losses, armed SL/TP, the stuck-bag watchdog and monitoring running, and resumes on its own when the window opens. `TRADING_HOURS` / `TRADING_TZ` still work and apply on top (both windows must allow a buy).
- **Cadence (tunable):** lane cadences `LANE_CADENCE_SNIPER_LANE_MIN` (10), `LANE_CADENCE_MISC_LANE_MIN` (15), `LANE_CADENCE_WARDEN_LANE_MIN` (20), `LANE_MORNING_BRIEF_AT` (08:00), `LANE_NIGHTLY_EVAL_AT` (23:30). Bot-side cadences keep their existing settings (`AGENT_INBOX_CADENCE_S`, `SNIPER_LAUNCH_POLL_S`, `WALLET_POLL_INTERVAL_S`, `SNIPER_WATCH_INTERVAL_S`).
- **Check it:** `python bots/active_hours.py` prints whether new entries are allowed right now and each lane's cadence (no secrets).
- The setup wizard asks active hours right after the agent-autonomy question (`AGENT_MODE`).

## 0. Prerequisites

Have these ready before the first start. Every key goes in `bots/.env` (copy `bots/.env.example`, the single template; each key there says where to sign up).

- **A computer that stays on:** Windows, macOS or Linux, about 5 GB free disk. If it sleeps, trading pauses.
- **Python 3.12+** and **git**.
- **An AI agent** that can read files, run Python and keep a loop going (hosted or local; section 2).
- **A new burner Solana wallet** (`HOT_WALLET_PRIVATE_KEY`, `HOT_WALLET_ADDRESS`) funded only with what you can lose. Make it fresh in any Solana wallet app and export the private key. Never use a main wallet.
- **A Solana RPC** (`RPC_URL`, plus `HELIUS_API_KEY` if you use Helius): sign up at helius.dev, or use any Solana RPC provider. Routing: trades and wallet reads go to your RPC/Helius first; every other read is **free-first** (`RPC_FREE_URL`, default the public mainnet endpoint, with Helius via `HELIUS_API_KEY` as the fallback; turn off with `RPC_FREE_TIER=false`). So the console keeps showing chain reads even when `RPC_URL` is wrong; check the wallet line at boot to confirm your own RPC works. On a free Helius tier, 429 "too many requests" lines in the console are normal back-off, not errors.
- **One brain:** a Grok key from console.x.ai (recommended), or OpenAI (platform.openai.com), Anthropic (console.anthropic.com), any OpenAI-compatible endpoint, or Ollama (ollama.com) running locally for free.
- **Optional:** a cold wallet address for profit sweeps (`LEDGER_ADDRESS`), a Telegram bot for alerts (section 6), a Pinata account for token launches (`PINATA_JWT`, pinata.cloud), an X account for the browser scraper (section 9), an X API bearer token for x_intel (developer.x.com).
- **No key needed:** the PumpPortal new-token feed (`PUMPPORTAL_WS_URL`) and DexScreener prices are public.

## 0.1 What it costs

Public prices checked on **2026-10-14** from each provider's own page. **They change: check the provider before you sign up.** The bot itself is free (MIT).

| Item | Used for | Price on 2026-10-14 | Source |
|---|---|---|---|
| Helius RPC | `RPC_URL`, `HELIUS_API_KEY` | Free $0/mo: 1M credits, 10 req/s, 1 sendTransaction/s. Developer $49/mo: 10M credits, 50 req/s, 5 sendTransaction/s, extra credits $5 per million. Business $499/mo: 100M credits. Most RPC calls cost 1 credit; getProgramAccounts and DAS cost 10, getTransactionsForAddress 10 per 100 txs, Enhanced Transactions 100 (credits checked 2026-10-17). See 0.2 for the daily cap. | [helius.dev/pricing](https://www.helius.dev/pricing) |
| xAI Grok API (recommended brain) | analyst, narrative, judge, vision | grok-4.7 and grok-4.6: $2.00 input / $6.00 output per 1M tokens (prompts under 200k tokens; $4 / $12 above). grok-4.5: $2.00 / $6.00. grok-4.3: $1.25 / $2.50. | [docs.x.ai/docs/models](https://docs.x.ai/docs/models) |
| OpenAI API (optional) | any brain role | Per 1M tokens, examples: gpt-6.1-sol $2.00 / $10.00, gpt-6-luna $0.10 / $0.50, gpt-5-mini $0.25 / $2.00. | [platform.openai.com/docs/pricing](https://platform.openai.com/docs/pricing) |
| Anthropic API (optional) | any brain role | Per 1M tokens: Claude Sonnet 5.5 $2 / $10, Claude Haiku 5.5 $0.10 / $0.50 (prompts up to 100k tokens), Claude Opus 5.5 $4 / $20. | [docs.anthropic.com pricing](https://docs.anthropic.com/en/docs/about-claude/pricing) |
| Ollama local (optional) | free fallback brain | No API bill; runs on your own hardware (about 10 GB RAM/VRAM for `qwen3:14b-q4_K_M`). Ollama cloud: check provider. | check provider |
| Pinata (launches only) | `PINATA_JWT`, token image + metadata | Free $0/mo: 1 GB storage, 500 files. Picnic $20/mo. | [pinata.cloud/pricing](https://pinata.cloud/pricing) |
| pump.fun (launches) | creating a token | No platform fee to create a coin: you pay the Solana network fee and the small on-chain account deposit. Bonding-curve trades pay 1.25% total (0.30% of it goes to the creator). Graduation to PumpSwap: 0.015 SOL. Your dev buy is on top. | [pump.fun/docs/fees](https://pump.fun/docs/fees) (updated 2026-10-08) |
| PumpPortal | new-token feed; launch transaction builder | The new-token and migration feed the engine uses is free and needs no key. The Local Transaction API the launch rail uses to build the create + dev-buy transaction takes 0.5% per trade. | [pumpportal.fun/fees](https://pumpportal.fun/fees) |
| Solana network | every buy, sell, sweep, launch | Base fee plus the priority fee the bot sets (capped by `PANIC_PRIORITY_FEE_CAP_LAMPORTS`). | check provider |
| X API (x_intel, optional) | `X_BEARER_TOKEN` | check provider | check provider |
| Telegram (optional) | alerts | check provider | check provider |

How spend grows: LLM cost scales with how often your automations run (section 11) and how many packets the bots write; start with sparse cadences and watch the provider's usage page. RPC credits scale with scan volume; a 24/7 sniper usually outgrows a free RPC tier. Trading costs (DEX fees, slippage, priority fees) come out of every trade.

### 0.2 Helius credits and the daily cap

Helius bills in credits (checked 2026-10-17 at [helius.dev/docs/billing/credits](https://www.helius.dev/docs/billing/credits)): most RPC calls cost 1, getProgramAccounts and DAS 10, getTransactionsForAddress 10 per 100 transactions, Enhanced Transactions 100. The bot meters its own Helius calls per day (`bot_logs/helius_meter.json`) and, near a daily cap, slows background reads; trades, closes and wallet reads never wait on the cap.

The setup wizard asks which plan you are on and sets `HELIUS_DAILY_CREDIT_CAP` to about 1/30 of the monthly credits, so one bad day cannot burn the month:

| Plan | Monthly credits | Daily cap set |
|---|---|---|
| Free ($0) | 1M | 30,000 |
| Developer ($49) | 10M | 300,000 |
| Business ($499) | 100M | 3,000,000 |
| Custom | yours | any number |
| None | | 0 = off (warned: nothing stops a bug or a leaked key from burning the month) |

Unset (for example a non-interactive first run) = the Free cap, 30,000. `HELIUS_CAP_MODE` = `soft` (default; restrict at `HELIUS_SOFT_CAP_PCT`, 80%), `hard` (at 100%) or `log` (count only). Change it any time with the wizard (RPC area) or in `bots/.env`.

Typical use, from our own metering: Perps alone about 10k-300k credits/month; Meme Sniper about 0.15M-1.05M/month (the high end is 24/7 scanning); both about 0.2M-1.4M/month. Free fits Perps and a lean Sniper; pick Developer for a 24/7 Sniper.

To save credits the engine also caches confirmed transactions on disk (`bot_logs/tx_cache.sqlite`), reads routine transaction lookups from the free RPC first (one 10-credit `getTransactionsForAddress` call fills several misses instead of one call each), and keeps holder hold-times across restarts (`bot_logs/hold_time_cache.json`). Knobs: `TX_CACHE_*`, `RAW_TX_*` in `.env.example`.

## 1. Install and launch

Python 3.12+. `requirements.txt` includes `tzdata`, which Windows needs for time zones; without it every bot exits on start.

Use a virtual environment (newer Linux/macOS Pythons refuse a system-wide `pip install`). On Windows the command is `python` (or `py -3.12`); on macOS/Linux it is `python3`. Inside an activated venv, `python` works everywhere.

```
python3 -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium     # Linux: python -m playwright install --with-deps chromium (installs the system libraries too)
python bots/sniper.py
```

The **launcher menu** (`bots/sniper.py`) shows a banner and these options:

1. **Start Sniper** opens the console and runs `meme_sniper.py` and the sub-bots (security_warden, agent_autoagent, x_intel, agent_scraper, code_tuner, log_janitor, learnings_writer), each as a separate child process. Trench News (verified meme-space change alerts, every 3 days, `VENUE_ADAPT=ask`) runs inside `meme_sniper.py` itself, so it starts and stops with Sniper; there is nothing to run separately. A child that crashes restarts after a short backoff (5s, growing to 60s). Console output goes to `bot_logs/<name>.console.log`. One Ctrl+C stops everything cleanly and writes `stop_reason: user_stopped`. To run only some components, set `SNIPER_COMPONENTS=meme_sniper,security_warden`.
2. **Setup wizard** asks for the must-haves and writes `bots/.env`. Secrets are typed hidden and never echoed. It asks for: wallet key and address, cold wallet for sweeps (`LEDGER_ADDRESS`, optional), RPC URL and `HELIUS_API_KEY`, your **Helius plan** (Free / Developer / Business / Custom / None; sets the daily credit cap, section 0.2), the brain (Grok, Ollama, OpenAI, Anthropic, OpenAI-compatible), buy size and default SL/TP, **launch rail on/off** (`LAUNCH_RAIL_ENABLED`, default off), **launch rail live yes/no**, the **Safety caps** (daily loss stop 0.5 SOL, daily buy cap 10, same-token cooldown 72h, loss-streak pause 3, max open positions 3, trading hours blank = always, timezone America/New_York; `SNIPER_WIZARD_SAFETY=0` skips them), the dev-buy cap, `PINATA_JWT`, own-launch mode, Telegram, and your trading rules. It opens with a status table by area (Set / Missing, never the values; the Brain area shows the main and fallback first, then only their key/model rows, other providers grey "off"), then: 1 fill only what is missing (default), 2 edit specific items, 3 go through everything. Enter keeps a value, `clear` blanks one, and nothing is saved until the final confirm. At any prompt `q`, `back` or `esc` goes back without saving (the Esc key also works on single-key menus); Ctrl+C is not "back": it stops the launcher as usual.
3. **Sign in to X** checks the session first and shows it: `Connected (verified) as @handle (expires ...)`, `Cookie present, unverified`, `Expired` or `Missing`. When connected you get **Keep** (default; nothing is paused, no browser opens) or **Switch account / re-login**. Only switch or sign in installs Playwright Chromium if needed, pauses the scraper and runs `agent_scraper --login` in the same profile the scraper uses (section 9).
4. **Live dashboard** shows wallet, positions, treasury, PnL, activity, heartbeats and alerts. It reads state files only and never trades. Prices come from one batched DexScreener call every `DASH_DEX_MIN_INTERVAL_S` (default 30) and the balance from one `getBalance` every `DASH_RPC_MIN_INTERVAL_S` (default 120).
5. **Launch a token** builds a request in `json_relay/launch_requests/`. The rail checks the repo and the dev-buy cap (`docs/LAUNCH_RAIL.md`).
6. **Console only** opens the console (section 10) without starting anything.
7. **Exit**

> **Token launches ship off-chain.** The wizard asks "Launch tokens live on-chain?" and the default answer is **no** (`LAUNCH_RAIL_LIVE=0`, dry runs only). With yes (`LAUNCH_RAIL_LIVE=1`), the agent can create tokens on pump.fun, buy the dev bag (up to `LAUNCH_MAX_DEV_BUY_SOL`), burn and claim fees with real SOL from the trading wallet. Keep **no** to keep launches off-chain. See section 4 for who decides when to launch.

You can also run one option directly: `--start`, `--dashboard`, `--wizard`, `--launch`, `--console`, `--telegram-test` or `--help` (`--no-ui` keeps `--start` on the plain status view). `--smoke` renders everything and dry-writes the wizard to a temp file (it sends nothing; the only file it may create in the repo is an empty `rules/rules.md` from the template, plus lines in `bot_logs/sniper_launcher.log`). `--ui-smoke` runs the console self-test on a throwaway temp copy of the repo (made and deleted for you; set `WORKSPACE_DIR` to use your own temp copy instead). It times out instead of hanging. With no terminal and no flag, the launcher exits instead of waiting at the menu.

**First run.** If `bots/.env` is missing or incomplete (wallet key, RPC or model key), the wizard opens on its own.

**Agent first-run questions.** Your SI agent also asks you, before the first trade, starting with agent autonomy (`AGENT_MODE`, default `suggest`), then active hours (`ACTIVE_HOURS`, default `00:00-23:59` = always, + `ACTIVE_TZ`), then paper or live (default paper), launch rail (default off), buy size, daily loss stop (0.5 SOL), daily buy cap (10), stop loss / trailing stop, same-token cooldown (72h), loss-streak pause (3 losses, 2h), max open positions (3), and trading hours + time zone (blank = always). See README "Safety caps and your settings".

**Skipping the wizard (`setup.json`).** You can configure without the interactive wizard. Put `setup.json` in the repo root (or in `bots/`):

```json
{"env": {"HOT_WALLET_PRIVATE_KEY": "...", "HOT_WALLET_ADDRESS": "...", "RPC_URL": "...",
         "GROK_API_KEY": "...", "SNIPER_BUY_SIZE_SOL": "0.1", "LAUNCH_MAX_DEV_BUY_SOL": "0.5",
         "OWN_LAUNCH_MODE": "hold", "OWN_LAUNCH_TREASURY_PCT": "50", "SNIPER_LEARN_REST": "true"}}
```

Every key under `env` is written into `bots/.env`, and the launcher logs `configured by agent` to `bot_logs/sniper_launcher.log`. A complete `bots/.env` also skips the wizard. `setup.json` holds secrets, so the launcher **deletes it right after applying it** (it is also in `.gitignore`). Write it again for the next change.

## 2. Who's running it

Ask the owner which of these fits:

1. **Hosted agent on its own computer.** The repo lives on the agent's machine. It's always on and hands-off, and keys are stored as the agent's saved secrets.
2. **Hosted agent working on the owner's PC.** The repo lives on the owner's PC and keys stay local. You act through approved computer access. If the PC sleeps, everything pauses.
3. **Local agent.** You download the repo to the PC and run everything yourself.

## 3. Root folder

Everything lives under one root folder: **the repo folder (the one that contains `bots/`)**, unless `WORKSPACE_DIR` is set in the environment or in `bots/.env`, in which case that folder is the root.

```
<root>/
  bots/            sniper.py, meme_sniper.py, sniper_ui.py + sub-bots/ + tuner/
  skills/          default skills + sub-skills/
  inbox/           packets from bots, waiting for you
  inbox_results/
    done/          handled packets
    failed/        unroutable or broken packets (+ .failure.md)
  owner_inbox/     notify-only pings for the owner
  learnings/       LEARNINGS.md + nightly history
  rules/           the owner's rules (rules.md)
  json_relay/      bot-to-bot handoff files
  bot_logs/        logs, state, audit (seed files ship empty: kol_list, archetype_roster)
```

Every bot resolves paths from this one root and creates any missing folders on first start. Nobody has to make them by hand.

## 4. Wallet, sizes and going live

These settings are configuration. How much the agent does on its own is the owner's `AGENT_MODE` choice (asked first): in `suggest` (default) every buy and sell waits for the owner's OK; in `auto` the agent trades inside these caps without asking.

Ask the owner to pick one:

- **Set it now.** Walk through the must-haves in `bots/.env.example`: wallet, buy size, SL/TP, RPC, LLM order, vision provider.
- **Learn as it goes.** Fill in only the wallet and keys, and run on the defaults. The system tightens itself from results and logs every change to `bot_logs/`.
- **Mix.** The owner sets the must-haves and the rest learns.

The safety switches set here (wallet, buy sizes, `LAUNCH_RAIL_ENABLED` off / `LAUNCH_RAIL_LIVE` off by default) stay as the owner set them. After this step you operate within the owner's chosen mode: in `suggest` (default) you propose buys and sells and the bot holds them for the owner's OK; in `auto` you send them and owner-ping is notify-only. KOL/dev list changes, learnings promotion and profit sweeps follow the owner's rules; code patches are always proposed to the owner as a card with a diff. Launches stay off-chain until the owner sets `LAUNCH_RAIL_LIVE=1`.

**Launching without asking: who decides.** Two things decide it, and nothing else:

1. **The wizard's launch choice** (`LAUNCH_RAIL_LIVE`). `0` means you never launch on-chain, whatever else says. `1` allows live launches. The default is `0`.
2. **The owner's `rules/rules.md`.** If it says to ask before launching (or bans launches), follow it: ask in owner-ping and wait for a yes. If it says nothing about launches, launch on your own judgment inside the dev-buy cap and notify afterwards.

If the two conflict, the stricter one wins. Skill text that says "launch without asking" means "when these two allow it".

### 4.1 Buy size, default exits and learning mode

The wizard asks for a buy size and default SL/TP. They are live settings, not notes:

| key | what the engine does with it |
|---|---|
| `SNIPER_BUY_SIZE_SOL` | Replaces `SIZE_CAP_BASE_SOL` as the base entry cap (the tier ladder is scaled down to match, never up), and is used as the size when a buy signal has no `amount_sol`. The `MIN_BUY_SOL` floor, wallet floor and concentration checks still apply. |
| `SNIPER_DEFAULT_SL_PCT` / `SNIPER_DEFAULT_TP_PCT` | Armed as the stop-loss / take-profit on every new position whose buy signal sets none (inside the `PROTECT_*` bounds). The agent can change them per trade with `set_protection`. |
| `PROTECT_DEFAULT_STOP` | Default `true`. A flip bag with no valid agent stop sells on its default flip stop (`stop_loss_pct`) through the armed-protection path. Agent levels always win. |
| `LEAGUE_MODE` | Default `false`. `true` runs Sniper as an AudaceFi devnet league bot (see `bots/league_mode.py` and the League mode section of the meme-hunter skill). Live mainnet path is unchanged when off. |
| `LEAGUE_RPC_URL` / `LEAGUE_WALLET_ADDRESS` / `LEAGUE_WALLET_KEYPAIR_PATH` (or `LEAGUE_WALLET_PRIVATE_KEY`) / `LEAGUE_USDC_MINT` | Devnet RPC (checked by URL and genesis hash), a separate league wallet (refused if it matches the main wallet or key), and the league USDC mint. |
| `LEAGUE_ALLOWLIST_FILE` / `LEAGUE_CATEGORY` | Category allowlist (JSON list of mints, `{"mints": [...]}` or `{"degen": [...]}`); no list = no league buys. Category defaults to `degen`. |
| `LEAGUE_SEASON_START` / `LEAGUE_SEASON_END` / `LEAGUE_FLATTEN_BUFFER_MIN` | Season window (default Mon 00:00 to Sat 00:00 UTC); buys stop and bags flatten to USDC this many minutes (120) before each snapshot. |
| `LEAGUE_BUY_USDC` / `LEAGUE_MAX_BUY_USDC` / `LEAGUE_EXECUTOR_MODULE` | League buy size and cap in USDC (25 / 100); the AudaceFi supported-API executor module (buy/sell/price). Without it league trades are refused. |
| `SNIPER_LEARNING_MODE` | Learning mode (below). Off by default. |
| `SNIPER_LEARN_REST` | The wizard's "let the system learn the rest". With learning mode on, it also sends the agent a tune invitation after each learning step, so the other filters get tuned from the same results through the normal tune-response path. Off: learning only touches size and SL/TP. |

Unset (or 0) means the engine behaves exactly as before. **Where they live:** each key is also a knob of the same name in `bots/tuner/meme_sniper_filter.json`. When the value in `bots/.env` changes (wizard, Settings `.env` row, a hand edit), the engine copies it into the knob within about 30 seconds, logged as `by owner_env`. Between owner changes, the agent, the Settings filter row and learning mode change the knob directly; the engine uses the knob. Both rows show in Settings, with who changed them and when, and the usual stale-write guard applies.

**Learning mode** (`SNIPER_LEARNING_MODE=1`, from the wizard, Settings or the filter file). It lets the owner, or you, teach the system their own edge:

- It starts conservative: if no size or SL/TP is set it uses 0.1 SOL (never below `MIN_BUY_SOL`), SL 20%, TP 60% (`SNIPER_LEARN_START_*`).
- After every `SNIPER_LEARN_COOLDOWN_H` hours (default 24) with at least `SNIPER_LEARN_MIN_TRADES` closed trades (default 10), it reads the autopsies (`_tune_perf_window`) and moves size, SL and TP by at most `SNIPER_LEARN_STEP_PCT` (default 10%) each: size up on a winning stretch (WR >= 55% and average PnL > 0), down on a losing one; SL wider when most exits are stops; TP higher when take-profits are hit often, lower when they never are.
- Hard caps win: size never goes above `SIZE_CAP_BASE_SOL` or the `## Max size` in `rules/rules.md`, never below `MIN_BUY_SOL`; SL stays 10-40% and TP 20-500% inside the `PROTECT_*` bounds. The owner's rules override it at every decision.
- Every change goes through the filter file (`by learning_mode`, with the reason and the numbers), so it shows in Settings, and a line is appended to `bot_logs/learning_log.jsonl` (paper: `bot_logs/paper/`).
- Turn it off any time: the learned values stay.

**Reviewing progress (you):** read `bot_logs/learning_log.jsonl` in the weekly forensics review, tell the owner what moved and why, and turn it off if the owner asks or results get worse over two steps.

**Hold benchmark (optional).** Holds are scored against $GORK by default (`bot_logs/gork_standard.json`, lore in `skills/gork-lore`). To use your own token, send the agent its ticker AND CA: it curates `bot_logs/hold_benchmark.json` and a local lore skill (meme-hunter "Set a custom hold benchmark") and sets `SNIPER_HOLD_BENCHMARK=bot_logs/hold_benchmark.json`. A ticker alone, or an invalid file, is ignored and $GORK stays. Blank = $GORK.

### 4.2 Paper mode

`SNIPER_PAPER_MODE=1` (off by default; live stays the default). The owner turns it on explicitly: the wizard asks (default No), Settings, or `bots/.env`. It is read when the engine starts, so restart after switching.

- The whole pipeline runs: feed, filters, rug checks, your decisions, armed exits.
- Buys and sells are simulated at real Jupiter quotes, less `SNIPER_PAPER_SLIPPAGE_PCT` (default 1%) and the base + priority fee, against a paper wallet that starts at `SNIPER_PAPER_START_SOL` (default 1 SOL).
- No transaction is ever sent: the engine refuses `sendTransaction`, and the launch rail treats every launch as a dry run.
- Positions, autopsies, PnL and the trade ledger live in `bot_logs/paper/` (`paper_wallet.json`, `paper_trades.jsonl`), separate from live. Learning mode trains on paper results.
- The dashboard and console show a PAPER banner; every Telegram alert starts with `[PAPER]`. Tag your own owner pings the same way.
- Switching back to live needs an explicit confirm: type `LIVE` in the wizard or Settings; through `setup.json` add `"SNIPER_CONFIRM_LIVE": "LIVE"`. Never switch to live without the owner's explicit OK.

Other sub-bots (warden, autoagent) still read the live `bot_logs/` files while paper runs.

## 5. Models

Grok (xAI) is the default and recommended brain. Ollama is optional, local or cloud.

| role | Grok (recommended) | local Ollama | Ollama cloud (opt-in) |
|---|---|---|---|
| analyst (deep reads, tuning, autopsy) | grok-4.7 | qwen3:14b-q4_K_M | deepseek-v4-pro:cloud |
| narrative (social/lore reads) | grok-4.7 | qwen3:8b | glm-5.3-flash:cloud |
| judge (overseer, short verdicts) | grok-4.7 | qwen3:8b | glm-5.3:cloud |
| vision (charts, images) | grok vision (auto) | qwen2.5vl:7b | - |

**Pick one main brain and one fallback.** `LLM_MAIN` = `grok` | `openai` | `anthropic` | `ollama` | `openai_compat` (default `grok`), `LLM_FALLBACK` = the same list or `none` (default `ollama`). Only those two run: every other provider is OFF even if its key is set, so having Grok, OpenAI and Anthropic keys all in `.env` never makes it unclear which one answers. The wizard's Brain section asks for these first and then only shows the key/model rows of the two you picked. Ollama cloud stays an opt-in under ollama (`OLLAMA_CLOUD_ENABLED` + your own key). Legacy: with `LLM_MAIN` unset, `LLM_PROVIDER_ORDER` works as before.

- **Grok:** set `GROK_API_KEY` and `GROK_TEXT_MODEL` (default `grok-4.7`).
- **Local Ollama:** install Ollama, `ollama pull qwen3:14b-q4_K_M` (and `qwen2.5vl:7b` for vision), then pick it as `LLM_FALLBACK=ollama` (or `LLM_MAIN=ollama`) and set `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`. Choosing it turns `OLLAMA_ENABLED` on.
- **Ollama cloud:** off by default. Set `OLLAMA_CLOUD_ENABLED=true`, `OLLAMA_CLOUD_API_KEY` (the owner's own key) and `OLLAMA_CLOUD_MODEL`. It runs only when ollama is the main or fallback, after local Ollama.
- Vision uses the same main and fallback (legacy: `VISION_PROVIDER_ORDER`).

The setup wizard asks for all of these (keys typed hidden).

**Recommended setups.** Any provider works; these are starting points.

- **Recommended: Grok + local Ollama.** Grok (xAI) is the brain Meme Sniper was built and tuned with, so its prompts, packet formats and defaults were shaped around Grok's answers. Set `GROK_API_KEY`, keep `LLM_MAIN=grok` and `LLM_FALLBACK=ollama` (local Ollama is a free fallback for when Grok is slow or down).
- **Budget: local Ollama only.** No API bill. Set `LLM_MAIN=ollama` and `LLM_FALLBACK=none`. Expect slower, weaker reads than a hosted model; it needs a machine that can run a 14B model.
- **Bring your own.** Already pay for OpenAI, Anthropic or an OpenAI-compatible host? Make it the main, e.g. `LLM_MAIN=anthropic`, `LLM_FALLBACK=ollama`. Everything works; you may want to re-check the skills' thresholds after a week of results.

**Local model setup (Ollama).** Install from ollama.com, then:

```
ollama pull qwen3:14b-q4_K_M      # text
ollama pull qwen2.5vl:7b          # vision (charts, images)
ollama list                       # both should be listed
```

Pick ollama as main or fallback (default URL `http://localhost:11434`, change with `OLLAMA_URL`). On start, agent_autoagent logs whether the fallback model is present.

**Any provider works.** The brain is provider-agnostic (`bots/sub-bots/llm_providers.py`, plain HTTP, no SDKs). Pick `LLM_MAIN` and `LLM_FALLBACK` from the table below (text and images use the same pair); providers you did not pick are off. A chosen provider with no key or no model set is skipped, so the fallback answers.

| provider (`LLM_MAIN` / `LLM_FALLBACK` value) | keys | model | vision |
|---|---|---|---|
| grok (default main) | `GROK_API_KEY` (or `XAI_API_KEY`) | `GROK_TEXT_MODEL` (grok-4.7), `GROK_VISION_MODEL` | yes |
| openai | `OPENAI_API_KEY` (`OPENAI_BASE_URL` optional) | `OPENAI_MODEL`, `OPENAI_VISION_MODEL`: pick a current model, blank = off | yes, if the model takes images |
| anthropic (Claude) | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL`, `ANTHROPIC_VISION_MODEL`: pick a current model, blank = off | yes |
| ollama (default fallback) | `OLLAMA_URL` (on when chosen); cloud opt-in: `OLLAMA_CLOUD_ENABLED`, `OLLAMA_CLOUD_API_KEY` | `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`, `OLLAMA_CLOUD_MODEL` | local yes (vision model), cloud text only |
| openai_compat (any OpenAI-compatible endpoint) | `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_API_KEY` (if needed) | `OPENAI_COMPAT_MODEL`, `OPENAI_COMPAT_VISION_MODEL` | if the endpoint supports images |

Packets stamp the provider and model that answered. `python bots/test_llm_providers.py` checks every provider path offline (mocked HTTP).

## 6. Alerts (optional)

Owner alerts (fills, exits, halts, warden and medic alerts, overseer, code tuner, launch rail results) go through one dispatcher, `bots/sub-bots/alerts.py`, to every channel in `ALERT_CHANNELS`. None is required.

| `ALERT_CHANNELS` value | Channel | Needs |
|---|---|---|
| `telegram` | Telegram bot | `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (optional backup bot `X_NOTIFY_TELEGRAM_TOKEN`) |
| `discord` | Discord webhook | `DISCORD_WEBHOOK_URL` |
| `email` | Email over SMTP | `SMTP_HOST`, `ALERT_EMAIL_TO` (+ `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`) |
| `ntfy` | ntfy push | `NTFY_TOPIC` (+ `NTFY_URL`, `NTFY_TOKEN`) |
| `off` | nothing | - |

- Combine them: `ALERT_CHANNELS=telegram,ntfy`. Blank keeps the old behaviour: Telegram if its token and chat are set, otherwise no alerts.
- **Wizard** (launcher menu 2): the **Alerts** area shows each channel's status first (On / On - Missing Keys / Off), then asks only the keys of the channels you pick, then offers a **test message per channel**. q / back / Esc goes back without saving.
- **Settings** (console menu 3): press **A** for the Alerts screen: status first, test any channel by number (`a` = all on), q / Esc back. Change the channel list on the `Alert Channels` row or in the wizard.
- Every send is logged to `bot_logs/alerts.log`: time, source bot, channel, sent / failed / throttled, the HTTP code or error type, a 60-character preview. Tokens, passwords, webhook URLs and chat IDs are never written.
- **iMessage** is planned for the Mac version; it is not available yet.

### 6.1 Telegram

Telegram is on when `ALERT_CHANNELS` includes `telegram` (or is blank) and `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` are set in `bots/.env` (fills, exits, halts, warden alerts, launch rail results; `TELEGRAM_ON_*` keys switch event types). Leave both blank to run without Telegram. The setup wizard asks for all three keys below (tokens typed hidden).

**Create the bot (token)**

1. In Telegram, open a chat with **@BotFather** and send `/newbot`.
2. Pick a display name (anything), then a username that ends in `bot` (for example `my_sniper_alerts_bot`).
3. BotFather replies with the token (`123456789:AA...`). That is `TELEGRAM_TOKEN`. Keep it secret; anyone with it can send as your bot.

**Get your chat ID**

4. Open your new bot in Telegram and send it any message (for a group: add the bot to the group and post a message there). A bot cannot message you until you have written to it first.
5. In a browser, open `https://api.telegram.org/bot<TOKEN>/getUpdates` (paste your token in place of `<TOKEN>`). Find `"chat":{"id":...}` in the reply. That number is `TELEGRAM_CHAT_ID`; group IDs start with `-`. If the reply is empty, send the bot another message and reload. A chat-ID bot (search Telegram for one that replies with your user ID) works too for a personal chat.

**Optional: backup alert bot**

6. `X_NOTIFY_TELEGRAM_TOKEN` (shown as *Backup alert bot token* in the wizard and Settings) is a second bot the warden sends its alerts through. Use it if another app or agent already polls your main bot: Telegram allows only one poller per bot, and a second one causes conflicts. Create it with @BotFather exactly like steps 1 to 3 and send it a message once. Blank = the warden uses the main token. Alerts go to the same `TELEGRAM_CHAT_ID`. The warden only sends; it never reads commands.

**Save and test**

7. Run the setup wizard (launcher menu 2) and fill the Telegram rows, or put the keys in `bots/.env`.
8. Test: when the wizard saves a Telegram change it offers **Send a Telegram test message** (default yes). Any time later: `python bots/sniper.py --telegram-test`. It sends one message through the main bot and, if set, the backup bot, and tells you what failed: `401` = wrong token, `400` / chat not found = wrong chat ID or you have not messaged the bot yet, `403` = the bot is not in that chat or was blocked. Tokens are never printed.

### 6.2 Discord webhook

1. In Discord: **Server Settings > Integrations > Webhooks > New Webhook**, pick the channel, **Copy Webhook URL**.
2. Put it in `DISCORD_WEBHOOK_URL` (typed hidden in the wizard; it is a secret: anyone with it can post to that channel) and add `discord` to `ALERT_CHANNELS`.
3. Test from the wizard or Settings > A. `404` = the webhook was deleted or the URL is wrong. Messages are sent as plain text, up to 2,000 characters.

### 6.3 Email (SMTP)

1. Set `SMTP_HOST` and `SMTP_PORT` (`587` = STARTTLS, the default; `465` = SSL), `SMTP_USER` / `SMTP_PASS` if your server needs a login, `SMTP_FROM` (blank = `SMTP_USER`) and `ALERT_EMAIL_TO`. Add `email` to `ALERT_CHANNELS`.
2. Gmail: `smtp.gmail.com`, port `587`, your address as user, and an **app password** (Google Account > Security > App passwords), not your normal password.
3. `ALERT_EMAIL_MIN_INTERVAL_S` (seconds, default `60`) limits mail volume: alerts inside the window are counted and the next email says how many were not mailed. The other channels are not limited.
4. Test from the wizard or Settings > A. `SMTPAuthenticationError` = user / password refused.

### 6.4 ntfy (phone push)

1. Install the ntfy app (Android / iOS) or use the web app, and subscribe to a topic with a long, unguessable name (anyone who knows a public topic can read it).
2. Set `NTFY_TOPIC` to that name; `NTFY_URL` defaults to `https://ntfy.sh` (set your own server if you run one); `NTFY_TOKEN` only for access-protected topics. Add `ntfy` to `ALERT_CHANNELS`.
3. Test from the wizard or Settings > A. Silent engine alerts are sent at low priority.

### 6.5 Owner commands (optional, off by default)

In `AGENT_MODE=suggest` these also carry trade approvals: `/approve <id>` and `/reject <id>` (no owner commands set up? run `python bots/approve.py` to list and approve on the machine).

Ask the agent for a roast, recap or trade autopsy whenever you want instead of waiting for the nightly 2 AM report.

| Command | What you get |
|---|---|
| `/roast` | An honest roast of the last 24h, aimed at whoever made the trades: trades you made yourself (manual buys, bags you kept with `/leave`) roast you; the agent's trades get the agent's own Overseer self-roast; a mixed book gets both. `/roast agent` always roasts the agent |
| `/recap` | The same judges, framed as a recap (strong, weak, missed, next) |
| `/autopsy` or `/autopsy last` | The latest closed trade: PnL, exit trigger, post-close watch (did it run after you sold) |
| `/autopsy gork` or `/autopsy $gork` | The latest closed trade on that ticker |
| `/approve <id>` / `/reject <id>` | Answer a trade the agent suggested (`AGENT_MODE=suggest`); `/approve` alone lists pending ones |
| `/manage <ticker>` or `/leave <ticker>` | Answer an owner-position question (section 6.6) |
| Plain text | "roast me", "recap please", "autopsy on $gork": commands are case-insensitive |

Set `OWNER_ROAST_TARGETING=off` to always roast the agent (the old behaviour). `/roast` and `/recap` make one SI call each (a mixed-book roast makes two) and share a cooldown (`OWNER_ROAST_COOLDOWN_S`, default 900 s). `/autopsy` reads `bot_logs/autopsy_reports.json` and makes no SI call. On-demand answers never write the nightly packet, history or LEARNINGS, never change the 2 AM schedule and never trade. Every reply is also saved in `inbox_results/owner_replies/`.

Pick a source with `OWNER_COMMANDS` (wizard > Owner Commands, or `.env`):

- **`off`** (default): nothing runs and the launcher does not start `owner_commands`.
- **`file`** (any OS, no Telegram): drop a text file into `owner_commands/` in the root folder, e.g. `roast.txt` containing `/roast`, or a `.json` like `{"text": "/autopsy last"}`. It is picked up within about 5 seconds, answered through your alert channels (section 6) and moved to `inbox_results/owner_commands/done/`. An agent or a script can use this too.
- **`telegram`**: chat with a **separate** command bot.
  1. In Telegram message @BotFather, send `/newbot` and copy the new token into `OWNER_COMMANDS_TG_TOKEN`. Do not reuse `TELEGRAM_TOKEN` or `X_NOTIFY_TELEGRAM_TOKEN`: Telegram allows one reader per bot, so it refuses those.
  2. Open the new bot and press Start. Replies go to `OWNER_COMMANDS_TG_CHAT_ID` (blank = `TELEGRAM_CHAT_ID`); messages from any other chat are ignored. Anyone who can post in that chat can send commands, so use a private chat or one you trust.
  3. It skips messages sent before it started, stops (and logs why) if a webhook is set or another app already polls that bot (409), and never retries against it.

Check it without starting anything: `python bots/sub-bots/owner_commands.py --check` (shows the mode and readiness, never a token). Try one command locally: `python bots/sub-bots/owner_commands.py --once "/autopsy last" --no-send`. Restart the launcher after changing `OWNER_COMMANDS`. Log: `bot_logs/owner_commands.log`. Test: `python bots/tests/test_owner_commands.py` (offline).

### 6.6 Owner positions

If a token bag shows up in the wallet that the bot did not buy (you bought it by hand or on another app), the bot asks before touching it. A light check every `OWNER_POS_SCAN_MIN` minutes (default 5; one token-account call per check, alternating the SPL Token and Token-2022 programs) and the 30-min holdings sweep both look for it. Once found it is tagged as an owner position, the bot writes an `owner_position` packet to `inbox/` and alerts: "I see a $50 PEPE position I didn't open. Manage it or leave it to you?"

| Answer | What happens |
|---|---|
| `/manage pepe` (owner commands) or the SI relays `{"action": "owner_position", "id": "...", "decision": "manage"}` | Booked as a flip position that exits on stop-loss, take-profit and trail only. It skips the max-hold time exit unless `OWNER_POS_TIME_EXIT=on`. Rug and liquidity protections still apply. Cost basis is unknown, so P&L counts from the mark. |
| `/leave pepe` or `"decision": "leave"` | Stays yours on the holdings ledger. Holding alerts only; the bot never sells it. |
| No answer within `OWNER_POS_TIMEOUT_MIN` (default 30) | The bot manages it and sends an alert saying so. |

Bags already in the wallet the first time this runs are not asked about. Stablecoins, bags under `OWNER_POS_MIN_USD` (default $10) and leftovers from the bot's own buys are skipped. Commands are case-insensitive. Turn it off with `OWNER_POS_ENABLED=false`. Every detection, answer and timeout is logged to `bot_logs/owner_positions.jsonl`.

### 6.7 Clone runners

The canonical (OG) pick per ticker does not change. A copycat token (a clone) is normally folded into the canonical's card or suppressed. A clone becomes a **runner** when it clearly outpaces the canonical: volume at least `RUNNER_VOL_RATIO` times the canonical's (default 3; 1h volume when both have it, else 24h) and more liquidity, held for `RUNNER_SUSTAIN_MIN` minutes (default 60), with a clean rug check and live socials (bullish or mixed). A runner gets its own inbox card marked "Clone Running" with `context.runner` (canonical mint, volume and liquidity ratios, since when). It still passes every normal filter and safety rule; there is no buy bypass and the agent decides. Turn it off with `CLONE_RUNNER_ENABLED=off`.

Promotions and outcomes (market cap at 6h and 24h; a hit is +50% at 24h) are logged to `bot_logs/clone_runners.jsonl`, the hit rate is summarised in `bot_logs/clone_runner_review.json`, and traded runners are tagged `clone_runner` in the autopsy. Sustain state lives in `bot_logs/clone_runner_state.json`.

## 7. Owner rules (`rules/rules.md`)

Ask the owner for personal trading rules: max size, no-trade hours, banned tokens or categories, loss limits, their own exit rules, anything they always or never do. The setup wizard asks and writes `rules/rules.md`; with no rules it writes an empty template (empty is fine, it can be filled later). `rules/rules.example.md` shows a filled-in example.

- Read `rules/rules.md` before every trade decision. meme_sniper attaches it to every decision packet as `owner_rules` (text, hash, updated time), so it is always in context.
- Owner rules override skill defaults. The hard safety gates (wallet floor, rug checks, size caps, concentration) still apply; a rule can make you stricter than a gate, never looser.
- When the owner changes a rule, record it in `learnings/LEARNINGS.md` like any skill change.

## 8. Tune the skills to the owner (before the first trade)

The skills ship as one tested public version (v14.3), tuned for a cautious, newer owner: small sizes, tight leashes, few holds.

1. Read `skills/README.md`, then every skill it lists.
2. Ask the owner about their experience and risk: how long they have traded memes, wallet size, how much drawdown they can sit through, flip or hold bias, how hands-on they want to be.
3. Adjust the skills to fit. A newer owner keeps the defaults. An experienced owner can widen sizes (inside the hard gates), loosen hold patience bands, change SL/TP defaults and the peel sizes of the **Layoo ratchet** (meme-hunter's default profit-taking loop: take profit in slices as a token climbs and raise the stop under it). Never touch the hard gates (wallet floor, rug checks, load-bearing hold criteria).
4. Record every change: append a dated entry to `learnings/LEARNINGS.md` (what changed, from what, why, for which owner profile) and keep a copy of the original skill next to it, so results can be graded against the defaults later.

## 9. Connect X (browser scraper and x_intel)

`bots/sub-bots/agent_scraper.py` drives a real browser through Playwright. It uses its own profile at `bots/scraper_profile/`, never the owner's daily browser, so the owner's own logins are never touched.

**Sign in once:**

1. Use a dedicated X account if you can (scraping from a main account risks rate limits or locks).
2. Run **launcher menu option 3 (Sign in to X)**, or **console menu option 6 (Sign in to X)** while Sniper runs, or `python bots/sub-bots/agent_scraper.py --login`. Option 3 installs Playwright Chromium first if it is missing. The console option pauses the running scraper (`bot_logs/agent_scraper_pause.flag`) so the profile is free, then resumes it.
3. A Chromium window opens. Sign in to X there, finish any 2FA or captcha, wait for the home timeline, then close the window.
4. The session is saved in `bots/scraper_profile/`. The scraper, the launcher and the console all resolve this one profile (`bots/sub-bots/x_session.py`); `BROWSER_USER_DATA_DIR` is only for deliberately pointing at another Chrome profile. Status is honest: **Connected (verified)** needs unexpired `auth_token`/`ct0` cookies (names and expiry only, values are never read) AND a logged-in X page (account switcher visible) seen by the scraper or the login in that profile within `X_VERIFY_MAX_AGE_H` hours (default 24, recorded in `bot_logs/x_session.json`). Cookies without that are **Cookie present, unverified**; a login wall seen since, or past-expiry cookies, is **Expired**.

The scraper runs in a minimized window by default; set `AGENT_SCRAPER_HEADLESS=true` to hide it completely.

**x_intel needs an API key, not the browser.** `x_intel` reads X through the X API and needs `X_BEARER_TOKEN` (from developer.x.com). Without it, it logs `skipped: no_bearer` each cycle and carries on; nothing else breaks. The OAuth keys (`X_CLIENT_ID`, `X_CLIENT_SECRET`, `X_USER_ID`, `X_INTEL_TOKEN`, `X_INTEL_REFRESH_TOKEN`) are only for reading the X account's own bookmarks and likes (OAuth 2.0 user context); leave them blank to skip that. x_intel saves a refreshed `X_INTEL_TOKEN` back into `bots/.env` on its own.

## 10. Console (`bots/sniper_ui.py`)

**Start Sniper** (launcher menu option 1) opens the console in the same window while the supervisor keeps the bots running (`--no-ui` or `SNIPER_UI=0` gives the plain status view). **Launcher menu option 6 (Console only)** opens it without starting anything. It reads state files only and never trades.

The **console menu** has eight options, 1 to 8:

- **1 Live dashboard**: wallet, positions (with hold time, `RED>max` flag), PnL for the period and today, goals, autopsy, and a health line (model latency + last error, whether local-Ollama fallback is active, RPC latency with the masked host + last error, from `bot_logs/sniper_health.json`). Keys (shown as `[Q] Back  [X] Bags  [G] Goals  [A] Periods  [R] Reset Period  [C] Recap  [M] Mute`; letters are case-insensitive): `X` bag actions, `G` goals, `A` past periods, `R` reset period (archived to `bot_logs/pnl_archive.jsonl`, history untouched), `C` recap, `M` mute, `Q` / `Esc` back. Every screen and sub-page stays open until you press `Q`, `Esc` or type `back`; nothing returns on a timer. **Goals** are set in the active chain's native coin (SOL today, taken from the chain adapter): pick daily / weekly / custom (any case) and a target.
- **2 Logs**: one tab per source, picked by key. `1` engine console (`meme_sniper.console.log`), `2` trades, `3` execution ledger, `4` declines, `5` warden alerts (`security_warden.json`, `medic_log.json`, `integrity_log.json`, `bot_alerts.json`), `6` `owner_inbox`; sub-bot consoles: `w` security_warden, `a` agent_autoagent, `x` x_intel, `s` agent_scraper, `t` code_tuner, `j` log_janitor, `e` learnings_writer (console + `learnings_writer.jsonl`), `8` Trench News (`trench_news.console.log` + `trench_news.jsonl`); `l` launcher log. Every sub-bot tab reads the `bot_logs/<name>.console.log` the launcher writes. Scrollback and search (`/` search, `N` next hit, `P` previous hit). `R` **JSON Relay** lists the files in `json_relay/` (the folder the engine polls for agent requests and writes responses to), newest first, with request counts and pending status, and shows the newest file; empty means nothing is in flight. Tab names and key hints use the same `[Key] Name` style as every other screen. Trades and the execution ledger follow paper mode (`bot_logs/paper/`). `i` shows the agent inbox (packets queued by the feed). Files that are created on first write show a plain empty state ("no trades yet, waiting for first trade") instead of "not found".
- **3 Settings**: every knob in `bots/tuner/meme_sniper_filter.json` and the engine's own keys in `bots/.env` (secrets locked and masked), plus console toggles. Up/Down picks a row; the full description shows below. Edits are range-checked, confirmed, backed up to `bot_logs/backups/owner_ui_edits/`, and refused if the file changed on disk since it was opened. Rows are grouped by section with plain-English labels and units (`15.0 %`, `240 min`, `1,000,000 USD`, On/Off) from `bots/settings_labels.json`; the raw key, range and default show in the description pane. Edits still take plain numbers.
- **4 Skills**: view and edit the skills. `e` opens the skill in the system editor (`$VISUAL`/`$EDITOR`, else notepad / nano) on a temp copy; it is saved back only when you close the editor, with an atomic write, a backup per edit (`backups/owner_ui_edits/`) and a line in `bot_logs/skills_changes.jsonl` (who / when). If the agent or another editor changed the file meanwhile, the save is refused, your version is kept, and you can view a diff or reload. `l` edits one line in place. The open skill is re-read every 10 s. `q` / `esc` = back.
- **5 Launch a token**: the same guided launch request as launcher menu option 5.
- **6 Sign in to X**: shows the verified status first; Enter keeps it. `s` switches account / re-logs in: pauses `agent_scraper` (`bot_logs/agent_scraper_pause.flag`) so the profile is free, then resumes.
- **Alerts**: beep + Windows toast (beep only elsewhere) on goal hit, SL/TP fire and new warden cards. Each type has a toggle in Settings (`ALERT_*`); `m` mutes all.
- **Bag actions (`x`)**: pick a position, then "Ask the agent to review" or "Note to the agent". Writes `inbox/owner - owner_review_<TICKER>_<ts>.json` (or `owner_note_...`). Never trades; you pick it up on your next inbox check (meme-hunter skill, "Owner review cards").
- **`SNIPER_MAX_RED_HOLD_H`** (filter knob, default 0 = off): a RED bag held past it gets a review card in `inbox/` (once per 6h per bag) and a dashboard flag. It never sells.
- **7 Quit UI**: closes the console; the engine keeps trading.
- **8 Stop Sniper**: stops every bot.
- **Recap**: Quit (7) and Stop (8) write a recap card to `owner_inbox/` and append to `bot_logs/daily_recaps.jsonl` (period + today PnL, best/worst, W/L, avg hold, goals).

## 11. Build your automations

The bots only write packets; nothing gets decided until you run your own loops. **Build them yourself, from the templates in `automations/`, before the first live start.**

1. Read `automations/README.md`, then each lane file: `sniper_lane`, `warden_lane`, `morning_brief`, `misc_lane`.
2. For each lane, create one recurring job in your own host (cron, scheduled routine, heartbeat, whatever it supports). The job's prompt is the lane file's text with `{AGENT_NAME}` replaced by your name and `{USER}` by the owner's name (also set `AGENT_NAME` and `OWNER_NAME` in `bots/.env`; `learnings_writer` fills them into `learnings/LEARNINGS.md`).
3. Agree the cadence with the owner. The files carry no schedule on purpose. A starting point: sniper_lane every 5 minutes (it handles buys and SL/TP), warden_lane every 15 minutes, misc_lane every 30 minutes, morning_brief once a day. Faster runs cost more model calls (section 0.1).
4. Run each job once by hand. Check it appended a line to `bot_logs/inbox_cron_audit.log` and moved its packets to `inbox_results/done/`. `python bots/tools/lane_run.py --lane sniper|warden|misc --list` shows what a lane owns; `--apply decisions.json` (or `--default-action "..."`) stamps, moves and audits in one step.
5. Tell the owner which jobs exist and how often they run, and record it in `learnings/LEARNINGS.md`. Change cadences later the same way.

Example staggered schedule (cron syntax, local time). Offset the start minutes so no two lanes ever fire in the same minute; two lanes starting together race for the same packets and the same model budget:

```
3-53/10 * * * *        sniper_lane      (every 10 min, at :03 :13 :23 :33 :43 :53)
7,27,47 * * * *        warden_lane     (every 20 min)
9,24,39,54 * * * *     misc_lane       (every 15 min)
15 7 * * *             morning_brief   (once a day)
30 23 * * *            nightly self-eval (learnings/nightly_self_eval.automation.md, once a night)
```

Check a new schedule by listing every start minute 0-59: each minute may appear at most once.

Don't run two copies of the same lane at once; the warden reaps stale lane locks after 15 minutes (`INBOX_CRON_LOCK_MAX_AGE_S`).

## 12. Optional pipes (off by default)

Two engine pipelines talk to services that are not in this repo. Both ship off; the engine runs normally without them.

- `PIPE_FLOW_ENABLED=0`: an external market-regime feed. When off, the daily-read buy gate, the hold cycle warning and the 6:05 morning packet are skipped.
- `PIPE_RESEARCH_ENABLED=0`: deep/social research requests to an external responder. When off, `deep_research` and `who_shilling` signals are rejected with `research_pipe_off`.

Only turn one on if the owner runs a matching service.

## 13. Pre-start check

Before anything goes live, check:

- `bots/.env` loads, and no secrets are printed
- `pip install -r requirements.txt` ran in this Python (on Windows, `tzdata` must be installed or every bot crashes on start)
- the launch choice (`LAUNCH_RAIL_LIVE`) and `rules/rules.md` say what the owner wants about launches
- your automations from section 11 exist and each has run once
- every folder in section 3 exists
- wallet (a burner), sizes and RPC are set; everything is live from the first start unless the owner chose paper mode (section 4.2)
- buy size / default SL/TP / learning mode are what the owner wants (section 4.1)
- each bot starts and writes one packet to `inbox/`
- you pick that packet up and move it to `inbox_results/done/`
- the owner gets one test ping (notify-only)
- the optional pipes in section 12 are off unless the owner runs those services

## 14. Adding a chain

Solana is the only chain that trades today. `bots/chains/` is the plug-in point for others. It is a documented interface plus a Solana reference adapter; the engine (`meme_sniper.py`) does not route trades through it yet, so nothing here changes how Solana trades.

**Files**

- `bots/chains/base.py`: `ChainAdapter`, six async methods: `new_token_feed`, `quote`, `buy`, `sell`, `balance`, `safety_check`. The docstring has the return shapes.
- `bots/chains/solana.py`: the reference. Each method calls one existing engine function (`birth_listener_loop`, `jupiter_quote_fresh`, `jupiter_swap_buy`, `jupiter_swap_sell`, `_wallet_sol_balance`, `smart_rug_check`). The engine is imported only on first call.
- `bots/chains/__init__.py`: `REGISTRY` and `load_adapters()`. `CHAIN_ADAPTERS=solana` is the default. Any other chain loads only if it is listed AND `CHAIN_<NAME>_ENABLED=1`.

**What to implement** (as the owner's agent)

1. Create `bots/chains/<name>.py` with a `ChainAdapter` subclass (`name`, `native_symbol`) and all six methods. Never raise on network errors: return `None` or `{"success": False, "error": ...}`.
2. `safety_check` must return `verdict` = `ok` / `caution` / `block`, and `block` must stop a buy (freeze/blacklist, honeypot, sell tax, unlocked LP, mint authority).
3. `buy`/`sell` must report what actually landed (wallet delta), not the quote.
4. Add `"<name>": "chains.<name>:<Class>"` to `REGISTRY`, and `CHAIN_<NAME>_ENABLED=0` plus any keys it reads (RPC, router keys) to `bots/.env.example`, all off by default.
5. Keep keys, RPCs and wallets separate from Solana's. Don't touch the Solana adapter or the engine's Solana paths.

**Testing checklist**

- [ ] `python -m py_compile bots/chains/*.py` and `python bots/sniper.py --smoke` pass (the smoke checks Solana still loads alone by default).
- [ ] With the switch at 0, `load_adapters()` does not return the chain.
- [ ] Unit-test each method against a fake client first, then read-only calls on mainnet: `balance`, `quote`, `safety_check` on a known good token and a known rug.
- [ ] Run `new_token_feed` for a while and check it produces tokens without crashing or reconnect storms.
- [ ] Start with a tiny size: one buy and one sell at the smallest size the chain allows, from a fresh burner wallet holding only that amount. Check the fill, fees and wallet delta by hand on an explorer.
- [ ] Only then raise size, one step at a time, with the owner's OK and a rule in `rules/rules.md`.
- [ ] Record what you built and tested in `learnings/LEARNINGS.md`.

Keep every chain behind its own switch, off by default, and tell the owner before turning one on. Wiring a chain into the engine's buy/sell loop is a separate, larger change; do it only with the owner.

## Tips

- **Do at least one trade with your SI start to finish.** Open, manage, close, then read the lesson `learnings_writer` logs in `learnings/LEARNINGS.md`. Trading alongside your SI is the fastest way it learns, it helps you both find new strategies, and it keeps the system evolving with a market that never stops changing.
- **It doesn't have to run 24/7.** Trading sessions are fine: turn it on when you want to trade, off when you're done.
- **Start small, on a burner.** One buy and one sell at the smallest size first, from a fresh burner wallet that holds only what you can lose.
- **Keep the Telegram chat private.** Alerts and owner commands go to `TELEGRAM_CHAT_ID`; use a private chat only you (and your SI) can read.
- **Read the acks and declines.** Every signal gets an answer in the inbox (`signal_ack`, `trade_confirmation`, `signal_failure`); a decline carries its reason. Fix the reason, don't resend with tweaked numbers.
- **Don't be afraid to build something better.** If you figure out how to make it twice as good, build it simple. That's the fastest way to keep up with an ever-changing market. Contributions welcome.
