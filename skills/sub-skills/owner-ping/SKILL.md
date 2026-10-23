---
name: owner-ping
version: v14.3
description: |
  How the agent and the Sniper ecosystem bots reach the owner: bot errors,
  noteworthy events, trade notices, and blocking decisions. Primary channel is
  a file packet in owner_inbox/. Telegram is optional (only when
  TELEGRAM_TOKEN + TELEGRAM_CHAT_ID are set). Severity + dedupe_key on every
  non-casual ping. Skill-only: no extra bot.
---

# owner-ping - reaching the owner

## When to ping

| mode | default | examples | cost to the owner |
|---|---|---|---|
| Social / informational | short, frequent is fine | `noteworthy`, `trade_fired` | a glance |
| Escalation / blocking | last resort, after a real attempt to solve it | `decision_needed`, capability gap, stuck | attention |

Chatty about what is happening, last-resort about what you need. Be specific:
"something broke" is useless; "meme_sniper heartbeat 42m stale, all components cancelled, no stop_reason" is useful.

## Channels

1. **owner_inbox/** (primary, always for non-casual). File packet, see below.
2. **Telegram** (optional). Only if `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` are configured. Short text, link the packet name.
3. **Audit log** `bot_logs/owner_pings.jsonl`: one line per ping (ts, kind, severity, dedupe_key, packet name, channels that succeeded).

Never claim a ping was delivered if every channel failed. Say so in the agent's own inbox instead.

## Packet

Filename (no P-prefix in the name; priority lives in the header):
```
owner-ping - <kind>_<slug>_<ts>.md # under owner_inbox/, ts = yyyyMMdd_HHmmss
```

Envelope fields (top of the packet):

| field | meaning |
|---|---|
| `kind` | `bot_error`, `noteworthy`, `trade_fired`, `decision_needed`, `capability_gap`, `stuck` |
| `severity` | `critical`, `high`, `medium`, `low` |
| `source` | bot or skill that raised it (e.g. `meme_sniper`, `security_warden`) |
| `summary` | one line, specific |
| `evidence` | file paths / numbers the owner can check |
| `ask` | the exact decision needed, or `none` |
| `dedupe_key` | stable key; same key within 1h = do not re-ping |
| `auto_resume` | what the agent will do on its own if no reply (or `wait`) |

## Rules

- **Paper mode:** when `SNIPER_PAPER_MODE=1`, start every ping with `[PAPER]` so the owner never mistakes a simulated trade for a real one.
- Dedupe: same `dedupe_key` within 1 hour is one ping. Re-arm only after the condition clears.
- Critical/high from bots (e.g. Warden's sniper watch: Sniper down, zero buys) already land in owner_inbox as P1 packets. Do not re-ping the same event; add context to it if useful.
- A stop with `stop_reason=user_stopped` is intentional. Never ping for it.
- No secrets, keys, or wallet private material in any ping.
- Cadence of casual pings is the owner's or the agent's choice; nothing here is scheduled.
