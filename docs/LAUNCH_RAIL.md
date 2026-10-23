# Sniper Launch Rail - mini launchpad (Pump.fun via PumpPortal)

> "An agent ships something real and useful? SNIPER will attach a repo, and mint a token around it."

Module: `bots/sub-bots/launch_rail.py` (ships off-chain: dry runs until `LAUNCH_RAIL_LIVE=1`). `meme_sniper.py` has one loop, `launch_rail_relay_loop`, registered as `SupervisedTask("launch_rail_relay")` right after `relay_janitor`. It polls the relay every 5 s, and only while LAUNCH_RAIL_ENABLED is on. You can call it from the CLI or from code with `import launch_rail; launch_rail.launch(req, ...)` / `launch_rail.check_repo(url)`.

## What it does
1. **Request**: a JSON file passed with `--request`, or (how agents do it) one file per request in `json_relay/launch_requests/<id>.json`, which the engine's relay loop picks up (see Agent relay below). The legacy folder `bot_logs/launch_requests/` is only read by `scan-requests` and is always dry-run.
2. **Repo gate ("real and useful")**: uses the GitHub API to check that the repo is public, not archived, original (a fork must be at least 3 commits ahead of its parent), has a README of 200+ bytes, has 3+ code files, and was pushed within 90 days. The score runs 0–100. It passes at 60 or more with no hard FAIL. A failure blocks the launch unless you pass `--force`.
3. **Metadata**: name/symbol/description/twitter/telegram/website. The website defaults to the repo URL, and the description gets "Built on: <repo>" added. The upload goes to IPFS via **Pinata** (`PINATA_JWT`), because the PumpPortal docs (checked 2026-10-13) say `pump.fun/api/ipfs` is no longer supported. The legacy endpoint is still available as `--ipfs pumpfun`. `--no-upload` mocks the upload.
4. **Create**: `POST https://pumpportal.fun/api/trade-local` with `{publicKey, action:"create", tokenMetadata{name,symbol,uri}, mint:<new keypair pubkey>, denominatedInSol:"true", amount:<dev buy>, slippage, priorityFee, pool:"pump"}`. The rail signs the returned transaction with the **mint keypair and the creator wallet** (solders), runs `simulateTransaction`, and sends only when live, through `RPC_URL` (or Helius via `HELIUS_API_KEY`, falling back to the public mainnet RPC).
5. **After a live send**: it saves the mint keypair to `bot_logs/launch_keys/<mint>.json` (that folder has a `.gitignore` that ignores everything in it) and records the mint, `https://pump.fun/coin/<mint>`, the signature and the solscan link. Optional hooks, all OFF: Telegram and the agent inbox card.
6. **Creator fees**: `claim-fees` uses PumpPortal `collectCreatorFee` (pump claims everything at once). It ships live, with the same gates as a launch.
7. **Log**: every attempt is appended to `bot_logs/launch_rail_log.jsonl`.

## Agent relay (how agents launch)
Agents write JSON into the bot's `json_relay/` (same convention as `agent_signals.json`, with paths built from `_BASE / "json_relay"`):
- **Requests:** `json_relay/launch_requests.json` (one object or `{"requests":[...]}`), or one file per request in `json_relay/launch_requests/<id>.json` (preferred).
- **Results:** `json_relay/launch_results.json` → `{"results": {"<id>": {...}}}` with status, mode, why_not_live, mint, pump_url, signature, solscan, metadata_uri, cost_estimate_sol, repo_score/reasons, simulation, creator (pubkey/balance), and metadata. Full detail is in `bot_logs/launch_rail_log.jsonl`.
- **Idempotency:** `bot_logs/launch_rail_seen.json`. An id is marked seen *before* launching and is never processed twice. Processed files are renamed `*.processed_<ms>`.
- **Schema:** `id`, `action` ("launch"), `repo_url`, `name`, `ticker`, `description`, `image`, `website`, `twitter`, `telegram`, `dev_buy_sol`, `slippage`, `priority_fee`, `dry_run` (bool, optional), `requested_by` (`confirm` is accepted and ignored). Required: id, action, repo_url, name, ticker, description, image, dev_buy_sol, requested_by. Unknown fields or wrong types → `rejected_schema`.
- **Live from the relay when:** LAUNCH_RAIL_ENABLED on and env LAUNCH_RAIL_LIVE=1 (LIVE ships 0, so launches are dry runs until the owner sets it). The agent decides each launch; there is no human confirm. `"dry_run": true` keeps one request off-chain. Otherwise `why_not_live` lists the reasons. The dev-buy cap and repo gate still apply.
- **Rule change:** the earlier rule "dropped requests are always dry-run" now applies only to the legacy `bot_logs/launch_requests/` folder (`scan-requests`). The json_relay path goes live under the config above.
- To test without the bot running (from the drop folder): `python bots/sub-bots/launch_rail.py --env bots/.env relay-once --no-upload`.

## Env file
`launch_rail` loads secrets from `--env <file>`, else `LAUNCH_ENV_FILE`, else `bots/.env` (one .env per bot). See `bots/.env.example` (names only). Wallet lookup order: `LAUNCH_WALLET_PRIVATE_KEY` → `HOT_WALLET_PRIVATE_KEY` → `PRIVATE_KEY`. Pinata: `PINATA_JWT` or `pinata_secret_token`. `python bots/sub-bots/launch_rail.py pinata-auth` checks the credentials. RPC: `RPC_URL` → `RPC_URL_FALLBACK` → public mainnet for reads and simulation. Sends use only the first RPC and are never re-broadcast.

