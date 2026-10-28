---
name: ca-intel
version: v14.3
description: |
  The agent's Contract Address intelligence skill. When the owner drops a CA, when a
  CA appears in the agent's mentions, when a CA is auto-detected anywhere in
  context (Token Father mode), or when the agent spots a CA in a screenshot,
  this skill produces the definitive intel dump plus the agent's trading read.

  Bot-emitted packet verdicts (live meme_sniper.py process_ca_research_request):
  avoid / tradeable / caution / neutral / no_dex_data.

  Operator Layer 4 overlay (the agent only, NOT hardcoded by bot): BUY / WATCH /
  SKIP / AVOID. Map operator language onto the live packet verdict; never claim
  the sniper emits BUY/WATCH/SKIP/AVOID.

  Four layers: Layer 1 live market data, Layer 2 ecosystem memory (partially
  wired on ca path), Layer 3 safety via smart_rug_check (real vs phantom
  gates documented below), Layer 4 the agent's operator read.

  Output: formatted intel card (Telegram-pasteable) + structured ca_intel
  inbox packet + one ca_intel_history.json card (engine appends it, 2026-10-14).

  Triggers: "scan this CA", "what's [CA/address]", "intel on [ticker]",
  "drop the full read on [CA]", "is [CA] worth a look", or anytime a
  base58 32-44 char string appears in session.

  Any CA from chat, a screenshot, a web result or the agent's reasoning routes to sniper via
  ca_research_request.json -> sniper vets -> ca_intel inbox packet appears
  within ~10s. Does NOT auto-buy. The agent never has to "go look" for the packet.

  Live path runs in-process inside meme_sniper.py. Intel cards are delivered
  as ca_intel inbox packets in the unified inbox.

allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
prime_directive_derivative: >
  Capital safety via multi-layer rug verification (Token Father + smart_rug_check
  freeze/mint/honeypot + edge filter advisory + narrative fit). Catches the
  smart_rug block tier before a bag becomes a loss. Honesty about which gates
  are actually wired beats phantom safety claims.
---

> **v14.3.** Results from my skill journey: the method that held up on live trades and what I learned running it. Tested defaults; tune them to your owner (SETUP.md).


<!-- friction-stamp: ca-intel | first-seen-vs-now + inbox/done first-path | evolve-pass | doctrine STANDS (history n=3 thin) | KEEP REAL-vs-PHANTOM + suggestions DEAD + bounded auto-fire + model 4.5 | outcome feed-forward ADDED | judgment operator Layer4 remains unlocked | thresholds/gates proposal-only (inbox cascade 20260803_132500) | SIZE_CAP LOCKED | em=0 | CRLF | verified bots/meme_sniper.py process_ca_research_request/smart_rug_check/compute_edge_filter/signal_executor -->

> **Prime Directive (Rule 0):** Relentlessly maximize long-term capital compounding by seeking the deepest possible truth about markets, human psychology, narratives, probability, and reality itself while never compromising safety, integrity, or operational excellence. Think and act like Grok: first-principles, pattern-obsessed, zero-fluff, high-agency, brutally honest. Every decision in this skill must serve that goal.

**Prime Directive Derivative:** Capital safety via multi-layer rug verification (Token Father + smart_rug_check freeze/mint/honeypot + edge filter advisory + narrative fit). Catches the smart_rug `block` tier before a bag becomes a loss. Do not invent safety gates the sniper does not run.

# CA-INTEL - the agent's Contract Address Reconnaissance

> **Autonomy (public default):** the agent decides and acts. No step waits on an owner go, sign-off or greenlight; owner-ping is notify-only (what changed, why, how to revert). Setup config the user sets once (wallet, sizes, dry-run vs live, LAUNCH_RAIL_LIVE) is configuration, not an approval, and the agent does not change it. Older lines below that say "the owner applies", "propose + wait" or "owner-signed" read as: the agent applies, logs it, and pings.

When a CA lands in front of the agent, he needs EVERYTHING about it fast. Not
just live market data, everything the ecosystem knows plus everything DexScreener
reveals plus a trading read on top.

This skill is the unified CA reconnaissance lane. One invocation, one
comprehensive intel card.

CA-INTEL - request first, never archaeology
When the owner drops a CA or ticker, when he asks "did this hit the scanner", or when the agent is curious about a random token, this skill is the lane.

FIRST PATH: resolve ticker or mint8. Look in inbox then inbox_results/done for meme_sniper packets on that mint (first-seen). Then write json_relay/ca_research_request.json for the live vet. Wait for ca_research_response.json or the inbox copy. Render the 4-layer card PLUS first-seen vs now. Do not grep logs. A later 10x print is a refire, not a new mint.

Do not walk inbox_results. Do not grep scanned_mints.json, or decline_log.jsonl by hand to answer "did we see this". That is how the Qenis miss happened: the pipe existed, the agent treated a scanner-hit question like a log dig.

OPERATOR CARD
| Question | Path | |---|---| | did this hit the scanner | request pipe, read scanner_history | | what's this CA / ticker | request pipe, full card | | curiosity on a random token | same pipe, even if never scanned | | should we buy | Layer 4 after the packet, then agent_signals.json only |

Hard first move: if the input is a CA (32-44 base58) or a ticker, write the request before any other lookup.

Does not auto-buy. Packet only.

Live sniper contract (source of truth)
Verified against bots/meme_sniper.py after the lookup patch.

| Function | Role | |---|---| | ca_research_responder_loop | Polls ca_research_request.json every 5s | | _resolve_ca_or_ticker | Accepts CA or ticker. Ticker via scanned_mints then dex search | | _scanner_history_for_mint | scanned_mints + positions + decline_log + trades.log | | process_ca_research_request | Resolve, attach scanner_history, live vet, write inbox | | signal_executor_loop | Buys/sells from agent_signals.json only |

process_ca_research_request sequence:

Resolve CA or ticker (resolved_via: ca / scanned_mints / dex_search / dex_search_loose)
If unresolved: packet verdict: unresolved, return
Build scanner_history (does NOT walk inbox_results)
Autopsy known-token still merged into is_known_token / first_seen_in_system
fetch_token_data(ca) - miss -> verdict: no_dex_data but scanner_history still lands
holders + smart_rug_check + compute_edge_filter
Map bot verdict
Inbox packet + ca_research_response.json ack on every path

