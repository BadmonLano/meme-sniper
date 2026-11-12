# Learnings loop

A nightly self-eval for your agent. One question: **what did I learn today that can make money tomorrow?** Reports are noise; edges stay.

## How entries flow

1. **Section 8 (raw):** during the day the agent and bots append short entries between the two append-window markers in `LEARNINGS.md` (`### [ISO] | [TYPE] | [SOURCE]` + 1-3 lines).
2. **Nightly distill:** the self-eval run archives the raw window, takes a dual backup, then distills each entry into Sections 1-7 (lane lessons, patterns, tooling, open items) and empties Section 8.
3. **Candidates to Section 7:** anything that looks like a hard rule, a contradiction, or doctrine drift goes to Section 7 as a candidate or P1 item.
4. **The agent promotes to Section 2:** the agent adds or retires Critical Rules itself when a candidate has repeat evidence, logs each change (rule, reason, evidence) to `bot_logs/learnings_summarizer_history.jsonl` and in Section 7 "Recently Resolved", and sends a notify-only owner-ping.

Recurring lessons that keep showing up but never get promoted are tracked as coverage gaps, so the leak is visible instead of silently restated.

## Files

| file | what |
|---|---|
| `learnings/LEARNINGS.md` | the baseline (start from `LEARNINGS.template.md`) |
| `bots/sub-bots/learnings_writer.py` | the one safe writer: puts entries between the Section 8 markers, file lock, atomic write; as a sub-bot it creates LEARNINGS.md from the template, restores missing markers and drains `json_relay/learnings/*.json` |
| `bot_logs/learnings_writer.jsonl` | one line per append (type, source, size; never the text) |
| `bot_logs/learnings_writer_heartbeat.json` | writer health (the warden pages if it goes stale) |
| `bot_logs/learnings_archive/<DATE>.md` | raw Section 8 archive, append-only |
| `bot_logs/learnings_archive/LEARNINGS.<DATE>.bak` | per-date backup |
| `bot_logs/learnings_archive/LEARNINGS.yesterday.bak` | rolling backup used for wipe detection |
| `bot_logs/learnings_distill_cron_state.json` | last run time + absorbed memory file hashes (seed: `{}`) |
| `bot_logs/learnings_coverage_gaps.json` | recurring un-promoted lessons (seed: `[]`) |
| `bot_logs/learnings_summarizer_history.jsonl` | one line per run, mandatory |
| `bot_logs/learnings_summarizer_heartbeat.json` | last run status |

## Cadence

Set by the user or their agent. Nightly is suggested. See `nightly_self_eval.automation.md` for the prompt.
