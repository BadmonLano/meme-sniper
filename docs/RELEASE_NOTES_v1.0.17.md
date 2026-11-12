# v1.0.17 — safe defaults

This release makes the shipped bot match the safety story. Features and the MIT license are unchanged. Nothing here turns trading on.

## Defaults

- If `SNIPER_PAPER_MODE` is missing or blank, the engine and the launch rail do not sign. Live signing requires an explicit `0`, `false`, `no`, or `off`, plus the existing `LIVE` confirmation in the wizard.
- `AGENT_MODE` still defaults to `suggest`. A buy or sell signal waits for `/approve`.
- `ARMED_STOPS` defaults off. A breached stop or take-profit is a suggestion card (`protective_exit_suggested`), not a sell.
- `OWNER_POS_AUTO_TIMEOUT` defaults off. After 30 minutes with no answer, a bag the bot did not buy stays pending. It is not taken over and it is not sold.
- The launch rail still ships off (`LAUNCH_RAIL_ENABLED=false`, `LAUNCH_RAIL_LIVE=0`). `SECURITY.md` now says that, matching the code and `bots/.env.example`.

## Agents

Skills, especially meme-hunter, ca-intel, and code-monitor, are opt-in. A base58 address in a coding session is not a trigger. Trade ideas are suggestions for the owner. Source patches are diffs in `owner_inbox/`. The owner applies them. The plugin manifests say the same thing.

## Tests

`bots/tests/test_safe_defaults.py` locks the paper, armed-stop, and timeout defaults, and rejects the old contradictory skill phrases.
