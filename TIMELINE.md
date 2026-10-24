# Timeline

Version history, newest first. Release numbers (v1.x) are the public repo; the engine inside keeps its own number (v14.3).

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

## v1.0.1 (2026-10-23): setup questions, docs, fixes
- Setup wizard asks the safety caps (daily loss stop, daily buy cap, same-token cooldown, loss-streak pause, max open positions, trading hours + timezone) and the launch rail on/off switch.
- Filter defaults ship as `meme_sniper_filter.default.json`; the live copy is git-ignored, so `git pull` stays clean.
- Buy signals can carry `mcap_at_signal` for the pre-buy drift check; rejected-signal packets now have a summary.
- Missing alert key warned once per run; Ctrl+C exits quietly in log_janitor, x_intel and learnings_writer.
- `--help`; `--ui-smoke` runs on a temp copy by itself. README: clone URL, Mac/Linux venv, menus, wallet risk, RPC note, Updating.

## v14.3 (2026-10-14): public release
- Self-contained repo: no references to anything outside it.
- Pipes to external services (market-regime feed, deep/social research) are now off by default behind `PIPE_FLOW_ENABLED` / `PIPE_RESEARCH_ENABLED`.
- Scrollable console screens; README, SETUP, skills index, license, contributing and security docs.

## v14.2 (2026-10-14)
- Unified ranking for KOLs, devs and wallets, scored on token outcome.
- Fixed the KOL lookup, shiller tracking and the wallet tracker's owner check.

## v14.1 (2026-10-14)
- One positions digest per inbox check; batch stop-loss/take-profit replies.
- Per-bag sensor alerts folded into the digest; module header slimmed (notes moved here).

## v14.0 (2026-10-14)
- Agent-armed stop-loss / take-profit on every position; 15s position checks.
- Free-RPC-first routing with paid fallback; Helius credit meter + optional daily cap; PumpPortal launch feed.
- Forensics fixes: late/vibes flags, impossible-runner filter, duplicate-card collapse, autopsy hold time, wallet zero-read guard, panic fee cap.

## v13.x (2026-08-06 to 2026-10-14)
- RPC failover with cooldown; wallet reads never treated as zero on RPC failure; signature cache; observers pause while RPC is down; key redaction; watchlist prune fix; discovery moved to Grok. Skill consolidated into one current ruleset with scoreboard-based exits.
- Named dip-buy zones (2026-10-05).
- Hold floor ratchet; Grok cooldown; dead auto-buy relay and dead pipes removed; filter file consolidated (2026-08-10 to 08-16).
- Edge v2 entry maps and catalyst clock; potential-watch tier; treasury mark-to-market alerts (2026-08-06 to 08-08).

## v13.0 to v13.2
- Phase-1 foundation: execution ledger, wallet PnL tracker, ledger-sweep math rebuild, time-decay exits.

## v12.x (2026-07-23 to 2026-07-30)
- Flip defaults tightened (trail 12/20, max hold 4h, breakeven 20m); timed-out sells tracked as pending.
- Executable-quote exits (mark vs real fill); never book -100% from a missing price; failed sells logged as failures; old knobs and dead scan cadences retired.
- Treasury funding loop (sell_holding); forced exits skip preflight; send-path RPC fallback; no stacked sells while one is in flight.
- Trail giveback made tunable; archetype validation; ignored-runner re-fire watch.
