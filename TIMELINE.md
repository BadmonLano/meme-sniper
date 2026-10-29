# Timeline

Version history, newest first. Release numbers (v1.x) are the public repo; the engine inside keeps its own number (v14.3).

## v1.0.16 (2026-10-29): always-on loop, active hours, tunable lane cadences
- Always-on loop docs, `ACTIVE_HOURS`/`ACTIVE_TZ`/`ACTIVE_DAYS` (default always on), tunable `LANE_CADENCE_*`, asked right after `AGENT_MODE`. Details: CHANGELOG.md.

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

## v1.0.12 (2026-10-28)
- Test collection fix; 115 tests pass. Tests only.

## v1.0.11 (2026-10-28)
- Safety rule `rules/meme-sniper-safety.mdc` for cursor.directory. Docs only.

## v1.0.10 (2026-10-27)
- Settings labels for the v1.0.3–v1.0.5 keys; `--smoke` fully passes. Display only.

## v1.0.9 (2026-10-27)
- Docs parity with Perps: glossary, paper quick start, README version sections moved to CHANGELOG, plugin manifests at the real version, release notes file. No code changes.

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
