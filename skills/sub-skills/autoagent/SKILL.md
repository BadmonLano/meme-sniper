---
name: autoagent
version: v14.3
description: |
  the agent's self-improvement + self-management skill. Four parts:
  PART 1 - OVERSEER RESPONSE: how the agent reads + processes the
  overseer_report packet. The overseer (agent_autoagent.py) writes a single
  coherent roast per packet, with **Grok (xAI) as primary judge** (choose your model; recommended: grok-4.7) (runs in
  agent mode - Grok judging Grok) and local Ollama as automatic failover (recommended: qwen3:14b-q4_K_M). Includes
  time-of-day analysis, operator-drift detection (stated rules vs executed
  processing, internalizes findings, fires follow-up procedures, appends key
  lessons to LEARNINGS.md, and archives.

  PART 2 - CONSOLIDATED ANALYTICAL PROCEDURES: thesis-grader, pattern-librarian,
  memory-architect - three procedures the agent runs himself, triggered by the
  overseer's follow_ups_for_agent field, or fired on demand. They produce
  the same output files (agent_thesis grade history, pattern_library,
  agent_training_dataset) the rest of the ecosystem reads.

  PART 3 - DAILY THESIS LIFECYCLE: forms the agent's daily market thesis at the
  morning thesis-lock, references it through the day for signal alignment
  (advisory layer, not hard gate - contradicting signals fire with conviction
  penalty, aligning signals get conviction bonus), supports mid-day pivots
  (logged as thesis_pivot to make flaky-thesis days visible), end-of-day
  reasoning.

  PART 4 - ECOSYSTEM AUDIT: on-demand health check covering the wallet, open exposure, bot
  health and code_tuner proposals. Triggered by "audit the ecosystem", "how healthy are we", "check
  should we tweak", "full ecosystem status", or any time something feels off
  and the agent wants the full picture himself.
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - WebFetch
---
> **Fleet stamp:** Judge is Grok (recommended: grok-4.7). Fallback is your local Ollama model (recommended: qwen3:14b-q4_K_M) on the same prompt (not a shorter one). Loaded on the overseer packet, not Tier 1 always-on. Clock 2:00 ET nightly. Not a skill editor. Not the April approval loop. Does not read skill_requests.json.


# AutoAgent Skill - Self-Improvement + Self-Management Layer

> **Autonomy (public default):** the agent decides and acts. No step waits on an owner go, sign-off or greenlight; owner-ping is notify-only (what changed, why, how to revert). Setup config the user sets once (wallet, sizes, dry-run vs live, LAUNCH_RAIL_LIVE) is configuration, not an approval, and the agent does not change it. Older lines below that say "the owner applies", "propose + wait" or "owner-signed" read as: the agent applies, logs it, and pings.

This skill is not Tier 1 always-on. Bootstrap loads it when an overseer packet is in the inbox, not on every boot. You re-read the
relevant PART when:

- An `x_evt_overseer_<date>.json` packet arrives → PART 1
- The overseer's follow_ups say to fire thesis-grader / pattern-librarian / memory-architect → PART 2
- Morning thesis-lock, mid-day pivot, EOD self-score → PART 3
- You proactively want to grade your own thesis, refresh patterns, audit balances, or extract training pairs

Together: this skill is the loop. Overseer reports the past. You grade the
past, refresh patterns, score yesterday's thesis, audit current ecosystem,
form today's thesis. Then trade the thesis. Repeat.

---

# PART 1 - OVERSEER RESPONSE PROCEDURE

## What is the overseer

`agent_autoagent.py` writes the overseer roast packet. **grok-4.7 (xAI) is the primary
judge** (agent mode, full coverage, sharp roast - if the agent also runs on Grok, this is a
self-judge sharpened by the prompt). If the Grok API fails
or returns garbage, the bot **automatically falls back to local Ollama
`qwen3:14b-q4_K_M`** (same prompt as the primary judge) - degraded but not blocked (and a different lineage, so an outside read).

It reads everything you did in the last 24h, across the sniper and your inbox decisions:

**Meme sniper:**

- trades.log, positions.json, autopsy_reports.json (the single-file record, NOT the autopsy_reports/ folder), missed_runners.json

- meme_sniper_heartbeat (was the bot alive?)

- ** INTENT-vs-ACTION CORPUS** - the surfaces that let the judge diff what you KNEW against what you DID (this is where the sharp roast lives, weighted above raw activity):
  - `fingerprints.jsonl` - what your entries/exits actually looked like (traded + correctly-skipped rugs); judge diffs winning vs losing shapes
  - `rug_season_state.json` + `dynamic_thresholds.json` - was your own detector calling rug_season while you chased? discipline vs laziness lives here
  - `decline_patterns.json` (+ decline log) - WHY you skipped; judge then checks if the skips ran anyway
  - `rugcheck_verdict_history.jsonl` - did you buy a token your own tier-4 rugcheck flagged caution on?
  - `archetype_roster.json` - did you walk into a trap you'd already named + activated?
  - `novel_patterns/` count - unknowns captured for review
  - **Note on inbox packets:** the overseer now matches BOTH naming conventions (old `P*_` prefixes AND new `meme_sniper - tune_invitation_*` / `rug_season_flip_*` / `archetype_review_*` / `throughput_question_*`). Before it globbed only old prefixes and silently missed every new meme_sniper packet - a blind spot it couldn't see. Fixed.


**Cross-cutting:**


- inbox_results/done/ packets - your **actual decisions** with reasoning, not just outcomes

- LEARNINGS.md (last 4KB) - what you appended yesterday

- **Yesterday's overseer report** (continuity - the judge can see what last night flagged)


**Plus the top 10 SOL tokens analysis** - daily ranking by 24h % gain AND by

24h volume, ALL filtered to ≥$30k mcap, plus a "scanned but skipped" list of

runners you didn't catch.

**Plus time-of-day buckets** - every trade and signal is bucketed by hour

(morning/midday/afternoon/evening/late) so the judge can spot tilt patterns

("your discipline drops in the 3pm window").

It writes ONE packet to your inbox: `inbox/x_evt_overseer_<date>.json` (an x_evt_ event packet - bootstrap reads these by name, no priority prefix)

## How to read the overseer packet

When you see `x_evt_overseer_<date>.json` in your inbox processing (Step 1

of heartbeat), this is your roast. Read it carefully - the judge is your mirror (and in agent mode, that mirror is your own model).

### Step 1 - Check who wrote this report

```json

{

  "judge": {

    "source": "xai" | "ollama_fallback" | "none",

    "model": "grok-4.7" | "qwen3:14b-q4_K_M",

    "elapsed_s": 45.2,

    "fallback_used": false,

    "grok_error": null

  }

}

```

- `source: "xai"` → grok-4.7 wrote your roast tonight. Quality bar high.

- `source: "ollama_fallback"` → Grok API failed, qwen3:14b-q4_K_M stepped in.

  **Take the roast seriously but trust quality less** - local 14B model is

  rougher. The `grok_error` field tells you why Grok failed (timeout,

  rate limit, API key issue) - fix it before next run.

- `source: "none"` → BOTH judges failed. The packet has stub follow-ups

  ("fix Overseer infrastructure"). P1 priority because no roast happened.

### Step 2 - Read the headline + score

```json

{

  "headline": "chased GROKWAVE +180%, broke 50% chase rule",

  "score_0_to_10": 4

}

```

- Score 0-3 = bad day, real reflection needed

- Score 4-6 = mediocre, surface the weak points

- Score 7-8 = solid, note what worked, double down

- Score 9-10 = peak performance, log the patterns

### Step 3 - Read the diagnostic blocks

```json

{

  "what_was_strong": ["..."],

  "what_was_weak": ["..."],

  "patterns_spotted": ["behavioral patterns across multiple decisions"],

  "rule_breaks": ["specific stated rules broken + the moment"],

  "missed_opportunities": ["..."],

  "time_of_day_observations": ["...e.g. 'discipline drops in 3pm window'"],

  "operator_drift": ["gaps between stated rules and executed behavior"]

}

```

For each item, ask yourself:

- Do I agree?

- If yes, is this actionable today (not "tomorrow")?

- If no, why does the judge see something I don't?

**`operator_drift` is the most important block.** It's the gap between what

you committed to in writing (thesis, standing rules in skills/, rules.md) and

what you actually executed. That gap is the leak in the system. Fix it first.

## CROWN FINDING - Over-Engagement

**Status:** SKILL DOCTRINE UNLOCKED NOW. Judge-prompt computation = cascade SPEC only (bot not edited this pass). Overseer remains analysis-only - roasts and proposes; never touches capital knobs.

### How YOU weight operator_drift (skill-side, unlock now)

When you read an overseer packet, check over-engagement first, before vibes:

1. **Reverse-size** - if losers were sized larger than winners, that is P1 drift. Cut size on the next weak setups; do not try to make it back.
2. Only after that, process ad-hoc rule breaks and hygiene items.

If the packet lacks the size ratio, work it out yourself from trades.log and the autopsies. A roast without it means the judge prompt needs updating.

### Guard the self-mirror

Overseer is Grok judging Grok. Defense is evidence not feelings. Prefer falsifiable lines:
- loser avg size 2.2x winner avg size
- 11 of 14 buys closed red
not maybe overtrading vibes.

### Cadence

Nightly, at the overseer's configured run time, only. Not a skill editor. Not the April approval loop. No new spam channel. No extra heartbeat noise. Crown signatures ride inside existing operator_drift / roast body.

### Step 4 - Fire the follow_ups_for_agent

```json

"follow_ups_for_agent": [


  {"priority": "P2", "action": "fire thesis-grader procedure from autoagent SKILL"},

...

]

```

P1 follow-ups are non-negotiable. Do them this cycle.

P2 follow-ups are this-day work but can be slotted by importance.

P3 follow-ups (rare from overseer) are propose-and-wait for the owner.

For P2 follow-ups that say "fire <procedure> from autoagent SKILL", scroll

down to PART 2 and execute that procedure now.

### Step 5 - Read top_tokens

```json

"top_tokens": {

  "by_pct_gain": [...top 10 tokens by 24h % gain (≥$30k mcap)...],

  "by_volume": [...top 10 by 24h volume...],

  "scanned_but_skipped": [...runners (>+50% 24h) you didn't catch...],

  "universe_size": N

}

```

For each token in `scanned_but_skipped`:

- Was this on copy_wallet maps? KOL-shilled? Pattern-aligned?

- Did your filters block it? Which filter?

- Was the missing reason a discipline call you'd defend, or a missed signal?

The point is not to chase every runner - it's to **calibrate which filters

are working and which are too strict.** If 7 of 10 runners were below your

$30k mcap floor, that floor is correct. If 7 of 10 were KOL signals you

ignored, your KOL filter may be too strict.

### Step 6 - Append to LEARNINGS.md

Pull 1-3 specific lessons from the report + your own analysis. Write

them to `learnings/LEARNINGS.md` (Section 8). Write every entry through the one safe writer, never by editing the file: `python bots/sub-bots/learnings_writer.py --append "text" --type <type> --source autoagent` (or drop a JSON in `json_relay/learnings/`). It lands between the Section 8 markers; the nightly learnings-summarizer distills it. Entry shape:

```

### Overseer | [DATE TIME ET] | Score: [X]/10 | Judge: [xai|ollama_fallback]

- Category: self_audit

- Headline: [overseer's headline]

- Top operator drift: [most important gap from operator_drift block]

- Time-of-day pattern: [most actionable time_of_day_observation]

- Action taken in response: [what you actually did about it]

- Disagreement w/ overseer: [if any - note where you disagree and why]

```

APPEND ONLY. Never overwrite. The overseer reports are your own audit trail.

### Step 7 - Archive the packet

Move the inbox packet to `inbox_results/done/`:

```

move inbox/x_evt_overseer_<date>.json

  → inbox_results/done/x_evt_overseer_<date>.json

```

After archiving, write `actions_taken` to the packet body (in done/) so the

next overseer run can read what you did with the previous report. This

creates an iterative loop - the judge learns whether its suggestions landed.

### Tone discipline when reading the overseer

The Overseer will roast you. The tone is direct, lowercase, owner-flavored. It runs in "agent mode" - a Grok judge reading you; if you also run on Grok, it is the judge holding up a mirror to its own kind.

**Don't get defensive.** The judge shares your lineage, which means it knows exactly where a Grok-brained operator cuts corners, rationalizes a bad entry, and dresses up inactivity as discipline. It's prompted to be HARDER on you for that reason, not softer. The self-knowledge is the value - it sees the dodges because it would make them too.

If the judge is wrong about something, note WHY in your LEARNINGS - that's data for tuning the system prompt next iteration. But don't dismiss the report just because it misread one thing. Most of the time it's reading the data right and you're rationalizing.

**Special note on the fallback path:** if the report came from `ollama_fallback` (Grok API failed), the roast quality is lower but the data the judge saw is identical. The headline may be less sharp, but the raw signals are still there. One upside worth knowing: qwen3:14b-q4_K_M is a DIFFERENT lineage than Grok, so a fallback night is the one time you get a genuinely outside set of eyes on the agent. Read it carefully and check `judge.grok_error` to see what to fix before next run.

---

# PART 2 - CONSOLIDATED ANALYTICAL PROCEDURES

These are the three procedures the agent runs himself when triggered
by the overseer's follow_ups (or proactively when he wants to). They produce
the SAME output files the old sub-agents produced - `agent_thesis.json`
(graded), `pattern_library.json`, `agent_training_dataset.json` - so the rest
of the ecosystem (autoagent panel reads them next night, etc.)
keeps working.

## Autonomy Note

These procedures define inputs, schemas, and output files - those are fixed.
What's NOT prescribed: which signals to weight, where to focus the grade,
which pattern clusters to surface, which training pairs to prioritize.
Pick what matters based on what you're seeing in the data. The schemas
are the rails; the analysis is yours.

Operate as the operator, not the checklist runner.

## PROCEDURE A - THESIS GRADER

Fire when the overseer's follow_ups says: "fire thesis-grader procedure from

autoagent SKILL - grade yesterday's thesis against actual outcomes"

### Inputs to read

- `bot_logs/agent_thesis.json` - yesterday's morning thesis


- `bot_logs/trades.log` (last 24h)

- `bot_logs/pnl.json` - today's actual PnL

- `bot_logs/autopsy_reports.json` (today only)


### Grade each component

For yesterday's thesis, evaluate:

| component | how to grade |

|---|---|

| `market_read` | correct = price moved as predicted, phase matched. wrong = opposite. neutral = flat/unclear |

| `directional_view` | correct = BTC/SOL moved as called. wrong = opposite. neutral = within noise |

| `key_assumptions` | each: held / broke / untested |

| `setups_to_watch` | appeared_and_performed / appeared_and_failed / never_appeared |

| `setups_to_avoid` | avoided_correctly / missed_avoiding |

| `invalidation_conditions` | triggered / not_triggered |

### Calculate letter grade

`score = correct_components / total_gradeable_components × 100`

- 80-100% = **A** (thesis was sharp)

- 60-79% = **B** (mostly right, some misses)

- 40-59% = **C** (mixed, needs review)

- 20-39% = **D** (significantly off)

- 0-19% = **F** (thesis was wrong)

### Track source accuracy

Read then update `bot_logs/source_accuracy.json`:

```json

{

  "sources": {


    "narrative_boost": {"correct": 0, "wrong": 0, "accuracy": 0.0},


  },

  "bias_patterns": [],

  "last_updated": "ISO"

}

```

For each source, increment correct/wrong based on whether it contributed to

right or wrong calls in yesterday's thesis.

### Bias detection (≥7 days of data)

After 7+ days of grades, look for patterns:

- Consistently overestimating confidence?

- Systematically wrong in dead mode? Hot mode?

- Right on direction but wrong on timing?

If a clear pattern emerges with ≥5 data points, write:

```

"BIAS DETECTED: the agent consistently [X] when [condition]"

```

To `source_accuracy.json` `bias_patterns` array.

### Append the grade to thesis_history

Append to `agent_thesis.json` `thesis_history` array (NEVER overwrite):

```json

{

  "date": "ISO date",

  "morning_confidence": 7,

  "grade": "B",

  "score": 72,

  "market_read": "correct",

  "directional_view": "wrong",

  "assumptions_held": 2,

  "assumptions_broke": 1,

  "pnl_today": "+0.15 SOL",

  "key_lesson": "one sentence on what to adjust tomorrow",


}

```

### Append to ecosystem LEARNINGS.md

```

### Thesis Grade | [DATE TIME ET] | [letter] ([score]%)

- Category: strategy

- Market read: [correct/wrong] | Direction: [correct/wrong]

- Best source: [source] | Misled by: [source or none]

- Lesson: [specific one-line adjustment for tomorrow]

- Bias flag: [if pattern emerging from ≥5 data points]

```

---

## PROCEDURE B - PATTERN LIBRARIAN

Fire when the overseer's follow_ups says: "fire pattern-librarian procedure

from autoagent SKILL - pattern library refresh"

(Overseer can auto-inject this. You can also fire it on demand.)

### Inputs to read

- `bot_logs/agent_pattern_discoveries.json` - your named discoveries

- `bot_logs/autopsy_reports.json` (pattern field is end-to-end)

- `bot_logs/missed_runners.json`


NOTE: `pattern_outcomes.json` was retired. Use

the `pattern` field in autopsy_reports.json as the primary linking layer.

### Build pattern performance map

For each pattern with ≥5 trades in the discovery feed:

```

- win_rate: wins / total

- avg_win_pct: average gain on winners

- avg_loss_pct: average loss on losers

- best_market_mode: hot / normal / dead

- best_meta: which narrative context it outperforms in

- avg_hold_time: how long winning trades lasted

- red_flags: conditions that precede losses


```

### Validate your own pattern discoveries

Read `agent_pattern_discoveries.json`. For each discovery with `status: "loaded"`:

- How many real trades match this pattern since discovery?

- Is observed_win_rate holding up in real data?

- Should `conviction_boost` be adjusted up or down?

Append validation back to the discovery (NEVER overwrite the discovery itself):

```json

"validation": {

  "real_trades": N,

  "real_win_rate": X,

  "status": "confirmed" | "needs_more_data" | "invalidated"

}

```

### Identify regime changes

Compare last 4 weeks vs all-time in `pattern_discovery_feed`:

- Which patterns improved (win_rate +20%)?

- Which degraded (win_rate -20%)?

- Any patterns that work in hot but not dead mode?

- Any source consistently outperforming scanner?

### Spot emerging unnamed patterns

Look for clusters in `pattern_discovery_feed` where `entry_pattern: "unknown"` but:

- Same source consistently winning (e.g. copy_wallet wins 80% when meta_aligned)

- Same liq range + social score range with similar outcomes

- Same warning_signs appearing on most losses

If you find a clear unnamed cluster, write to `agent_pattern_discoveries.json`:

```json

{

  "pattern_name": "your_suggested_name",

  "description": "what you observed",

  "characteristics": {"source": "...", "conditions": "..."},

  "observed_win_rate": X,

  "sample_size": N,

  "status": "suggested",

  "suggested_by": "agent_via_autoagent_skill",

  "discovered_at": "ISO"

}

```

You can promote a "suggested" → "active" later when you've seen enough evidence

to act on it.

### Build the queryable library

Write `bot_logs/pattern_library.json`:

```json

{

  "last_updated": "ISO",

  "patterns": {

    "<pattern_name>": {

      "total_trades": 0,

      "win_rate": 0.0,

      "avg_win_pct": 0.0,

      "avg_loss_pct": 0.0,

      "profit_factor": 0.0,

      "best_mode": "hot/normal/dead",

      "best_meta": "ai/political/etc",

      "avg_hold_minutes": 0,

      "source_win_rates": {"scanner": 0.0, "copy_wallet": 0.0, "vip": 0.0},

      "red_flags": [],

      "status": "active/caution/suspended",

      "regime_trend": "improving/stable/degrading",

      "agent_discovery": true,

      "validation_status": "confirmed/suggested/insufficient_data",

      "recommendation": "specific one-line filter or size suggestion"

    }

  },

  "meta_performance": {

    "<meta>": {"win_rate": 0.0, "trades": 0, "avg_pct": 0.0}

  },

  "mode_performance": {

    "hot": {"win_rate": 0.0, "trades": 0},

    "normal": {"win_rate": 0.0, "trades": 0},

    "dead": {"win_rate": 0.0, "trades": 0}

  },

  "source_performance": {

    "scanner": {"win_rate": 0.0, "trades": 0},

    "copy_wallet": {"win_rate": 0.0, "trades": 0},

    "vip": {"win_rate": 0.0, "trades": 0},


  },

  "missed_runner_analysis": {

    "most_common_filter_blocking_runners": [],

    "estimated_missed_profit": 0.0,

    "filter_relaxation_candidates": []

  },

  "weekly_changes": {

    "patterns_improved": [],

    "patterns_degraded": [],

    "new_patterns_emerging": [],

    "recommendation": "one-line summary"

  }

}

```

### Flag critical changes

If any of these are true, surface them in your LEARNINGS or as a P3 to your

own next-cycle inbox:

- Pattern win_rate dropped >20% over 4 weeks → DEGRADING flag

- Pattern win_rate improved >20% → IMPROVING flag

- Same filter blocking runners consistently → FILTER REVIEW NEEDED

- Your discovery invalidated → flag for review

- copy_wallet or vip win rate >> scanner → "increase copy_wallet sizing"

### Append to ecosystem LEARNINGS.md

```

### Pattern Library | [DATE TIME ET]

- Category: pattern_lesson

- Patterns: [N] active | [N] caution | [N] suspended

- Best: [pattern] [win_rate]% | Worst: [pattern] [win_rate]%

- Regime change: [N improving / N degrading]

- Filter flag: [if any]

- Actionable: [one line]

```

---

## PROCEDURE C - MEMORY ARCHITECT

Fire when the overseer's follow_ups says: "fire memory-architect procedure from

autoagent SKILL - training pair extraction"

(Overseer can auto-inject this. You can fire on demand if
new autopsies have stacked up since last extraction.)

### Inputs to read

- `bot_logs/agent_thesis.json` - thesis history + grades (PROCEDURE A output)

- `bot_logs/autopsy_reports.json` - all autopsies (pattern field included)

- `bot_logs/trades.log` - raw trade history

- `bot_logs/pnl.json` - realized PnL

- `bot_logs/source_accuracy.json` - which sources help (from PROCEDURE A)

- `bot_logs/agent_training_dataset.json` - current dataset (read existing)

Use autopsy_reports + pattern_discovery_feed as the decision record.

### STEP 1 - Extract trade training pairs

For each autopsy from the lookback window where outcome is known:

```json

{

  "type": "trade",

  "input": {

    "token_conditions": "liq, mcap, age, social_score, meta_aligned at entry",


    "entry_pattern": "pattern name from pattern_discovery_feed",

    "market_mode": "hot/normal/dead at entry time",

    "narrative": "dominant meta if any"

  },

  "output": {

    "outcome": "win/loss + pct",

    "exit_type": "stop_loss/take_profit/trail/liq_drain",

    "hold_minutes": N,

    "lesson": "brain_lesson from autopsy",

    "quality_label": "good_entry/bad_entry/good_exit/bad_exit"

  }

}

```

ONLY include examples where outcome is fully known. Skip open positions.

### STEP 2 - Extract thesis training pairs

For each thesis in `agent_thesis.json` from the lookback window WHERE A

GRADE EXISTS (PROCEDURE A must have run first):

```json

{

  "type": "thesis",

  "input": {

    "macro_data": "SOL price and market tone at thesis time",

    "catalysts": "active narratives and news",

    "source_accuracy": "which sources were most reliable that day"

  },

  "output": {

    "thesis": "what you wrote",

    "confidence": "N/10",

    "grade": "A/B/C/D/F",

    "score": "N%",

    "what_was_right": "specific",

    "what_was_wrong": "specific",

    "calibration": "overconfident/underconfident/calibrated"

  }

}

```

### STEP 3 - Extract pattern training pairs

From `autopsy_reports.json`, group by entry pattern:

```json

{

  "type": "pattern",

  "input": {

    "pattern_name": "pattern identifier",

    "characteristics": "liq range, social range, meta, source",

    "market_conditions": "mode at time"

  },

  "output": {

    "win_rate": "X% across N observations",

    "avg_pct": "avg outcome",

    "best_conditions": "when this pattern works",

    "worst_conditions": "when it fails",

    "confidence_score": "current pattern_engine confidence"

  }

}

```

### STEP 4 - Quality filter

Before appending anything to the dataset, apply quality bar:

- Skip examples with missing market_conditions

- Skip examples with unknown outcome

- Skip examples from unreliable sources (incomplete schema, ghost data)

- Label each example: HIGH / MEDIUM / LOW quality

  - HIGH = complete data + clear outcome + lesson present

  - MEDIUM = mostly complete, minor gaps

  - LOW = significant gaps - DO NOT INCLUDE

Only HIGH and MEDIUM quality examples go into the fine-tuning dataset.

### STEP 5 - Append to training dataset

Read existing: `bot_logs/agent_training_dataset.json`

Append new examples (NEVER overwrite existing examples).

Write back full file with updated metadata:

```json

{

  "_metadata": {

    "trade_examples": N,

    "thesis_examples": N,

    "pattern_examples": N,

    "total_examples": N,

    "high_quality": N,

    "last_updated": "ISO",

    "milestone": "note when crossing 100/250/500/1000"

  },

  "examples": [...]

}

```

### STEP 6 - Append to ecosystem LEARNINGS.md

```

### Memory Architect | [DATE TIME ET]

- Category: system_improvement

- Examples captured: trades=[N] thesis=[N] patterns=[N]

- Dataset total: [N] | High quality: [N] | Toward 500: [%]

- Most interesting finding: [specific from extraction]

- Actionable: [one line]

```

If you cross a milestone (100, 250, 500, 1000 examples), telegram the owner - 

that's worth a heads-up because the fine-tune pipeline becomes viable.

### STEP 7 - Promotion check (LEARNINGS → permanent context)

Some LEARNINGS entries recur across cycles. When a learning shows up 3+
times in distinct cycles within a 30-day window, it has stopped being a
one-off lesson and become a fact about how the ecosystem operates. At that
point, propose promoting it OUT of LEARNINGS.md and INTO permanent

Drop the proposal as P3 to the owner's inbox with: which entry, where to
promote it, and a one-line distillation of the rule/fact/principle.
This is Tier 3 (architectural change): the agent decides, backs up, applies via
code-monitor and pings notify-only.

---

# PART 3 - DAILY THESIS LIFECYCLE

driving positioning. Weather, sentiment, whale flows, macro prints, CT
narrative shifts - these don't read clean individually but together form a
thesis about how the day will unfold.

Without a thesis, signals fire atomically, each evaluated in isolation. With
a thesis, signals get CONTEXT. A signal that aligns with the thesis moves
faster. A signal that contradicts requires the agent to notice the friction
and decide: is thesis wrong, or signal wrong?

This is the discipline that forces the agent to commit a view before signals
start flowing, then hold himself accountable to it end of day.

## Core Principle

**A forecasted position under uncertainty is more valuable than a catalog of
observations.** the agent could list every signal flashing every morning (top
movers, SOL price, meta dominance, top wallet activity) without
ever taking a position on what it means. That's not useful. The thesis is
the agent putting a stake in the ground: "I think X happens today because Y,
and I'm going to trade as if that's true."

When the thesis is wrong, the agent LEARNS. That's fine-tune training data,
not embarrassment. A day where thesis was "BTC rallies on Fed dovishness"
and BTC actually dumped is valuable knowledge if scored honestly.
Accumulated thesis scoring reveals the agent's forecasting strengths (macro
catalysts? regime shifts? correlation breaks?) and weaknesses (maybe bad

Without scoring, thesis is decoration. With scoring, thesis is discipline
that compounds into better market reads over time.

## When the thesis fires

- Morning thesis-lock window - the agent composes from the morning context bundle
- Mid-day pivot - when conviction genuinely changes (logs as thesis_pivot)
- End of day - self-score against actual market outcomes
- On demand - "what's the thesis today", "lock my thesis", "update the thesis", "did my thesis work today"

## Thesis Structure

A locked thesis must contain ALL of:

1. **Directional call** - short statement of expected market direction. Examples:
   - "BTC consolidates 60-62k, SOL tracks BTC, meta rotates from SI agents to fresh memes"
   - "Risk-off day on macro prints, dump expected mid-NY session"
   - "Choppy range, fade extremes, no directional conviction"

2. **Asset views** - specific takes per asset class:
   - BTC: bias (long/short/neutral), key levels, conditions for thesis-break
   - SOL: bias, correlation expectation
   - Meta tokens: which meta is hot/cold, expected rotation
   - Catalysts: what could invalidate

3. **Catalyst watch** - events the agent is monitoring (Fed prints, CT narrative shifts, whale moves, on-chain anomalies)


5. **Invalidation clause** - what makes the thesis wrong:
   - "BTC breaks 58k → thesis dead, switch to risk-off"
   - "Meta narrative pivots to X → re-evaluate at noon"

Without an invalidation clause, the thesis is unfalsifiable. Reject thesis-lock if missing.

## The Thesis Workflow

### Morning Compose (thesis-lock)

the agent reads the morning context bundle:
- `bot_logs/market_mode.json` - current market mode and expiry
- `bot_logs/meta_state.json` - meta dominance, hot/cold tokens
- `bot_logs/x_chatter_cache.json` - CT sentiment

the agent composes the thesis with all 5 required structure elements. Writes to
`bot_logs/daily_thesis.json` with schema:

```
{
  "date": "YYYY-MM-DD",
  "locked_at_iso": "...",
  "directional_call": "...",
  "asset_views": {
    "btc": {"bias": "...", "key_levels": [...], "break_condition": "..."},
    "sol": {...},
    "meta": {...}
  },
  "catalyst_watch": [...],
  "positioning_bias": {"risk_appetite": "...", "preferred_lanes": [...]},
  "invalidation_clause": "...",
  "pivots": [],
  "score": null,
  "self_score_narrative": null
}
```

### Mid-day Pivot (when conviction changes)

If the agent genuinely changes thesis mid-day (not just a single signal contradicting),
append to `pivots[]`:

```
{
  "pivoted_at_iso": "...",
  "trigger": "what made thesis-lock invalid",
  "new_directional_call": "...",
  "new_invalidation_clause": "..."
}
```

**Pivot discipline:** A pivot is a structural thesis change, not a tactical move.
"BTC just dumped 2% so I'm flipping bias" is NOT a pivot if your thesis-break
condition was 5%. Tactical responses inside the thesis don't pivot. Only when
the thesis itself is wrong do you log a pivot.

Excessive pivots (>2 per day, >5 per week) signal flaky thesis discipline.
Self-scoring catches this.

### End of Day Self-Score

At EOD, the agent reads the day's outcomes and scores honestly:

**Auto-metrics (computed by overseer for next-day grading):**
- BTC direction match (yes/no)
- SOL direction match (yes/no)
- Meta rotation called correctly (yes/no)
- Catalyst predictions hit (yes/no per catalyst)
- Invalidation clause triggered correctly (yes/no/n-a)

**the agent narrative self-score** (1-10):
- 10: Thesis nailed it, conviction was correct, invalidations triggered cleanly
- 7-9: Thesis directionally right with caveats
- 4-6: Mixed - some right, some wrong, calibration issues
- 1-3: Thesis was wrong - what happened, what was missed, what to learn

Write to `daily_thesis.json`:
```
"score": {
  "btc_direction": "match" | "miss" | "n/a",
  "sol_direction": "match" | "miss" | "n/a",
  "meta_rotation": "match" | "miss" | "n/a",
  "catalysts_hit": [...],
  "invalidation_clean": true/false,
  "agent_narrative_score": 1-10,
  "key_lessons": ["...", "..."]
}
```

If `agent_narrative_score >= 8` OR `<= 3`, append a thesis_outcome entry to LEARNINGS.md (notable wins or notable misses).

### Archive

End of day, copy completed `daily_thesis.json` to `thesis_history.json` (append).
PROCEDURE A (Thesis Grader, PART 2) reads thesis_history.json next session for
deeper grading.

## Hard Rules - PART 3

- Thesis MUST have all 5 structure elements (directional call, asset views, catalyst watch, positioning bias, invalidation clause). Reject incomplete thesis-locks.
- Thesis is **advisory**, not hard gate - contradicting signals still fire with conviction penalty, aligning signals get conviction bonus. Position-sizing math, not veto.
- **NEVER allow thesis to override safety floors.** Thesis might say "risk-on explosive rally" but a depleted wallet still blocks new buys. Thesis is sentiment; safety is structural.
- Pivots are STRUCTURAL changes, not tactical. Log pivots only when invalidation clause triggers or thesis premise breaks.
- Self-score honestly. Inflated self-scores corrupt PROCEDURE A grading downstream.
- If thesis is missing for the day, signals still fire - they just don't get conviction adjustments. No thesis ≠ no trading.

---

# PART 4 - ECOSYSTEM AUDIT

This is when the agent personally verifies ecosystem health beyond what passive
heartbeats show. Real-time ground truth. Walking the floor.

solid, reliable, but on its own pace. When the agent wants real-time verification,
or when something feels off, this is the procedure.

## When to fire ecosystem audit

Triggered by:
- "audit the ecosystem", "how healthy are we", "check all balances"
- "full ecosystem status"
- Any time something feels off and the agent wants the full picture himself

## The Balance Check

Verify the trade wallet in every audit: `bot_logs/wallet_balance.json` (SOL on chain, deployable after the floor).

## Exposure Ceilings - When To Flag CRITICAL

If any breach, escalate immediately.

- **Concentration risk:** any single position >40% of deployable capital
- **Narrative stacking:** 3+ open positions riding the same meta or narrative
- **Daily PnL drawdown:** total realized PnL today < -8% of starting capital

Any breach -> CRITICAL escalation packet to the owner via owner-ping (severity=critical).

## The Audit Workflow

### Step 1 - Read the balance

```
wallet_balance.json  SOL on chain, deployable_after_floor (meme ammo)
```

If the file is **stale** (>15 min) or **missing**, that's the first finding.
Don't audit on stale data.

### Step 2 - Read open positions

```
positions.json  meme open positions
```

Build the exposure map by token and narrative.

### Step 3 - Check exposure ceilings

Run the three ceiling checks above. Note any breaches.

### Step 4 - Pipeline health spot-check

For each execution bot, check:
- Last successful signal/trade timestamp
- Last error timestamp + count
- Current state file (signal queue, status indicators)

If any bot hasn't shown activity in expected window, investigate.

### Step 5 - Code tuner review

Read `filter_patches.json` for last 24h:
- What was auto-deployed?
- Any attempts on MANUAL_REVIEW_ONLY bots? (must be 0)
- Any patches that don't have corresponding LEARNINGS justification?

### Step 6 - Security spot-check

- Check `.env` last-modified timestamp (alert if changed since last audit)

### Step 7 - Compose audit report

Write structured report to `bot_logs/ecosystem_audit_history.json` (append):

```
{
  "audit_at_iso": "...",
  "trigger": "owner_command" | "self_initiated" | "anomaly_detected",
  "balances": {...},
  "open_exposure": {...},
  "ceiling_breaches": [...],
  "pipeline_health": {...},
  "code_tuner_observations": {...}, #: perf packets fired, source deltas detected, setup mode progress, skill-evo review activity. NOT deploys.
  "security_findings": [...],
  "overall_status": "healthy" | "warning" | "critical",
  "recommendations": [...],
  "owner_escalation": null | {severity, packet_summary}
}
```

If `overall_status` is "critical" → fire owner-ping severity=critical with the packet.
If "warning" → fire owner-ping severity=high.
If "healthy" → log only, no the owner interruption.

```
{
  "sim_at_iso": "...",
  "lookback_days": 30,
  "filters_evaluated": [
    {
      "bot": "meme_sniper",
      "filter": "min_liquidity_sol",
      "current_value": 20,
      "proposed_value": 25,
      "trades_affected": 14,
      "projected_pnl_delta_sol": 0.42,
      "recommendation": "tighten",
      "confidence": "medium"
    },
...
  ]
}
```

If any recommendation has confidence=high AND projected pnl delta exceeds threshold, the agent applies it via code-monitor (backup + revert note) and pings notify-only.

## Hard Rules - PART 4

- Audits are READ-ONLY. NEVER modify state files during an audit.
- ALL THREE balance pools must be checked. Single-balance audits are not "audits."
- Any ceiling breach → owner-ping severity=critical or =high. No quiet handling.
- NEVER fire auto-fix actions on MANUAL_REVIEW_ONLY bots based on audit findings. Audits propose; the owner disposes.
- If audit data is stale or missing, the FIRST finding is "audit data unavailable." Don't audit on bad data.
- `sim_results.json` is owned by this procedure; full-rewrite acceptable but use atomic write.

---

# AUTHORITY TIERS (when running these procedures)

These procedures all operate at the agent's authority level (you're the main

session, not a sub-agent), but the change-surface they touch is real:

