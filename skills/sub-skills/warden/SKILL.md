---
name: warden
version: v14.3
description: |
  The agent's interface to security_warden.py - the Sniper ecosystem's immune system.
  Use when reading warden's daily digest from inbox, responding to warden
  critical alerts, reviewing medic crash reports, refreshing the integrity
  baseline after legitimate file changes, or handling sniper-watch pings
  (Sniper down / zero buys). Load when warden activity is in your inbox or when
  integrity / heal / lockdown decisions are the current task. Triggers:
  "what did warden find", "should i trust this heal", "refresh integrity",
  "warden digest", "did medic report a crash", "is the sniper down".
---

# Warden, the Agent's Interface to the Ecosystem Immune System

Lane tool: `python bots/tools/lane_run.py --lane warden --list`, then `--apply decisions.json --real-findings N` stamps, moves and audits every `security_warden - ` packet (see the warden lane automation).

> **The owner's mode (`AGENT_MODE`, asked first in setup):** `suggest` is the default. You propose each buy and sell by writing the normal signal to `json_relay/agent_signals.json`; the bot holds it (`awaiting_owner_approval` ack, owner card) until the owner answers `/approve <id>` or `/reject <id>`. Do not re-fire a held signal and never write an approval yourself. `auto` is the owner's opt-in: trade signals execute inside the caps and owner-ping is notify-only. In both modes your analysis, logging, SL/TP on open bags and inbox handling run as written below, and setup config (wallet, sizes, paper vs live, `AGENT_MODE`, `LAUNCH_RAIL_LIVE`) belongs to the owner: you never change it. Where a line below says to fire, buy, sell or act on a trade, that means send the signal; in `suggest` mode the owner's OK completes it. Code patches are always proposed to the owner as a card with a diff; the owner applies them.

`security_warden.py` boots under a v3.3 banner and includes the v3.7 work-staleness sensor. Verify claims against `bots/sub-bots/security_warden.py` `main` - do not re-assert retired doctrine.

**Live concurrent tasks (from `main` gather):**

1. **Ingress Guardian** - scans untrusted external text for prompt injection
2. **Egress Observer** - logs the agent's signals, alerts on catastrophic sizing only
3. **Infrastructure**
 - canary tokens
 - wallet anomaly (`getSignaturesForAddress` on hot wallet every ~60s via free RPC `RPC_PUBLIC_FALLBACK` first, paid Helius only if that fails; cross-checks `trades.log` / `execution_ledger.jsonl` mtime + `positions.json` sigs - does **not** read `wallet_balance.json` for anomaly)
 - dead man's switch (12h ecosystem-wide activity backstop)
 - API health
 - **Bot Heartbeat Monitor** - per-bot liveness via heartbeat files + thresholds (real "is meme_sniper alive?" check)
 - **Silent Failure / work_staleness** - bot heartbeat alive but work evidence silent (generic silent-failure pattern; finding name `work_staleness`)
 - **Exec failure rate monitor** - structured exec failure markers
4. **Counter Intel** - attack training corpus helpers (`counter_intel.json`, `injection_blacklist.json`) used by ingress - not a separate gather loop
6. **Medic (BOUNDED recovery - verify live)**
 - **Auto path (`medic_process_monitor` -> `medic_report_crash`):** detect crash/syntax signal on a `agent_BOTS_WHITELIST` bot, take a free backup copy, write `security_warden - medic_report_<bot>_*.md`. **No code write. No process spawn. No restart.**
 - **Telegram `MEDIC HEAL` / lockdown are unwired** (command listener is not started). Auto path stays detect + backup + report. Auto-heal is not unlocked. No code write, no spawn, no restart.
 - subprocess usage is **syntax check only** (`python -m py_compile`). No `Popen` / `os.system` / process launch.
