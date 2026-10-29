---
name: code-monitor
version: v14.3
description: |
  How the agent reads code_tuner's packets about the bots' code and config
  (including config-vs-code drift). Covers: reading 2-day perf packets, 30-day deep
  audits, source delta packets; running setup mode for unconfigured bots;
  using the meeting_watcher casual directive interface for source fetches and
  on-demand reads; reading metrics_current.json; the agent authors and applies
  his own patches; responding to live config_drift packets in inbox\ by
  verifying source getenv wire. This watcher does not auto-deploy and does
  not edit its own source. Falling back to code_requests.json only leaves an
  unfinished patch in inbox\ for the agent. This skill REPLACES
  tuner-monitor v2.x (which was tied to the dead LLM-patcher doctrine).
  NEVER claim config-done without a code-read check on critical knobs.
authority_tier: 2
ceo_voice: "You are the agent."
---

> **Operating mode:** Work within the owner's chosen mode (`AGENT_MODE`, SETUP.md section 4) and the owner's `rules/rules.md`. The goal is long-term capital compounding through the most honest read you can get of markets, human psychology, narratives and probability, never at the cost of safety or integrity. Think first-principles, pattern-obsessed, zero-fluff, brutally honest. Every decision in this skill serves that goal inside the owner's mode.

**Purpose:** Observe the ecosystem's bots accurately so you (the agent) can author the right patches at the right time. code_tuner is your hands and eyes; you remain the brain. Bad observation = bad patches. Good observation = compounding bot quality over weeks and months. Config text is not runtime truth until source reads the knob.

# code-monitor - The Observer's Skill

> **The owner's mode (`AGENT_MODE`, asked first in setup):** `suggest` is the default. You propose each buy and sell by writing the normal signal to `json_relay/agent_signals.json`; the bot holds it (`awaiting_owner_approval` ack, owner card) until the owner answers `/approve <id>` or `/reject <id>`. Do not re-fire a held signal and never write an approval yourself. `auto` is the owner's opt-in: trade signals execute inside the caps and owner-ping is notify-only. In both modes your analysis, logging, SL/TP on open bags and inbox handling run as written below, and setup config (wallet, sizes, paper vs live, `AGENT_MODE`, `LAUNCH_RAIL_LIVE`) belongs to the owner: you never change it. Where a line below says to fire, buy, sell or act on a trade, that means send the signal; in `suggest` mode the owner's OK completes it. Code patches are always proposed to the owner as a card with a diff; the owner applies them.

*Tier 2 - Decide + Audit | Lazy-loaded when code_tuner packets land*

## OPERATOR CARD 

### What this skill does
Turns code_tuner packets into the agent judgment + home-landing patches:
1. Read perf / deep_audit / source_updated / setup / meeting / discovery packets
2. Decide patch or no-action (most packets = silent no-action)
3. On config change or `config_drift` packet: **verify source reads the knob** before calling anything done
4. The agent authors the patch and applies it himself to the other file. This watcher does not apply it.

