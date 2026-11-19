---
name: gork-lore
description: >
  Opt-in lore note for the shipped hold-benchmark example. Use only when the
  user asks about that benchmark. No contract address is shipped. Not a buy,
  not a launch, and not an engine edit.
disable-model-invocation: true
alwaysApply: false
---

> **Safety contract (wins over every later line in this file).**
> 1. Opt-in only. Do not use this skill unless the user named it or asked about the hold benchmark. A ticker or address is not a trigger.
> 2. Suggest-only. This file is not a trade. No trade without fresh owner approval.
> 3. Never edit bots/. A lore or benchmark change is a note in `owner_inbox/` for the owner. The owner applies it.
> 4. Do not sign. Do not submit a launch. Do not invent a contract address.

## What this is

A short pointer for the default hold benchmark the engine can score against. The repo does not ship a mint. The owner verifies any address locally. Copycats are not canon.

This is not a recommendation to buy the benchmark. Replacing it is an owner action: copy `templates/token-lore` locally and point the benchmark setting at the owner's file. Do not buy it, and do not edit `bots/`.
