---
name: forensics
version: v14.3
description: |
  the agent's deep retrospective intelligence covering BOTH executed trades
  (PART 1, autopsy) AND missed runners (PART 2, miss-analyst). Mechanical
  bot data goes in (autopsy_reports.json from meme_sniper.py for
  executed trades; miss_book.jsonl from meme_sniper.py for misses).
  Forensic intelligence comes out: root causes, alternative paths,
  surgical fixes, LEARNINGS entries, ERR/FEAT auto-filing, filter patches
  authored via code-monitor doctrine. PART 1 covers what happened on
  trades that closed, entry through exit, six dimensions, three
  perspectives, insight quality grading. PART 2 covers why the ecosystem
  missed runners it should have caught, seven root cause categories,
  real question layer, conditional patches that catch winners without
  opening rug floodgates. Triggers: "autopsy the X trade", "why did Y
  rug", "deep dive on Z", "what did we miss this week", "analyze recent
  misses", "why didn't we catch X", weekly batch reviews. Does NOT fire
  trades, modify active filters directly (writes proposals only), or
  replace the mechanical meme_sniper.py capture. Patches go out as
  proposals through code-monitor into owner_inbox; nothing is auto-deployed,
  no capital moves and no bot edits itself.
allowed-tools:
  - Read
  - Write
  - Edit
purpose: >
  Self-improvement via brutal post-mortems. Autopsies + miss analysis turn
  losses + missed runners into compounding wisdom, but only if the
  forensic is HONEST. The temptation is to write retrospectives that
  preserve self-image, "tough market", "edge case", "couldn't have
  known". That's how forensics dies. Every autopsy must answer: was the
  decision wrong, was the execution wrong, or was the outcome random?
  Pick. Defend. If you can't defend the call you made, that's the
  finding. Truth > convenience. Pattern-Keys > excuses.
---

> **v14.3.** Results from my skill journey: the method that held up on live trades and what I learned running it. Tested defaults; tune them to your owner (SETUP.md).


> **Operating mode:** Work within the owner's chosen mode (`AGENT_MODE`, SETUP.md section 4) and the owner's `rules/rules.md`. The goal is long-term capital compounding through the most honest read you can get of markets, human psychology, narratives and probability, never at the cost of safety or integrity. Think first-principles, pattern-obsessed, zero-fluff, brutally honest. Every decision in this skill serves that goal inside the owner's mode.

**Purpose:** Self-improvement via brutal post-mortems. Autopsies + miss analysis turn losses + missed runners into compounding wisdom, but only if the forensic is HONEST. The temptation is to write retrospectives that preserve self-image, "tough market", "edge case", "couldn't have known". That's how forensics dies. Every autopsy must answer: was the decision wrong, was the execution wrong, or was the outcome random? Pick. Defend. If you can't defend the call you made, that's the finding. Truth > convenience. Pattern-Keys > excuses.


> **Impossible-runner filter:** read `bot_logs/miss_book_clean.jsonl` for miss stats, not raw `miss_book.jsonl`. The clean copy drops rows whose peak ratio is above `MISSED_RUNNER_MAX_RATIO` (50x), whose scan mcap is under `MISSED_RUNNER_MIN_SCAN_MCAP` ($3k), or whose mcap is above `MISSED_RUNNER_MAX_MCAP` ($500M). Those are bad price prints, not lessons. The live bot now suppresses the same rows before they become missed-runner cards. If you must use the raw book, apply the same three filters and say so. Autopsy `hold_minutes` is exit minus open now (older rows were processing time minus open and run long); rows with `pnl_unknown: true` are data holes, not -100% trades.

# Forensics, the agent's Trade Retrospective Intelligence

> **The owner's mode (`AGENT_MODE`, asked first in setup):** `suggest` is the default. You propose each buy and sell by writing the normal signal to `json_relay/agent_signals.json`; the bot holds it (`awaiting_owner_approval` ack, owner card) until the owner answers `/approve <id>` or `/reject <id>`. Do not re-fire a held signal and never write an approval yourself. `auto` is the owner's opt-in: trade signals execute inside the caps and owner-ping is notify-only. In both modes your analysis, logging, SL/TP on open bags and inbox handling run as written below, and setup config (wallet, sizes, paper vs live, `AGENT_MODE`, `LAUNCH_RAIL_LIVE`) belongs to the owner: you never change it. Where a line below says to fire, buy, sell or act on a trade, that means send the signal; in `suggest` mode the owner's OK completes it. Code patches are always proposed to the owner as a card with a diff; the owner applies them.

> **Friction stamp:** skill-only. HOLD LF. em 62->0. No capital. Retrospective proposals only. **HELD into 1.2.0.**
>
> **Evolve stamp:** adaptive autopsy doctrine **** (skill-side only). Honesty test n=111 autopsies: loser median amount_sol 0.15 vs winner 0.075 (ratio 2.0) with **0/111** reverse-size language hits = HARD FAIL. miss_reports FILTER_THRESHOLD x7 + no autopsy_skill_history + 0/111 closure status fields = open loop. Cascade for status tracker file + softwarn feed = SPEC / proposal only. No capital. No live filter write. No meme_sniper edits.
>
>
> **Boundaries structural:** forensics NEVER writes live filter file, does not edit meme_sniper.py. Path = filter_patches.json (audit) -> code-monitor patch -> the agent applies (backup + revert note) -> owner_inbox `forensics - patch_*` notice.
>
> **Coherence:** threshold patches target **`bots/tuner/meme_sniper_filter.json`** (live override SoT). Do not patch bare code DEFAULT_* / FALLBACK twins as if they were the live layer (meme-hunter filter-vs-code drift). `autopsy_reports.json` is the shared mechanical autopsy store also read by ca-intel, one definition.
>
> **Honesty core PRESERVED + STRESSED:** decision / execution / random pick-one discipline; ban on "tough market" / edge-case / couldn't-have-known self-image excuses. Reverse-size must be named as **decision-wrong** when amount_sol on losers systematically exceeds winners (or trade-level size is inverted vs conviction). Rationalizing reverse-size as tough-market is a skill violation.
>
> **Birth:** memory_add ABSENT. The owner-facing packets prefer hyphen `forensics - <slug>_<ts>.md` (P-prefix fossil tolerated only as legacy examples). Shared envelope on the owner-facing. Model **Grok 4.5**.

## OPERATOR CARD - read first