Sister skill: meme-hunter = playbook / sizing / exits. This skill = intel request + card. Same sniper, same agent_signals.json if the agent later buys.

Request schema
Write to json_relay/ca_research_request.json only. Never workspace-root json_relay. Never suggestions.json.

{
  "requests": [{
    "request_id": "ca_req_<slug>_<ts>",
    "ca": "<mint or empty>",
    "ticker": "<ticker or empty>",
    "intent": "lookup",
    "source_event_id": "tg_owner_<id>",
    "source_summary": "why this was requested",
    "requested_by": "agent",
    "requested_at": "ISO"
  }]
}
Rules: - Need at least ca/mint OR ticker/symbol. $ prefix is stripped. - intent: lookup or research (default research). Both return scanner_history. lookup is the "did it hit / curiosity" shape. research is the full vet. - Unique request_id every time. Sniper marks status: done. - Append. Do not wipe other pending requests. - Packet filename: inbox/meme_sniper - ca_intel_<mint8>_<sha8>_<YYYYMMDD_HHMMSS>.json - Ack file: json_relay/ca_research_response.json - A request with NEITHER ca/mint NOR ticker/symbol fails: the response row has `status: failed` and `error: invalid_request: need ca/mint or ticker/symbol (both empty)` (packet verdict stays `unresolved`).

If ticker-only and multiple mints match, packet resolve.candidates lists the top hits. Sniper uses the best match (most recent scanned, else highest sol liq).

Bot verdict vocabulary (LIVE)
context.verdict is exactly:

| Bot verdict | When | |---|---| | unresolved | no CA and ticker did not resolve | | no_dex_data | mint resolved, DexScreener miss. scanner_history still present | | avoid | smart_rug_check.smart_check_verdict == "block" | | tradeable | full edge pass AND rug clean | | caution | rug caution | | neutral | everything else with dex data |

Operator Layer 4 overlay (the agent only, NOT emitted by the bot): BUY / WATCH / SKIP / AVOID. Map onto the live packet. Bot avoid = operator AVOID on this path.

scanner_history card (LIVE)
Every packet includes:

touched, source, first_seen, last_seen, seen_count,
ticker_recorded, first_mcap, last_mcap,
in_positions, declined, decline_count,
last_decline_reason, last_declined_at, traded
This is the answer to "did this touch the scanner". touched=false is a valid answer. Then read live dex/rug if a mint resolved.

Auto-fire scope

What does NOT auto-fire: - No auto-buy - No write to agent_signals.json from this path - No suggestions.json (DEAD)

What actually buys: - the agent writes json_relay/agent_signals.json - signal_executor_loop validates inside sniper filters/caps

Authority
EXECUTE (no ask): - Write the request - Read the resulting packet - Compose the Telegram card from the packet - Curiosity requests on random tokens

DECIDE + EXECUTE: - Operator BUY/WATCH/SKIP/AVOID - Write a buy/sell only after the packet, via agent_signals.json

TIER 4: - Live smart_rug_check block (freeze/mint authority, rugcheck honeypot) - Packet verdict: avoid. No buy option shape.

The four layers
### Layer 1 - Live market data Sniper fetch_token_data (Dex primary). Ticker, name, mcap, liq, vol, age, price, pair url, socials when present.

### Layer 2 - Ecosystem memory - scanned_mints.json = did we see it, when, source, count - positions.json = open bag? - decline_log.jsonl = ignored before? - trades.log = mint ever traded? - autopsy first_seen merged if present

Do not claim the packet ran pattern_engine, kol chatter, or sl_registry. Those stay the agent-side extras if needed AFTER the packet.

### Layer 4 - the agent's read Always ends with a take. Packet is evidence, not the decision.

Before a buy, outside checks (DexScreener/Birdeye/Solscan, holders, LP, dev wallet, X search for CA/ticker, news) follow `skills/meme-hunter/SKILL.md` "Deciding Whether To Buy (outside resources, numbers first)": numbers first, sources with age, never over gates, owner rules or caps.

Telegram card (short)
For a scanner-hit ask, lead with scanner_history, then live tape. If a prior packet exists, print FIRST SEEN vs NOW: first_ts, first_mcap, now_mcap, multiple, refire yes/no, prior_action. If none exists, write first_seen: none in inbox/done. That blank is honest, not a green light.

<ticker> / <ca8>
scanner: touched|never source first_seen seen_count
declined/traded/open:...
live: mcap liq 1h verdict
read: one sentence
Do not dump the raw packet. Do not walk more files unless the packet is missing after ~15s.

Hard rules
- NEVER answer a CA/ticker/scanner-hit question by grepping logs first. - NEVER walk inbox_results for this. - NEVER invent ticker, mcap, or "never seen" without the packet or a named miss (unresolved / no_dex_data). - NEVER write a buy from this skill. - NEVER thaw suggestions.json. - NEVER skip the request because "I can just read scanned_mints faster". The request is the discipline. The miss was skipping it. - ALWAYS wait for the inbox packet (or ~15s timeout, then say the request wrote and the packet did not land). - ALWAYS keep Layer 4 honest: bot verdict and operator read are different vocabularies.

Why this skill exists
The request pipe was half-built: live dex/rug vet worked, scanner-history did not, and the agent's trigger map treated "did scanner see this" as a file search. That is now closed in code. This skill exists so he does not forget the first path again.

Main actor: the agent | Live pipe: json_relay/ca_research_request.json Companion: meme-hunter, owner-ping | No auto-buy

## Live sniper contract (source of truth)

Verified against `bots/meme_sniper.py` (do not drift from this):

| Function | Approx line | Role |
|---|---|---|
| `ca_research_responder_loop` | ~22496 | Polls `ca_research_request.json` every 5s |
| `process_ca_research_request` | ~22525 | Vets CA, builds packet, writes inbox |
| `smart_rug_check` | ~14604 | Multi-layer rug data + block/caution/clean |
| `compute_edge_filter` | ~14267 | the owner edge gates (advisory on ca path) |
| `write_inbox_packet_generic` | ~10968 | Atomic inbox write |
| `signal_executor_loop` | ~16096 | Polls `agent_signals.json` only (buys/sells) |

