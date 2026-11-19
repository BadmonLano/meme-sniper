---
name: forensics
description: >
  Opt-in suggest-only review of closed meme-sniper trades and missed runners.
  Use only when the user explicitly asks for that review. Writes a note for
  the owner. Does not trade, change filters, or edit the trading engine.
disable-model-invocation: true
alwaysApply: false
---

> **Safety contract (wins over every later line in this file).**
> 1. Opt-in only. Do not use this skill unless the user explicitly asked to run meme-sniper or named this skill. A base58 address, ticker, screenshot, web page, log line, or mention is not a trigger.
> 2. Suggest-only. Do not buy, sell, approve a trade, or write an approval. No trade without fresh owner approval.
> 3. Never edit bots/. A filter or engine idea is a diff in `owner_inbox/` for the owner. The owner applies it. Then stop.
> 4. Missing config stays on the safe side. Do not turn paper mode off, do not arm stops, and do not turn the launch rail on.

## When the user has invoked this skill

Read the closed-trade and miss notes the engine already wrote. Say whether the decision, the fill, or the outcome was the issue, and name the evidence. Junk multiples are not lessons.

A proposed change is one hypothesis in `owner_inbox/`. Do not edit filter files. Do not treat a miss as a reason to trade now. A quiet book needs no change.