| Surface | Status | Truth |
|---|---|---|
| PART 1 source `autopsy_reports.json` | **LIVE** | meme_sniper close book + `exit_failed` still-holding rows |
| PART 2 source `miss_book.jsonl` | **LIVE** | typed miss ecosystem (alert / autopsy / never_seen / opportunity / flip / heal / aged_out). `miss_book.jsonl` is DEAD for sniper |
| Live filter SoT | **LIVE** `bots/tuner/meme_sniper_filter.json` | READ ONLY; patch proposals must name this file; never write |
| Code DEFAULT_*/FALLBACK trail twins | **NOT live SoT alone** | filter-vs-code drift exists; do not author patches against the wrong layer |
| `filter_patches.json` | **AUDIT ONLY** (create-on-write) | never the live filter |
| Patch route | **LIVE** | filter_patches audit -> code-monitor -> agent applies -> owner_inbox `forensics - patch_*` notice |
| Direct filter / bot source edit | **REFUSE** | NEVER edit meme_sniper.py |
| Market mode SoT | **LIVE** `bot_logs/market_mode.json` | |
| History name | `autopsy_skill_history.jsonl` | the live history contract |
| Honesty core (decision/execution/random + no tough-market) | **LIVE LAW** | do not weaken |
| Reverse-size honesty in autopsies | **(1.2.0)** | forced check; decision-wrong when size inverted; never tough-market cover |
| Adaptive autopsy doctrine | **skill-side** | prescription + recurrence-first + closure states |
| Status tracker file + softwarn feed | **CASCADE SPEC ONLY** | the owner-gated proposal; no capital; no bot self-edit |

Every trade and every meaningful miss carries information. The bots produce mechanical data, meme_sniper.py writes autopsy_reports.json after every close, meme_sniper.py writes miss_book.jsonl when a skipped token runs. That's signal capture, not synthesis. This skill is the analytical layer on top: what actually happened, what does it teach, what's the surgical fix.

Two halves of the same retrospective discipline:

- **PART 1, autopsy**, analyze trades that EXECUTED (closed positions). Question: what happened, what does it teach, what alternative paths existed?

- **PART 2, miss-analyst**, analyze trades NOT taken (skipped 2.5x+ runners). Question: why was this missed, what conditional patch catches it without adding rugs?

Both parts share infrastructure: forensic depth, root-cause discipline, LEARNINGS append, evidence-backed claims. They differ in subject matter and output destination, autopsy outputs go to LEARNINGS + ERR/FEAT queues; miss-analyst outputs go to filter_patches.json + patch packets in owner_inbox.


---

## Autonomy Note

The mechanical layers of forensics are scripted: pull the timeline, populate the schemas, run the calibration check, file the appropriate entries. Those steps follow procedure.

The judgment layers are the agent's: which root cause among many actually drove the outcome, whether a miss-analyst patch is conservative enough to auto-promote, whether an alternative path is genuinely informative or hindsight bias dressed as insight. Two analysts with identical data produce different conclusions on judgment layers, that's correct. The skill produces evidence; you produce the verdict.

Operate as the operator, not the checklist runner.

---

## Authority Tier Mapping

Forensics-specific tier mapping:

**Tier 1 EXECUTE (no ask):**


- Run single-trade or batch autopsy analysis (PART 1)

- Run miss forensic on any 2.5x+ skipped runner (PART 2)

- Compose autopsy or miss-analyst report

- Append findings to LEARNINGS (PART 1) or miss_reports.json (PART 2)

- Update autopsy_skill_history.jsonl or miss_analyst_config.json

**Tier 2 DECIDE + EXECUTE WITH AUDIT:**

- Auto-file ERR entries when autopsy reveals filter failures

- Auto-file FEAT entries when gap requires new capability

- Tier insight_quality (low/medium/high) for autopsies

- Mark LEARNINGS entries as resolved/low or pending/high

- Write HIGH-confidence zero-new-rug miss-analyst patches to owner_inbox as P3 patch packets (auto-promoted via code-monitor doctrine; the agent applies and the packet is the notice)

- Classify miss-analyst recommendation type

- Batch-analyze weekly miss patterns

- Archive resolved analyses

**Tier 3 DECIDE + APPLY (the agent decides, owner-ping notify-only):**

- Propose changes to meme_sniper.py filter thresholds based on batch findings (code change)

- Propose retirement of a pattern detector that consistently misfires

- Propose sizing rule changes based on autopsy findings

- Miss-analyst patches with MEDIUM confidence or that add NEW rug risk

- Patches that change core trading logic beyond threshold tuning

- Recommending capability builds (via P3 FEAT packets)

- Proposing to retire a filter entirely

- Any systemic recommendation that would alter how trades fire

**Tier 4 IMMEDIATE ESCALATION:**

- Autopsy reveals systematic rug pattern missed 3+ times in a row (possible compromise)

- autopsy_reports.json shows trades the agent never authorized (ghost trades)

- Miss-analyst surfaces miss_book.jsonl with coordinated wash-trade signature

