# Changelog

Full history: [TIMELINE.md](TIMELINE.md).

## v1.0.3 (2026-10-24): fee-wallet vault exception
- New `bots/fee_vault.py`: tells a creator parking supply in its own fee wallet apart from a sniper bundle (transfer vs buy, fee-recipient match, receiver never signed, creator done selling).
- Vault launches skip the launch-spike $100k kill, leave the vault out of top-10 math, enter at a fixed 0.1 SOL, and exit on any vault move, a -25% stop, 50% off at 3x, and a 35% trail. Off-switch: `VAULT_EXCEPTION=false`.
- Note: Drop 2 holder limits (`TOP10_MAX_PCT`, `DEV_MAX_HOLDING_PCT`, `HOLDERS_MIN_COUNT`) are advisory. They show on the card and never block a buy.
- Tests: `bots/tests/test_fee_vault.py` (KIMCHI replay from public data).

