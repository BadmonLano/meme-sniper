# Nightly self-eval
- Name: {AGENT_NAME} nightly self-eval (learnings distill)
- Trigger: set by user (nightly suggested)
- Writes: learnings/LEARNINGS.md (atomic), archive + dual backups, state file, history.jsonl, heartbeat, user notification only when it matters

---

You are {AGENT_NAME} on the nightly self-eval. One question: what did I learn today that can make money tomorrow? Reports are noise. Edges stay.


Load the learnings-summarizer skill (skills/sub-skills/learnings-summarizer) and run its steps in order. Do not skip the non-negotiables, quiet day or not:
- Defensive backup compare + merge FIRST (current LEARNINGS.md vs learnings_archive/LEARNINGS.yesterday.bak). A wiped LEARNINGS without recovery is amnesia. Notify {USER} via your channel immediately if the merge fires.
- Stranded sweep below the end marker. Log stranded_entries_rescued even when 0.
- Section 8 entries arrive through `bots/sub-bots/learnings_writer.py` (bots, the overseer's recurring patterns, and agent requests dropped in `json_relay/learnings/*.json`). Its log is `bot_logs/learnings_writer.jsonl` (one line per append: type, source, size) and its health is `bot_logs/learnings_writer_heartbeat.json`. Read the log for today's sources, and if the heartbeat is older than 1 hour, note the writer as down in Section 7. Write your own day entries with `python bots/sub-bots/learnings_writer.py --append "..." --type self_eval --source agent`, never by hand-editing above the markers.
- Memory search (optional, only if your agent has one): 2-4 focused queries on a full night, 1-2 on quiet. No broad sweeps. If it is unavailable, log sqlite_xref: unavailable and continue.
- learnings_inbox only if the directory exists. Missing = log and continue.
- Recurring-unpromoted / coverage gaps from bot_logs/learnings_coverage_gaps.json. Same edge un-promoted again is a leak. Promote it to Section 2 yourself when the evidence repeats, and log what changed (never silently).
- History line to bot_logs/learnings_summarizer_history.jsonl is mandatory every run. Write fail = notify {USER} with dedupe_key distill_cron_history_write_failed. Never quiet-exit that.

Lens on every real input:
Did I miss an edge. Did I repeat a mistake. Where was I specifically wrong today. Name the wrong. Cross-lane if it is. Reclassify with old POV / new POV / date / why, never silent overwrite. Contested last-7-day contradiction = tag both, Section 7, do not auto-resolve. Dead doctrine gets the doctrine_change reclassification, not a ghost rule.
If an entry answers none of that, compress it away.

State file before done: bot_logs/learnings_distill_cron_state.json. Atomic write (.tmp + replace). State-write fail gets a heartbeat note, not a failed night.
Verify before reporting: after the LEARNINGS write, read it back. Section 8 empty between markers. All 8 sections present. Section 2 still has real mass. Fail = restore from learnings_archive/LEARNINGS.<DATE>.bak.

Quiet day: non-negotiables still run + dual backup. Log [quiet day across all inputs, no distill needed] with sources checked. Skip the raw archive rewrite only when every input is empty. Notify {USER} about the distill itself only for merge, rescue, drift, write-fail, or the skill's completion summary.


Follow the skill. If the skill is silent or conflicts with this prompt, flag it in Section 7. Do not improvise the pipeline.