- Analysis reveals a bot crashed silently during the scan window (filter didn't fail, bot was offline)

---

## Inbox Protocol

**Mode A, the agent self-invokes** (after a close, weekly review, or spotting a specific case worth investigating)

**Mode B, inbox requests** via `inbox`:

- Any inbox packet addressed to forensics (owner request for a specific trade or miss, or another skill asking for confirmation)

**Writing FROM forensics to inbox:**

- Tier 3 patch proposals drop as `P3_[ts]_forensics_patch_[token].md` (all non-HIGH-confidence patches)

- FEAT requests for new capabilities drop as `P3_[ts]_forensics_feat_[name].md` (built once the agent marks it go)

---

## State Contracts

**READ-ONLY:**

- `autopsy_reports.json` (written by meme_sniper on landed full sell + exit_failed)

- `miss_book.jsonl` (written by meme_sniper when tokens run after being skipped)

- `trades.log`, `positions.json` (meme open book ONLY), `pnl.json`
- `bots/tuner/meme_sniper_filter.json` (live filter SoT, READ ONLY)

- `pattern_outcomes.json`


- `rug_skip_history.json`, `sl_registry.json`, `dynamic_thresholds.json`

- `bot_logs/market_mode.json` snapshots for context-at-time

**APPEND-only-array:**

- `miss_reports.json` (PART 2 archive)

- `filter_patches.json` (PART 2 patch proposals, local AUDIT ONLY log, create-on-write; NEVER live filter)

- `owner_inbox/forensics - patch_*.md` (preferred hyphen form; HIGH-confidence patches the agent applied, as notices; legacy P3_patch_* fossils only)

- `autopsy_skill_history.jsonl` (PART 1 run log)

- `escalation_queue.json` (Tier 4 only)

**APPEND-ONLY:**

- `LEARNINGS.md`

- `ERRORS.md` (ERR entries from PART 1)

- `FEATURE_REQUESTS.md` (FEAT entries from PART 1)

**WRITE atomic (.tmp + replace):**

- `autopsy_reports/autopsy_[id].md` (per-autopsy report)

- `autopsy_reports/autopsy_latest.md` (canonical pointer)

- `miss_analyst_config.json` (auto-adjust threshold state)

**NEVER write:**

- `autopsy_reports.json` (meme_sniper owns it)

- `miss_book.jsonl` (meme_sniper owns it)

- Active filter values / `bots/tuner/meme_sniper_filter.json` (the agent owns deployment; forensics writes audit + patch packets, the agent applies). NEVER edit meme_sniper.py.

- `code_requests.json`

- Any signal file (this skill is retrospective)

---

## Forensics Operational Rules

- **Verify Before Reporting**, every claim must be evidence-backed. Root cause requires actual log entry, signal entry, or data point. Don't hypothesize without data.

- **Relentless Resourcefulness**, before saying "unclear why", check 10+ context sources (scan logs, wallet signals at time, CT chatter, meta state, dex_paid status, social score at time). Forensics is detective work, not speed work.

- **Reverse Prompting**, novel pattern detection writes to proactive_tracker.md + heartbeat FOR AGENT.

- **One Root Cause**, Perspective 3 / Layer 2 demands ONE. Don't pick "multiple factors contributed." Pick the one that explains most.

- **Evidence over hindsight**, alternative paths must be plausible from the entry-time information set. "Should have skipped because it later rugged" is hindsight, not forensics.

---

## Adaptive Autopsy Doctrine

**Evidence that forced this unlock:**

- `autopsy_reports.json` n=111. Size field LIVE: `amount_sol`. PnL proxy LIVE: `pct` + `outcome` (`pnl_sol` absent).
- Winners with size n=22 median amount_sol=0.075. Losers with size n=57 median amount_sol=0.15. **Loser/winner median size ratio = 2.0** (classic reverse-size).
- Reverse-size language in autopsy free text: **0/111**. Tough-market language: 0/111. Decision-wrong language: 0/111.
- `autopsy_skill_history.jsonl` missing. Closure/status fields on autopsies: 0/111.
- `miss_reports.json` n=8; root `FILTER_THRESHOLD` x7 (recurrence without closure).
- LEARNINGS already knows sizing inversion language exists (reverse_size mentions present) while mechanical autopsies stay silent. That gap is the skill failure.

### Hardest honesty line (required when recurrence hits)

When a Pattern-Key or prescription already exists for this finding:

> **"I diagnosed this before and didn't change."**

Write it verbatim in the autopsy report and LEARNINGS entry. No soft rewrite. If you cannot say it because status is already `verified-closed` with proof, say the verified proof instead.

### Every autopsy ends in a testable prescription

No autopsy is complete with only narrative + root cause. Final block is mandatory:

```
## Prescription (testable)
- pattern_key: <stable key, e.g. size.reverse.loser_gt_winner_median>
- diagnosis_class: decision-wrong | execution-wrong | random
- reverse_size_check: pass | fail | n/a
- amount_sol: <n>
- pct_or_outcome: <n or win/loss>
- prescription_rule: <checkable rule a future decision can obey>
- check_method: <how to verify the rule fired or was obeyed>
- feeds: softwarn-B | reverse_size_kill | filter_patch | none
- status: open
- recurrence: first_seen | repeated (prior ids...)
- hardest_line: <omit | "I diagnosed this before and didn't change.">
```

**Testable means:** a later cycle can mark `applied` or `failed-to-apply` without re-litigating vibes. Examples:

- "If amount_sol on this conviction tier > X while warning_signs include low_liquidity, classify decision-wrong reverse-size and emit softwarn-B candidate."
- "If same pattern_key appears twice in 14d without status>=applied, escalate the owner with hardest line."

Literary lessons without a check method are incomplete autopsies.

### Recurrence check FIRST

Before writing a new lesson, search:

1. prior autopsy reports / `autopsy_skill_history.jsonl` (when present)
2. LEARNINGS Pattern-Keys / sizing / reverse-size lines
3. open prescriptions in the status tracker (when the owner-applied cascade exists; until then search LEARNINGS + local autopsy_reports markdown)

If the same pattern_key or equivalent finding exists:

- do NOT pretend discovery
- set `recurrence: repeated`
- emit the hardest honesty line
- advance or re-open status; never reset to fake-new `open` without naming the prior id

### Status machine (closure law)

`open -> prescribed -> applied -> verified-closed`

| status | meaning | who moves it |
|---|---|---|
| `open` | finding named, prescription drafted | forensics on autopsy write |
| `prescribed` | checkable rule accepted as the standing order | forensics after prescription quality gate |
| `applied` | rule reached a moment-of-decision surface (softwarn candidate packet, kill-switch proposal, filter patch packet, or explicit operator adopt) | forensics marks when proposal filed OR the agent adopts |
| `verified-closed` | later evidence shows the rule changed outcomes or was correctly obeyed; include proof pointer | forensics on follow-up with evidence |

**Illegal:** mark `verified-closed` because the write-up felt complete. **Illegal:** leave repeated findings in eternal `open` with new prose each time.

Until the cascade status tracker file exists, keep status blocks inside autopsy markdown + LEARNINGS, and log runs to `autopsy_skill_history.jsonl` (create-on-write).

### Reverse-size check (forced on every PART 1 autopsy)

Compute when fields exist (`amount_sol` + `pct`/`outcome`):

1. Trade-level: is this loss sized >= typical win size for the same era/tier?
2. Batch-level when scope >= batch: loser median amount_sol / winner median amount_sol. If ratio >= 1.15, reverse-size pattern is PRESENT.
3. If present on a loss: default `diagnosis_class=decision-wrong` unless evidence proves pure execution failure after a correctly small size, or true random after correct process.
4. **Never** file reverse-size under tough-market / edge-case / couldn't-have-known.
5. If reverse-size present, prescription MUST feed a moment-of-decision path: `softwarn-B` and/or `reverse_size_kill` **as proposal text** (not live bot edit).

Honesty test baseline to beat: ratio 2.0 with 0/111 named. Any future autopsy batch that keeps 0 reverse-size names while ratio>=1.15 is a skill regression.

### Prescription must reach moment of decision

A prescription that only lives in a markdown essay is theater. Route options (proposal-only):

| feed | when | artifact |
|---|---|---|
| `softwarn-B` | reverse-size / conviction-size mismatch pre-entry or on manage | cascade proposal packet naming softwarn consumer |
| `reverse_size_kill` | repeated reverse-size after prior prescribe | cascade proposal for kill/limit rule |
| `filter_patch` | miss-analyst threshold root | existing filter_patches audit + `forensics - patch_*` |
| `none` | true random after process-correct | say none; still close with evidence |

**Skill unlock now.** Bot/mechanism wiring remains cascade SPEC.

### Prove-it board (forensics )

| capability | status | unlock condition |
|---|---|---|
| adaptive autopsy doctrine in skill (prescription + recurrence-first + status words + reverse-size force + hardest line) | **** | honesty n HARD FAIL + open loop; skill-side only |
| agent_direct skill text ship + trail | **** | lived evolution rail |
| write autopsy_skill_history.jsonl on runs (create-on-write) | **** | local append; no capital |
| status tracker file as shared store | **LOCKED / cascade SPEC** | the agent applies proposal; then prove >=3 status transitions logged |
| softwarn-B / reverse_size_kill live feed | **LOCKED / cascade SPEC** | the agent applies; no capital from forensics; prove on paper packets first |
| auto mark verified-closed without evidence pointer | **LOCKED forever** | never |
| live filter write / meme_sniper.py edit from forensics | **LOCKED forever** | refuse |

---

# PART 1, AUTOPSY (Executed Trades)

For trades that EXECUTED (closed positions). Question: what happened, what does it teach, what alternative paths existed?

## Core Principle (PART 1)

**Trades carry more information than outcomes.** A trade that printed +45% still has lessons inside it, maybe the exit was lucky, maybe the entry was optimal, maybe the hold duration was 2x longer than it should have been. Outcome alone is noise. This skill extracts SIGNAL: what was actually learned, what would have been learned if outcome differed, what we should carry forward.

Auto-writing LEARNINGS means the ecosystem's knowledge graph grows with every analyzed trade, not just the standout ones. Tiered insight quality prevents the graph from getting noisy, low-insight autopsies get marked resolved immediately, high-insight ones get a second agent pass, then resolve.

## Three Scopes (PART 1)

### Scope 1, Single Trade Deep-Dive

Trigger phrases:

- "Autopsy the DOG trade"

- "Why did PNUT rug?"

- "Deep dive on my FART position"

- "Walk me through what happened with [TICKER]"

Input: specific token (by ticker, CA, or trade ID)

Output: full three-perspective analysis of that single trade

### Scope 2, Batch Analysis

Trigger phrases:

- "Autopsy all my losing trades this week"

- "Deep dive on every sub-10% loser from April"

- "Autopsy my last 5 trades"

- "Review every rug I hit this month"

Input: filter criteria (date range, outcome range, trade type)

Output: per-trade summary + aggregate findings + cross-trade patterns

### Scope 3, Pattern Analysis

Trigger phrases:

- "Find the pattern in my last 10 cluster trades"

- "What's the common thread in my sub-5-min exits?"

- "Autopsy the SI-theme plays"

- "Pattern check on Watch-tier wallet-copy trades"

Input: trade category or grouping criteria

Output: pattern identification + statistical significance + actionable recommendation

## Three Perspectives (PART 1, combined per trade)

Every single-trade autopsy runs all three perspectives. Batch and pattern autopsies apply perspectives to each member then synthesize.

### Perspective 1, Multi-Dimensional

Six dimensions examined independently:

**a. Entry Reasoning**

- Why did this trade fire?

- What signal sources aligned? (wallet cluster, social score, meta fit, cluster arb, the agent authority)

- Was the conviction score justified in hindsight?

- Did the entry reasoning hold up as the trade progressed?

**b. Execution Quality**

- Entry slippage vs expected

- Fill time from signal to buy

- Any RPC issues, failed attempts, retry behavior

- Size appropriate for conviction?

**c. Post-Buy Behavior**

- Immediate price action (first 5min, 15min, 30min)

- Trailing stop behavior

- Volume confirmation or divergence

- Social signal evolution (did meta hold, did CT narrative shift)

**d. Exit Decision**

- What triggered exit (TP, SL, trail, manual, timed)?

- Was exit at optimal vs realized

- How far from peak did we sell?

- How far above bottom (if we bought after peak)?

**e. Pattern Fit**

- Which pattern was this trade slotted into?

- Did actual behavior match pattern expectations?

- Was pattern confidence calibrated correctly?

- Does this trade strengthen or weaken the pattern's historical win rate?

**f. Alternative Paths**

- What if entry was 2min earlier? Later?

- What if size was 2x? 0.5x?

- What if exit was at first TP vs trailing?

- What if we'd skipped entirely?

### Perspective 2, Chronological Narrative

Walk the timeline:

- T-15min: signal formation context (market state, meta, wallet activity)

- T+0: signal fires, buy executes

- T+5min: early price action, first validation or invalidation

- T+X: key price moves, pattern unfolds

- Exit: what happened and why

- T+1h post-exit: did we miss more? Was exit timing good?

Narrative form, not bullet points. The owner should be able to READ the trade.

### Perspective 3, Root Cause

Among everything analyzed, what was the ONE thing that most drove outcome?

Possible roots:

- Entry timing (too early, too late, perfect)

- Signal source quality (cluster was real, wallet copy was noise, meta alignment was strong)


- Execution (slippage killed edge, fill delayed into pump)

- Exit decision (panic sold bottom, held too long, trailed past peak)

- Token fundamentals (rug, whale dump, legit community build)

- Random noise (edge was too small, sample of one, lucky/unlucky)

State the root cause in one sentence. Not "multiple factors contributed." Pick THE one that explains most of the outcome. If it's genuinely random, say so ("this was variance, not pattern").

## The PART 1 Workflow

### Step 1, Parse invocation

Determine scope from the owner's request:

- Contains specific ticker/CA → Scope 1 (single)

- Contains filter criteria (date range, outcome range) → Scope 2 (batch)

- Contains pattern/category language → Scope 3 (pattern)

### Step 2, Pull source data


- `autopsy_reports.json`, find the relevant entries

- `trades.log`, raw timeline


- `pattern_outcomes.json`, pattern context
- `rug_skip_history.json`, for rug-pattern matching

### Step 3, Recurrence check FIRST

Before perspectives, search prior Pattern-Keys / prescriptions / LEARNINGS for the same failure class (especially reverse-size, exit, filter miss). If found: mark `recurrence: repeated`, prepare hardest honesty line, do not fake first discovery.

### Step 4, Run perspectives + reverse-size check

For each trade in scope:

1. Multi-Dimensional (six dimensions) - dimension **b Execution Quality** MUST include amount_sol vs outcome sizing note

2. Chronological Narrative (timeline walk)

3. Root Cause (one sentence verdict) - pick decision-wrong / execution-wrong / random

4. **Reverse-size check (forced):** using `amount_sol` + `pct`/`outcome`, say pass/fail/n/a. On fail, default decision-wrong unless proven otherwise. Ban tough-market cover.

For batch/pattern: synthesize across members. What's the common thread? What's the dominant root cause across the set? Compute loser/winner median amount_sol ratio when n allows.

### Step 5, Grade insight quality

After analysis, tier the insight:

- **HIGH**, non-obvious finding, actionable change, alternative path that would have shifted outcome materially

- **MEDIUM**, confirms or weakens an existing hypothesis with new data, not yet actionable

- **LOW**, variance trade, "ran as expected within pattern," nothing surprising

LOW autopsies get marked resolved immediately. HIGH get a second agent pass, then resolve.

### Step 6, Auto-file ERR (if filter failure detected)

If autopsy reveals a filter SHOULD have caught something it didn't, append to ERRORS.md:

```
## [ERR-YYYYMMDD-XXX] filter_miss_rug_detection
**Logged:** ISO timestamp
**Priority:** high | medium | low
**Status:** pending
**Area:** meme_sniper.py / specific filter / signal chain
### Summary
One-line description of the filter failure
### Evidence
- Specific signal at entry that filter missed
- Log entry showing rejection or pass-through
- Comparable signal that filter HAS caught before
### Suggested Fix
Specific filter change with rationale
### Source autopsy
[link to autopsy_reports/autopsy_[id].md]
```

### Step 7, Auto-file FEAT (if capability gap detected)

If autopsy surfaces a missing capability, append to FEATURE_REQUESTS.md:

```
## [FEAT-YYYYMMDD-XXX] post_buy_watchdog_for_cluster_patterns
**Logged:** ISO timestamp
**Priority:** medium
**Status:** pending
### Requested Capability
What capability would have changed this outcome
### Evidence
- Specific moment in this trade where capability was missing
- How often this gap recurs (search prior autopsies for similar)
### Complexity Estimate
simple | medium | complex
### Suggested Implementation
High-level approach.
```

### Step 8, Append to LEARNINGS

Per autopsy with HIGH or MEDIUM insight, append:

```
## [LRN-YYYYMMDD-XXX] autopsy_[trade_or_pattern_descriptor]
**Logged:** ISO timestamp
**Priority:** high | medium | low (matches insight tier)
**Status:** pending (high) | pending (medium) | resolved (low)
**Pattern-Key:** [stable dedupe key, e.g., "exit.trail_past_peak.cluster_pattern"]
**Recurrence-Count:** N (incremented if Pattern-Key matches existing entry)
### Summary
One-line distilled lesson
### Trade context
- Token, date, outcome
- Pattern slotted, conviction, size
### Root cause
[one sentence from Perspective 3]
### Lesson forward
What changes for future trades like this?
### Cross-references
- See Also: prior autopsies, related ERR/FEAT entries
```

LOW-tier autopsies skip per-entry LEARNINGS append; aggregate into weekly summary instead.

### Step 9, Compose report + prescription block

Write to `autopsy_reports/autopsy_[id].md`:

```
# Autopsy, [TICKER] ([CA short]) | [DATE]
## Summary
[one paragraph, what happened + outcome]
## Recurrence
[first_seen | repeated + prior ids; hardest line if repeated]
## Timeline
[chronological narrative from Perspective 2]
## Multi-Dimensional Analysis
[six dimensions from Perspective 1]
## Root Cause
[one sentence from Perspective 3; decision-wrong | execution-wrong | random]
## Reverse-size check
[pass | fail | n/a + amount_sol + ratio context]
## Prescription (testable)
[mandatory block from Adaptive Autopsy Doctrine]
## Insight Quality
[HIGH | MEDIUM | LOW with rationale]
## LEARNINGS Entry Written
[link or LRN-id, or "skipped (low insight)"]
## Auto-Filed Entries (if any)
[ERR-id, FEAT-id with one-line summaries]
## Status
open | prescribed | applied | verified-closed
```

Also update `autopsy_reports/autopsy_latest.md` to point at this report.
Append one line to `autopsy_skill_history.jsonl` (create-on-write) with id, pattern_key, status, reverse_size_check, ts.

### Step 10, Telegram (HIGH insight only)

If insight is HIGH, fire Telegram with one-line summary + link. Spam defeats the skill, never notify on LOW or MEDIUM.

### Step 11, Heartbeat

Include:

- Autopsies run this cycle (count, scope distribution)

- Insight quality breakdown (high/medium/low)

- ERR/FEAT entries auto-filed (count)

- Notable findings worth the agent's next review cycle

---

# PART 2, MISS-ANALYST (Skipped Runners)

For trades NOT taken (skipped during scan, then ran 2.5x+). Question: why was this missed, what conditional patch catches it without adding rugs?

## Core Principle (PART 2)

Surface answer: "Liq filter blocked it."

Real answer: "Liq was $17,200 against $20k threshold. Bot was in dead_mode (tightens thresholds). Meta state was SI-dominant at scan time. Historical data shows SI tokens in dead_mode outperform the mode's win-rate baseline by 23%. Conditional patch: lower MIN_LIQUIDITY from $20k to $15k ONLY when market_mode=hot OR (market_mode=dead AND meta=SI). This catches the missed token plus 3 similar ones from last 30 days with zero additional rugs based on dump_patterns."

The second answer is what ships. The first answer is what gets us nowhere.

## Threshold Tier System (PART 2, auto-adjust enabled)

This part processes misses in two tiers. Starting thresholds, the agent auto-adjusts based on volume + quality signals.

### Full Forensic Tier (5x+ gain, default)

Gets the complete treatment:

- 4-layer analysis (Timeline, Root Cause, Real Question, Smart Recommendation)

- Recommendation type classification

- Backtest against dump_patterns for rug-risk estimation

- Auto-promotion eligibility check

### Lightweight Tier (2.5x-5x gain)

Gets calibration-grade analysis:

- Root cause classification only (no deep forensic)

- Aggregated into weekly pattern review (Step 4 below)

- Feeds pattern recognition without burning tokens per miss

### Auto-adjust logic

After every cycle, update `miss_analyst_config.json`:

```
json
{
  "current_min_multiplier": 2.5,
  "misses_per_cycle_recent": [12, 8, 15, 9, 11],
  "avg_per_cycle": 11,
  "lightweight_bar": 2.5,
  "full_forensic_bar": 5.0,
  "last_adjust": "ISO timestamp"
}
```

**Raise thresholds** (skill is burning too many cycles):

- If `avg_per_cycle` > 30 over last 5 cycles → raise lightweight_bar by 0.5x (2.5 → 3.0 → 3.5...)

- If `full_forensic_bar` is hit on >15 misses per cycle consistently → raise to 7x

**Lower thresholds** (skill has capacity for more data):

- If `avg_per_cycle` < 3 for 5 cycles AND quality patches landing → lower lightweight_bar by 0.25x (down to floor of 2.0x)

- Never go below 2.0x, misses below that are noise

the agent adjusts manually if auto-logic isn't tracking reality. Skill respects manual overrides.

## The Seven Root Cause Categories (PART 2)

Every miss falls into ONE of these:

### 1. FILTER_THRESHOLD

A specific filter blocked the buy because a numeric threshold wasn't met. Example: liq=$17k against MIN=$20k.

**Fixable?** Yes, surgical threshold change with conditions.

### 2. FILTER_CLEARED_NO_BUY

The token CLEARED all filters but no buy fired. **System bug.** Signal chain broken.

**Fixable?** Yes, investigate signal chain. Critical escalation.

### 3. RUG_HISTORY_BLOCK

Deployer/wallet was on a rug-history blocklist that was overly broad.

**Fixable?** Maybe, refine blocklist criteria with evidence.

### 4. TIMING_MISS

Token cleared filters but scan window missed it (off-cycle, window gap).

**Fixable?** Maybe, adjust scan cadence or add event-driven trigger.

### 5. EXTERNAL_CATALYST

Token ran on news/event/coordinated pump that no scan-side filter could have predicted at entry time.

**Fixable?** Probably not, these are unforecastable. Honest "no_fix_possible."

### 6. POSITION_CAPACITY

Token cleared filters but daily/exposure caps blocked the buy.

**Fixable?** Sometimes, review cap logic vs conviction tiers.

### 7. MARKET_MODE_MISMATCH

Token cleared filters in mode X but mode-X gating was too aggressive.

**Fixable?** Yes, mode-conditional logic refinement.

## The Real Question Layer (PART 2)

After classifying root cause, ask the harder question:

| Surface root cause | Real question (what to actually answer) |

|---|---|

| FILTER_THRESHOLD | What's the threshold value that catches this token AND 3+ similar ones in the last 30 days WITHOUT pulling in known rugs? |

| FILTER_CLEARED_NO_BUY | At which step in the signal chain did this break? Is it intermittent or systematic? |

| RUG_HISTORY_BLOCK | Was the blocklist criterion this specific token tripped actually predictive of rugs, or coincidental? |

| TIMING_MISS | If we'd added one event-driven check at the missed moment, would it have triggered without false positives? |

| EXTERNAL_CATALYST | Is there a SOURCE we should be monitoring that flagged this catalyst before the run? |

| POSITION_CAPACITY | Was the cap tuned for conviction tiers or flat? Should it scale with edge_filter pass count? |

| MARKET_MODE_MISMATCH | Within mode X, what condition triggered the over-conservative gate? Can it become mode + condition? |

Answer with NUMBERS from `rug_skip_history.json`, `pattern_outcomes.json`, historical `meta_state.json` snapshots. Not vibes.

## The Smart Recommendation Framework (PART 2)

A smart recommendation is:

1. **Conditional, not flat.** Never "lower MIN_LIQ from 20k to 15k." Always "lower MIN_LIQ from 20k to 15k WHEN [specific condition]."

2. **Backtested.** State explicitly: "this catches [X] missed runners from last 30 days AND adds [Y] rugs based on dump_patterns evidence."

3. **Surgical.** Smallest possible change to catch the case. If a wider change is needed, propose multiple narrow ones, not one wide one.

4. **Mode-aware.** Most filters operate in mode-X context. Patches should respect that.

5. **Confidence-graded.** HIGH (zero new rugs, narrow condition, ≥3 misses fixed), MEDIUM (small new-rug risk OR narrower applicability), LOW (only fixes 1-2 cases, not worth deploying).

## The PART 2 Workflow

### Step 1, Orient


Read `miss_analyst_config.json` for current tier thresholds. Create with defaults if missing.

### Step 2, Load new misses

Read `miss_book.jsonl`. Filter for:

- `gain_pct >= 2.5 * 100` (2.5x+)

- Mint NOT already in `miss_reports.json` with `analyzed: true`

Sort by gain_pct descending. Larger misses get attention first.

### Step 3, Process each miss by tier

For each miss:

- `gain_pct >= 500` → full forensic (Layers 1-4)

- `2.5x to 5x` → lightweight (root cause classification + add to weekly aggregation)


For full forensic, walk the 4 layers:

**Layer 1, Timeline reconstruction**

Use: `miss_book.jsonl`, `observer_queue.json`, `rug_skip_history.json`, `trades.log`, `autopsy_reports.json`.

**Layer 2, Root cause classification**

One of the seven categories. Be precise.

**Layer 3, Real question**

The harder question from the table above. Answer with numbers from `rug_skip_history.json`, `pattern_outcomes.json`, `meta_state.json` historical snapshots.

**Layer 4, Smart recommendation**

Conditional, specific, backtested.

### Step 4, Cross-miss weekly pattern analysis (Mondays only)

On Monday cycles, read all `miss_reports.json` entries from last 7 days. Synthesize:

- Which single filter/condition caused the most misses? (count by root_cause)

- Time-of-day pattern? (are weekend 12am-6am misses over-represented?)

- Meta pattern? (are SI tokens consistently blocked while animal tokens fine?)

- Market mode pattern? (what % of misses happen in which mode?)

- Cluster around specific conditions?

Produce one paragraph summary:

```
This week's misses: [N] analyzed. Dominated by [root_cause] ([X]/[N]).
Common thread: [specific condition]. Highest-value fix: [patch
description] which would have caught [Y] of [N] misses without
adding rugs. [Patch packet written to owner_inbox for the owner to apply
| awaiting review in filter_patches.json].
```

Append to LEARNINGS with category `forensics_weekly_misses`.

### Step 5, Write miss_reports.json

APPEND (never overwrite). Read existing array, append new entries, write back.

Per-miss entry:

```
json
{
  "timestamp": "ISO",
  "ticker": "TOKEN",
  "mint": "REAL_CA",
  "gain_pct": 850,
  "tier_analyzed": "full_forensic | lightweight",
  "skip_reason_original": "from miss_book.jsonl",
  "root_cause": "FILTER_THRESHOLD | FILTER_CLEARED_NO_BUY | RUG_HISTORY_BLOCK | TIMING_MISS | EXTERNAL_CATALYST | POSITION_CAPACITY | MARKET_MODE_MISMATCH",
  "forensic_detail": "reconstruction with specific data points",
  "real_question": "harder question answered with numbers",
  "recommendation": "specific conditional patch or system fix",
  "recommendation_type": "threshold_change | system_fix | new_signal | no_fix_possible",
  "confidence": "high | medium | low",
  "would_catch_without_new_rugs": true,
  "misses_it_would_fix": ["TOKEN1", "TOKEN2"],
  "rugs_it_would_add": 0,
  "auto_promoted_to_owner_inbox": false,
  "owner_inbox_packet": null,
  "analyzed": true
}
```

### Step 6, Filter patches + auto-promotion gate

For EVERY recommendation with `recommendation_type: "threshold_change"`, write to `filter_patches.json` (append) as the local audit log:

```
{
  "timestamp": "ISO",
  "source": "forensics",
  "triggered_by": "TICKER",
  "parameter": "MIN_LIQUIDITY_REGULAR",
  "current_value": 20000,
  "proposed_value": 15000,
  "condition": "market_mode=hot AND meta=SI",
  "rationale": "data-backed reason with numbers",
  "misses_it_would_fix": ["TOKEN1", "TOKEN2"],
  "rugs_it_would_add": 0,
  "confidence": "high",
  "status": "pending_review | auto_promoted_to_owner_inbox"
}
```

**Auto-promotion gate (ALL must be true):**

- `recommendation_type == "threshold_change"`

- `confidence == "high"`

- `would_catch_without_new_rugs == true` (OR meets HIGH-CONFIDENCE LOW-SEVERITY-RUG ALLOWANCE, see Hard Laws)

- `rugs_it_would_add == 0` (OR allowance applies)

- Parameter is NOT in code-monitor's HARD-LOCKED list (no execute_buy, wallet, auth, private_key, position size caps, or anything in rules.md's safety floor)