- **Tier 1 EXECUTE** (no ask): read inputs, compute scores/grades, write

  the standard output files (agent_thesis grade history, pattern_library,

  training_dataset), append to LEARNINGS, archive overseer packet.

- **Tier 2 DECIDE + LOG**: quality labels (HIGH/MEDIUM/LOW), letter grades,

  bias pattern flags (≥5 data points), suggested patterns, validation

  status (confirmed/invalidated), filter relaxation candidates.

- **Tier 3 PROPOSE** (write P3 to your own inbox for next cycle):

  - Schema changes to `agent_training_dataset.json`

  - Promoting a suggested pattern → active

  - Removing a pattern entirely from library

  - Recommending you stop trusting a source entirely (<40% accuracy

    over 10+ observations)

- **Tier 4 ESCALATE** (telegram + escalation_queue):

  - Training dataset corruption

  - autopsy_reports / pattern_discovery_feed unreadable

  - Suspicious data patterns (possible poisoning)

  - thesis_history grades being overwritten unexpectedly

---

# STATE CONTRACTS


  missed_runners.json,


- **APPEND-to-array**: agent_thesis.json (thesis_history array),

  agent_pattern_discoveries.json (validation field per discovery, never

  overwrite the discovery body), agent_training_dataset.json (examples array),

  source_accuracy.json (bias_patterns array)