## Request format
```json
{
  "repo_url": "https://github.com/<owner>/<repo>",
  "name": "Token Name (<=32)",
  "ticker": "TICKER (<=10)",
  "description": "What it is",
  "image": "bots/examples/placeholder_logo.png or https://...",
  "website": "", "twitter": "", "telegram": "",
  "dev_buy_sol": 0.1,
  "slippage": 10,
  "priority_fee": 0.0005
}
```
Examples: `bots/examples/launch_request_test_rail.json` (minimal test) and `bots/examples/launch_request_example.json` (full schema). Both use the placeholder image `bots/examples/placeholder_logo.png`; swap in your own logo.

## Commands (run from the drop folder, the one that contains `bots/`)
Inside an activated venv `python` works on every OS (outside one, use `python3` on macOS/Linux). Forward slashes work on Windows too.
```
python bots/sub-bots/launch_rail.py check-repo https://github.com/<owner>/<repo>
# full dry-run: no IPFS upload, throwaway creator, builds + signs + simulates, sends nothing
python bots/sub-bots/launch_rail.py launch --request bots/examples/launch_request_test_rail.json --no-upload --throwaway
# dry-run with the real creator wallet (still sends nothing)
python bots/sub-bots/launch_rail.py launch --request my_request.json --no-upload
python bots/sub-bots/launch_rail.py claim-fees --dry-run
python bots/sub-bots/test_launch_rail.py
```
Going live is setup config, not a per-launch flag. The usual way: set `LAUNCH_RAIL_LIVE=1` in `bots/.env` (and keep `"LAUNCH_RAIL_ENABLED": true` in `bot_logs/launch_rail_config.json` or `LAUNCH_RAIL_ENABLED=1` in `bots/.env`). For one shell session only:
```
# macOS / Linux
export LAUNCH_RAIL_LIVE=1
# Windows PowerShell
$env:LAUNCH_RAIL_LIVE = "1"
# Windows cmd
set LAUNCH_RAIL_LIVE=1
```
Then `python bots/sub-bots/launch_rail.py launch --request my_request.json` sends for real (add `--dry-run` to stay off-chain), and `claim-fees` without `--dry-run` claims live.

## Safety gates
- Ships off-chain: live needs **LAUNCH_RAIL_ENABLED on + LAUNCH_RAIL_LIVE=1**, and LAUNCH_RAIL_LIVE ships 0 (unset counts as 0). The agent is the decider; there is no human confirm step. If either is off, or the request says dry_run, it stays a dry-run and lists the blockers.
- Dev buy cap (first one set wins): `--max-dev-buy`, then env `LAUNCH_MAX_DEV_BUY_SOL`, then config `max_dev_buy_sol`, then 0.5. Anything over the cap is blocked.
- The repo gate blocks a failing repo unless `--force`.
- A throwaway creator can never go live. The legacy `bot_logs/launch_requests/` folder (`scan-requests`) can never go live. The json_relay can, under the config above.
- Secrets are read by name only: `LAUNCH_WALLET_PRIVATE_KEY` (override), else `HOT_WALLET_PRIVATE_KEY`, else `PRIVATE_KEY`. Also `PINATA_JWT` (or `pinata_secret_token`), `RPC_URL` / `HELIUS_API_KEY`, optionally `GITHUB_TOKEN` (rate limits), and `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` (hook only). Values are never printed. The RPC URL is not logged.
- The mint keypair is saved only on a live run, under the git-ignored `bot_logs/launch_keys/`.

## Live launch checklist (the agent decides)
The agent fills in:
1. Token **name** (max 32) and **ticker** (max 10)
2. **Description**
3. **Image** (path or URL; square PNG recommended)
4. **Links**: website (defaults to the repo), X, Telegram
5. **Dev buy** in SOL (cap 0.5 unless raised)
6. **Which repo** (must pass the gate or be forced)
7. Owner-ping after the send (notify-only: mint, pump URL, signature)

Setup:
- `bots/.env` with `LAUNCH_WALLET_PRIVATE_KEY` (the agent's wallet) or `HOT_WALLET_PRIVATE_KEY`, plus `RPC_URL`/`HELIUS_API_KEY` and `PINATA_JWT` (free Pinata account, JWT).
- Wallet balance ≥ dev buy + ~0.03 SOL.
- Run a dry-run with the real wallet first and check that the simulation succeeds.
- To go live, the owner sets LAUNCH_RAIL_ENABLED=1 and LAUNCH_RAIL_LIVE=1 at setup. After that the agent runs launches without `--confirm`.
- Afterwards: back up `bot_logs/launch_keys/<mint>.json`, check the pump.fun page, and decide on the hooks.

## Own launches (after a LIVE launch)
meme_sniper reads `json_relay/launch_results.json`, registers each LIVE mint in `bot_logs/own_launches.json` (tag `own_launch`), never buys it, keeps `OWN_LAUNCH_TREASURY_PCT` as treasury, arms the `OWN_LAUNCH_TP_LADDER` / `OWN_LAUNCH_SL_PCT` on the rest via set_protection, refreshes `bot_logs/own_launch_cards/<mint>.json`, and claims creator fees every `OWN_LAUNCH_FEE_CLAIM_H`. Every action goes to `bot_logs/own_launch_actions.jsonl`.
- `python bots/sub-bots/launch_rail.py burn --mint <mint> --amount-raw N [--dry-run]` burns part of the dev bag (SPL Token or Token-2022 `Burn`). Same live gates as a launch; otherwise it simulates.
- Lock / vesting is not supported yet (no reliable program in the current deps). `OWN_LAUNCH_LOCK_MODE` takes `off` or `burn`.