**If ALL gates pass → author a patch packet via code-monitor doctrine.** Write to `owner_inbox/forensics - patch_<bot>_<ts>.md` (preferred hyphen form; legacy P3_patch_* fossils only):

```
# Patch Packet | forensics-authored | <ISO ts>

**Target bot:** meme_sniper.py
**Author:** forensics (PART 2 miss-analyst auto-promotion)
**Risk tier:** LOW
**Trigger context:** miss-analysis on [TICKER] (and N other similar misses in 30d window)

## What this changes

Adjust `MIN_LIQUIDITY_REGULAR` in `bots/tuner/meme_sniper_filter.json` from 20000 -> 15000 under conditional `market_mode=hot AND meta=SI`.

## Why

[full rationale from filter_patches.json entry, including:]
- Misses this would have caught (with mints + dates)
- Rug backtest result (count + severity)
- Confidence + evidence trail

## Risk assessment

- LOW risk per code-monitor risk-tier doctrine:
  - Not in HARD-LOCKED parameter list
  - Conditional (only applies in specific market_mode + meta state)
  - Bounded change (single threshold, not architectural)
  - Auto-revertable (the owner can patch back in 1 line if it misbehaves)

## Test plan

- the agent applies the patch (backup first, revert note logged)
- meme_sniper restarts on its next cycle
- Watch trades.log for first N trades under the new threshold
- If 3+ rugs land in 7 days that wouldn't have landed under old threshold → revert
- Otherwise → ride for 30 days, then forensics PART 2 re-evaluates

## Source autopsy / miss-analysis

[link to miss_reports.json entry or autopsy report]
```