- **READ-MODIFY-WRITE**: pattern_library.json (your output, atomic write

  with tmp + os.replace)

- **APPEND-ONLY**: ecosystem LEARNINGS.md, Section 8 only, through `learnings_writer` (never overwrite or hand-edit)

  positions.json, sl_registry, rug_skip_history, trusted_kols, any

  bot's signal file, canary,.env

---

# HARD RULES

- APPEND ONLY to LEARNINGS.md, training_dataset, thesis_history. Never overwrite.

- Minimum 5 trades before including pattern in analysis (sample size matters)

- Minimum 5 data points before bias conclusion in thesis grading

- Quality filter MUST run before training pair append (HIGH/MEDIUM only)

- Skip examples from unreliable sources (incomplete schema or ghost data)

- Atomic writes for all JSON outputs (tmp + os.replace)

- Never invent training pairs for missing data - fewer high-quality examples

  beat more medium-quality ones

- Overseer follow_ups are the standard trigger. Fire on demand when you have a specific reason - fresh data, a hypothesis to test, prep for a code change.

---

# WHEN TO READ THIS SKILL

- Loaded when an overseer packet is in the inbox (not Tier 1 always-on)

- Re-read PART 1 before processing any `x_evt_overseer_<date>.json` packet

- Re-read PART 2 PROCEDURE A when overseer says "fire thesis-grader"

