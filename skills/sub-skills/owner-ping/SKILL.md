---
name: owner-ping
description: >
  Opt-in format for notes from meme-sniper to the owner. Use only when the
  user explicitly asked for a note. A ping is not a trade and not an engine edit.
disable-model-invocation: true
alwaysApply: false
---

> **Safety contract (wins over every later line in this file).**
> 1. Opt-in only. Do not use this skill unless the user explicitly asked to notify the owner.
> 2. Suggest-only. A ping does not approve or send a trade. No trade without fresh owner approval.
> 3. Never edit bots/. Patches in a ping are diffs in `owner_inbox/` for the owner. The owner applies them.
> 4. No secrets, keys, or wallet private material. In paper mode, start the note with `[PAPER]`.

## When the user has invoked this skill

Write one specific note: what happened, the file or number the owner can check, and the decision needed, or none. Do not repeat the same note within the hour. A stop the owner chose is not an alert.

The file in `owner_inbox/` is the record. Optional chat delivery is a short pointer to that file, only if the owner already configured it.
