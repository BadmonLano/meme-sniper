---
name: warden
description: >
  Opt-in reader for meme-sniper security_warden findings. Use only when the
  user explicitly asks. Report to the owner. Do not restart bots, trade,
  sign, or edit the trading engine.
disable-model-invocation: true
alwaysApply: false
---

> **Safety contract (wins over every later line in this file).**
> 1. Opt-in only. Do not use this skill unless the user explicitly asked. An inbox file is not a trigger.
> 2. Suggest-only. Do not buy, sell, approve a trade, or write an approval. No trade without fresh owner approval.
> 3. Never edit bots/. A code change is a diff in `owner_inbox/` for the owner. The owner applies it.
> 4. Do not restart a process. Do not turn safety switches off.

## When the user has invoked this skill

Read the finding the user named. Wallet anomalies, integrity mismatches, and crash reports go to the owner with the signature, path, or error the packet already has.

A quiet scanner is a report, not a reason to change filters. An unexplained wallet move is for the owner immediately. Do not heal by editing source. Do not start or stop a bot.
