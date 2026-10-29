# Changelog

Full history: [TIMELINE.md](TIMELINE.md).

## v1.0.15 (2026-10-29): owner-chosen agent autonomy (suggest by default), paper by default, league mode
For the cursor.directory review: the published skills no longer override human-in-the-loop.
- **`AGENT_MODE` (new, asked FIRST in setup):** `suggest` (default) = the agent proposes buys and sells and the bot holds them (`awaiting_owner_approval` ack + owner card in `owner_inbox/`) until the owner answers `/approve <id>` / `/reject <id>` (owner commands) or `python bots/approve.py <id>`; unanswered suggestions expire after `AGENT_MODE_APPROVAL_TTL_MIN` (60). `auto` = the old behaviour, behind a warning (wizard: type `AUTO`; setup.json: `AGENT_CONFIRM_AUTO=AUTO`). Gated actions: buy, sell, sell_holding, harvest_holding, panic_sell. Bot-armed SL/TP exits, the stuck-bag watchdog and SL/TP changes are not held. `bots/agent_mode.py`, `bots/approve.py`.
- **Paper by default, live keys opt-in:** `bots/.env.example` ships `SNIPER_PAPER_MODE=1`. The wizard asks autonomy, then paper or live (paper preselected); the wallet private key is asked only after the owner opts into live, with a warning, and paper setups are complete without it. Existing `bots/.env` files keep their values.
- **Skills:** "Prime Directive (Rule 0)" override wording replaced by "operate within the owner's chosen mode"; the "Autonomy (public default)" notes now describe suggest/auto; `AGENT_SELF_PATCH` removed (code fixes are always an owner card with a diff). gork-lore keeps all lore but ships no contract addresses (owner-verified, kept in local config). All heuristics and checklists unchanged.
- **League mode (`LEAGUE_MODE`, default off):** AudaceFi devnet league: devnet RPC + separate league wallet (boot refuses mainnet or the main wallet/key), degen allowlist only, buys only inside the season window, auto-flatten to USDC before each snapshot, execution only through a pluggable AudaceFi executor (never Jupiter). Config placeholders in `bots/.env.example`, no keys. `bots/league_mode.py`.
- Tests: `bots/tests/test_agent_mode.py`, `bots/tests/test_league_mode.py`.

## v1.0.14 (2026-10-28): outside resources, numbers first
- `skills/meme-hunter/SKILL.md`: new section "Deciding Whether To Buy (outside resources, numbers first)", matching Perps. Agents with web/X search may check DexScreener/Birdeye/Solscan, holders, LP, dev wallet, flows, X and news before a buy; raw numbers first, sources with age in the reason; never overrides hard gates, owner rules or caps. `skills/ca-intel/SKILL.md` references it.
- Docs/skills only; no trading code or defaults changed. (v1.0.13 is reserved.)

## v1.0.12 (2026-10-28): test suite collects cleanly
- Tests only: standalone-script test files no longer run side effects at import, so pytest collects (was 2 collection errors). Fixed a stale own-launch treasury default expectation (50 -> shipped 0). 115 tests pass. No trading code or defaults changed.

## v1.0.11 (2026-10-28): cursor.directory safety rule
- `rules/meme-sniper-safety.mdc: cursor.directory Rule component (paper default, no secrets, respect caps, confirm live orders). Docs/packaging only; no trading code or defaults changed.`

## v1.0.10 (2026-10-27): smoke check fully green
- `bots/settings_labels.json`: labels, sections and units for the 37 settings added in v1.0.3–v1.0.5 (vault exception, celebrity-post rule, scale-in, trail giveback, watchdog, celeb watcher). They were in `.env.example` but had no label, so `--smoke` failed its labels check (and the final summary line with it).
- Display only: no trading code, values or defaults changed.

## v1.0.9 (2026-10-27): docs and packaging parity with Perps
Docs only. No trading code or defaults changed.
- README: glossary, paper quick start (dry run; a burner key and RPC are still required to boot), Versions pointer.
- README version sections v1.0.3–v1.0.5 moved into this changelog under their versions.
- Plugin manifests now report the real version.
- `docs/RELEASE_NOTES_v1.0.9.md`.

