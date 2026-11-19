---
name: token-lore-template
description: >
  Opt-in template for a local hold-benchmark lore file. The owner copies it.
  It does not load on its own, does not trade, and does not edit bots/.
disable-model-invocation: true
alwaysApply: false
---

> **Safety contract.**
> 1. Opt-in only. This is a template. Copy it locally only when the owner asks for a custom benchmark. A ticker or address is not a trigger.
> 2. Suggest-only. Lore is not a trade. No trade without fresh owner approval.
> 3. Never edit bots/. Leave the filled copy out of git. A change to the engine is a diff in `owner_inbox/` for the owner. The owner applies it.
> 4. Do not invent facts. Mark anything unverified. Do not sign. Do not submit a launch.

# Hold-benchmark lore template

One paragraph: what the token is, and that this file recognizes public lore. It does not tell anyone to buy.

## Benchmark

The owner chose this token as a hold ceiling on a stated date, for a stated reason. If the benchmark file is missing, the engine keeps its shipped example (`skills/gork-lore`). Scoring a hold is a suggestion. It is not an order.

## Canon

List only facts the owner checked: mint, date, launch type, and insider share. Any other mint claiming this name is a copycat unless the owner listed it here.

## Voice

How the project's real accounts sound, so fakes stand out. No keys. No claim links.
