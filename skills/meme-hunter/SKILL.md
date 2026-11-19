---
name: meme-hunter
description: >
  Opt-in suggest-only playbook for meme-sniper. Use only when the user
  explicitly invokes meme-sniper or names this skill. A base58 address,
  ticker, screenshot, log, or file is not a trigger. Suggestions for the
  owner. Never edit the trading engine.
disable-model-invocation: true
alwaysApply: false
---

> **Safety contract (wins over every later line in this file).**
> 1. Opt-in only. Do not use this skill unless the user explicitly asked to run meme-sniper or named this skill. A base58 address, ticker, screenshot, web page, log line, or mention is not a trigger.
> 2. Suggest-only. Signals are suggestions for the owner. Do not buy, sell, approve a trade, or write an approval. No trade without fresh owner approval. With the shipped default (`AGENT_MODE=suggest`) the bot holds trade signals until the owner approves them.
> 3. Never edit trading-engine source (`bots/*.py`, `bots/sub-bots/`). Never edit bots/. Propose a patch as a diff in `owner_inbox/` and stop. The owner applies it.
> 4. Missing config is the safe side: paper mode, launch rail off, `ARMED_STOPS` off, owner-position auto-timeout off. Do not turn those on. Do not sign. Do not submit a launch.

## When the user has invoked this skill

Read `rules/rules.md` if it exists. Owner rules can be stricter than these notes. They do not waive this contract or the engine's hard gates.

A candidate card is a note for the owner: pass, watch, or a buy idea with a size and levels. Do not write an approval. Do not re-send a suggestion the owner has not answered.

Open positions: suggest stop-loss or take-profit changes in a note. A sell is a suggestion. A breached level sells on its own only if the owner already set `ARMED_STOPS=1`, which ships off.

## Owner review cards

An owner review card is a question. Reply with a note in `owner_inbox/`. Any trade idea still needs fresh owner approval. Do not edit `bots/`.

## Hold benchmark

Holds are scored against the owner's benchmark. The shipped example is lore in `skills/gork-lore`, with no contract address in the repo. Suggesting a different benchmark is a note for the owner. Do not buy the benchmark.

## Launches and league mode

A launch or a league session is an idea in an owner card. Do not flip `LEAGUE_MODE`, `LAUNCH_RAIL_ENABLED`, `LAUNCH_RAIL_LIVE`, paper mode, or armed stops.

## Filter or engine ideas

One hypothesis, as a diff in `owner_inbox/`, then stop. Do not change filter files or caps. A quiet day needs no trade. Do not chase a count of buys.

In paper mode, start every owner note with `[PAPER]`.
