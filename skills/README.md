# Skills

Opt-in notes for an owner who explicitly invokes meme-sniper. No skill is core. None loads on its own, and none loads because a base58 address, ticker, screenshot, log line, or file appeared.

Use a skill only when the user explicitly invokes the sniper or names that skill.

## One rule

Suggest-only. Patches go as diffs to `owner_inbox/` for the owner. No trade without fresh owner approval. Never edit `bots/`.

Paper mode, suggest mode, armed stops, the owner-position timeout, and the launch rail stay at their shipped defaults unless the owner changes them. Do not sign. Do not submit a launch. Do not write an approval.

## Opt-in list

| skill | use only when the user explicitly asks |
|---|---|
| `meme-hunter` | to review sniper cards or open positions with the sniper |
| `ca-intel` | to vet one contract address with the sniper |
| `forensics` | for a closed-trade or missed-runner review |
| `gork-lore` | about the default hold-benchmark lore |
| `sub-skills/warden` | to read a security_warden finding |
| `sub-skills/code-monitor` | to review a code_tuner note |
| `sub-skills/autoagent` | for a roast, recap, or ecosystem summary |
| `sub-skills/x` | to read X-sourced intel the user asked about |
| `sub-skills/owner-ping` | to write a note to the owner |
| `sub-skills/morning-brief` | for the daily brief the user asked for |
| `sub-skills/learnings-summarizer` | for the nightly learnings distill the user asked for |
| `../templates/token-lore` | template only; the owner copies it locally for a custom benchmark |

`automations/` holds lane prompts. They run only after the owner saves them. They follow the same rule.

## Settings

Sizes, stops, hours, and mode switches are owner settings in `bots/.env`. Do not change them. A proposal is a diff in `owner_inbox/`.

Solana is the only chain that trades today. Another chain is an owner change, proposed the same way. Do not edit `bots/`.
