# Skills

The skills are the agent's playbook. The bots produce data and packets; the skills tell the agent how to read them, decide and act. Each skill is a `SKILL.md` with a short front-matter header (name, version, description) and the full instructions below it.

## Load order

1. **`meme-hunter`** (core, always loaded): trading doctrine for meme_sniper (buy/pass, sizing, SL/TP, flip vs hold, the Gork Standard for holds, launches, owner review cards). Very long; load it in parts (below).
2. **`ca-intel`**: whenever a contract address shows up (owner drop, screenshot, chat, web). Produces the intel card and routes the CA to the sniper for vetting.
3. **`forensics`**: after closes and on weekly reviews. Autopsies of closed trades and missed runners; writes proposals, never edits live filters.
4. **Sub-skills**, loaded when their packets or tasks come up:

| skill | load when |
|---|---|
| `sub-skills/warden` | security_warden packets: wallet anomalies, integrity, crashes, sniper-down pings |
| `sub-skills/code-monitor` | code_tuner packets about the bots' code and config |
| `sub-skills/autoagent` | overseer reports, the daily thesis, ecosystem audits, owner commands (`/roast`, `/recap`, `/autopsy`) |
| `sub-skills/x` | anything sourced from X (x_intel, scraper output, CAs or links seen on X) |
| `sub-skills/owner-ping` | any time you notify the owner |
| `sub-skills/morning-brief` | the daily brief to the owner |
| `sub-skills/learnings-summarizer` | the nightly learnings distill |
| `gork-lore` | $GORK, its CAs or community come up, copycat checks, or a hold scored against the default benchmark |
| `_templates/token-lore` | template only: the agent copies it to `skills/<ticker>-lore/` when the owner sets a custom hold benchmark (local, git-ignored) |

Before acting on any trade, also read `rules/rules.md` (the owner's rules; they override skill defaults but never the hard safety gates).

All of these show in the console under **6 Console → 4 Skills** (including `gork-lore` and `_templates`).

`automations/` has one prompt per inbox lane and says which skill each lane uses.

## Loading meme-hunter in parts

`skills/meme-hunter/SKILL.md` is too long to keep in context at once. Find sections by their `##` headings:

1. **Always:** the front matter, "Owner rules come first" and "Current ruleset" (the top of the file). The Current ruleset wins on any conflict.
2. **For a buy/pass decision:** "reading a meme_candidate packet", "DUAL-GATE + PROJECTION MAP", "ARCHETYPES ARE MEASURED PRIORS", "sizing discipline", "the money".
3. **For open positions:** "exit/sizing model", "EXIT RETURN-CHANNEL DOCTRINE", "position modification, when to use which", "position-mod cheat sheet", "Layoo ratchet", "DCA LAW".
4. **For holds:** "FLIP VS HOLD", "convert flip → hold", "The Gork Standard: hold strength", "THE TREASURY", "THE HOLDINGS BRIDGE".
5. **For packet plumbing:** "the actions the agent can fire", "signal contract", "packet filename doctrine", "packet TTL summary", "meeting files", "cadence control is a decision lane".
6. **For launches:** "Launch (own tokens via launch_rail)" (and `docs/LAUNCH_RAIL.md`).
7. **For owner cards:** "Owner review cards".

Read the rest once during setup (SETUP.md section 8) so you know what's there.

## Sizes, default exits, learning mode and paper mode

SETUP.md sections 4.1 and 4.2. You may tune `SNIPER_BUY_SIZE_SOL`, `SNIPER_DEFAULT_SL_PCT`, `SNIPER_DEFAULT_TP_PCT` and the `SNIPER_LEARN_*` knobs in `bots/tuner/meme_sniper_filter.json` (the engine uses the knob; a changed `bots/.env` value from the owner overwrites it). Learning mode (`SNIPER_LEARNING_MODE`) adjusts them in small logged steps; review `bot_logs/learning_log.jsonl` weekly with the forensics skill. In paper mode (`SNIPER_PAPER_MODE=1`) nothing is sent, results are in `bot_logs/paper/`, and every owner ping starts with `[PAPER]`; never switch paper to live without the owner's explicit OK.

## Adding a chain

Solana is the only chain that trades today. To add another, follow SETUP.md section 14 "Adding a chain": implement `bots/chains/base.py` (feed, quote, buy, sell, balance, safety check), add it to the registry behind its own `CHAIN_<NAME>_ENABLED` switch (off by default), run the testing checklist and start with a tiny size from a fresh burner. The skills' doctrine is written for Solana; check every number before using it on another chain.

## Changing skills

The skills ship tuned for a cautious, newer owner. Change them only with the owner, never loosen the hard gates, and record every change in `learnings/LEARNINGS.md` (SETUP.md section 8).
