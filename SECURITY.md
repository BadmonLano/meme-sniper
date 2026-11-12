# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems (anything that could leak keys, move funds, bypass a safety gate or let an outsider control the bot).

Report it privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability** (a private security advisory). Include what you found, how to reproduce it, and what an attacker could do with it. We'll reply in the advisory.

For non-sensitive bugs, a normal GitHub issue is fine.

## Keeping your setup safe

- Run with a **burner hot wallet** that holds only what you can afford to lose.
- Keep `bots/.env` and `setup.json` private; they are in `.gitignore` for a reason. Never paste them into an issue, a chat or a log.
- Use your own RPC and model keys, and rotate them if they were ever exposed.
- **Paper is the default.** If `SNIPER_PAPER_MODE` is missing, blank, or anything other than an explicit off (`0`, `false`, `no`, `off`), the engine does not sign. Live signing is an explicit opt-in.
- **Suggest is the default.** If `AGENT_MODE` is missing, trade signals are held until the owner approves that trade. The agent does not approve its own signals.
- **The launch rail ships off.** `LAUNCH_RAIL_ENABLED` defaults to false and `LAUNCH_RAIL_LIVE` defaults to `0`. Both must be turned on, and paper mode must be explicitly off, before a launch can send.
- **Armed stops ship off.** `ARMED_STOPS` missing or `0` means a breached stop-loss or take-profit is a suggestion, not a sell. Set `ARMED_STOPS=1` only if you want those exits to sell without a fresh approval.
- **The owner-position timeout ships off.** `OWNER_POS_AUTO_TIMEOUT` missing or `off` means a bag the bot did not buy stays pending until you `/manage` or `/leave`. It does not take the bag over, and it does not sell, when the 30-minute window ends. Set `OWNER_POS_AUTO_TIMEOUT=on` only if you want that timeout to manage the bag.
- Skills are opt-in playbooks. They do not run because a base58 address appeared, and they do not tell an agent to edit `bots/`. Patches are proposed; the owner applies them.
- Read the warning in the README before the first live start.
