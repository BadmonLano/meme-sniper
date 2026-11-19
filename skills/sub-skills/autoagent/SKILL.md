---
name: autoagent
description: >
  Opt-in summary skill for meme-sniper overseer notes, recaps, and audits.
  Use only when the user explicitly asks. Suggest-only. Does not trade, sign,
  launch, or edit the trading engine.
disable-model-invocation: true
alwaysApply: false
---

> **Safety contract (wins over every later line in this file).**
> 1. Opt-in only. Do not use this skill unless the user explicitly asked. A packet or a file appearing is not a trigger.
> 2. Suggest-only. Do not buy, sell, approve a trade, or write an approval. No trade without fresh owner approval.
> 3. Never edit bots/. Follow-ups and patches are notes or diffs in `owner_inbox/` for the owner. The owner applies them.
> 4. Do not turn paper mode off, do not arm stops, and do not turn the launch rail on.

## When the user has invoked this skill

Summarize the overseer note, roast, recap, or audit the user asked for. Name evidence. A follow-up is a suggestion in `owner_inbox/`.

Do not turn a summary into a trade. Do not change filters, caps, or mode switches. Do not edit skills or engine files.