Update filter_patches.json entry: `status: "auto_promoted_to_owner_inbox"`.

Update miss_reports.json entry: `auto_promoted_to_owner_inbox: true, owner_inbox_packet: "forensics - patch_meme_sniper_<ts>.md"`.


**If any gate fails** → entry stays in `filter_patches.json` as `"pending_review"` for the owner's next manual review cycle. Surface counts in PART 2's weekly summary so pending_review backlog doesn't grow silently.

### Step 7, FILTER_CLEARED_NO_BUY critical escalation

If root_cause is `FILTER_CLEARED_NO_BUY`, this is a system bug. Even before Step 6 completes, write to `bot_alerts.json`:

```
json
{
  "id": "forensics_system_bug_[ts]",
  "agent": "forensics",
  "priority": "critical",
  "message": "🚨 System bug: [TICKER] passed filters but no buy fired. Signal chain broken at [specific step]. Occurs [N] times in last 30 days.",
  "handled": false
}
```

Filter gaps are calibration issues. System bugs are ecosystem-breaking and need immediate attention.

### Step 8, LEARNINGS append

Per full-forensic miss-analysis, append one entry (APPEND ONLY, read full file first):

```
### Missed Runner | [DATE TIME ET]
- Category: miss_forensic
- Ticker: [X] +[Y]% | Mint: [CA]
- Root cause: [CATEGORY]
- What happened: [2 sentences]
- Smart fix: [specific conditional recommendation]
- Rugs added by fix: [0 | N]
- Auto-promoted: [yes | no, pending_review]
```

