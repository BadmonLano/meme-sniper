# Meme Sniper: Dependency Map
Overview of what `bots/meme_sniper.py` depends on (one large file, run with `asyncio` `main()`).

## 1. Entry point and launch
- Launch: `python bots/sniper.py` (the launcher). It starts `meme_sniper.py` and the sub-bots as child processes and opens the console (see SETUP.md).
- Engine entry point: `bots/meme_sniper.py`, which runs `asyncio` `main()` (near the end of the file) under `if __name__ == "__main__"`.
- Python 3.12+ (Windows or Linux).

## 2. Imports
**Stdlib:** `__future__`, asyncio, base64, collections, dataclasses, datetime, difflib, hashlib, importlib, io, json, math, os, pathlib, re, shutil, sys, threading, time, traceback, typing, urllib.request/error, warnings, zoneinfo. agent_ack also uses `msvcrt`/`fcntl`, contextlib, and edge_map/meta_tracker use stdlib only.

**Third-party:** see `requirements.txt` (rich, httpx, requests, websockets, python-dotenv, solders, base58, Pillow, matplotlib, playwright).

**Local modules (`bots/sub-bots/`):**
| Module | Used for | Its deps |
|---|---|---|
| `llm_providers.py` | provider-agnostic LLM layer (Grok, OpenAI, Anthropic, Ollama, OpenAI-compatible) | httpx |
| `x_session.py` | one resolved X browser profile + honest session status, shared by scraper, launcher and console | stdlib |
| `cancel_input.py` (bots/) | q / back / esc = back at every prompt (Ctrl+C keeps stopping) | rich |
| `settings_labels.json` (bots/) | Settings / wizard display map: label, section, unit per key | - |
| `_self_description.py` | self-description JSON, patch detection | stdlib |
| `_vision.py` | chart/image vision via Grok or Ollama | httpx; env GROK_*, OLLAMA_VISION_* |
| `edge_map.py` | edge map | stdlib |
| `agent_ack.py` | ack protocol for the agent's relay files | stdlib (msvcrt/fcntl locks) |
| `launch_spike.py` | launch-spike gate | stdlib (urllib) |
| `meta_tracker.py` | atomic_write, meta classify/roll | stdlib |
| `learnings_writer.py` | the one safe LEARNINGS.md writer (Section 8, file lock, atomic); also a sub-bot that keeps the file healthy and drains `json_relay/learnings/` | stdlib |
| `utils\staleness.py` | staleness helpers (via sys.path.insert) | stdlib. (namespace package) |

## 3. Files read and written
Workspace root (resolved via `WORKSPACE_DIR` or by walking up to the folder containing `bots/`): `bots/`, `bots/sub-bots/`, `bot_logs/`, `json_relay/`, `inbox/`, `inbox_results/{done,failed}/`, `owner_inbox/`, `learnings/`, `rules/`, `skills/`.

**Config/tunables (read, hot-reloaded):** `bots/tuner/meme_sniper_filter.json`; history goes to `bots/tuner/tune history/meme_sniper_filter_history.jsonl`. Rubrics/rosters in `bot_logs/`: `gork_standard.json`, `archetype_roster.json`, `kol_list.json`, `capital_floor.json` (shipped as empty/neutral seeds). Large runtime state (`scanned_mints.json`, `watchlist.json`) is rebuilt from empty.

