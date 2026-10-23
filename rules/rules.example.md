# Owner trading rules (example)

Copy this file to `rules/rules.md` (or let the setup wizard write it) and edit it. The agent reads `rules/rules.md` before every trade decision. These rules override skill defaults. The bot's hard safety gates (wallet floor, rug checks, size caps) still apply: a rule can make the agent stricter, never looser. Leave a section empty if it does not apply.

## Max size
<!-- Largest buy in SOL, or % of wallet per trade (e.g. 0.25 SOL / 10%) -->
0.1 SOL per buy, never more than 10% of the wallet in one token.

## No-trade hours
<!-- Local hours or days you never trade (e.g. 00:00-07:00, weekends) -->
No new buys 01:00-07:00 local time.

## Banned tokens / categories
<!-- CAs, tickers or categories never to buy (e.g. political, AI agents) -->
No political tokens.

## Loss limits
<!-- Daily / weekly loss that stops trading (e.g. -1 SOL per day) -->
Stop new buys for the day after -0.5 SOL realized.

## Exits
<!-- Your own SL/TP or hold rules (e.g. always peel 50% at 2x) -->
Always peel half at 2x.

## Other
<!-- Anything else the agent must always or never do -->
Ping me before converting any bag to a hold.