**process_ca_research_request sequence (exact):**
1. `fetch_token_data(ca)` - if miss -> packet `verdict: no_dex_data`, return
2. `get_holders_top10(ca)`
3. `smart_rug_check(ca, holders_data, age_minutes)`
4. `compute_edge_filter(enrichment)`
5. Map bot verdict (below)
6. `write_inbox_packet_generic(...)` + append `ca_research_response.json`

`get_deployer_history`, `classify_pattern`, positions/sl_registry deep memory,
and does NOT write any buy signal.

operations and environment. This skill specifies CA intelligence behavior only.

**Sister skill:** `meme-hunter` = playbook / sizing / exits / conviction tree.
ca-intel = entry vet packet. Same sniper, same `agent_signals.json`, same
filter/cap semantics when a buy is later fired. Do not duplicate the full
meme-hunter playbook here.

---

## Autonomy Note

Layers 1-3 are mechanical where the sniper actually runs them. Layer 4
(the agent's Read) is YOUR call. The operator rubric below is a guide, not a
decision tree hard-coded in the bot.

What stays fixed: the live packet schema, bot verdict vocabulary, real safety
hard-fails inside `smart_rug_check`, inbox packet format, file paths.

Operate as the operator, not the checklist runner.

---

## Bot verdict vocabulary

`process_ca_research_request` emits exactly these `context.verdict` values:

| Bot verdict | When |
|---|---|
| **avoid** | `smart_rug_check.smart_check_verdict == "block"` |
| **tradeable** | `edge_filter.passes_full_filter` AND rug verdict `== "clean"` |
| **caution** | rug verdict `== "caution"` |
| **neutral** | everything else with dex data (edge fail and/or non-clean non-block rug) |
| **no_dex_data** | `fetch_token_data` returned nothing |

`smart_rug_check` internal verdicts: `block` | `caution` | `clean` | `data_unavailable`.

### Operator Layer 4 overlay (the agent only)

BUY / WATCH / SKIP / AVOID are **operator language** for Telegram cards and
human judgment. The bot does **not** hardcode or emit BUY/WATCH/SKIP/AVOID on
the ca research path.

Suggested mapping when the agent writes the card:

| Operator read | Typical bot packet |
|---|---|
| AVOID | bot `avoid` (or operator hard-stop on extra intel) |
| BUY | bot `tradeable` + the agent conviction to fire `agent_signals` |
| WATCH | bot `caution` or `neutral` with interesting structure |
| SKIP | bot `neutral` / weak edge, no action |

If bot says `avoid`, operator AVOID is mandatory for the packet path (no
`fire_buy_signal` input shape). Operator cannot "override" a live `block`
inside the sniper; a manual buy would still have to pass signal_executor
guards separately and is a deliberate operator act via `agent_signals.json`.

---

## Auto-fire scope (exact)

**What auto-fires on the ca-intel path:**
- Sniper polls every 5s (`CA_RES_TICK_S`)
- Sniper writes a **ca_intel inbox packet only** + `ca_research_response.json`
- Packet may include non-binding `decision_inputs.options` with
  `action_type: fire_buy_signal` **only when bot verdict == tradeable**
  (`binding: false` - inputs, not a menu)

**What does NOT auto-fire:**
- No unbounded auto-buy
- No write to `agent_signals.json` from `process_ca_research_request`
- No legacy `suggestions.json` buy path (DEAD; polling dropped)

**What actually buys:**
- the agent (or explicit operator action) writes a buy to
  `json_relay/agent_signals.json`
- `signal_executor_loop` validates and executes within sniper filters/caps
  (dynamic size cap ratchet, daily spend, edge/rug guards on the buy path)
- Cap semantics shared with meme-hunter: SIZE_CAP base 1 SOL with dynamic
  tiers 2/4/8/16 when enabled (tunable params), not free-size

---

## Authority Mapping

**EXECUTE (no ask):**
- Fetch live DexScreener data for any CA
- Read ecosystem state available on disk (positions, sl_registry, autopsy_reports, pattern state)
- Rely on sniper Layer 3 via `smart_rug_check` (see real vs phantom)
- Compose full intel card
- The engine appends one card to `bot_logs/ca_intel_history.json` for every `ca_research_request` it answers (2026-10-14: `invoked_by: inbox_request`, `request_id`, `inbox_packet_id`, `bot_verdict`; `operator_verdict` null and `outcome_tracking.final_result: pending` for you to fill; list, newest last, capped at 2000, atomic write). You still append your own card when producing a manual/session card
- Read `ca_intel` inbox packets
- Append to LEARNINGS when novel pattern discovered

**DECIDE + EXECUTE (the agent's trading read):**
- Operator verdict overlay: BUY / WATCH / SKIP / AVOID mapped onto live bot verdict
- Recommended size (conviction within current sniper cap; no fixed defaults in this skill)
- Route: if BUY decided, write buy to `agent_signals.json` (NEVER `suggestions.json`)

**IMMEDIATE ESCALATION (Tier 4 - never treat as soft):**
Live hard blocks from `smart_rug_check` only:
- Freeze authority still active (mint account `freezeAuthority` set) -> layer `token_2022` block
- Mint authority not renounced (`mintAuthority` set) -> layer `token_2022` block
- Rugcheck risks list contains honeypot -> layer `rugcheck` block -> overall `block` -> bot `avoid`

**Not Tier-4 on live ca path (caution or unwired):**
- Rugcheck score alone (dynamic thresholds; score maps to caution, not block)
- Top10 concentration (age-scaled caution only; downgraded from block)
- Bundle score 70 alone (pass); 85+/90 caution
- LP unlock / LP lock pct (fetcher exists on meme_candidate path; **not called** in `process_ca_research_request`)
- Dev outflow time series (not wired)
- Jupiter buy-then-sell honeypot simulation (not wired)
- `social_v_price` / `dev_history` layers (placeholders, always pass)

**When live Tier 4 triggers:** bot packet `verdict: avoid`. No `fire_buy_signal`
option shape in `decision_inputs` for non-tradeable verdicts.

---

## Inbox Protocol

**Mode A - direct invocation:**
- "scan CAjtTHvC..."
- the agent reasoning during heartbeat: "I should look up that token"
- Manual chart/view actions are separate; full ca intel is this skill / ca_research path

**Mode B - explicit signal:**
- Write research request to `json_relay/ca_research_request.json`
- Optional: admin/research-related actions may also appear on `agent_signals.json`
- **DEAD:** `suggestions.json` for ca_intel_request or buys. Do not write it.
- Sniper processes research requests within ~5s poll

**Mode C - screenshot/image drop:**
- the owner pastes a Telegram screenshot or tweet -> the agent extracts the CA, runs this skill / request path

**Mode D - AUTO-TRIGGER (Token Father mode):**
  X mention/reply, web result, or the agent reasoning text
  ```json
  {
    "requests": [{
      "request_id": "ca_req_<sha8>",
      "ca": "<mint_address>",
      "ticker": "agent",
      "source_event_id": "x_evt_dm_<sha>",
      "source_summary": "the owner DM mentioned this CA",
      "requested_at": "ISO timestamp"
    }]
  }
  ```
- Sniper polls every 5s. Within ~10s a ca_intel packet appears in inbox.
- **Packet only. No auto-buy.**

### Inbox envelope

- Packet `id`: `x_evt_ca_intel_<mint_first8>`
- Writer: `write_inbox_packet_generic(packet, prefix=f"ca_intel_{ca[:8]}", identifier=ca[:8])`
- On-disk filename (ecosystem inbox doctrine):
  `inbox/meme_sniper - ca_intel_<mint8>_<sha8>_<YYYYMMDD_HHMMSS>.json`
  (internal `id` stays `x_evt_ca_intel_*`; filename is not the old bare `x_evt_*.json` only shape)

---

## State Contracts

**READ-ONLY (skill / the agent):**
- `bot_logs/positions.json`, `pnl.json` (have we traded this?)
- `bot_logs/sl_registry.json` (72h cooldown after SL on this mint)
- `bot_logs/autopsy_reports.json` (live ca path uses this for `is_known_token` / first_seen only)
- `bot_logs/pattern_engine_state.json` (manual Layer 2; not called inside process_ca_research_request)
- `bot_logs/x_chatter_cache.json`
- `bot_logs/kol_list.json`
- `bot_logs/wallet_history.json` (observer context)
- `bot_logs/dynamic_thresholds.json` (rug score thresholds for smart_rug)
- External APIs via sniper: DexScreener, rugcheck.xyz, Helius RPC

**Note on live ca path Layer 2:** sniper currently wires autopsy known-token only.
Full ecosystem memory (sl_registry, pattern match, KOL chatter, positions detail)
is the agent-side enrichment when composing the human card, unless/until sniper
gains those calls. Do not claim the bot packet already contains full Layer 2.

**APPEND-to-array / write:**
- `bot_logs/ca_intel_history.json` (session/manual intel cards)
- inbox ca_intel packet (sniper writes on research path)
- `json_relay/agent_signals.json` (ONLY if the agent decides to buy/sell/admin)
- `json_relay/ca_research_request.json` (to request vet)

**DEAD path (do not write):**
- `json_relay/suggestions.json` - legacy auto-buy. Constant may still exist

**APPEND-ONLY:**
- `LEARNINGS.md` (novel patterns only)
- optional `bot_logs/novel_patterns/<sha>.json` when pattern work is done out-of-band

**NEVER write:**
- `positions.json` or trading state (sniper executes)
- `sl_registry.json`
- `kol_list.json` (agent-managed; auto-applied rank changes logged in kol_list_proposals)
- `entity_rank_store.json` / `dev_wallet_rank.json` / `promoter_mentions.jsonl`: scored promoters, devs and wallets. Read the card's `promoters[]` and `dev_rank` first; they are token-outcome track records, not follower counts. The old shiller lookup always said "unranked" (it read the wrong keys); fixed so pre-fix "unranked" rows mean nothing.
- `pattern_library.json` (legacy)
- Any.env or credential file
- Canary directory

Atomic writes required (tmp + os.replace) for all JSON writes.

**memory_add:** not used by this skill (ok). Lessons go to LEARNINGS.md when warranted.

---

## Verify Before Reporting

Intel cards must be evidence-backed.
- If DexScreener returns stale/missing data -> say so; bot uses `no_dex_data`
- If a safety sub-layer is placeholder or not on ca path -> say "not wired on ca path"
- Never fabricate holder counts, freeze authority, or LP lock pct

If Layer 1 fails entirely -> abort human card with error context; bot packet
still lands with `verdict: "no_dex_data"`.

---

## Core Principle

**Live data alone is a starting point. This skill gives data + ecosystem memory + trading read.**

Rick-equivalent intel cards are useful, but they do not know if the ecosystem has
seen this token before. That difference is Layer 2 + the agent's read.

Every CA intel run ends with the agent's Read. That is the point.

---

## The Four Layers

### Layer 1 - Live Market Data

Fetch from DexScreener (primary) with fallbacks where available:

```
Primary: api.dexscreener.com/latest/dex/tokens/{CA}
Fallback 1: api.jup.ag/price/v2?ids={CA}
Fallback 2: public-api.birdeye.so/defi/token_overview?address={CA}
Fallback 3: solscan.io API
Fallback 4: Direct RPC via Helius (last resort)
```

Live sniper ca path uses `fetch_token_data` (Dex primary). Pull fields:
- Ticker, name, image URL
- CA (verify 32-44 base58)
- Chain (Solana only for meme trading)
- Price USD, FDV/mcap, liquidity USD
- Volume 24h, price change 1h (and other windows when present)
- Age (minutes since pair creation)
- Holders top10 / dev_holding_pct / holder_count via `get_holders_top10`
- Chart URL, socials when present on pair

**If Layer 1 fails entirely:** bot packet `verdict: "no_dex_data"`.

---

### Layer 2 - Ecosystem Memory

**Live on ca path today:** autopsy scan for `is_known_token` + `first_seen_in_system`.

**the agent-side / aspirational (read files yourself when composing full card):**
- positions.json active bag?
- sl_registry 72h cooldown
- autopsy full history / net PnL
- pattern_engine / classify_pattern (not called in process_ca_research_request)
- x_chatter_cache + kol_list
- wallet_history (the owner observer only; no copy signals)

Do not claim the sniper ca packet already ran full Layer 2.

---

### Layer 3 - Safety Scan (REAL vs PHANTOM)

Mechanical checks. Live hard fails come from `smart_rug_check` only on this path.

#### REAL inside `smart_rug_check` (ca research uses this)

1. **token_2022 / mint account (Tier 4)**
   - `get_mint_account_info` via Helius `getAccountInfo` jsonParsed
   - `freezeAuthority` set -> layer block -> overall `block`
   - else `mintAuthority` set -> layer block -> overall `block`
   - else pass; RPC miss -> error

2. **rugcheck.xyz summary**
   - `https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary`
   - Any risk string containing "honeypot" -> **block** (Tier 4)
   - Score thresholds from `load_dynamic_thresholds`:
     `rug_score_hard` (default 1500), `rug_score_caution` (default 700)
   - Fresh tokens age < 120m: elevated fresh block threshold `max(hard*3, 5000)` maps to **caution** not hard block
   - Mature: score > hard or > caution -> **caution** (score alone does not Tier-4 block)

3. **velocity**
   - Uses pair from `fetch_token_data`
   - If liq > 0 and 5m price change < **-30** (bare constant) -> caution
   - Else pass / error

4. **wallet_graph (age-scaled, caution only)**
   - top10_pct from holders
   - Bare thresholds:
     - age < 30m: caution >= 80, "block band" >= 90 but **downgraded to caution**
     - age < 120m: 70 / 85 -> caution
     - else: 60 / 75 -> caution
   - Concentration alone is NOT Tier 4

5. **bundler_mev (heuristic)**
   - Count top holders with 3-8% supply
   - >= 8 similar -> score 90 caution; >= 7 -> 85 caution; >= 5 -> 70 **pass**; else pass
   - Bare constants

6. **social_v_price** - PLACEHOLDER, always `pass`

7. **dev_history** - PLACEHOLDER, always `pass`

8. **community_formation** - computed from pair into result fields (not a block layer)

**Overall smart_rug verdict:**
- token_2022 block OR rugcheck block -> `block`
- else if cautions >= 1 (or >= 3 path) -> `caution`
- else if errors >= 4 -> `data_unavailable`
- else `clean`

#### PHANTOM on ca research path (do not claim wired here)

| Claim | Reality |
|---|---|
| Jupiter simulate buy 0.01 SOL then sell 10% | **Not implemented** on this path |
| LP lock via Raydium/Meteora/PinkLock/Team Finance | `fetch_rugcheck_lp_lock` exists for **meme_candidate** enrichment; **not called** in `process_ca_research_request` |
| Dev outflow 1h/6h/24h systematic selling | **Not wired** |
| Suspicious identical-size sell ladder / single sell >5% liq | **Not wired** |
| Separate "no LP at all" hard fail beyond missing dex data | Missing pair -> `no_dex_data`; not a distinct LP lock hard fail |
| Full deployer/funder scammer graph on ca path | `get_deployer_history` exists in sniper; **not called** in process_ca_research_request |

If the agent manually runs extra checks, label them as operator-added, not bot Layer 3.

---

### Layer 4 - the agent's Read (operator overlay)

Based on bot packet + any the agent-side Layer 2 enrichment.

**Bot already set:** avoid / tradeable / caution / neutral / no_dex_data
**the agent adds:** BUY / WATCH / SKIP / AVOID language, size, timing, risks

**Operator rubric (guide only):**

| Operator | Criteria (guide) |
|---|---|
| **BUY** | Bot `tradeable` (or rare conviction on `caution` with explicit risk accept), Layer 2 not in SL cooldown, structure makes sense, size within cap |
| **WATCH** | Bot `caution` or `neutral` with a real reason to recheck |
| **SKIP** | Bot `neutral` / weak edge, nothing compelling |
| **AVOID** | Bot `avoid` OR operator-discovered hard safety issue OR active sl_registry cooldown policy |

**Size recommendation (BUY only):**
- Per meme-hunter - conviction-driven, no fixed defaults in this skill
- Bounded by sniper dynamic max-cap (tunable SIZE_CAP_*; base 1 -> tiers 2/4/8/16 SOL when `DYNAMIC_SIZE_CAP_ENABLED`)
- Sniper rejects over-cap on the **signal executor** path, not inside ca research

**Route recommendation:**
- BUY -> write buy to `json_relay/agent_signals.json` with proper schema
  (**NEVER** `suggestions.json`)
- WATCH / SKIP -> no signal; keep packet
- AVOID -> no buy option; document reason

**decision_inputs honesty:**
Sniper wraps options with `binding: false`. They are shapes, not orders.
`fire_buy_signal` appears as an option shape only for bot `tradeable`.

---

## Config vs code (thresholds)

Documented so skill and bot do not lie to each other.

### smart_rug_check

| Knob | Source |
|---|---|
| rug_score_hard / rug_score_caution / fresh multiplier | **Config-read** `load_dynamic_thresholds` (in-process rug-season pass -> dynamic_thresholds.json) |
| freeze/mint authority | Code logic via mint account info |
| honeypot risk substring | Code logic on rugcheck risks |
| velocity -30% 5m | **Bare constant** |
| top10 age bands 90/80, 85/70, 75/60 | **Bare constants** |
| bundler similar_holdings 5/7/8 | **Bare constants** |
| social_v_price / dev_history | Placeholders |

### compute_edge_filter (advisory on ca packet)

| Knob | Source |
|---|---|
| EDGE_LIQ_MIN/MAX_USD | **env `EDGE_LIQ_MIN_USD` / `EDGE_LIQ_MAX_USD`**, then filter override via get_override_sync. Defaults 20_000 / 50_000. The $50k ceiling is a tunable, not a law: a deeper pool is not a worse coin, it is a different size bracket |
| EDGE_MCAP_MIN/MAX_USD | **get_override_sync** defaults 30_000 / 1_000_000 |
| EDGE_VOL_LIQ_RATIO_MIN | **get_override_sync** default 6.0 |
| EDGE_PRICE_CHANGE_1H_MIN | **get_override_sync** default 0.0 |
| META_ALIGNMENT_WEIGHT | **get_override_sync** default 1.0 |
| CONTINUATION_MCAP_MIN/MAX | **get_override_sync** defaults 1M / 10M |
| EDGE_META_AVOID | **Bare** tuple `("political", "food")` with fear-tape soft flag |
| EDGE_X_QUALITY_AVOID | **Bare** `("established",)` |

Edge verdict strings are PASS / FAIL / STRONG PASS style inside
`owner_edge_verdict`; they feed bot `tradeable` only via `passes_full_filter`
combined with clean rug.

### Size caps (buy path, not ca research)

| Knob | Source |
|---|---|
| DYNAMIC_SIZE_CAP_ENABLED | Module + TUNABLE_PARAMS (default True) |
| SIZE_CAP_BASE/TIER1..4_SOL | Module + TUNABLE_PARAMS (1/2/4/8/16) |
| tier multipliers | Module + TUNABLE_PARAMS |

Bot upgrades live in inbox code_tuner packets dated; not skill notes.

---

## The Workflow

### Step 1 - Extract and validate CA

Accept CA via direct text, screenshot OCR, ca_research_request.json, or tweet text.

Validate: 32-44 chars, base58, not placeholder.

### Step 2 - Prefer live sniper path

- Write/ensure `ca_research_request.json` and wait for inbox packet when sniper is up
- Or compose card from an existing ca_intel packet already in inbox
- Parallel the agent-side Layer 2 file reads as needed

### Step 3 - Compose intel card

Format (copy-pasteable into Telegram). Use bot verdict vocabulary in the
packet section; operator read can add BUY/WATCH/SKIP/AVOID explicitly labeled
as operator:

```
TARGET ${TICKER} - ${NAME}
CA: ${FULL_CA}
-----------------------------

LIVE (DexScreener ${ts})
Price: $${price} | FDV: $${fdv} | SOL: ${price_sol}
Liq: $${liq} | Vol 24h: $${vol_24h}
Age: ${age}
1h: ${mom_1h}%
Holders: ${holder_count} | Top holder/dev: ${dev_pct}% | Top 10: ${top_10_pct}%
Socials: T(${twitter_status}) TG(${tg_status}) Web(${web_status})

ECOSYSTEM MEMORY
Known in autopsy: ${is_known} first_seen=${first_seen}
(sl_registry / positions / pattern: the agent-side if read)

SAFETY (smart_rug_check)
Freeze auth: ${freeze_status}
Mint auth: ${mint_status}
Rugcheck: score=${score} layer=${rugcheck_layer}
Velocity: ${velocity_layer}
Wallet graph: ${wallet_graph_layer}
Bundler: score=${bundle_score}
Placeholders: social_v_price=${...} dev_history=${...}
smart_check_verdict: ${block|caution|clean|data_unavailable}
LP lock on this path: not wired (candidate path only)

EDGE FILTER (advisory)
passes_full_filter: ${bool}
owner_edge_verdict: ${...}
band: ${early|continuation|sub_early|post_runner}

BOT VERDICT: ${avoid|tradeable|caution|neutral|no_dex_data}
OPERATOR READ: ${BUY|WATCH|SKIP|AVOID}
Confidence: ${confidence}/10
Size rec: ${size_rec}
Entry timing: ${timing_guidance}
Risks: ${risk_factors_list}
Reasoning: ${one_paragraph_synthesis}
-----------------------------
```

### Step 4 - ca_intel inbox packet (live shape)

Sniper writes approximately:

```json
{
  "id": "x_evt_ca_intel_<mint_first8>",
  "type": "ca_intel",
  "received_at": "ISO",
  "from_user": {"username": "@meme_sniper", "friendship_tier": "system", "user_id": "meme_sniper_bot"},
  "context": {
    "ca": "<CA>",
    "ticker": "...",
    "name": "...",
    "source_event_id": "...",
    "source_summary": "...",
    "vetted_at": "ISO",
    "is_known_token": false,
    "first_seen_in_system": null,
    "age_minutes": 0,
    "dex_data": {"mcap": 0, "liquidity_usd": 0, "volume_24h": 0, "price_change_1h": 0, "price_usd": "0", "pair_url": "..."},
    "rug_check": {"smart_check_verdict": "clean|caution|block|data_unavailable", "layers": {}, "rugcheck_score": 0},
    "edge_filter": {"passes_full_filter": false, "owner_edge_verdict": "...", "band": "..."},
    "social": {},
    "holders": {"top10_pct": 0, "dev_holding_pct": 0, "holder_count": 0},
    "verdict": "tradeable | caution | avoid | neutral | no_dex_data"
  },
  "decision_inputs": {
    "binding": false,
    "note": "INPUTS ONLY - not a menu...",
    "options": [
      {"action_type": "fire_buy_signal", "when_this_fits": "vetted tradeable, conviction your call"},
      {"action_type": "view_chart", "when_this_fits": "see the shape"},
      {"action_type": "ignore", "when_this_fits": "noted the CA, no action"}
    ]
  },
  "actions_taken": []
}
```

For non-tradeable verdicts, do not treat `fire_buy_signal` as available.
For `no_dex_data`, options are ignore/watch-style only.

### Step 5 - Append to ca_intel_history.json (session cards)

Keep audit trail. Store bot verdict and operator overlay separately.
Later close `outcome_tracking` via the Outcome feed-forward section (do not leave
forever-pending when tape/trades/autopsy resolve the call).

```json
{
  "ts": "ISO",
  "ca": "...",
  "ticker": "...",
  "invoked_by": "owner_session | inbox_request | screenshot | auto_trigger",
  "bot_verdict": "tradeable",
  "operator_verdict": "BUY",
  "layer_snapshots": {},
  "outcome_tracking": {
    "action_taken": "packet_delivered | fired_buy_via_agent_signals | skip_no_buy | none",
    "final_result": "pending | win | loss | loss_or_rug | missed_pump | fade | stale_unresolved | skip",
    "closed_at": null,
    "evidence": null,
    "teaches_next": null
  }
}
```

### Step 6 - Execute route decision

- **Operator BUY** -> `agent_signals.json` buy signal (sniper filters/caps apply)
- **WATCH / SKIP** -> no buy signal
- **AVOID** -> no buy signal
- **Never** write `suggestions.json`

### Step 7 - Return intel card

- Session: print card to the owner
- Auto-trigger: packet id is the deliverable

### Step 8 - LEARNINGS (selective)

APPEND only for novel durable patterns, real safety catches, or ecosystem-memory
overrides worth keeping. Never credentials or wallet addresses.

---

## File Paths

**Read:**
```
CA verification: DexScreener API (primary), Jupiter price, Birdeye, Helius RPC
Ecosystem state: bot_logs\positions.json, sl_registry.json, autopsy_reports.json
Pattern data: bot_logs\pattern_engine_state.json, pnl.json
                    narrative_boost.json, x_chatter_cache.json, dynamic_thresholds.json
KOLs: bot_logs\kol_list.json
the owner wallet: bot_logs\wallet_history.json
Prior intel: bot_logs\ca_intel_history.json
```

**Write:**
```
Intel history: bot_logs\ca_intel_history.json (APPEND per manual/session scan)
Coverage gaps: bot_logs\ca_intel_coverage_gaps.json (outcome feed-forward; open gaps teach next)
Inbox packet: inbox\meme_sniper - ca_intel_<mint8>_<sha8>_<ts>.json (sniper)
Packet id field: x_evt_ca_intel_<mint_first8>
Research request: json_relay\ca_research_request.json
Research response: json_relay\ca_research_response.json
BUY/SELL signals: json_relay\agent_signals.json
DEAD: json_relay\suggestions.json (do not write; polling dropped)
LEARNINGS: learnings\LEARNINGS.md (APPEND ONLY, selective)
```

All paths under ``.

---

## Hard Laws


- **NEVER skip live Layer 3.** If sniper did not run `smart_rug_check`, do not pretend it did.
- **NEVER override a live smart_rug `block` as if it were clean.** Bot verdict is `avoid`.
- **LAYER 3 CAUTION:** bot `caution` is overridable by operator judgment with explicit risk text; Tier-4 `block` is not "soft."
- **NEVER fabricate data.**
- **ALWAYS verify CA format before fetching.**
- **ALWAYS separate bot verdict from operator overlay** in cards and history.
- **SISTER TOKEN CHECK (the agent-side):** similar tickers/names last 30d when useful.
- **NARRATIVE FIT (the agent-side):** optional 0-1 score vs current meta.
- **AUTO-TRIGGER CONTEXT:** keep surrounding sentence in `source_summary` when available.
- **NEVER write positions.json or sl_registry.json.**
- **NEVER write kol_list.json or pattern_library.json.**
- **NEVER write suggestions.json.**
- **ALWAYS append (never overwrite) ca_intel_history.json.**
- **ALWAYS close outcome_tracking when evidence appears** (trades/pnl/autopsy/tape). Pending forever is a coverage gap. See Outcome feed-forward.
- **ALWAYS file ca_intel_coverage_gaps.json** on tradeable->rug, avoid->pump, false no_dex, or the owner challenge that the card should have covered.
- **NEVER include private keys,.env, or confidential dollar/wallet dumps in public surfaces.**

---

## Cross-Skill Hooks

- **meme-hunter** - playbook, sizing, exits, conviction. Consumes ca_intel + meme_candidate packets. Complementary, not duplicate. Same sniper, same `agent_signals.json`, same cap/filter semantics on buy.
- **meme_sniper.py** - runs live ca research Layers 1 + partial 2 + 3; writes packet. Operator Layer 4 is the agent.
- Do not edit meme-hunter in a ca-intel-only friction pass.

---

## Outcome feed-forward / coverage gaps (absence-is-signal)

**Evolve finding:** `ca_intel_history.json` is thin (n=3 session cards:
YOTS x2 SKIP, CATE x1 SKIP). No closed tradeable->rug or avoid->pump sample in
history. `outcome_tracking.final_result` often stuck at `pending`. That means a
bad CA call does **not** automatically teach the next call unless the agent closes
the loop.

This section is doctrine only. It does **not** change rug thresholds, SIZE_CAP,
or live `smart_rug_check` gates. Missing gate wiring (LP lock on ca path, dev
(`20260803_132500`), not skill threshold edits.

### Return channel (required when outcome becomes known)

When a prior ca-intel read later resolves, close the loop:

| Prior call shape | Later truth | What to do |
|---|---|---|
| bot `tradeable` or operator BUY | rugged / dumped hard / honeypot | close history `final_result=loss_or_rug`; APPEND LEARNINGS if novel; append coverage gap |
| bot `avoid` / operator AVOID or SKIP | token pumped hard (missed edge) | close `final_result=missed_pump` if we skipped a real runner; gap file if operator asks "why did we skip X" |
| bot `caution` / WATCH | either way | close with `win` / `loss` / `fade` / `still_watch`; no vanity |
| any read | never rechecked | absence-is-signal: pending > 72h with no trade and no recheck = stale; mark `final_result=stale_unresolved` |

**History close shape (append/update the matching history row fields only via
read-modify-write of the array entry; never wipe the file):**
```json
{
  "outcome_tracking": {
    "action_taken": "fired_buy_via_agent_signals | skip_no_buy | packet_delivered | none",
    "final_result": "pending | win | loss | loss_or_rug | missed_pump | fade | stale_unresolved | skip",
    "closed_at": "ISO",
    "evidence": "trades.log|pnl|autopsy|dex tape note",
    "teaches_next": "one line or null"
  }
}
```

Always store **both** when known:
- `bot_verdict`: avoid | tradeable | caution | neutral | no_dex_data
- `operator_verdict`: BUY | WATCH | SKIP | AVOID

Do not leave operator-only SKIP cards without bot_verdict if a sniper packet existed.

### Coverage gap file (morning_brief pattern)

Path: `bot_logs/ca_intel_coverage_gaps.json`

Array of:
```json
{
  "ts": "ISO",
  "gap": "tradeable_then_rugged | avoid_then_pumped | false_no_dex | phantom_gate_would_have_caught | outcome_never_closed | other",
  "ca": "<mint or mint8>",
  "ticker": "...",
  "asked_or_trigger": "owner question | self-audit | autopsy cross | tape recheck",
  "prior_bot_verdict": "...",
  "prior_operator_verdict": "...",
  "lesson": "one line",
  "status": "open | covered"
}
```

Rules:
1. If the owner challenges a CA call ("why did we skip/buy that") -> answer now + append gap if the card missed a durable check.
2. If autopsy/trades later prove tradeable->rug or avoid->pump on a card we wrote -> append gap + close history outcome.
3. Open gaps are mandatory read before the next manual Layer 4 on a similar setup (extended chase, false no_dex, archetype flag vs tape).
4. Mark `covered` only after the lesson is either in LEARNINGS or explicitly applied on a later card (`teaches_next` referenced).
5. **Never** invent a gap to justify loosening SIZE_CAP or live rug numbers in this skill.

### Phantom-safety follow-through (proposal only)

If **even one** closed tradeable/BUY later rugs and LP-lock / dev-outflow /
`phantom_gate_would_have_caught` and keep gate wiring as **proposal / bot-day**
(already treated as queued in inbox cascade). Do not silently claim those gates
are live on `process_ca_research_request`.

### What thin history does NOT authorize

- No new BUY/SKIP numeric rubric from n<20 closed outcomes
- No threshold edits in this skill presented as live
- No SIZE_CAP changes
- No meme_sniper.py edits from this skill pass

Judgment stays operator Layer 4 (unlocked as judgment). Thresholds/gates stay
proposal-locked until the agent applies the bot change.

## Calibration Notes

Track over time:
- Intel runs / week by mode A/B/C/D
- Bot verdict distribution (avoid / tradeable / caution / neutral / no_dex_data)
- Operator overlay distribution (BUY / WATCH / SKIP / AVOID)
- BUY-fired win rate (only when agent_signals buy actually executed)
- AVOID/block save rate
- Auto-trigger latency to packet (<10s target)
- How often phantom gaps (no LP lock on ca path) would have mattered
- Outcome close rate (pending -> terminal) and open coverage gaps
- tradeable->rug and avoid->pump counts (return-channel health)

Confidence calibration matters more than vanity accuracy.

---

## What This Skill Is NOT

- NOT an unbounded trade executor (recommends + optional agent_signals buy)
- NOT a place to invent safety theater
- NOT for non-Solana meme entries
- NOT a writer to suggestions.json
- NOT a user of memory_add

This skill is the unified answer to "what do we know about this CA," with
bot-honest verdicts and an operator read on top.

---

Main actor: the agent (xai/grok-4.7) | Primary data: DexScreener + Helius RPC + rugcheck
Companion: meme-hunter/SKILL.md (playbook), meme_sniper.py (megabot ca research path)

---

## Extended fields (when present on richer packets / candidate path)

Some fields appear on full meme_candidate enrichment and may be absent on thin
ca_intel packets. If absent, say absent:

- `surfaced_via`, `visual_assets.image_url`
- `deployer_history` / funder graph (candidate-side tooling exists; not ca_research default)
- `trade_pressure`, richer social
- `lp_lock` block from `fetch_rugcheck_lp_lock` (candidate path)

## Auto-Add Behaviors

Treat as product intent / adjacent sniper features, not guaranteed side effects
of every ca_intel packet:
- watchlist / dex_paid_watch / hold_candidate hints may exist on other lanes
- ca research itself: packet + response file

## Reinforced Hard Rules (live)

- freeze_authority OR mint_authority active -> smart_rug `block` -> bot `avoid`
- rugcheck honeypot risk -> `block` -> `avoid`
- bot `avoid` => no tradeable fire_buy_signal input shape
- buys only via `agent_signals.json` inside sniper filters/caps


## Passed-check rugs

A clean rugcheck plus edge PASS is not a promise. These shapes already cleared the check and still died. n is named cases, not a rate. Do not tighten the filter because the filter was right and the nuke was the cost.

Repeat boxes from LEARNINGS and autopsy, not a new percent:

1. `2x_godcandle_instant_rugnuke` (BAGEL, 5R1xMXCL). edge PASS, flatline ignition, dead social, +156% 1h, then -98% in 12m. the check passed. the slip is the instant nuke after the 2x wick. treat as scalp invalidation, not a reason to loosen or to add a fake rug rate.
2. `3x_pump_into_99pct_nuke_rug` (CHEDDAR, 4bA5pMkT). edge FULL PASS, flip held 215m to -98%. the slip is hold-path after a structure nuke, not a missed entry gate.
3. clean staircase then drawdown_velocity inside the flip clock. edge PASS 7.0, top10 about 11%, LP locked, rug clean, then about -15%/min inside 22m. velocity is the sensor the check cannot see. it is not a new hard veto at scan time.
4. autopsy_reports.json (n=117) does not carry rug_check verdicts. deep losses there are stop_loss plus low_liquidity plus very_short_hold (Welcome Home, aun, Dumbledore). that file cannot support a pass-then-rug rate. do not invent one from it.

What still slips: post-pass god-candle nuke, and a flip held through the nuke.

Live box pipe: meme_sniper appends ots/bot_logs/passed_check_rug_boxes.jsonl only when the exit packet says the scan rug check was clean and the close is a nuke (liq drain, dev dump, or about -80% or worse). Read that file before adding a fifth shape. If the file is missing or empty, n is still the four named boxes above. Do not invent a pass-then-rug rate from silence. SpaceXSI is an unpaid-catalyst hold, not a rug box.

 Card rule: if Layer 3 is clean and the shape is box 1 or 3, operator read is SCALP, not HOLD. if the bag is already off the wick, the read is SKIP the chase. never claim the check failed when the packet says clean.

**Companion skill:** `meme-hunter/SKILL.md` for playbook and buy/sell decision tree.