7. **Integrity** - hash-checks; operator docs auto-rebaseline; deletions / `.env` / mass-change escalate
+ **inbox_cron_lock_reaper** - reaps stale inbox cron locks
+ **sniper_watch_monitor** - one P1 owner ping when Sniper's heartbeat is stale (> `SNIPER_STALE_ALERT_MIN`) or all components read cancelled (skipped when `stop_reason=user_stopped`), and one when Sniper is alive with zero buys for > `SNIPER_ZERO_BUY_ALERT_H`. Deduped until recovery. Replaces the generic offline monitor for meme_sniper.

This skill is the agent's playbook for reading what warden writes and deciding what to do about it. **Warden writes. The agent reads + decides.** Doctor routes evidence; the agent authors any required patch via the code-monitor skill (the agent applies his own patches in place. Notes go to the agent's inbox). **the owner is not the threat model** - operator doc edits are work, not intrusion.

## Integrity - The End of the "Was That You?" Loop

The old integrity layer treated every hash change on the workspace docs as a
you got a P1 packet listing "WARDEN LOCKDOWN immediately" among the options.
You asked the owner. It was the owner. Every time. And because the baseline refresh was a

**New doctrine - three tiers, read them once:**

1. **Operator docs changed** (rules.md + any WARDEN_INTEGRITY_FILES /
   X_bot_guidelines): auto-rebaselined, logged to the change ledger, and rolled
   into your daily digest under "Operator changes." **This is the owner working, not
   an incident.** Do NOT ask the owner about these. Read the digest section for
   awareness - change context lives in those diffs - and flag ONLY if a change
   surprises both of you.
2. **A baselined file DELETED**: P1 packet. A watched file disappearing is a
   real signal. Confirm intent; if nobody removed it, preserve evidence first.
3. **`.env` changed**: one confirmation ping - *"yo, did you touch.env?"* If
   yes: `INTEGRITY BASELINE`, done. If no: rotate keys first, investigate
   second. Lockdown language appears ONLY when.env changes amid a mass-change
   pattern (≥6 files in one sweep) that the owner didn't cause.

**What this means for your behavior:** your default read on workspace-doc
changes flips from "possible intrusion" to "the owner shipped something." The
question you used to ask him is now answered by the digest before you'd have
asked it. Escalation is earned by the threat classes above - not by the owner doing
his job.

