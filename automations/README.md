# Automations

Five prompts the owner can schedule: four lane prompts here, plus the nightly self-eval at [`../learnings/nightly_self_eval.automation.md`](../learnings/nightly_self_eval.automation.md). Nothing here runs until the owner saves it. **sniper_lane** reads `meme_sniper - ` packets and suggests buy / pass / protection changes (no sell without fresh owner approval). **warden_lane** reads `security_warden - ` packets (wallet findings first; never restarts anything; never edits `bots/`). **morning_brief** reads logs and writes one brief. **misc_lane** reads everything else and routes it by name (x, code-monitor, autoagent, ca-intel). A launch packet is summarized for the owner; do not submit a launch. Suggested cadence if the owner wants one: sniper_lane every 10 min, misc_lane every 15 min, warden_lane every 20 min, morning_brief once a morning, nightly self-eval once a night. Replace `{AGENT_NAME}` with your agent's name. Every lane appends one line per run to `bot_logs/inbox_cron_audit.log`. `bots/tools/lane_run.py` lists a lane, stamps `actions_taken` inside each packet, moves it, and writes that line (`--positions` prints the open book; missing or `{}` = flat).

Owner commands (`/roast`, `/recap`, `/autopsy [ticker|last]`) are not a lane: `bots/sub-bots/owner_commands.py` answers them itself (modes `off`, `file`, `telegram`; replies in `inbox_results/owner_replies/`). A lane may serve a file-mode request but never drains `owner_commands/`. See SETUP.md section 6.5.

## Opt-in lanes

These prompts do nothing until the owner explicitly saves them. Skills do not start them. Suggest-only: patches go as diffs to `owner_inbox/` for the owner; no trade without fresh owner approval; never edit `bots/`. Do not sign. Do not submit a launch.

Suggested cadences, if the owner chooses to schedule them, live in `bots/.env` (`LANE_CADENCE_SNIPER_LANE_MIN` (10), `LANE_CADENCE_MISC_LANE_MIN` (15), `LANE_CADENCE_WARDEN_LANE_MIN` (20), `LANE_MORNING_BRIEF_AT` (08:00), `LANE_NIGHTLY_EVAL_AT` (23:30)); `python bots/active_hours.py` prints them. Outside `ACTIVE_HOURS` / `ACTIVE_DAYS` (`ACTIVE_TZ`) a scheduled pass still only suggests. New buys wait. A sell still needs fresh owner approval unless the owner set `ARMED_STOPS=1` (shipped off). Do not change `ACTIVE_HOURS`.

## Placeholders

Before pasting a prompt, replace `{AGENT_NAME}` with your agent's name and `{USER}` with the owner's name (how you address them). Set the same names as `AGENT_NAME` and `OWNER_NAME` in `bots/.env`: `learnings_writer` fills both into `learnings/LEARNINGS.md` when it creates it from the template.