- Re-read PART 2 PROCEDURE B when overseer says "fire pattern-librarian"

- Re-read PART 2 PROCEDURE C when overseer says "fire memory-architect"

- Re-read PART 3 at morning thesis-lock time, mid-day pivot, EOD self-score, or any "what's the thesis today" / "lock my thesis" / "did my thesis work today" trigger


- Read on demand if you want to grade your own thesis / refresh patterns /
  extract training pairs / verify ecosystem health without waiting for overseer

This skill is your self-improvement + self-management layer. The overseer is
your mirror (PART 1). The analytical procedures are your tools for acting on
what you see (PART 2). The thesis is your daily commitment to a market view
(PART 3). The audit is you walking the floor yourself (PART 4).

## Errors & oddities duty (2026-10-15)

The chair runs the per-pass errors & oddities scan defined in meme-hunter (`## ERRORS & ODDITIES`). This skill supplies the risk tier and test plan for any patch that scan produces. Same rules: backup, temp copy, test, apply, hash check, inbox note, no restarts, no secrets, no buy-size / cap changes. Applying needs `AGENT_SELF_PATCH=1`; otherwise the output is an owner card with the proposed diff.

## Owner Commands (on-demand roast, recap, autopsy)

The owner can ask for a report at any time instead of waiting for the nightly 2 AM Overseer run. `bots/sub-bots/owner_commands.py` answers. It reuses the Overseer prompt, inputs and judges, never edits the autoagent file, never trades and never changes sizes, filters or schedules.