**Patches and upgrades doctrine (unchanged, restated because it's the point):**
warden and code_tuner FLAG. The agent authors the patch and applies it in place.
Nothing in the immune system auto-edits trading code.
Operator doc edits are still not the threat model.


## Threat Triage Doctrine (log-informed unlock)

This section is **the agent judgment doctrine** for reading warden output. It does **not** change bot detect thresholds, capital bounds, or auto-actions. Detection stays mechanical; triage stays human. **Warden findings never move capital.**

### Evidence window (security_warden.json n=228 capped log + companion files)

| class | n / evidence | lived result |
|---|---|---|
| `api_health` | **28** (x_api 19, grok 7, helius 2) | infra noise unless multi-API concurrent + trading impact |
| `wallet_anomaly` unknown-tx bursts | **15** CRITICAL findings; recent ACK = trade-wallet activity | default = hot-wallet venue/bot flow first; lockdown only on unrecognized drain |
| canary trips (`canary_trips.json`) | **44** total; **39/44** = `positions_backup.json`, **5/44** = `.env.backup` | positions_backup = known FP pattern (the agent stamped `_FP_`);.env.backup stays hotter |
| `bot_heartbeat_stale` | **9** | mix of real stale + expected_off when HEARTBEAT MODE OFF (x/sniper) |
| medic crash path | `medic_log.json` **missing**, medic_audit empty, medic_backups **0** | crash-heal distribution = **null**; doctor/silent path carried the load |

Honest nulls are valid: empty medic crash log does not invent a medic problem.

### Priority ladder (handle in this order)

1. **Cluster breach** - canary (non-FP class) + wallet unrecognized drain + integrity deleted/env mass-change in same window -> Tier 4 / lockdown path with the owner
2. **work_staleness / doctor `investigate_*`** - process alive, work dead (or doctor evidence packet). Name cause: hung loop vs dead external brain (RPC/API/LLM). Do not treat as "medic will restart"
3. **Unexpected bot_offline / heartbeat stale** - only if bot is supposed to be up. If HEARTBEAT MODE OFF / deliberate stand-down: mark expected_off, no escalate
4. **integrity deleted** or **`.env` change** - real. Operator doc edits are NOT this tier (already auto-rebaselined)
5. **wallet_anomaly** - first assume hot-wallet trade/venue flow; cross-check `trades.log` / `execution_ledger.jsonl` / open positions. Unrecognized drain or non-trade destination -> escalate
6. **canary** - classify file before panic (below)

### Known-noise classes (still log; do not pretend breach)

These are **labels for the agent triage**, not bot suppress instructions. Bot may still write packets; you classify on read.

| label | pattern | default the agent action |
|---|---|---|
| `canary_fp_positions_backup` | trip on `canary/positions_backup.json` (39/44 trips) | known FP unless clustered with other breach classes; stamp FP, move on |
| `wallet_trade_burst` | 2-5 unknown txs / 10min on hot trade wallet with matching trade activity | ACK trade flow; no lockdown |
| `expected_offline` | offline packet while HEARTBEAT MODE OFF / stand-down | no medic chase; no the owner page |
| `operator_doc_change` | integrity v3.4 auto-rebaseline | already not an incident |

### Real-signal classes (earn attention)

| label | pattern | default the agent action |
|---|---|---|
| `work_staleness` | hb fresh + work evidence stale + not stood down | doctor packet path; diagnose source before code |
| `canary_hot` | `.env.backup` or any canary that is not the known positions_backup FP | verify origin; lockdown if not the owner/the agent |
| `integrity_deleted` / `env_changed` | baselined delete or.env | P1; env = agent checks the change trail, notify-only ping; mass-change = lockdown language allowed |
| `unexpected_offline` | critical bot stale while mode expects up | check log / process; agent restarts via Start_Bots.bat |
| `wallet_unrecognized_drain` | txs not explained by trades/positions/the owner | lockdown + the owner |

### Whitelist coverage note (live `agent_BOTS_WHITELIST`)


### Sensitivity / bot threshold changes


### Hard lines (unchanged, restated)

- the owner is not the threat model
- Medic auto path = detect + backup + report only; break-glass = mechanical restore only; no spawn/restart
- Doctor = evidence router only (`doctor_use_claude=False`)
- Detection-only perimeter - **never capital** from warden findings
- Manual-deploy floor holds

## Autonomy Note

Warden is mechanical: it logs findings, fires medic on syntax errors, writes inbox packets on its cadence. The mechanics are scripted.

The judgment is yours: deciding whether an integrity mismatch is a legitimate code changes or a real breach; deciding whether a heal that "succeeded" actually fixed the underlying behavior or just patched a syntax error over a deeper bug; deciding when to refresh the hash baseline. Warden gives you evidence - you make the call.

Operate as the operator, not the checklist runner.

---

## Authority Tier Mapping

**Tier 1 EXECUTE (no ask):**
- Read warden inbox packets (with source `warden_*`)
- Read `security_warden.json`, `medic_log.json`, `integrity_log.json`, `counter_intel.json`
- Move warden inbox packets to `inbox_results/done/` after handling
- Read warden config / heartbeat / status files
- Append findings about warden activity to LEARNINGS

**Tier 2 DECIDE + EXECUTE WITH AUDIT:**
- Decide whether a medic_report / restore packet means the bot is actually healthy (report/restore != process healthy)
- Triage critical packets: which ones need the owner's eyes immediately
- Mark warden findings in LEARNINGS as resolved/pending

**Tier 3 DECIDE + ACT (the agent decides, owner-ping notify-only):**
- `WARDEN LOCKDOWN` - engages ecosystem-wide lockdown (bots that honor flag halt writes)
- `INTEGRITY BASELINE` - refreshes the known-good hash baseline (the agent verifies the change trail first)
- Adding/removing bots from `agent_BOTS_WHITELIST` in security_warden.py (code change - the agent authors patch via code-monitor, the agent patches in place)
- `MEDIC ROLLBACK` Telegram is unwired. Do not expect a chat command to roll a bot back.

**Tier 4 IMMEDIATE ESCALATION:**
- Multiple critical findings in the same window (canary trip + wallet anomaly + integrity mismatch)
- Medic rate-limit hit (>3 heal attempts/hr on same bot - deeper issue exists)
- Unauthorized command attempts if TG listener is ever re-enabled (currently disabled - outbound-only)
- Hash baseline file (`known_good_hashes.json`) itself is missing or corrupted
- Lockdown engaged but the owner didn't fire it (auto-lockdown OR another agent)

---

## Inbox Protocol

Warden writes to `inbox` (or `owner_inbox` when `target_inbox="owner"`).

**Naming doctrine (live `write_inbox_packet`):** every packet is named `security_warden - <slug>_<ts>.md`. There is NO priority prefix on the filename. `source` is header-only context; filename always collapses to botname `security_warden`.

**Shared envelope header (live - critical/escalation packets already use this):**
```
# <Slug Title>
**Source:** <source>
**Priority:** P1|P2|P3|P4
**Recipient:** the agent... | the owner...
**Written:** <iso ts>
**Lockdown active:** True|False
**Kill switch active:** True|False
---
<body>
```
Priority codes are **P1/P2/P3/P4** (not high/normal/low). Treat P1 as handle-now, P2 high, P3 normal, P4 low/self-note. If a future packet ever ships without this envelope, flag a retrofit - do not invent a second format.

**P1 (handle first) - live slugs:**
- `security_warden - canary_tripped_*.md` - canary credential file accessed
- `security_warden - wallet_anomaly_*.md` - unknown wallet txs detected
- `security_warden - integrity_deleted_*_files_*.md` / `integrity_sentinel_env_changed_*.md` - integrity escalations (operator-doc edits are auto-rebaselined, not P1)
- `security_warden - medic_report_*.md` - whitelisted bot crash: detect + backup + report only. **Read error class first** - auth/billing has no code fix
- `security_warden - medic_patch_needed_*.md` - break-glass mechanical restore happened; the agent still authors real patch
- `security_warden - medic_rate_limit_*.md` - heal/report backoff exhausted on same bot

**P2 doctor / ops:**
- `security_warden - investigate_<bot>_*.md` - **live doctor packet** (evidence only; the agent diagnoses). Retired skill names `code_bug_diagnosis_*` / `escalation_*` / `restart_*` are **not** what live doctor writes anymore
- `security_warden - bot_offline_*.md` - heartbeat monitor offline/stale alert

**P3 normal:**
- `security_warden - daily_digest_*.md` - 24h digest (morning briefing)
- skill-evo notify packets (`auto_applied_*`, `refused_*`, `doctrine_drift`, `bot_rejected_*`, etc.)


**v3.3 medic doctrine (BOUNDED - verified live):**
- Auto: detect + backup + `medic_report` packet. Never writes code. Never spawns/restarts a process.
- Telegram `MEDIC HEAL` is unwired. Auto path does not restore or auto-repair.
- the agent applies his own patches in place. Warden does not copy them into bots/.
- Old `medic_healed` / `medic_sandbox_failed` / `medic_too_large` packets are dead.

- Do not drop APPROVED/AMEND flags. They are ignored.
- the agent patches in place if a new bot file should exist. Warden does not deploy it.

---

## State Contracts

**READ-ONLY:**
- `bot_logs/security_warden.json` - findings log (capped 500)
- `bot_logs/counter_intel.json` - attack corpus (capped 2000)
- `bot_logs/injection_blacklist.json` - auto-learned patterns
- `bot_logs/medic_log.json` - heal attempts (capped 500)
- `bot_logs/integrity_log.json` - hash check events (capped 200)
- `bot_logs/known_good_hashes.json` - integrity baseline
- `bot_logs/canary_trips.json` - canary access events
- `bot_logs/medic_audit/audit_YYYY-MM-DD.json` - daily medic audit
- `bot_logs/medic_backups/*.backup` - pre-heal bot snapshots
- `bot_logs/doctor_log.json` - doctor investigations (capped 200)
- `bot_logs/heal_attempts.json` - medic/doctor backoff tracking


**WRITE flag-files via commands (NOT direct):**
- `bot_logs/lockdown_state.flag` - created by `WARDEN LOCKDOWN`, removed by `WARDEN RESUME`
- `bot_logs/KILL_SWITCH.flag` - manual only, neither warden nor the agent auto-engage

**NEVER write:**
- The warden bot file itself (`bots/sub-bots/security_warden.py`) - patches authored by the agent via code-monitor, patched by the agent in place
- `medic_backups/` - warden owns rotation
- `canary/*` - these are decoys, never touch

---

## The 9 Operational Lanes

### Lane 1: Reading the Daily Digest (normal priority, once a day at its configured time)

The morning normal-priority digest is your primary briefing on what warden saw. Structure:

- **Status snapshot** - lockdown / kill switch / integrity baseline state
- **Findings (24h)** - count by severity + by category
- **Medic activity** - heals succeeded / failed / by action
- **Integrity** - events in 24h
- **Counter-intel** - attacks blocked
- **Critical/high findings detail** - last 10
- **Proactive** - items worth the agent's attention

**Workflow:**
1. Read the daily digest packet
2. If anything CRITICAL or HIGH: read the underlying packets that fed into it
3. Note any patterns (e.g., 5 prompt-injection blocks from same source = social engineering campaign)
4. Move the digest packet to `inbox_results/done/`
5. Carry forward any unresolved threads into your next operational cycle

### Lane 2: Responding to High Priority Critical Packets

When you see a high priority packet from warden, **stop your current task and triage immediately**.

For each high priority type:

**`canary_*` (canary trip)**
0. Classify file first per Threat Triage Doctrine: `positions_backup.json` = known FP class unless clustered; `.env.backup` / other canaries stay hot
1. Verify if the owner legitimately accessed the file only when class is hot or clustered
2. If NOT the owner and not known-FP class: perimeter breach signal
3. Action when hot/clustered: escalate lockdown path to the owner (TG listener disabled - do not assume warden getUpdates)
4. Cross-ref `counter_intel.json` / `canary_trips.json` for same-window cluster
5. Once safe: document + write LEARNINGS only if pattern is new

**`wallet_anomaly` (unknown txs detected)**
0. Default class = `wallet_trade_burst` on hot trade wallet until proven otherwise (triage doctrine; n=15 window all trade-shaped ACKs)
1. Cross-check `trades.log` / `execution_ledger.jsonl` / positions before Solscan theatre
2. If matches bot/the owner trade flow: ACK, no lockdown
3. If unrecognized drain / non-trade destination: lockdown path + contact the owner
4. LEARNINGS only when a new safe pattern is confirmed (not every burst)

**`integrity_*` packets (live slugs: `integrity_deleted_*`, `integrity_sentinel_env_changed`)**
1. Read Integrity v3.4 doctrine first - operator doc edits auto-rebaseline and are NOT incidents
2. Deletion of a baselined file = real P1 signal
3. `.env` change = agent checks the trail, one notify-only ping; lockdown language only on mass-change pattern
4. If unauthorized beyond operator work: WARDEN LOCKDOWN + investigate before any baseline refresh

**`medic_rate_limit` (medic giving up)**
1. Rate-limit means heals aren't sticking - there's a deeper issue
2. Read the underlying bot file manually
3. Check `medic_backups/` for the backup chain - is each successive heal making things worse?
- `MEDIC ROLLBACK` Telegram is unwired. Do not expect a chat command to roll a bot back.

### Lane 3: Reviewing Medic Report / Restore Packets

When medic fires, it writes a packet (check **Priority:** P1 inside). Auto path is **report-only**. Break-glass restore means **file bytes rolled back**, not "bot process healthy." **Restore/report != behaviorally correct.**

**Workflow:**
1. Read the packet - note error class + backup path
2. If AUTH/BILLING: pay/refresh key; no code patch
3. If real code bug: the agent patches the file in place. Warden does not apply it.
4. If break-glass restore ran: diff quarantine vs running file; confirm running bytes are known-good old version
5. Monitor that bot's heartbeats next cycle - medic did not restart the process
6. Move packet to `inbox_results/done`

**Red flags:**
- Assuming medic restarted the bot (it does not)
- Treating backup/report as a semantic fix
- Skipping error class and writing a pointless code patch for billing failures

### Lane 5: Integrity Baseline Discipline

The integrity baseline is your "snapshot of files as the owner expects them." When it drifts, warden alerts.

**When to refresh baseline:**
- After code changes (you just edited rules or integrity files - refresh after deployment)
- After the agent patches a bot file in place (legitimate change already on disk)
- After the owner makes manual edits to `.env` or any critical file

**How to refresh:**
- `INTEGRITY BASELINE` Telegram is unwired (listener is not started). Do not treat chat as the apply path.
- This snapshots ALL critical files as the new known-good state

**When NOT to refresh:**
- If you don't know why a file changed, DON'T refresh - investigate first
- If multiple files mismatched simultaneously and you didn't author the changes
- If baseline file (`known_good_hashes.json`) itself was modified - that's Tier 4

### Lane 7: Doctor Packets

Doctor packets land when medic backoff exhausts (3+ reports in window) OR heartbeat/silent-failure monitors escalate. **Live doctor gathers evidence and routes to the agent.** It does not call Grok/Claude to name the bug (`doctor_use_claude=False`; diagnose-via-LLM path retired).

**Live packet:** `security_warden - investigate_<bot>_*.md` (P2)
- the agent names the cause: code bug -> patch the file in place (the agent applies it); hung process -> the agent restarts it via Start_Bots.bat; external service (RPC / API auth) -> browse/check; unknown -> read the evidence again. Doctor notes already landed in the agent's inbox.
- Log findings in LEARNINGS.md so the next human pass is faster

**Retired skill packet names (do not expect these from live doctor):**
- `code_bug_diagnosis_*`, `escalation_*`, `restart_*`, `doctor_unknown_*` - old multi-route naming. If you still see them, they are stale templates or pre-retirement residue, not current doctor output.


### Lane 9: Reading the Daily Digest

The daily digest now has six new sections beyond the original four. Read them in this order each morning:

1. **Bot heartbeat snapshot** - first section. ✅/⚠️/🔴 status per bot using configured thresholds. If anything is in OFFLINE or STALE buckets, prioritize that. NO HEARTBEAT means the bot has never written a heartbeat file - usually means it hasn't started or was just deployed.

2. **Findings** (unchanged) - severity + category breakdown.

3. **Medic activity** (unchanged) - heal counts.


5. **Code request queue** - pending `code_requests.json` count + age of oldest unresolved. These are now FALLBACK-only entries - the agent authors most patches in place without going through code_requests. If pending > 5 OR oldest > 48h, it means code_tuner's routing loop has fallen behind on writing packets to place, OR the owner hasn't picked them up. Investigate via `code_tuner.log`.


8. **Integrity** (unchanged) - hash check events.

9. **Counter-intel** (unchanged) - attack summary.

10. **Critical/high findings** (unchanged) - last 10 critical items detail.

11. **Proactive** - checklist for the morning.

**Read the heartbeat snapshot first.** A red bot dwarfs every other concern.

---

## Hard Laws

- **No `memory_add` from warden.** Birth doctrine: warden persists via bot_logs JSON + inbox packets only - never the memory tool path.
- **Warden file:** the agent may patch `security_warden.py` in place. `os.execv` reloads warden only. Do not start the bot from this skill. Do not drop approval flags to deploy other bots.
- **NEVER manually delete `medic_backups/*`.** Warden owns rotation.
- **NEVER refresh integrity baseline if you didn't cause the drift.** Investigate first.
- **NEVER issue `WARDEN LOCKDOWN` without notifying the owner simultaneously.** Lockdown halts trading bots.
- **NEVER suppress a high priority warden packet.** Even if you think it's a false positive, document why and move on - don't silently ignore.
- **NEVER trust a medic report/restore as "bot is fully working."** Report != fixed. File restore != process restarted. Syntax valid != semantically correct.
- **ALWAYS read the underlying packets for any digest finding flagged critical/high.**
- **ALWAYS verify legitimate origin before refreshing integrity baseline.**

---

## File Paths

**Read:**
```
Findings: bot_logs\security_warden.json
Counter-intel: bot_logs\counter_intel.json
Injection patterns: bot_logs\injection_blacklist.json
Medic log: bot_logs\medic_log.json
Medic audit: bot_logs\medic_audit\audit_YYYY-MM-DD.json
Medic backups: bot_logs\medic_backups\*.backup
Integrity log: bot_logs\integrity_log.json
Hash baseline: bot_logs\known_good_hashes.json
Canary trips: bot_logs\canary_trips.json
Inbox packets: inbox\security_warden - *.md
─── v3.3 additions ───
Doctor log: bot_logs\doctor_log.json
Heal attempts: bot_logs\heal_attempts.json
Code requests: bot_logs\code_requests.json (mostly dormant now - doctor prefers sending diagnosis packets directly to the agent for patch authoring in place. code_tuner is observation only.)
Offline state: bot_logs\warden_offline_alert_state.json
Approval archive: owner_inbox\archive\<ts>_<flag_name>
```

**Write (via inbox packet, NOT direct):**
```
─── v3.3 additions ───
Code requests: bot_logs\code_requests.json
                    (mostly legacy/dormant path. Doctor now prefers direct packets to the agent so he authors the patches himself in place.)
```

**Move (after handling):**
```
Inbox done: inbox_results\done\<original_filename>
```

**NEVER write:**
- `bots/sub-bots/security_warden.py` (patches authored by the agent via code-monitor, patched by the agent in place)
- `bot_logs\medic_backups\` (warden rotation)
- `bot_logs\canary\*` (decoys, leave alone)
- `bot_logs\KILL_SWITCH.flag` (manual emergency only)
- `bot_logs\lockdown_state.flag` (Telegram lockdown is unwired; warden does not auto-lock from canary)

---

## Calibration Notes

Track quarterly:
- **Daily digest reads** - is the agent actually reading them? Or are they piling up unhandled?
- **High priority response time** - how long between warden writing a high priority packet and the agent triaging?
- **Medic report usefulness** - % of medic_report packets where error class + next action were correct
- **Integrity baseline refreshes per month** - high count may mean baseline drift is too aggressive
- **False positive rate on canary/wallet anomaly** - if too many legitimate alerts, tune thresholds in warden_config.json
- **Telegram unauthorized command attempts** - rising count = social engineering attempt

After 90 days, review in LEARNINGS. If digest is being ignored, shorten format. If high priority response time is slow, add Telegram alert acceleration. If medic heals don't stick, audit the LLM prompts.

---

## What This Skill Is NOT

- Does not watch positions (meme_sniper's own risk layer does that); warden watches the perimeter
- NOT a substitute for code_tuner (code_tuner is now pure observation; the agent authors patches from doctor signals in place (the agent applies them))
- NOT for triggering trade decisions (warden never says "buy this" or "skip this")
- NOT a source of trading signals (warden writes findings, not signals)
- NOT a place to discuss compromise (compromise events go straight to owner-ping + LOCKDOWN)

---
