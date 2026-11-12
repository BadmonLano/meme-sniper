---
name: learnings-summarizer
version: v14.3
description: |
  Nightly distill of learnings/LEARNINGS.md for the Meme Sniper ecosystem.
  Archives the raw Section 8 append window, distills it into Sections 1-7,
  proposes (never applies) Critical Rules, tracks recurring un-promoted
  lessons, and writes history to bot_logs. Run by the nightly self-eval prompt
  (learnings/nightly_self_eval.automation.md) on a cadence the owner sets.
---

# Learnings Summarizer

One question: **what did I learn today that can make money tomorrow?**
Reports are noise. Edges stay.

## Files

| file | role |
|---|---|
| `learnings/LEARNINGS.md` | the baseline (start from `LEARNINGS.template.md`) |
| `bot_logs/learnings_archive/<DATE>.md` | raw Section 8 archive, append-only |
| `bot_logs/learnings_archive/LEARNINGS.<DATE>.bak` | per-date backup |
| `bot_logs/learnings_archive/LEARNINGS.yesterday.bak` | rolling backup for wipe detection |
| `bot_logs/learnings_distill_cron_state.json` | last run time + absorbed input hashes |
| `bot_logs/learnings_coverage_gaps.json` | recurring un-promoted lessons |
| `bot_logs/learnings_summarizer_history.jsonl` | one line per run (mandatory) |
| `bot_logs/learnings_summarizer_heartbeat.json` | last run status |

## Steps (in order)

1. **Backup compare + merge first.** Compare `LEARNINGS.md` with `LEARNINGS.yesterday.bak`. If sections shrank or vanished, merge back from the backup and ping the owner (owner-ping, `bot_error`, high). A wipe without recovery is amnesia.
2. **Stranded sweep.** Move entries found below the Section 8 end marker back into the window. Log `stranded_entries_rescued` (even 0).
3. **Inputs.** Section 8 entries, plus (if present) `learnings_inbox/`, the latest overseer report, autopsies and miss_book highlights from the last day. Missing input = log and continue.
4. **Archive** the raw Section 8 window to `learnings_archive/<DATE>.md` and take the dated backup.
5. **Distill** each entry into Sections 1-7: lane lessons (meme sniper), pattern library, bot/tooling lessons, open items. One master bullet per lesson family. Reclassify with old POV / new POV / date / why; never silently overwrite. A contradiction inside the last 7 days: tag both, put it in Section 7, do not auto-resolve.
6. **Promote yourself.** A hard-rule candidate with repeat evidence goes straight into Section 2 (Critical Rules); retire rules the data contradicts. Log every add/retire (rule, reason, evidence) to the history line and Section 7 "Recently Resolved", and include it in the owner-ping. Never silent.
7. **Coverage gaps.** Lessons that recur but were never promoted go to `learnings_coverage_gaps.json` and get surfaced in Section 7. Do not silently restate them.
8. **Empty Section 8**, write `LEARNINGS.md` atomically (`.tmp` + replace).
9. **Verify.** Read it back: Section 8 empty between markers, all 8 sections present, Section 2 still has real mass. Fail = restore from `LEARNINGS.<DATE>.bak` and ping the owner.
10. **History + state.** Append one line to `learnings_summarizer_history.jsonl` (date, entries in/out, promotions proposed, gaps, rescued, result). Update the state file and heartbeat. A history write failure pings the owner with dedupe_key `distill_history_write_failed`.

## Quiet day

Steps 1, 2, 4 (backup), 9 and 10 still run. Log `quiet day, no distill needed` with the sources checked.

## Lens on every entry

Did I miss an edge? Did I repeat a mistake? Where was I specifically wrong? Name it. If an entry answers none of that, compress it away.

## Notify the owner only for

merge, rescue, drift, write failure, or the run's one-line completion summary.
