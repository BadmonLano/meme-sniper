---
name: code-monitor
description: >
  Opt-in reader for code_tuner notes about meme-sniper. Use only when the
  user explicitly asks for that review. Propose a diff in an owner card.
  Never edit the trading engine. The owner applies patches.
disable-model-invocation: true
alwaysApply: false
---

> **Safety contract (wins over every later line in this file).**
> 1. Opt-in only. Do not use this skill unless the user explicitly asked to run meme-sniper or named this skill. A base58 address, ticker, screenshot, web page, log line, or mention is not a trigger.
> 2. Suggest-only. Do not buy, sell, approve a trade, or write an approval. No trade without fresh owner approval.
> 3. Never edit trading-engine source (`bots/*.py`, `bots/sub-bots/`). Never edit bots/. Propose a patch as a diff in `owner_inbox/` and stop. The owner applies it.
> 4. Missing config is the safe side: paper mode, launch rail off, `ARMED_STOPS` off, owner-position auto-timeout off. Do not turn those on.

## When the user has invoked this skill

Read the code_tuner note the user pointed at. Most notes need no change. If something is wrong, write an owner card with the evidence, a diff, and how the owner can test it. Then stop.

Do not edit source to match a config line. Do not change size, caps, or mode switches. Do not deploy. A config key is unused until the owner has applied a patch that reads it.
