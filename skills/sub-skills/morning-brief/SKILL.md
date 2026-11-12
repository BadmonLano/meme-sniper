---
name: morning-brief
version: v14.3
description: |
  The agent's daily orientation for the Meme Sniper ecosystem, on demand or on
  whatever cadence the owner or agent sets. One brief built from Sniper cards
  in inbox_results/done, SL/TP status on open bags, Warden counts, and the
  day's thesis, delivered to the owner through owner-ping. Triggers: "morning
  brief", "daily brief", "catch me up", "what's the setup".
---

# Morning Brief

One read that tells the owner what the sniper did, what is open, what is
protected, and what the agent plans today. Lead with the one thing that
matters most. Skip sections that have nothing in them; absence is signal, so
say "no X" in one line instead of padding.

## Inputs (read-only)

| what | where |
|---|---|
| Sniper cards handled since the last brief (buys, ignores, exits, digests, meeting responses) | `inbox_results/done/meme_sniper - *` |
| Open positions + armed SL/TP | `bot_logs/positions.json`, latest positions digest card |
| Bags with nothing armed | `bot_logs/protection_missing.jsonl` |
| Fills and PnL | `bot_logs/execution_ledger.jsonl`, `bot_logs/trades.log` |
| Closes and misses | `bot_logs/autopsy_reports.json`, `bot_logs/miss_book.jsonl` |
| Sniper health + stop reason | `bot_logs/meme_sniper_heartbeat.json` (`stop_reason`, `stopped_at`) |
| Throughput / zero-buy | `bot_logs/sniper_throughput_state.json` |
| Warden | latest `security_warden - *` packets in `inbox/` and `owner_inbox/` |
| Overseer | latest overseer report (agent_autoagent) |
| Wallet | treasury summary from the sniper heartbeat / wallet status card |

## Sections (use what applies)

1. **Lead story.** One or two lines: the most important thing since the last brief.
2. **Sniper activity.** Cards in, buys, ignores (with the top decline reasons), exits. Count + the 1-3 that matter.
3. **Open bags + protection.** Each open bag: entry, now, SL / TP armed (yes/no, levels). Any bag without SL/TP is flagged first. The bot never auto-sells; the armed levels are the plan.
4. **PnL.** Realized since last brief, from the ledger. No estimates dressed up as fills.
5. **Misses.** Top runners from miss_book that the sniper saw and passed, with the reason it passed.
6. **Warden.** Counts by severity since the last brief, plus any sniper-watch ping (down / zero buys). Note intentional stops (`user_stopped`) as such.
7. **Overseer.** Last score + the one follow-up that matters.
8. **Today's plan.** Regime read (from the sniper's own regime/rug-season state), filters or cadence changes the agent intends (via meeting file, never a workaround), and what would change the plan.

## Delivery

- Send through **owner-ping** (kind `noteworthy`, severity `low`; raise it if a bag is unprotected or Sniper is down).
- Persist the day's thesis to `bot_logs/agent_thesis.json` (append to `thesis_history`, never overwrite). The overseer grades it.
- Move nothing out of `inbox_results/done`; the brief only reads.

## Rules

- Specific numbers, tickers, timestamps. No kitchen sink.
- No public posting. The brief is private to the owner.
- No secrets, keys or full wallet strings.
- Cadence is set by the owner or the agent; this skill fixes no time.