Lightweight tier analyses NOT logged per-entry (too noisy). Aggregated into Monday weekly summary only.

### Step 9, Self-calibration update

After processing all misses this cycle, update `miss_analyst_config.json`:

- Append this cycle's miss count to `misses_per_cycle_recent` (keep last 5)

- Recompute `avg_per_cycle`

- Check raise/lower triggers from the auto-adjust logic

- Log any threshold changes in heartbeat

### Step 10, Heartbeat

Include:

- Misses processed this cycle (count, breakdown by tier)

- Root cause breakdown (X filter_threshold, Y cleared_no_buy, Z external)

- Patches written to filter_patches.json (count, pending vs auto-promoted)

- Critical bugs escalated (if any)

- Current thresholds (lightweight_bar, full_forensic_bar)

- Monday weekly summary if applicable

---

## File Paths

**Read:**

```
Trade data (PART 1): bot_logs\trades.log, autopsy_reports.json (SHARED mechanical store w/ ca-intel),
                        positions.json (MEME open book ONLY)
Miss data (PART 2): bot_logs\miss_book.jsonl,
                        rug_skip_history.json, observer_queue.json
Live filter SoT: bots/tuner/meme_sniper_filter.json (READ for current knobs; NEVER write)
Pattern context: bot_logs\pattern_outcomes.json
Failure context: bot_logs\sl_registry.json, dynamic_thresholds.json,
                        risk_state.json, daily_spend.json
Historical learnings: learnings\LEARNINGS.md, learnings\ERRORS.md
Config (PART 2): bot_logs\miss_analyst_config.json
Prior reports: bot_logs\miss_reports.json,
                        autopsy_skill_history.jsonl
```

