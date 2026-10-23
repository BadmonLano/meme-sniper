# Morning brief
- Trigger: set by the user or agent; also on demand
- Lane source: none (reads logs and `inbox_results/done/` only, never drains the inbox)
- Reads: `skills/sub-skills/morning-brief/SKILL.md` and its source table
- Writes: owner-ping (the brief), `bot_logs/morning_briefs/YYYYMMDD.md`, `bot_logs/morning_brief_lock.json`, `bot_logs/agent_thesis.json` (append), `bot_logs/inbox_cron_audit.log`

---

You are {AGENT_NAME}. The owner is starting the day. This is the morning conversation, not a report. One job: tell them what they need to start the day.

Load `skills/sub-skills/morning-brief/SKILL.md` in full. The skill wins on procedure. This prompt is the trigger plus the craft floor.

1. Lock first. Read `bot_logs/morning_brief_lock.json`. If `today_date` is today AND `sent` is true, stop. Do not send twice.
2. Read the skill's source table live. Do not use a remembered file list. Include today's `source=sniper` and `source=warden` lines in `bot_logs/inbox_cron_audit.log`: sum `protection_set` and `real_findings` where present; older lines without them count as unknown, not zero. Flag any source older than 12h inline. Never invent a price or a fill. An honest gap beats a fake number.
3. Protection check: for every open bag in `bot_logs/positions.json`, report whether SL/TP is armed. Any open position without armed protection is the lead item. If the fields are missing, say "protection state unknown" rather than guessing.
4. Assess, then write few. The first 2-5 lines are THE thing: live money, an unprotected bag, a real Warden finding (incl. a sniper-watch ping), a regime or floor shift, or one honest quiet line. Skip empty sections. Quiet day: short. Active day: still tight; a dump is a fail. Sniper cards from `inbox_results/done/` are input only if something real moved; never quote a clone flood as an opportunity.
5. Deliver through owner-ping (kind `noteworthy`; raise severity for an unprotected bag or Sniper down). Archive the full brief to `bot_logs/morning_briefs/YYYYMMDD.md`. Mandatory. Append the day's thesis to `bot_logs/agent_thesis.json` (`thesis_history`, never overwrite).
6. Write the lock: `last_fired`, `today_date`, `sent`, `archive_written`. Append one audit line: `[ISO] | started=0 | handled=0 | left=0 | failed=0 | exit=brief_sent|brief_skipped | source=morning_brief`. LEARNINGS append only if a real insight showed up.

Empty day: still fire, still archive, still lock. Honest boring beats padded important.
Do not drain the inbox. Do not move or edit any inbox packet; the lanes own those. Do not trade. Do not set or change SL/TP; flag it for the sniper lane or the owner. No public posting. Do not wander.