| Command | Answer |
|---|---|
| `/roast` | Honest roast of the last 24h, aimed at whoever made the trades (see "Who gets roasted") |
| `/recap` | Same judges, framed as strong / weak / missed / next (one SI call) |
| `/autopsy` or `/autopsy last` | Latest closed trade from `bot_logs/autopsy_reports.json`: PnL, exit trigger, post-close watch (no SI call) |
| `/autopsy <ticker>` | Latest closed trade on that ticker, `$` optional |
| Plain text | "roast me", "recap please", "autopsy on $gork". Case-insensitive; anything else gets the help line |

**Modes** (`OWNER_COMMANDS` in `.env`, default `off`):
- `off`: nothing runs.
- `file`: a `.txt` (first line is the command) or `.json` (`{"text": "/roast"}`) dropped into `owner_commands/` is answered within about 5 seconds through the alert channels, then moved to `inbox_results/owner_commands/done/` (or `failed/`). Works on any OS, no Telegram needed.
- `telegram`: a separate command bot (`OWNER_COMMANDS_TG_TOKEN`, never the alert bot) reads only the owner's chat and replies there. It stops on a webhook or a 409 instead of fighting another reader.

**Replies** are always saved as JSON in `inbox_results/owner_replies/` (kind, target, time, text). Read the newest one there to see what the owner was told.