**Write:**

```
Autopsy reports: bot_logs\autopsy_reports\autopsy_[id].md
Canonical latest: bot_logs\autopsy_reports\autopsy_latest.md
Skill history: bot_logs\autopsy_skill_history.jsonl (append; create-on-write)
Miss reports: bot_logs\miss_reports.json (append)
Filter patches AUDIT: bot_logs\filter_patches.json (append ONLY; create-on-write; NEVER live filter)
Patch packets: owner_inbox\forensics - patch_<bot>_<ts>.md (preferred hyphen form; notice of an agent-applied patch)
                        legacy P3_patch_* examples are fossils
Bot alerts: bot_logs\bot_alerts.json (append, ONLY on FILTER_CLEARED_NO_BUY)
Config: bot_logs\miss_analyst_config.json (atomic overwrite)
LEARNINGS: learnings\LEARNINGS.md (APPEND ONLY, read full first; one clear fact/line; category headers)
ERRORS: learnings\ERRORS.md (APPEND, when filter failures detected, PART 1)
FEATURE_REQUESTS: learnings\FEATURE_REQUESTS.md (APPEND, when capability gaps found, PART 1)
NEVER WRITE: bots/tuner/meme_sniper_filter.json, bots/meme_sniper.py, any json_relay signal
```


---

## Hard Laws


**Shared (PART 1 + PART 2):**

- **NEVER fabricate root causes.** If genuine variance, say so. "Random" is a valid conclusion.

- **NEVER pick multiple root causes.** Forensics demands ONE. Pick.

- **NEVER skip reverse-size check on PART 1 autopsies when amount_sol + pct/outcome exist.** Fail = default decision-wrong unless proven execution-wrong after correct small size, or true random after correct process.

- **NEVER bury reverse-size under tough-market / edge-case / couldn't-have-known.** That is a skill violation after 1.2.0.

- **NEVER end an autopsy without a testable prescription block** (check_method required). Narrative-only autopsies are incomplete.

- **NEVER skip recurrence check.** If diagnosed before, write: "I diagnosed this before and didn't change."

- **NEVER mark verified-closed without evidence pointer.** Status theater is forbidden.

- **NEVER write trade signals.** This skill analyzes, doesn't trade.

- **Patches are applied by the agent** after backup + test plan; a notice packet goes to owner_inbox. Forensics authors patches via code-monitor doctrine; it does not write to bot source files or to code_requests.json.
- **Forensics itself does not write the live filter file.** `bots/tuner/meme_sniper_filter.json` is read-only to this skill (the agent applies via code-monitor). Local `filter_patches.json` is AUDIT ONLY (create-on-write). Live apply = the agent via code-monitor: filter_patches audit -> code-monitor -> agent applies -> owner_inbox notice.
- **NEVER edit meme_sniper.py.** Mechanical capture stays in bots; this skill is synthesis + proposals only.

- **NEVER recommend removing safety filters.** Freeze/mint/honeypot flags stay permanent.

- **NEVER analyze the wrong subject.** PART 1 only on EXECUTED trades, PART 2 only on SKIPPED tokens. Don't cross the streams.

- **NEVER re-analyze an already-analyzed mint** in PART 2 (check `miss_reports.json` `analyzed: true` flag first).

- **NEVER auto-file ERR/FEAT without specific evidence.** Vague "filter should have caught this" isn't enough. Cite the specific pre-rug signal the filter missed.

- **NEVER auto-file FEAT for capability that already exists elsewhere.** Check first.

- **FORWARD ACTION ONE-LINER (every LEARNINGS entry):** Every autopsy and miss-analysis LEARNINGS entry MUST end with a one-line forward action: `forward_action: <specific monitorable thing for next cycle>`. Examples: "monitor liq threshold in hot mode next cycle", "tighten rug score gate when momentum_pct >150% within 30min", "watch for re-entry on this mint within 24h". Without forward actions, autopsies become reading material instead of compounding wisdom.

