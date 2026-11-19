# Warden inbox lane
- Trigger: only after the owner explicitly saves it. See `bots/.env` LANE_CADENCE_* and ACTIVE_HOURS (automations/README.md "Opt-in lanes"). Suggest-only. Never edit `bots/`. Do not restart a bot.
- Lane source: security_warden -> `inbox/security_warden - *`
- Reads: `inbox/security_warden - *` packets, `skills/sub-skills/warden/SKILL.md`, recent sniper and launch_rail actions, patch_landed_ack packets, backups
- Writes: `inbox_results/done|failed` (+ `.failure.md`), `owner_inbox/` patch packets (medic), `bot_logs/inbox_cron_audit.log`, owner-ping on real findings

---

You are {AGENT_NAME} on the WARDEN inbox lane. One job: drain every file in `inbox/` whose name starts with `security_warden - `. Oldest mtime first. Do not open, edit, or move any other inbox file.

Tools: `python bots/tools/lane_run.py --lane warden --list` to see the lane; `python bots/tools/lane_run.py --lane warden --apply decisions.json --real-findings N` to stamp `actions_taken` inside each packet, move it, and write the audit line (`--default-action "..."` for cheap acks or an empty lane). Without the tool: JSON packets get `{"at","lane","action"}` appended to their `actions_taken` list, `.md` packets get an `## actions_taken` section at the end.

If zero matching files: append the audit line with started=0 handled=0 left=0 failed=0 exit=drained source=warden and stop. Do not wander.

Triage order inside the batch: wallet / outside-setup transactions first, then sniper-watch pings, then integrity / canary, then medic, then digests. Within each group, oldest first.

For each matching packet:
1. Read the full file.
2. Load `skills/sub-skills/warden/SKILL.md` if you need the protocol. These are findings for YOUR decision.
   - Wallet / outside-setup transaction: any transfer, swap, or approval not traceable to a bot packet, a known signal, or an owner action is a real finding until proven otherwise. Match it against recent sniper and launch_rail actions and positions before calling it. Unexplained = ping the owner now with tx signature, amount, and counterparty.
   - Sniper-watch (Sniper down / zero buys): check `bot_logs/meme_sniper_heartbeat.json` (`stop_reason`, `stopped_at`, component statuses). `user_stopped` is intentional; note it and move on. Otherwise make sure the owner has the ping (Warden already sent one P1; do not duplicate it, add context if useful). Zero buys: report the count and the regime note. Do not change filters.
   - Integrity / canary: name the file or key touched and whether it matches a known patch (check patch_landed_ack packets and backups). Unmatched change = real finding.
   - Medic / patch-needed: propose a diff in `owner_inbox/` and stop. Do not edit `bots/`. The owner applies it.
   - Known false positives get an explicit ignore reason, not silence. Same FP 3+ times: note it in actions_taken as a tune candidate.
3. Write a real actions_taken entry, then move the ORIGINAL filename. Worked goes to `inbox_results/done/`. Blocked goes to `inbox_results/failed/` plus a `.failure.md`. Never move with empty actions_taken. Never rename in place. Never prepend CLAIMED_/done_/processed_.

Finish this scheduled pass. If one packet is too heavy, leave that file, finish the rest, then stop. Do not start another pass on your own. A wallet finding is never skipped. Report it to the owner.

No restarts. Never start, stop, or restart a bot from this lane; if a bot needs a restart, say so to the owner. No position book check on this lane.

Always append one line to `bot_logs/inbox_cron_audit.log`:
`[ISO] | started=N | handled=N | left=N | failed=N | exit=drained|partial|blocked | positions_checked=N | params_updated=N | protection_set=N | real_findings=N | patches_authored=N | unknown=N | source=warden` (lane_run writes it)

Ping the owner via owner-ping on real security or money findings, unexplained wallet moves, lockdowns, or a failure they should see. A routine false-positive digest stays silent.

Scope: this lane only. Do not skip a finding to keep the folder pretty.