## v1.0.8 (2026-10-27): protective orders never fail quiet
SL/TP is enforced by the bot itself (no exchange order). This closes the gaps after a filled buy.
- **Bad levels on a buy are reported:** SL/TP sent with a buy (or any position touch) that fails to arm (out of `PROTECT_*` bounds, bad values) now writes a high-priority `protection_missing` packet to the agent with the levels sent and the reason, a `protect:` log line, and a row in `bot_logs/protection_missing.jsonl`. Before, the `respond=False` arm failed silently.
- **Default flip stop sells:** a flip bag with no valid agent stop now sells on its default stop (`params.stop_loss_pct`, same number and higher-cap floor the `sl_hit` alert uses) through the same armed-protection path: retries, `protective_order_fired` packet, plus the existing exit Telegram. Agent-armed levels always win; hold-mode and own launches are unchanged. Off-switch `PROTECT_DEFAULT_STOP=false`.
- **Retries exhausted alert:** when a breached level has failed `PROTECT_MAX_RETRIES` (5) sells, the agent gets one high-priority `protective_order_exhausted` packet and a Telegram. The sell escalation ladder and stuck-bag watchdog are unchanged.
- No size, threshold or other behavior changes.
- Tests: `bots/tests/test_v108.py`.

## v1.0.7 (2026-10-25): six-token replay fixes (trending fast lane, clone runner, expired cards, parody lane, X profile, bundles)
Built from a replay of six parody-ticker runners Sniper saw but never bought. All rules live in `bots/v107_rules.py`; each has an env off-switch (default on).
- **Trending fast lane** (`TREND_FAST`): a coin holding top-3 trending for 1h+ becomes a full buy candidate (was 8h only), with pump.fun story, socials and social read. Knobs `TREND_FAST_TOP_N` 3, `TREND_FAST_HOURS` 1, `TREND_FAST_MAX_GAP_MIN` 40. Scale-in and the +20% trail apply.
- **Clone gate runner override** (`CLONE_RUNNER_OVERRIDE`): a "clone" passes when it is the one running: mcap >= `CLONE_OVERRIDE_MCAP_USD` ($500K), or >= `CLONE_OVERRIDE_X_ORIGINAL` (2x) the "original", or on the miss book.
- **Expired card fallback** (`EXPIRED_CARD_FALLBACK`): a candidate that expires with no decision gets a small buy (`EXPIRED_CARD_FALLBACK_SOL` 0.05) if its rug check is clean (`EXPIRED_CARD_FALLBACK_ALLOW_CAUTION` to allow caution); otherwise ignored with the reason in `bot_logs/ttl_fallback.jsonl`. The buy still goes through every normal executor gate.
- **Parody-ticker lane** (`PARODY_LANE`): tickers copying big coins (BTC, ETH, SOL, LTC...) go to `json_relay/parody_ticker_alerts.json`. Alerts only, never buys. Add names with `PARODY_EXTRA_TICKERS`.
- **X profile fill** (`X_PROFILE_FILL`): follower count, account age and verified via your `X_BEARER_TOKEN`, cached 24h in `bot_logs/x_profile_cache.json`, capped by `X_PROFILE_MAX_PER_HOUR` (60).
- **Trending ticker fix** (`TRENDING_TICKER_FIX`): trending_track entries refresh their ticker from the base-side pair, so a mint is no longer stuck with another coin's ticker.
- **Bundle check** (`BUNDLE_CHECK`, 1 Helius call per mint, cached): bundle % goes on the buy. At >= `BUNDLE_REDUCE_PCT` (25%) size x `BUNDLE_SIZE_MULT` (0.5), stop `BUNDLE_STOP_LOSS_PCT` (15) and trail giveback `BUNDLE_TRAIL_GIVEBACK_PTS` (10). Blocks only when bundle wallets sold >= `BUNDLE_BLOCK_SOLD_PCT` (50%) into a drawdown >= `BUNDLE_BLOCK_DRAWDOWN_PCT` (40%) (`BUNDLE_BLOCK_ON_DUMP`).
- **Coverage** (`COVERAGE_GECKO`): GeckoTerminal Solana trending pools feed the trending tracker. Coins that never pay for DexScreener boosts were invisible before.
- Tests: `bots/tests/test_v107.py` (replays of the six tokens).

## v1.0.6 (2026-10-24): owner-position takeover pricing fix
- **Root cause:** `fetch_token_data` took the highest-liquidity DexScreener pair even when the mint sat on the QUOTE side (`OTHER/<mint>`), so it used the other token's price and symbol. A $0.09 bag was booked at $2.67M/token ($1,711) and tripped a fake -100% stop after the 30-min auto-takeover.
- `fetch_token_data` now only uses pairs where the mint is the base token (`_base_side_pairs`).
- **Takeover guard:** an adopted owner bag is priced from a live Jupiter sell quote of the wallet's actual raw balance. Under `OWNER_POS_ADOPT_MIN_USD` (default $1) or no quote: not adopted, logged as `take_over_refused`. Detection mark vs live off by more than `OWNER_POS_PRICE_MAX_RATIO` (default 3x): booked at the live price and logged as `price_flag`.
- Tests: ORE replay in `bots/tests/test_owner_positions_sniper.py`; fixed the `_env_clean` harness import in that test and `test_clone_runner.py`.