## 4. Env vars and secrets (names only; loaded via `load_dotenv()` from `bots/.env`; see `bots/.env.example`)
- **Wallet / keys (critical):** `HOT_WALLET_PRIVATE_KEY` / `PRIVATE_KEY` (base58 or JSON byte array), `HOT_WALLET_ADDRESS`, `LEDGER_ADDRESS`, `owner_WALLET_ADDRESS`
- **RPC:** `HELIUS_API_KEY`, `RPC_URL`, `RPC_URL_FALLBACK`, `RPC_FREE_TIER`, `SNIPER_RPC_MAX_CONCURRENT`, `SNIPER_RPC_MIN_INTERVAL_S`, `SNIPER_RPC_SEND_MIN_INTERVAL_S`
- **Data APIs:** `BIRDEYE_API_KEY`, `JUPITER_API_KEY`, `JUPITER_BASE`, `COINCOMMS_API_KEY`, `COINCOMMS_SERVER_KEY`, `COINCOMMS_SERVER_SECRET`, `X_BEARER_TOKEN`
- **LLM:** `LLM_MAIN`, `LLM_FALLBACK` (only these two providers run), `XAI_API_KEY`, `GROK_API_KEY`, `GROK_API_BASE`, `GROK_TEXT_MODEL`, `GROK_VISION_MODEL`, `GROK_REASONING_EFFORT`, `GROK_*_TIMEOUT`, `GROK_COOLDOWN_SECONDS`, `NARRATIVE_LLM_PRIMARY`, `OLLAMA_*` (ENABLED, URL, MODEL, VISION_MODEL, MEETING_MODEL, CONCURRENCY, ENABLED, timeouts)
- **Alerts:** `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
- **Misc tunables:** `BRAND_DEAD_OG_LIQ`, `BRAND_DEAD_OG_VOL_24H`, `RELAY_FAILED_TTL_HOURS`, `RELAY_RESPONSE_TTL_HOURS`, `TREASURY_MTM_SUMMARY_HOUR`

## 5. External services
Solana RPC (Helius: mainnet.helius-rpc.com, api.helius.xyz), Jupiter swap/price (api.jup.ag, lite-api, price.jup.ag), DexScreener (api + site), GeckoTerminal, Birdeye, RugCheck (api.rugcheck.xyz), CoinGecko, Binance (price), Coin Communities (coincommunities.org, api.coin-communities.xyz), xAI Grok (api.x.ai), Ollama (local only, fallback under Grok), Telegram Bot API, Solscan links. Pump.fun program IDs are used for on-chain decoding (birth listener over websocket).

## 6. Other bots and pipelines
| Dependency | Direction | If it's off | Flag? |
|---|---|---|---|
| **the agent** (inbox cards, agent_signals.json, wallet/archetype commands, meetings, tune responses, discovery queries) | both | No human-in-loop buy signals or approvals. Cards pile up in inbox. Autonomous scanner/filters still run. | none today; needs `agent_RELAY=off` |
| **agent_scraper** (scraper_task → agent_scraper_response, dex_solana_top_latest) | reads | dex_top_digest and X-chatter enrichment go empty | none |
| **ca_intel** (ca_research request/response) | serves | requests go unanswered | none |
| **code_tuner** (tuner filter file, tune invitations) | both | filters stay static (fine) | n/a |
| **owner_ping** (owner_pings.jsonl) | writes | none | none |
| **Telegram** | writes | silent if token is empty | effectively env-gated |
| **flow feed** (`PIPE_FLOW_ENABLED`, default 0) | reads | regime gate, cycle warning and morning packet are skipped | `PIPE_FLOW_ENABLED` |
| **deep/social research** (`PIPE_RESEARCH_ENABLED`, default 0) | writes | research signals are rejected with `research_pipe_off` | `PIPE_RESEARCH_ENABLED` |
| **Grok/Ollama LLM** | calls | narrative/vision features degrade | OLLAMA_ENABLED, NARRATIVE_LLM_PRIMARY |


## 7. Money logic
- **Buy size:** `DYNAMIC_SIZE_CAP_ENABLED=True` and `SIZE_CAP_BASE_SOL=1.0`. The cap ratchets with wallet growth vs `size_scale_anchor` (SOL tiers set by `SIZE_CAP_TIER1..4_SOL`). Also a 30%-of-wallet cap, a 0.1 SOL floor, and `capital_floor.json`. All are overridable via `meme_sniper_filter.json`.
- **Sunday sweep (`weekly_sweep` task):** checks hourly. On Sunday (`WEEKLY_SWEEP_DAY=6`), if profit ≥ `WEEKLY_SWEEP_MIN_PROFIT_SOL` (0.05) and floor > 0, it sends (wallet − capital floor) to the ledger. Guards: max 5 SOL per tx, 0.5 SOL reserve, 0.1 SOL min profit, 24 h cooldown. Destination is `LEDGER_ADDRESS` from `.env`, captured at boot; if it is blank the sweep refuses.
- It signs and sends real transactions with the hot wallet (solders + Jupiter). Leave the key blank until you have read SETUP.md.
