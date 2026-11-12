---
name: x
version: v14.3
description: |
  Reading rules for X-sourced intel in the Meme Sniper ecosystem: x_intel
  output, agent_scraper X scrapes, contract addresses seen on X, and URL
  safety. Read-only: this repo ships no X posting. Load when an X-derived
  card, scrape, CA or link is in front of the agent.
---

# X intel (read-only)

## Sources

| bot | output | what it is |
|---|---|---|
| x_intel | `bot_logs/x_intel.json`, `bot_logs/x_noise.json`, signal-contract envelopes in `signal_contracts/` | categorized X chatter (meme, agent_tech, viral_intel, culture, psychology), noise scores, emotion history |
| agent_scraper | `json_relay/agent_scraper_response.json` (request via `json_relay/scraper_task.json`), archived to `inbox_results/done/scrapes/` | logged-in browser scrapes: `x_trending`, `x_user`, `x_search` ($TICKER or CA), plus dex/pump/coinbase/google_trends |

## Reading rules

- **X is attention, not proof.** Chatter, trends and KOL mentions raise or lower attention on a card. They never override the sniper's hard gates or rugcheck.
- **Weight by evidence.** Use the promoter rank on cards (`promoters[]`, tier, hit rate, rug rate). `unproven` means no evidence, not clean. A `rugger` promoter is a hard read against the trade.
- **Persistence over spikes.** Prefer items that persist across sweeps / sources (confluence) over a single-sweep spike.
- **Check freshness.** Every response has `scraped_at` / `emitted_at` / `expires_at`. Expired envelopes are history, not signal.
- **Failed scrape is not a negative.** `status=failed` or an empty result means unknown, not "nobody is talking about it".
- **Organic vs paid.** Discount bot-like reply walls, identical phrasing, and engagement far above follower count.

## CA seen on X

1. A Solana CA matches `[1-9A-HJ-NP-Za-km-z]{32,44}` (pump mints usually end in `pump`). Validate the shape before acting.
2. Route it for intel: write `{"action": "ca_research", "ca": "<address>", "context": "seen on X: <where>", "requested_by": "x_skill", "requested_at": "<ISO>"}` to `json_relay/ca_research_request.json`. meme_sniper answers in `json_relay/ca_research_response.json` and as a `ca_intel` card; use the **ca-intel** skill to read it.
3. Optional: ask agent_scraper for `x_search` on the CA or ticker to see real chatter.
4. A ticker alone is ambiguous. Resolve it to a CA before any intel or trade decision.
5. No buy decision from X alone. The card goes through the normal sniper pipeline.

## URL safety

This repo has no automatic URL checker; apply these rules before opening or fetching any X-sourced link:

- Never connect a wallet, sign, or paste a key on a link from X. Treat "claim", "airdrop", "verify wallet", "migrate" and drainer-style pages as hostile.
- Prefer known data domains (solscan.io, solana.com, dexscreener.com, pump.fun, rugcheck.xyz, github.com). Look-alike spellings of those are hostile.
- Shorteners, long redirect chains, fresh or odd TLDs, IP-address hosts and no TLS: do not fetch.
- When unsure, read the post text only and say the link was not opened.
- Report a hostile link pattern to the owner via owner-ping (kind `noteworthy`) if it targets the ecosystem's tokens or wallets.