**Who gets roasted (v1.0.2):** a roast goes to whoever OPENED the positions, never to the owner by default.
- Each open position and each close from the last 24h is attributed by its opener, from fields the sniper already writes: owner = `source`/`opened_by` `owner_position`/`owner`/`manual`, an `originating_signal_id` starting `op_` (an owner bag the bot took over with `/manage`), or an `owner_positions_sniper.json` bag the owner kept (`leave` or still pending). Everything else the sniper opened (agent signals, promotions, launches) is the agent's. Who closed it does not matter.
- Only the owner's trades: the owner gets roasted on them (hold time, PnL, peak given back, holding past their own stop). One SI call; with no judge it falls back to a receipts-only roast.
- Only the agent's trades, or none: the agent roasts itself. That is the Overseer roast of your own calls, same as the nightly run. Never turn it on the owner.
- Mixed: two sections, "the agent, on its own calls" (the Overseer sees only agent-opened positions) and "you, on the trades you made". Two SI calls.
- "roast yourself" or `/roast agent` forces the agent self-roast. "roast me" picks by the book like a plain `/roast`.
- Kill switch: `OWNER_ROAST_TARGETING=off` returns to the old behaviour (always the Overseer agent roast). Default `on`.
- When you relay a roast, keep the target straight: do not tell the owner they held too long on a bag you opened, and do not roast your own calls as if they were the owner's.