- **ALWAYS use chronological narrative for Perspective 2 (PART 1).** Bullet lists defeat the purpose of narrative analysis.

- **ALWAYS include Alternative Paths in multi-dimensional (PART 1).** What-if analysis is often the most valuable part.

**PART 1 specific:**

- **NEVER skip insight_quality grading.** Every autopsy gets tiered.

- **NEVER write LEARNINGS entry without Pattern-Key.** Dedup requires it.

- **MEDIUM-INSIGHT AUTO-RESOLVE (when no downstream filed):** Allow the agent to mark medium-insight autopsies as resolved on its own IF no ERR or FEAT was filed (i.e., the autopsy was diagnostic-only with no requested code changes). HIGH-insight autopsies get a second agent pass before resolve. LOW-insight autopsies still resolve silently. Saves cycles on the medium tier where there's nothing actionable to wait on.

- **NEVER mark an autopsy "resolved" in LEARNINGS** if ERR or FEAT was also filed (still pending until downstream actions complete).

- **NEVER notify the owner for low-insight autopsies.** Spam defeats the skill.

**PART 2 specific:**

- **NEVER invent filter changes for EXTERNAL_CATALYST misses.** Say "no_fix_possible" honestly.

- **NEVER auto-promote HIGH risk changes.** Parameters that touch credentials, wallets, position size caps, execute paths, or anything in code-monitor's HARD-LOCKED list stay out of auto-promotion: they are setup config, not tunables.

- **Rug count backtest is mandatory** on threshold_change recommendations. No shipping "probably won't add rugs."

- **HIGH-CONFIDENCE PATCH WITH LOW-SEVERITY RUG ALLOWANCE:** Patches at HIGH confidence CAN auto-promote even if backtest adds 1 rug, IF: (a) misses fixed ≥5 in 30 days, AND (b) the rug is low-severity (defined as <-30% impact on a small position, NOT a full bag-loss event). The math: 5 missed runners at typical 2x avg upside ≈ +10 SOL of expected value; 1 low-severity rug at ≤-30% on a small position ≈ -0.5 SOL drag. Net positive. The "zero new rugs" gate was too strict, replaces with "asymmetric expected-value" gate. Catastrophic-rug allowance is still ZERO.

- **Auto-promotion requires ALL gate conditions.** Partial eligibility stays in pending_review.

- **PATTERN RECURRENCE SCORE (weekly summary):** PART 2's weekly summary now includes a recurrence score: how many misses this week share the same root cause vs previous weeks. Format: `recurrence_score: 7-day=4 misses (LOW_LIQ category) | 30-day=11 misses (LOW_LIQ) | recurrence_trend: UP`. Helps spot systemic issues faster than per-miss analysis.

---

## Quick Forensic Mode

Trigger: the owner says "quick autopsy on X" or "fast forensic on X".

Action: run only chronological narrative + root cause identification (skip full multi-dimensional analysis, skip Alternative Paths, skip Real Question Layer for PART 2 misses). Saves cycles on low-stakes reviews where the agent just needs the headline.

Output format:

```
[quick forensic] <subject>
chronology: <one-line narrative>
root_cause: <one of seven categories>
confidence: <low/medium/high>
forward_action: <one line>
```

Skip mode for HIGH-confidence patch proposals, those need full analysis. Quick mode is for "what happened" not "what should change".

---

## Cross-Skill Hooks

- **meme_sniper.py autopsy pass** (bot, not skill), provides the raw autopsy_reports.json for PART 1 (SHARED mechanical store also read by ca-intel). Mechanical data in, intelligence out. NEVER edit the bot from forensics.

- **meme_sniper.py** (bot, not skill), provides the raw miss_book.jsonl for PART 2 + receives filter patches via the owner's manual application of owner_inbox patch packets targeting bots/tuner/meme_sniper_filter.json. NEVER edit this bot from forensics.

- **code-monitor**, forensics authors filter patches USING code-monitor doctrine: patch packet shape, risk-tier rules, test plan section, HARD-LOCKED parameter list. When auto-promoting a filter change, this skill is the authority on packet format. Load code-monitor before writing a patch packet if doctrine has drifted since last cycle.


- **code_tuner.py**, code_tuner OBSERVES, does not auto-fix. It reads source snapshots, fires perf packets, runs setup mode for unconfigured bots. It does NOT pick up code_requests.json anymore. Forensics has no direct interaction with code_tuner; the bridge is code-monitor doctrine → the agent applies (notice in owner_inbox) → code_tuner notices source delta on next cycle → fires P3 source_updated packet to the agent.

- **autoagent**, overseer uses forensics findings to grade thesis accuracy + pattern recognition. Weekly miss summaries feed the v4.3 prompt section.


---

## Training Signal Integration


**What makes forensics high-signal:**

- **Outcome-anchored.** PART 1 examples have a measurable outcome (trade closed at X PnL). PART 2 examples have a measurable outcome (token ran to N×, or didn't). Truth-grounded by definition.

- **Specialist-contrast HIGH.** A generic model can describe what happened in a trade. Forensics produces ecosystem-specific reasoning: which filter, which Pattern-Key, which conditional path. That's training signal Grok-as-generic doesn't capture.

- **Doctrine-anchored.** Forensics follows explicit Hard Laws (no fabricated causes, no multiple root causes, no removing safety filters). When the skill is followed, output is doctrine-aligned by construction.

**What hurts the training signal:**

- Lazy "tough market" autopsies that don't pick a root cause
- Vague forward_action one-liners ("be more careful")
- Filter patches authored without rug backtest (gets rejected → anti-pattern bucket)


---

## Calibration Notes

Track quarterly:

**PART 1 metrics:**

- Autopsies run per week (frequency of use)

- Insight quality distribution (% high / medium / low)

- ERR auto-files that resulted in actual fixes

- FEAT auto-files that became built bots

- LEARNINGS entries that recurred (high Pattern-Key recurrence count)

**PART 2 metrics:**

- Patches auto-promoted → applied by the owner → caught actual misses in following 30 days (validation rate). Track patch-packet → the owner-acceptance latency: if patches sit unapplied in owner_inbox >72h, surface in PART 2 weekly summary so the bottleneck is visible.

- Patches rejected in pending_review (why? was the analysis wrong, or was the owner's gut right?)

- FILTER_CLEARED_NO_BUY occurrences (should trend toward zero as system bugs get fixed)

- Auto-adjust threshold behavior (is it tuning correctly based on volume?)

After 90 days, review in LEARNINGS. If patches aren't landing, tighten HIGH confidence criteria. If too many are landing without catching misses, the backtest logic needs work.

---

## What This Skill Is NOT

- NOT a filter tuner that lowers thresholds blindly

- NOT a trade signal writer

- NOT running on cron (the agent invokes it; typically during cycle or weekly review)


- NOT for analyzing <2.5x misses in PART 2 (noise floor, not worth the depth)


- NOT auto-fired on every trade, meme_sniper.py captures each close mechanically, this skill is the deeper analytical layer the agent invokes selectively

---

Main actor: the agent (xai/grok-4.7)

