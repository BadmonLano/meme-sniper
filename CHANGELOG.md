# Changelog

Full history: [TIMELINE.md](TIMELINE.md).

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

## v1.0.4 (2026-10-24): celebrity-post rule, scale-in, trail, exit logging, watchdog
- **Celebrity-post rule** (`bots/celeb_post.py`, `CELEB_POST_RULE`): enters on a verified, big-account CA post only after the creator has fully sold. Skips fan-out-funded creators and clusters that launch a second coin. Fixed 0.1 SOL, half off at 3x, 35% trail, -25% stop. Missing data means no entry. FLOYD replay test included.
- **Scale-in** (`bots/scale_in.py`, `SCALE_IN`): 0.05 SOL first leg, then the rest after 5 min if liquidity and price hold.
- **Trail:** arms at +20% and exits after giving back 15 PnL points (`TRAIL_GIVEBACK_PTS`).
- **Exit logging** (`bots/exit_log.py`): one exit-type resolver shared by the ledger and the autopsy, the monitor trigger is remembered, the post-exit peak match is fixed, and post-exit numbers are mirrored into the ledger.
- **Watchdog** (`bots/sub-bots/monitor_watchdog.py`, `MONITOR_WATCHDOG`): alerts when the monitor goes stale with open positions.
- Tests: `bots/tests/test_v104.py`.

## v1.0.3 (2026-10-24): fee-wallet vault exception
- New `bots/fee_vault.py`: tells a creator parking supply in its own fee wallet apart from a sniper bundle (transfer vs buy, fee-recipient match, receiver never signed, creator done selling).
- Vault launches skip the launch-spike $100k kill, leave the vault out of top-10 math, enter at a fixed 0.1 SOL, and exit on any vault move, a -25% stop, 50% off at 3x, and a 35% trail. Off-switch: `VAULT_EXCEPTION=false`.
- Note: Drop 2 holder limits (`TOP10_MAX_PCT`, `DEV_MAX_HOLDING_PCT`, `HOLDERS_MIN_COUNT`) are advisory. They show on the card and never block a buy.
- Tests: `bots/tests/test_fee_vault.py` (KIMCHI replay from public data).