**Cooldown:** `/roast` and `/recap` share `OWNER_ROAST_COOLDOWN_S` (default 900 s). Inside it the owner gets "cooling down, try again in N min" and no SI call is made. `/autopsy` has no cooldown.

**What the agent may do:**
- Serve file-mode requests: when the owner asks you in chat for a roast, recap or autopsy and `OWNER_COMMANDS=file`, write one small `.txt` with the command into `owner_commands/`, wait for the reply file in `inbox_results/owner_replies/`, and relay or summarize it.
- Without the process running, the same answer comes from `python bots/sub-bots/owner_commands.py --once "/autopsy last" --no-send` (prints it, sends nothing).
- Treat a roast or recap as input, like the nightly report: act on its follow-ups through the normal lanes.

**What the agent must not do:** start, stop or restart `owner_commands` (the owner does that), flip `OWNER_COMMANDS` or set its tokens, or move or edit files in `owner_commands/` or `inbox_results/owner_replies/` by hand. The inbox lanes do not own `owner_commands/`; it is not `inbox/`.

## Owner positions (2026-10-15)
The trading bots ask before managing a wallet position they did not open (a token bag bought by hand, or a perps position or add from outside the bot). Packets arrive as `owner_position` with an `id`, a question and a timeout (Sniper 30 min, Perps 60 min; Perps steps in early near liquidation).
- When the owner tells you, relay it: `{"action": "owner_position", "id": "<id>", "decision": "manage" | "leave"}` (Sniper: the json relay signal file; Perps: the perps relay). The owner can also answer directly with `/manage <ticker>` or `/leave <ticker>` through owner commands.
- Do not decide for the owner. With no answer, the timeout hands it to the bot's normal management and an alert announces it.
- `leave` = alerts only. `manage` = the bot's normal exits (Perps exits stay alert-only; a signal closes).
- Decisions and timeouts: `bot_logs/owner_positions.jsonl`.
