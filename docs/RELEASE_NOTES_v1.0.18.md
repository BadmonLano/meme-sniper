# v1.0.18 — opt-in skills

This release shortens the skills and makes them agree with the safety contract. The trading engine, the shipped defaults, and the MIT license are unchanged. Nothing here turns trading on.

## Skills

- No skill is core, and none loads unless you explicitly invoke the sniper or name that skill.
- One rule: suggest-only. Patches are diffs in `owner_inbox/` for the owner. No trade without fresh owner approval. The agent does not edit `bots/`.
- The long duplicated playbooks are gone. `skills/` is well under 40KB.
- Paper mode, suggest mode, armed stops, the owner-position timeout, and the launch rail still ship off (paper and suggest are the defaults when their env vars are missing).

## Tests

`bots/tests/test_skill_opt_in.py` fails if skill text grows back to 40KB, or if an always-on marker or an auto-trade / self-patch phrase returns.
