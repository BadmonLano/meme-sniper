# Contributing

Thanks for wanting to help. This code moves real money, so the bar is "safe and tested" before "clever".

## Ground rules

- **Never commit secrets.** No private keys, API keys, `.env` files, `setup.json`, browser profiles or wallet addresses you own. `.gitignore` covers the usual files; check `git diff --staged` anyway.
- **No personal data** in code, skills or docs (names, handles, home paths).
- **Keep it self-contained.** Don't reference bots, files or services that aren't in this repo. If a feature needs an outside service, put it behind an env switch that defaults to off (see `PIPE_FLOW_ENABLED`).
- **The hard safety gates are not up for loosening** in a PR: wallet floor, rug checks, size caps, concentration limits.
- **UI code must never be able to stop trading.** Console faults are caught and logged.

## Before you open a PR

Run everything in the README "Tests" section (all offline), plus:

```
python -m py_compile bots/meme_sniper.py bots/sniper.py bots/sniper_ui.py
```

Describe what changed, why, and how you tested it. If you change a skill, say which behaviour of the agent it changes.

## Issues

Use GitHub issues for bugs and ideas. Include your OS, Python version, the menu option or command you ran, and the relevant lines from `bot_logs/` with any keys or addresses removed. For security problems, see [SECURITY.md](SECURITY.md) instead.