## v1.0.5 (2026-10-24): celeb_post cards for agents
- New relay card `celeb_post_card/1` (`bots/celeb_card.py`) in `json_relay/celeb_post_cards.json`: celeb_post {handle, followers, verified, post_id, posted_ts, text, url} plus shill history, deleted-post flag, creator-sold status, funding-cluster verdict and a rule preview. The agent decides; nothing auto-buys.
- Optional watcher `bots/sub-bots/x_celeb_watch.py` (your own X bearer token): skips posts it has seen, backs off on rate limits, rechecks for deletes, and emits nothing on errors. Off-switch `CELEB_WATCH`.
- The meme-hunter skill now covers how to reason on celeb_post cards.
- Tests: `bots/tests/test_v105.py`.

### celeb_post cards: X Intel to agent to Sniper

When X Intel, the bundled watcher, or any agent sees a verified X account with 250k+ followers post a Solana CA, it writes a **card** to `json_relay/celeb_post_cards.json` (schema `celeb_post_card/1`, see `bots/celeb_card.py`). **Nothing buys automatically.** An agent reads the card, decides, and only if it wants the trade writes a normal buy to `json_relay/agent_signals.json` with the card's `celeb_post` block attached. Sniper's celeb rule then re-checks on-chain before it buys.

Each card carries `celeb_post` {handle, followers, verified, post_id, posted_ts, text, url} plus context:
- `shill_history`: how many other CAs this account has posted before.
- `post_deleted`: true, false, or null (null means not rechecked yet).
- `creator_sold` and `creator_balance_pct`.
- `funding_cluster`: clean, fanout_funder, second_coin or unknown.
- `rule_preview`: what the celeb rule says right now.

`decision` is always `"agent"`. Any unknown means risk, not clean.

**Optional watcher:** `python bots/sub-bots/x_celeb_watch.py` (add `--once` for a single pass). It uses your own `X_BEARER_TOKEN` from `bots/.env`. Watch specific accounts with `CELEB_WATCH_HANDLES`, or a search with `CELEB_WATCH_QUERY` (set it to `off` to disable). It polls every `CELEB_WATCH_INTERVAL_S` (180s), backs off when X rate-limits, skips posts it has already seen, and rechecks recent posts for deletion. With `SOLANA_RPC_URL` or `HELIUS_RPC_URL` set, it also fills in the on-chain context. No token or an API error means no cards. Off: `CELEB_WATCH=false`.

## v1.0.4 (2026-10-24): celebrity-post rule, scale-in, trail, exit logging, watchdog
- **Celebrity-post rule** (`bots/celeb_post.py`, `CELEB_POST_RULE`): enters on a verified, big-account CA post only after the creator has fully sold. Skips fan-out-funded creators and clusters that launch a second coin. Fixed 0.1 SOL, half off at 3x, 35% trail, -25% stop. Missing data means no entry. FLOYD replay test included.
- **Scale-in** (`bots/scale_in.py`, `SCALE_IN`): 0.05 SOL first leg, then the rest after 5 min if liquidity and price hold.
- **Trail:** arms at +20% and exits after giving back 15 PnL points (`TRAIL_GIVEBACK_PTS`).
- **Exit logging** (`bots/exit_log.py`): one exit-type resolver shared by the ledger and the autopsy, the monitor trigger is remembered, the post-exit peak match is fixed, and post-exit numbers are mirrored into the ledger.
- **Watchdog** (`bots/sub-bots/monitor_watchdog.py`, `MONITOR_WATCHDOG`): alerts when the monitor goes stale with open positions.
- Tests: `bots/tests/test_v104.py`.

### Celebrity-post rule