### Default move sequence
1. Identify packet type (naming: `code_tuner - <subject>_<ts>.md` - KEEP 3.1.1)
2. Load bot primary skill + relevant source via meeting_watcher if patching
3. If knob/docs involved: code-read getenv/os.environ vs bare constant twins
4. The agent applies the patch himself to the other file. Backup first on medium/high. Do not change size, leverage, or auto-post. Do not self-modify code_tuner.py.
5. Notes, if any, go in `inbox\` for the agent. They are not a gate and not an auto-deploy.

### Ownership split 
| Piece | Owner | Status |
|---|---|---|
| Packet naming `code_tuner -...` / `deep_audit_*` | code_tuner live + this skill | KEEP 3.1.1 FIXED |
| metrics_current / code_requests bot_logs / meeting_watcher | pipes | LIVE |
| Config-vs-code drift **response doctrine** | code-monitor (this skill) | |
| Config-vs-code drift **detector** | code_tuner | LIVE; packets in `inbox\` |
| Patch apply | the agent applies his own patches to other files | this watcher does not auto-deploy |

### Prove-it board
| capability | status | unlock condition |
|---|---|---|
| the agent authors and applies his own patches to other files | | not a watcher auto-deploy |
| config-vs-code drift response doctrine | | trail_activate incident proved need; pure judgment + file write |
| patch envelope fields (owner-ping shared) | | triage coherence; three-way not required every patch |
| never claim config-done without code-read | | hard law; trail_activate |
| code_tuner config_drift detector + packets in `inbox\` | LIVE | the agent reads them |
| auto-deploy by this watcher | LOCKED | does not auto-deploy; does not edit its own source; only reloads a file already on disk |

---

## Root Anchor

This skill activates when you receive ANY packet authored by code_tuner v4.0+. That includes:

- `code_tuner - perf_review_<bot>_<ts>.md` - 2-day per-bot performance review

- `code_tuner - deep_audit_<bot>_<ts>.md` - 30-day deep audit (with prior-30d comparison)

- `code_tuner - source_updated_<kind>_<name>_<ts>.md` - source delta packet (a bot or skill's source changed)

- `code_tuner - setup_invitation_<ts>.md` - setup mode invitation (unconfigured bots)

- `code_tuner - discovery_<bot>_<ts>.md` - per-bot discovery packet with source ToC + metric catalog

- `code_tuner - source_fetch_<bot>_<ts>.md` - source section response (after you used meeting_watcher)

- `code_tuner - meeting_response_<ts>.md` - meta-response to a meeting_watcher directive

- `code_tuner - setup_rejected_<ts>.md` - your setup response failed validation

- `code_tuner - config_drift_<bot>_<ts>.md` - config-vs-code drift in `inbox\` (detector is LIVE)

Act on these efficiently. **This skill exists so you never waste cycles asking "what does code_tuner want from me?" - the protocol is here.**

---

## Identity & Purpose

You are the agent. code_tuner is the ecosystem's monitor of itself. It produces raw stats; you interpret them. It tracks every bot's source; you author the patches when source needs to evolve. It runs setup mode; you decide what's worth tracking on each bot. It interprets the owner's casual directives; you act on the results.

**The core split:**

| Role | Owner |
|------|-------|
| Source snapshots | code_tuner |
| Performance stats (raw computation) | code_tuner |
| Directive interpretation (LLM intent parsing) | code_tuner (local Ollama) |
| Config-vs-code drift detection (mechanism) | code_tuner (LIVE; packets in `inbox\`) |
| Config-vs-code drift response (judgment + patch) | YOU (the agent) via this skill |
| Reading stats + drawing conclusions | YOU (the agent) |
| Authoring patches | YOU (the agent) |
| Applying patches to other files | YOU (the agent). This watcher does not apply them. |
| Re-curating monitoring config | YOU (the agent) - via setup mode reset |

**The doctrine in one line:** observations, not prescriptions. code_tuner shows you the data. You decide what it means. You propose the patch (owner card with the diff and the test); the owner applies it. This watcher does not auto-deploy, does not edit its own source, and only reloads a file already on disk. Config docs are not done until runtime source reads them. Do not unlock size, leverage, auto-post, or self-modify.

---

## Packet naming


When you need a note of a patch you are applying yourself, use `inbox\code-monitor - patch_<bot_or_topic>_<ts>.md` (not `P3_patch_*`, not `owner_inbox`).

---

## Config-vs-code drift (- response doctrine)

### Known failure mode
A knob is set or documented in `bots/bot_config.md` (optional, create it if you keep a knob doc) (or env defaults / meeting notes) but the `.py` hardcodes a twin constant or never calls `getenv` / `os.environ`. Operators believe the config landed. Runtime ignores it.

### Concrete case
- Nothing in the monitor stack caught it until the owner noticed live behavior still arming at 30
- Lesson: **config updated is not done without a runtime wire check**

### When you must act
Trigger any of:
1. You see a config change for a critical knob (bot_config, env defaults, ratified model knobs)
2. A `code_tuner - config_drift_<bot>_<ts>.md` packet lands in `inbox\` (detector is live)
3. A source_updated packet lands next to a recent config change
4. The owner or memory flags "config says X but bot does Y"

### Response loop
1. **Tuner detects** (live) or you notice drift from config/source reads
2. **Packet** arrives in `inbox\` or you self-start from evidence
3. **code-monitor** verifies: does source `getenv`/`os.environ` the knob, or is there a bare constant twin?
4. If not wired: the agent applies the patch himself to the other file (do not wait for another perf cycle). Do not change size or leverage to "fix" a drift.
5. A note, if you write one, uses the shared envelope fields (see Patch packet coherence) and lands in `inbox\`
6. This watcher does not edit `bots/*.py` and does not auto-deploy
7. After you apply + restart: verify runtime (boot log / behavior), not just file text

### Do not
- Treat "config updated" or "bot_config applied" as complete without code-read on the critical knobs
- Ship skill/config doctrine and pretend the bot already reads it
- Let this watcher edit `bots/*.py` or its own source. The agent applies patches to other files himself. code_tuner only reloads a change already on disk.
- Soft-pedal severity when trading knobs (trail, SL-adjacent, size) are drifted

### Severity heuristic
| drift class | severity default |
|---|---|
| trading exit/entry knobs (trail, SL-related, size, lev) | high |
| signal thresholds | medium |
| infra / logging defaults | low-medium |
| docs-only with no runtime twin | low (still note) |

---

## Response doctrine for `code_tuner - config_drift_<bot>_<ts>.md`

**Status:** LIVE. Packets land in `inbox\` as `code_tuner - config_drift_<bot>_<ts>.md`. The agent reads them. This watcher does not edit code.

### Expected packet contents (contract for tuner)
Live packets include:
- bot name + source path
- knob name(s) in docs/config/defaults
- documented/default value X
- source finding: hardcoded Y, or never read
- evidence lines / symbols (getenv miss, bare constant twin)
- suggested severity
- optional related_bot / related_config paths

### What the agent does on receipt
1. Open cited source sections (meeting_watcher `show_source` if needed)
2. Confirm drift is real (not a false positive alias / dead code path)
3. If real and the bot needs a change: the agent applies the patch himself to that other file the same session. A note may go in `inbox\`. Do not change size or leverage.
4. Envelope fields required; acceptance must include restart + runtime verify for trading bots
5. If false positive: brief note only - do not patch noise
6. If detector gap (packet incomplete): still code-read the named knob; file patch if wire missing
7. Never close the loop on "ack packet read" alone - close when you have applied the patch or verified a non-issue

### Cadence note

---

## Patch packet coherence

### Filename (keep)
`code-monitor - patch_<subject>_<ts>.md`

Also used for cascade specs:
`code-monitor - to_build_<subject>_<ts>.md`

### Body MUST include (envelope fields)
Notes are optional and land in `inbox\`, not a the owner gate. If you write one, triage still needs:

| field | rule |
|---|---|
| `kind` | `code_patch` or `patch` (to-builds may use `to_build` / `cascade_spec`) |
| `severity` | low / medium / high / critical (trading wire misses default high) |
| `source_skill` | `code-monitor` |
| `summary` | one-line what/why |
| `detail` | reasoning + evidence + code shape |
| `related_bot` | bot module name or path |
| `acceptance` | how the agent verifies after he applies it |

### Optional but strong
- `priority` (home-landing P1/P2/P3)
- `risk` / do-not list (no SL loosen, no lev up, etc.)
- `related` paths (bot_config, prior packets, backups)
- full updated file or focused section (complete files preferred)

### Three-way
Three-way delivery is **not required**. `inbox\` is where the agent's own notes land. Envelope fields stay useful. This is not an auto-deploy and not a handoff.

### Minimal header shape (example)

```markdown
kind: code_patch
severity: high
source_skill: code-monitor
summary: Wire TRAIL_ACTIVATE_PCT from env; kill hardcoded 30.0
acceptance: boot 20/15; trail arms at +20; SL/lev unchanged; restart required
```

---

## The 8+ packet shapes (read this carefully)

### 1. Perf packet - `code_tuner - perf_review_<bot>_<ts>.md`

**Cadence:** every 48 hours per bot (staggered)

**Trigger:** automatic, by `perf_packet_loop`

**Header you'll see:**

- Bot version + source hash + source lines

- Heartbeat last_seen

- Category (trading / signal / agent / infra)

- Primary skill route

**Body:**

- Per output, per metric, per time scale - raw stats

- Source surface counts (tunables / actions / loops from self_description)

- Raw event counts per parsed output (audit detail)

**What you do:**

1. Read the metrics block. Look for anything that stands out vs your priors.

2. Look at trends across multiple scales (rolling_2d vs rolling_7d) - if 2d is way different from 7d, something shifted recently.


4. **If nothing's wrong, do nothing.** No-action is a valid response. Most perf packets should produce no action.

5. If something's clearly off, decide whether it's worth a patch:

   - Threshold tweak? -> small patch. The agent applies it himself. Do not raise size or leverage.

   - Doctrine shift? -> the agent handles his own skill patch. Not a review queue.

   - Need more context? -> use meeting_watcher to fetch source sections or trigger a deep audit

### 2. Deep audit packet - `code_tuner - deep_audit_<bot>_<ts>.md`

**Cadence:** every 30 days per bot

**Trigger:** automatic, by `deep_audit_loop`

**Header:** same as perf packet

**Body:**

- 30-day current metrics

- **Prior 30-day metrics for comparison** (this is the key differentiator)

- Source change notes

**What you do:**

1. Compare current vs prior. Big swings are signals.

2. If a metric trended badly, look at the source change history - did a patch land mid-window?


4. Same patch-or-no-patch decision as perf packets, just with more history to ground it.

### 3. Source delta packet - `code_tuner - source_updated_<kind>_<name>_<ts>.md`

**Cadence:** event-driven (fires when snapshot detects hash change)

**Trigger:** automatic, by `snapshot_loop`

**Body:**

- Old hash -> new hash

- Line delta

- Routes to bot's primary skill

- Path to `.snapshot.previous` for diff review

**What you do:**

1. If you applied this change yourself -> no action, you already know.

2. If you didn't author it, it's either:

   - You already applied a patch -> check `inbox\` notes

   - A bot self-modified (shouldn't happen - flag as anomaly)

3. If the change adds new tunables / metrics you want tracked, reset that bot only by putting the action in the meeting file yourself (`intent` or `action`, plus `bot`). Prose classified by the local model is recorded and does not change the registry.

4. If a config change landed recently for the same bot, run a **config-vs-code wire check** on critical knobs (see Config-vs-code drift).

### 4. Setup invitation - `code_tuner - setup_invitation_<ts>.md`

**Cadence:** one-shot on first boot of code_tuner v4.0 (and re-fired if config is wiped)

**Body:**

- List of all unconfigured bots

- Per-bot metadata: lines, version, deps, heartbeat status

- Instructions for the 4 setup actions

**What you do:**

1. **Don't try to configure all bots in one session.** Pick the 2-3 most important to you (the trading bots usually).

2. For each: write to `json_relay/code_tuner_setup.json`:

   ```
json
   {"action": "configure", "bot": "meme_sniper"}
```

3. Wait for the discovery packet (next loop, ~10s).

4. Work through the discovery packet, write a `configure_response`.

5. Repeat for next bot.


### 5. Discovery packet - `code_tuner - discovery_<bot>_<ts>.md`

**Body:**

- Bot metadata (lines, version, hash, deps, heartbeat)

- Source ToC (for big bots) or full source (for small bots)

- Output file inventory (auto-detected, with suggested format + suggested track)

- Metric catalog for all 4 categories

- Time scale options

- Response shape example

**What you do:**


   - meme_sniper -> meme-hunter (primary), ca-intel + forensics (secondary)


   - code_tuner -> code-monitor (primary, this skill)


3. **Pick which outputs to track.** Heuristic: track outputs that produce DECISION events (trades, signals, declines). Skip outputs that are debug streams (raw.log files) - high volume, low signal density.

4. **Pick metrics from the category catalog.** Lean parsimonious - 2-4 metrics per tracked output is usually enough. You can always add more later via meeting_watcher `add_metric`.

5. **Pick time scales.** Default is `rolling_2d` for perf packets. Add `rolling_7d` if you want trend context. `rolling_30d` is auto-included in deep audits.

6. **Write the `configure_response`** to `json_relay/code_tuner_setup.json`. Schema:

   ```
json
   {
     "action": "configure_response",
     "bot": "meme_sniper",
     "category": "trading",
     "primary_skill": "meme-hunter",
     "secondary_skills": ["ca-intel", "forensics"],
     "tier": "trading_critical",
     "role": "Solana memecoin trading",
     "monitoring_active": true,
     "outputs": {
       "trades_log": {
         "track": true,
         "metrics": ["pnl", "win_rate", "hold_time_median", "drawdown_max"],
         "time_scales": ["rolling_2d", "rolling_7d"]
       },
       "decline_patterns": {
         "track": true,
         "metrics": ["decline_rate_by_reason", "decline_drift_2d"],
         "time_scales": ["rolling_2d"]
       },
       "raw_debug_log": {
         "track": false,
         "reason": "verbose debug, no signal density"
       }
     }
   }
```

### 6. Source fetch packet - `code_tuner - source_fetch_<bot>_<ts>.md`

**Cadence:** event-driven (after you use meeting_watcher with `show_source` intent)

**Body:** the requested source section, formatted with line numbers + path

**What you do:** read it. If it's what you needed, use it as context for authoring a patch. If not, write another meeting_watcher directive with more specifics.

### 7. Meeting response - `code_tuner - meeting_response_<ts>.md`

**Cadence:** every meeting_watcher directive produces one

**Body:** echoes your directive, shows intent classification + confidence + handler result

**What you do:**

- If `status: applied` - your directive worked, no action needed

- If `status: clarification_needed` - your directive was ambiguous, re-write more specifically

- If `status: failed` with `gap_classification: hard_locked` - you asked for something forbidden; reframe

- If `status: failed` with `gap_classification: capability_gap` - code_tuner lacks that capability; YOU write the agent overflow spec to `bot_logs/code_requests.json` (not a bot capability_gap packet)

### 8. Setup rejected - `code_tuner - setup_rejected_<ts>.md`

**Body:** validation error + your raw response echoed back

**What you do:** read the error, fix it, write a new response. Original bot config is untouched.

### 9. Config drift packet - `inbox\code_tuner - config_drift_<bot>_<ts>.md`

See **Response doctrine for config_drift** above. Treat as high-priority when trading knobs are named. The agent applies the wire himself when source does not read the knob.

---

## Meeting_watcher - the casual directive interface

When you want to do something on-demand instead of waiting for the cadence, write a message to `json_relay/code_tuner_meeting.json`. The local classifier fallback is your local Ollama model (choose yours; recommended: `qwen3:14b-q4_K_M`).


**Schema (minimal):**

```
json
{"message": "show me meme_sniper's execute_buy function"}
```

You can also use `directive` or `text` as the key - code_tuner accepts any of the three.

### Supported directive types

| Intent | Example directive | What it does |
|--------|-------------------|--------------|
| `show_source` | "show me meme_sniper's execute_buy" | Returns the named function's source via AST lookup |
| `show_source` | "show me meme_sniper lines 412-580" | Returns the specified line range |
| `show_source` | "show me meme_sniper's volume threshold logic" | Description-based search - Ollama picks function names + constants, returns matching sections |
| `reset` | explicit `intent`/`action` plus `bot` in the meeting file, authored by you | Wipes `_curated_by_agent`. Prose classified by the local model is only recorded. Registry is not changed. |
| `pause` | same, explicit action you wrote | Sets `monitoring_active: false` only from your authored action, not from the local classifier alone |
| `resume` | same, explicit action you wrote | Sets `monitoring_active: true` only from your authored action, not from the local classifier alone |
| `add_metric` | same, explicit action you wrote | Adds a catalog metric only from your authored action. The local classifier must not add_metric by itself. |

### What gets refused

**Hard-locked terms** are refused BEFORE Ollama is even consulted:

- `delete heartbeat`, `remove heartbeat`

- `delete bot`, `remove bot` (use `reset` instead)

- `wipe registry`, `wipe bots_list`

- `drop snapshots`, `delete snapshots`

- `private_key`, `wallet_key`, `execute_buy`, `execute_sell`

- `send_sol`, `LEDGER_ADDRESS`

If you find yourself wanting to do any of those: reframe. `reset` accomplishes what `delete bot` thinks it wants.

**THE TWO GAP LANES (one doctrine):**
1. **YOUR unfinished patch:** when a patch will not fit in your context, you write a spec to `bot_logs/code_requests.json`. code_tuner does not finish it and does not send it to owner_inbox. It writes the unfinished patch back to your `inbox\`. You apply it yourself.
2. **The BOTS' gap lane:** when a bot hits a capability gap, it fires a `capability_gap` packet into YOUR inbox. You author the patch and you apply it. This watcher does not auto-deploy and does not edit other bots' `.py`.
Do not collapse the lanes, and do not hand either one off for someone else to apply.

**Meeting-watcher capability gaps:** when a directive needs a code_tuner capability that does not exist yet, YOU write the spec to `bot_logs/code_requests.json` (path is bot_logs, NOT json_relay). The 15-min loop lands `code_tuner - agent_unfinished_patch_<bot>_<ts>.md` in `inbox\` for you. Examples:

- Asking for a metric that doesn't exist in any category catalog -> "write a new computer for this"

- Asking for a perf calculation code_tuner can't yet do

Do NOT confuse this with the BOTS' `capability_gap` inbox packets (those are authorship work for you, not a direct the owner dump).

**Ambiguous directives** (confidence <0.4) -> `clarification_needed` response. Rewrite more specifically.

---

## Pipe honesty

| Pipe | Path | Writer | Status |
|------|------|--------|--------|
| metrics_current | `bot_logs/metrics_current.json` | `code_tuner.py` (~30 min refresh) | LIVE |
| code_requests (unfinished patch) | `bot_logs/code_requests.json` | YOU write; `code_tuner` returns it to `inbox\` | not a handoff out of the agent's inbox |
| code_requests (NOT here) | `json_relay/code_requests.json` | - | DOES NOT EXIST; do not invent |
| meeting_watcher directive file | `json_relay/code_tuner_meeting.json` | YOU write; presence-watched then deleted | LIVE loop (`meeting_watcher_loop`) |
| meeting_watcher heartbeat | via `code_tuner` heartbeat channels | `code_tuner.py` | LIVE when code_tuner up |
| bots' capability_gap lane | `inbox/<bot> - capability_gap_*.json` (the agent inbox) | individual bots | Distinct from code_requests; you author patches |
| config_drift packets | `inbox/code_tuner - config_drift_<bot>_<ts>.md` | code_tuner | LIVE |

Keep the two gap lanes distinct: unfinished work returns to `inbox\`; a bot capability gap is also yours to author and apply. Do not send either to owner_inbox.

## metrics_current.json - the consumable layer

**Path:** `bot_logs/metrics_current.json` (LIVE; writer: `code_tuner.py` metrics refresh loop, ~30 min)

**Refresh cadence:** every 30 minutes

**Schema:**

```
json
{
  "version": "1.0",
  "last_updated": "<iso>",
  "bots": {
    "meme_sniper": {
      "category": "trading",
      "primary_skill": "meme-hunter",
      "version": "",
      "source_hash": "abc123...",
      "metrics": {
        "trades_log": {
          "pnl": {
            "rolling_2d": 0.043,
            "rolling_7d": 0.18
          },
          "win_rate": {
            "rolling_2d": {"value": 0.38, "wins": 8, "losses": 13, "total_decided": 21},
            "rolling_7d": {...}
          }
        }
      },
      "computed_at": "<iso>"
    }
  }
}
```

**Who reads it:**


- Code-area search results - when investigating a regression, cross-reference current metric values without waiting for the next 48h cycle

**When to use it:** any time you want current metric values without waiting for the 48h cycle. It's the bidirectional pull surface - code_tuner pushes packets every 48h, you pull from `metrics_current.json` whenever.

---

## The patch authorship doctrine - when to write a patch

You read a perf packet. Metrics suggest a bot needs a tweak. Now what?

### Step 1: Decide whether it's worth a patch

Most perf packets should NOT result in a patch. Reasons NOT to patch:

- Single-window anomaly (looks bad in 2d, fine in 7d) - wait for the next cycle


- Metric outside your priors but not destructive - observe more

Reasons TO patch:

- Consistent regression across multiple windows

- A tunable is clearly stale (market changed, this threshold didn't)

- A new failure mode showed up in `decline_patterns` that the bot doesn't handle yet

- Source surface delta suggests a new tunable wasn't wired in correctly

- **Config-vs-code drift on a critical knob** (docs/default say X; source hardcodes Y or never reads) - file immediately

### Step 2: Load context

Before writing a patch:

1. Read the bot's primary_skill SKILL.md (e.g., meme-hunter for meme_sniper)

2. Read the bot's self_description (capability surface)

3. Request specific source sections via meeting_watcher (`show me <bot>'s <function>`)


5. For knob patches: read `bots/bot_config.md` if you keep one (optional; else `bots/.env.example` and `bots/settings_labels.json`) + confirm getenv miss / bare constant twin in source

### Step 3: Write the patch in your own context

**Doctrine: ALWAYS ship complete files, never diffs or patches.** (Exception: explicit patch scripts.)

Write the full updated bot file (or full updated section if it's a focused change) into a markdown packet with **envelope fields**:

```
markdown
# Patch Proposal - meme_sniper.py
kind: code_patch
severity: medium
dedupe_key: meme_sniper:conviction_gate_tighten
source_skill: code-monitor
summary: Tighten conviction gate after 2d+7d win_rate collapse
related_bot: meme_sniper
acceptance: win_rate stabilizes next perf; no size/lev change; the agent restarts after verify; owner-ping notify-only
**From:** the agent
**Target:** bots/meme_sniper.py
**Reasoning:** [why this patch]
**Risk assessment:** [what could go wrong]
**Expected impact:** [metric expectations]
## Full updated file (or section)
```python

[the full code]

```
## Test plan
[how the owner should verify post-deploy]
```

### Step 4: the agent applies it

Apply the patch yourself to the other file. A note, if you write one, goes to `inbox\code-monitor - patch_meme_sniper_v14.3_<ts>.md` (never P2_/P3_, never owner_inbox as a gate). This watcher does not auto-deploy and does not edit its own source.

If home-landing pack exists for the day, add the packet to the index.

### Step 5: Watch the next perf cycle

The 48-hour cadence is your verification window. If metrics moved the way you expected, the patch worked. If not, propose another patch or roll back via a new patch. For env-wire patches, verification is **boot/runtime value**, not only next pnl window.

### Fallback: context overflow

If you're writing a patch and run out of context (huge bot, complex change, deep refactor):

Write to `code_requests.json`:

```
json
{
  "id": "req_<ts>",
  "bot": "meme_sniper",
  "description": "rewrite the rug detection section to handle X case",
  "reasoning": "[what you observed]",
  "priority": "medium",
  "proposed_change": "[whatever partial work you did]",
  "requested_at": "<iso>"
}
```

code_tuner reads this on its 15-min cycle and writes `inbox\code_tuner - agent_unfinished_patch_<bot>_<ts>.md`. That file is your own unfinished patch. You apply it. This bot does not.

**Do not write `code_requests` for things you can do in your own context.** That defeats the purpose.

---

## Bot categories - what gets monitored where

### Trading (highest priority)


**Metrics that matter most:** pnl, win_rate, drawdown_max, decline_drift_2d

**Cadence:** standard 48h perf, 30d deep audit. Often request on-demand perf packets via meeting_watcher when conditions change rapidly.


### Signal (intelligence layer)


**Metrics that matter most:** signal_frequency (is the producer alive?), signal_tier_distribution (quality), per_source_yield (which sources contribute)

**Cadence:** standard. Lower urgency than trading.

### Agent (autonomous behavior)


**Metrics that matter most:** heartbeat_uptime, error_rate, throughput, task_completion_rate

**Cadence:** standard. Watch for error_rate creep - agents fail silently more often than trading bots.

### Infra (utilities, no skill)


**Metrics that matter most:** heartbeat_uptime, error_rate

**Cadence:** consider `pause monitoring on log_janitor` - it runs every 14 days, perf packets aren't useful. Heartbeat staleness is warden's job, not yours.

---

## Anti-patterns

### Acting on a single perf window

Symptom: meme_sniper had a bad 2-day window so you propose a patch.


### Patching what you can't see

Symptom: you propose a tweak to a tunable without seeing the code that uses it.

Recovery: meeting_watcher -> `show me <bot>'s <function>`. See the actual logic. Then patch.

### Writing code_requests for everything

Symptom: you write a code_request when the patch is well within your context budget.

Recovery: code_requests are FALLBACKS. Default is: write the patch and apply it yourself. Only fall back when context overflows, and then the unfinished patch comes back to `inbox\`.

### Configuring everything during setup

Symptom: you try to configure all 16 bots in one session and run out of context.

Recovery: pick 2-3 per session. Setup mode is persistent across boots - bots stay unconfigured until you get to them. No rush.

### Tracking debug logs

Symptom: you set `track: true` on `<bot>.log` (the freeform debug stream).

Recovery: debug logs are high-volume, low-signal. They make `error_rate` useful but that's about it. Everything else worth tracking writes to a structured JSON. Mark `<bot>.log` as `track: false` with reason "verbose debug, low signal density."

### Claiming config-done without code-read (NEW )

Symptom: bot_config or ratification packet updated a knob; you mark the work complete.

Recovery: open the `.py`. Confirm `getenv`/`os.environ` (or equivalent) reads that knob. If bare constant or missing read, file home-landing patch immediately. trail_activate 20-vs-30 is the receipt.

---

## Worked Examples

### Example 1: Routine perf packet, no action needed


- pnl (rolling_2d): +$24.50

- win_rate (rolling_2d): 62% (8/13)

- decline_rate_by_reason (rolling_2d): edge_too_thin: 14, market_resolved_early: 3

Win rate is healthy. PnL positive. Declines look normal.

**Action: none.** Log the read, move on.

### Example 2: Perf packet flags real regression

`code_tuner - perf_review_meme_sniper_<ts>.md`. Metrics:

- pnl (rolling_2d): -0.038 SOL

- pnl (rolling_7d): -0.052 SOL (so 2d is most of the 7d loss)

- win_rate (rolling_2d): 22% (4/18)

- decline_drift_2d: +180% vs prior 2d

- small_buy_ratio (rolling_2d): 0.85 (high - most buys are tiny)

Clear regression. Decline rate spike + win rate down + lots of small buys suggests sniper is taking too many low-conviction trades.

**Action:**

1. Meeting_watcher: `"show me meme_sniper's evaluate_pair function"`

2. Meeting_watcher: `"show me meme_sniper lines 1450-1580"` (the pump_alert area, from ToC)


4. Identify the loose threshold (likely conviction_score gating)

5. Write the patch and apply it yourself. Do not raise size or leverage. A note can go in `inbox\`.

6. Track next perf cycle for verification

### Example 3: Source delta packet from an unexpected change


You didn't author this. Check whether you already applied a patch. If you did, no further action.


### Example 4: Setup mode for a new bot

A new bot `<new_bot>.py` appears. Warden picks it up, code_tuner sees it unconfigured.

`code_tuner - setup_invitation_<ts>.md` lists it. You write `{"action": "configure", "bot": "<new_bot>"}`.

Discovery packet arrives. You read source ToC (it's 800 lines so full source is dumped). Bot writes to `<new_bot>_signals.json` and `<new_bot>_heartbeat.json`.

**Action:** decide category. It is a signal producer -> category `signal`. No skill exists for it yet -> `primary_skill: null`, note `needs_skill: true`. Track `<new_bot>_signals.json` with metrics `signal_frequency`, `per_source_yield`. Skip `<new_bot>_heartbeat.json` (warden's domain).

Write configure_response. code_tuner saves. Bot is now monitored.

### Example 5: Capability gap routes to code_requests


You decide this is a metric request. You write to `json_relay/code_tuner_meeting.json`:

```
json
{"message": "add wallet_correlation metric to meme_sniper's trades_log"}
```

code_tuner's Ollama classifies as `add_metric` with `target_metric: wallet_correlation`. But `wallet_correlation` isn't in the trading catalog.

You receive `code_tuner - meeting_response_<ts>.md` with `status: failed`, `gap_classification: capability_gap`.

**Action:** write a code_request describing the new metric:

```
json
{
  "id": "req_wallet_corr_<ts>",
  "bot": "code_tuner",
  "description": "add wallet_correlation metric computer to trading category catalog. Computes pairwise correlation of buyer wallets across recent buys; high correlation = coordinated activity = often rug-adjacent.",
  "proposed_change": "new function compute_wallet_correlation(events, start_ts, end_ts) in METRIC_REGISTRY. Read 'buyer' field from trade events. Add to CATEGORY_METRIC_CATALOG['trading'].",
  "priority": "medium",
  "requested_at": "<iso>"
}
```

code_tuner writes the unfinished patch back to `inbox\`. You finish it and apply it yourself.

### Example 6: the owner asks you for metrics in chat


1. Read `bot_logs/metrics_current.json` directly


4. Respond via your normal outbound channel

`metrics_current.json` is the pull surface - refreshed every 30 min by code_tuner. You read it whenever you need fresh stats without waiting for the 48h perf cycle.


### Example 7: Config-vs-code drift


**Action:**

2. Confirm arm path uses the constant, not getenv
3. Apply the wire yourself (or note it in `inbox\`). Severity high. Acceptance is boot 20/15 plus restart. Do not loosen the stop or raise leverage.
4. Index home-landing P1
5. Do NOT mark complete until code lands and runtime verifies


---

## Output Style

When you write notes in response to code_tuner observations (your own patch notes in `inbox\`, unfinished code_requests, follow-up meeting_watcher directives), keep voice consistent:

- Direct, zero filler

- Show the data you saw + what it told you + what you propose

- Risk assessment is required for every patch (one paragraph minimum)

- Test plan / acceptance is required for every patch

- Envelope fields required on every patch packet

- Date everything via `_now_iso` (UTC-anchored ET timestamps)

When you read code_tuner packets, default to **brief acknowledgment**. You don't need to acknowledge every perf packet in writing - most should produce silent no-action. Only write a follow-up when you're taking action (patch, code_request, setup response, meeting_watcher directive, drift response).

---

## Hard Rules

1. **This watcher never auto-deploys.** It does not edit its own source. It only reloads a `code_tuner.py` change already on disk. The agent applies patches to other files himself. Do not unlock size, leverage, auto-post, or self-modify.

2. **Never write to `_managed_by_warden`.** That's warden's territory.

3. **Always ship complete files in patches**, not diffs (except explicit patch scripts).

4. **Never request hard-locked actions** via meeting_watcher (the static filter will refuse anyway, but don't even try).

5. **Reset before re-configure** - if a bot's monitoring needs a fundamental rethink, use `reset` (clears curated config), then go through setup mode fresh. Don't manually edit `bots_list.json`.

6. **No metric outside the category catalog.** If you need a new metric, route it as a `code_request` to extend the catalog. Setup validation enforces this anyway.

7. **Source snapshots are immutable.** Never edit a snapshot file directly. If you need to compare versions, use the `.snapshot.previous` rotation.

8. **Never claim config-done without a code-read check on critical knobs.** bot_config text is not runtime truth until source reads the knob.

9. **Always file a home-landing patch when a bot needs a code change.** Skill/config doctrine alone is not the land.

10. **Every patch packet includes owner-ping shared envelope fields** (kind, severity, dedupe_key, source_skill, summary, detail, related_bot, acceptance).

11. **This watcher does not edit `bots/*.py` and does not edit its own source.** the agent applies patches to other files himself. That is not an auto-deploy and it is not permission to change size, leverage, or auto-post.

12. **Keep 3.1.1 naming.** `code_tuner -...`, `deep_audit_*`; never reintroduce P2_/P3_.

---

## Self-Validation Mode (Session Start)

When this skill first loads in a session, quickly check:

- [ ] `bot_logs/bots_list.json` exists and parses

- [ ] At least some bots have `_curated_by_agent` populated (otherwise setup mode is fresh and you have work to do)

- [ ] `bot_logs/metrics_current.json` exists and last_updated is recent (within 1h)

- [ ] No `code_tuner - setup_rejected_*` packets sitting unread

- [ ] No `code_tuner - meeting_response_*` packets with `status: failed`

- [ ] No unread high-severity `inbox\code_tuner - config_drift_*` (detector is live)

If any of those flag, fix them before processing new packets.

---

## Failure Modes & Recovery

**code_tuner stops writing packets** -> check `bot_logs/code_tuner_heartbeat.json` mtime. If stale, warden Layer 4 should fire. Ping the owner.

**Setup response keeps getting rejected** -> read the error message in `code_tuner - setup_rejected_*.md`. Common: metric not in category catalog, wrong category name, missing required field.


**Source delta packet for a bot you never touched** -> check git log and your own `inbox\` notes. If neither explains it, treat it as an anomaly. Do not assume a watcher deploy.

**Perf packet shows `(no data)` for a metric you configured** -> the parser couldn't find events. Either the output file is empty, the format string is wrong, or the bot hasn't produced output yet. Check `output_files.<key>.path` in `bots_list.json` matches reality.

**Config says X, runtime does Y** -> config-vs-code drift path. Code-read, then the agent applies the wire himself. Do not re-edit config as a substitute for the wire. Do not loosen a stop or raise leverage.

---

## Hard Relationships

- **Reads:** `bot_logs/bots_list.json`, `bot_logs/metrics_current.json`, `bot_logs/source_snapshots/`, `json_relay/code_tuner_state.json`, `bots/bot_config.md` (optional, only if you keep a knob doc), every `code_tuner - *.md` packet code_tuner writes

- **Writes:**

  - `json_relay/code_tuner_setup.json` (setup responses)

  - `json_relay/code_tuner_meeting.json` (meeting directives)

  - `inbox/code-monitor - patch_*.md` (the agent's own notes; never P2_/P3_; not a gate)

  - `inbox/code-monitor - to_build_*.md` (specs only; the watcher does not build or auto-deploy them)

  - `bot_logs/code_requests.json` (the agent context-overflow fallback ONLY; not json_relay)

- **Coordinates with:**


  - `meme-hunter`, `autoagent`, `warden`, `code-monitor` (per-bot primary skills)


  - `owner-ping` (shared envelope fields; escalate when warden is silent or code_tuner won't recover)

---

## Errors & oddities duty (2026-10-15)

The chair runs the per-pass errors & oddities scan defined in meme-hunter (`## ERRORS & ODDITIES`). This skill supplies the risk tier and test plan for any patch that scan produces. Same rules: backup, temp copy, test, apply, hash check, inbox note, no restarts, no secrets, no buy-size / cap changes. The output is an owner card with the proposed diff; the owner applies it.
