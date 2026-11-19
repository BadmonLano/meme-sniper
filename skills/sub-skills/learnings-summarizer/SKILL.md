---
name: learnings-summarizer
description: >
  Opt-in nightly distill of meme-sniper learnings. Use only when the user
  explicitly asks for that distill. Edits the learnings note only as a
  suggestion. Does not trade or edit the trading engine.
disable-model-invocation: true
alwaysApply: false
---

> **Safety contract (wins over every later line in this file).**
> 1. Opt-in only. Do not use this skill unless the user explicitly asked for the distill.
> 2. Suggest-only. A lesson is not a trade. No trade without fresh owner approval.
> 3. Never edit bots/. A rule that would change gates or code is a diff in `owner_inbox/` for the owner. The owner applies it.
> 4. Do not turn safety switches off. Do not sign. Do not submit a launch.

## When the user has invoked this skill

Compare the learnings file with its backup before changing it. If sections vanished, restore them and tell the owner. Archive the raw window, fold repeated lessons into the summary sections, and leave a one-line history of the run.

Do not promote a lesson into a gate change or a buy. Quiet input is a logged quiet day, not a prompt to trade.