When a verified X account with a big following (`CELEB_MIN_FOLLOWERS`, 250k) posts a pump.fun CA, an agent or X Intel can send a buy signal with `celeb_post: {handle, followers, verified, post_id, posted_ts}`. Sniper then:
- **Skips the coin** if the creator was funded before launch by a wallet that paid several wallets in one transaction (`CELEB_FANOUT_MIN`, 3), or if the same cluster launched another coin within `CELEB_CLUSTER_WINDOW_H` (24h).
- **Waits** until the creator has fully sold (under `CELEB_CREATOR_MAX_PCT`, 1%).
- **Enters** at a fixed `CELEB_ENTRY_SOL` (0.1). Exits: half off at 3x, the rest on a 35% trail, -25% stop.
- If any data is missing, it doesn't enter. Turn it off with `CELEB_POST_RULE=false`.

FLOYD (Oct 13) would have been skipped on both checks: its creator was funded by a fan-out wallet and also launched $MONEY.

### Scale-in, trail, exit logging, watchdog

- **Scale-in:** a normal buy goes in at `SCALE_IN_FIRST_SOL` (0.05) first. After `SCALE_IN_ADD_AFTER_S` (300s) Sniper adds the rest, but only if the position is still open, liquidity is at least `SCALE_IN_LIQ_KEEP_PCT` (80%) of what it was at entry, and price is no more than `SCALE_IN_MAX_DRAWDOWN_PCT` (15%) below entry. The planned total still has to clear the 0.1 SOL floor. Vault and celeb entries are never split. Off: `SCALE_IN=false`.
- **Trail:** it arms at +20% (`DEFAULT_TRAIL_ACTIVATE_PCT`) and exits after giving back `TRAIL_GIVEBACK_PTS` (15) points of PnL (peak +40% -> exit at +25%). Set it to 0 to go back to the old % trail. Vault and celeb positions keep their 35% trail.
- **Exit logging:** the ledger and the autopsy now use one resolver for exit type, and the monitor's last trigger fills it in, so "manual" and "unknown_exit" stop showing up for monitored exits. The post-exit peak is matched by exit tx or a lone row within 6h, and the same numbers now go into the ledger as a `post_exit` row.
- **Watchdog:** if the position monitor's heartbeat is older than `WATCHDOG_STALE_S` (300s) while positions are open, you get an alert through your alerts channel. It repeats every `WATCHDOG_REALERT_S` (30 min) and sends a "recovered" note when the monitor comes back. It runs inside the bot, and you can also run `python bots/sub-bots/monitor_watchdog.py` separately to catch a dead process. Off: `MONITOR_WATCHDOG=false`.

## v1.0.3 (2026-10-24): fee-wallet vault exception
- New `bots/fee_vault.py`: tells a creator parking supply in its own fee wallet apart from a sniper bundle (transfer vs buy, fee-recipient match, receiver never signed, creator done selling).
- Vault launches skip the launch-spike $100k kill, leave the vault out of top-10 math, enter at a fixed 0.1 SOL, and exit on any vault move, a -25% stop, 50% off at 3x, and a 35% trail. Off-switch: `VAULT_EXCEPTION=false`.
- Note: Drop 2 holder limits (`TOP10_MAX_PCT`, `DEV_MAX_HOLDING_PCT`, `HOLDERS_MIN_COUNT`) are advisory. They show on the card and never block a buy.
- Tests: `bots/tests/test_fee_vault.py` (KIMCHI replay from public data).

### Fee-wallet vault exception

Some pump.fun launches look like a bundle but aren't. The creator buys most of the supply at creation, then **transfers** (not sells) a big slice to one wallet that is also the coin's creator-fee recipient and has never signed a transaction. Then the creator sells its small remainder. KIMCHI (Oct 20, 2026) did exactly this and ran to about $40M. The launch-spike rule ($100k in under 10 min) used to skip these.

Sniper now treats a launch as a **vault** only when all four checks pass:
1. The creator made an SPL transfer of at least `VAULT_MIN_TRANSFER_PCT` (20%) to one wallet.
2. That wallet is the pump.fun creator-fee recipient.
3. That wallet has zero outgoing (self-signed) transactions.
4. The creator is done selling: under `VAULT_CREATOR_DONE_PCT` (5%) left, or no sell for `VAULT_CREATOR_QUIET_S` (60s).

When it's a vault: the vault is left out of top-10 math (`float_top10_pct` on the card), the launch-spike kill is skipped, and every other hard cap still applies (size cap, 0.1 SOL floor, drawdown, liquidity floor, authorities). Entry is a fixed `VAULT_ENTRY_SOL` (0.1). Exits: **instant exit if the vault signs any transaction**, a -25% stop, 50% off at 3x, then a 35% trail.

Turn it off with `VAULT_EXCEPTION=false`. If any data is missing (RPC down, pump.fun API down), the check fails and the normal rules apply.

