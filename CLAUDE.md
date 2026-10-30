# FPL bot

## Rules knowledge base

`docs/fpl-rules-context.md` is the authoritative FPL rules reference for this project (2026/27 season, v2.6, verified 2026-10-29 at GW9). Read the relevant part before writing or changing any logic that touches squads, transfers, prices, chips, deadlines, scoring, leagues or cups.

- Part A: official rules. The only part to treat as fact.
- Part B: undocumented mechanics, each tagged `[OFFICIAL-API]`, `[OFFICIAL-NEWS]`, `[COMMUNITY]` or `[SPECULATIVE]`. Rely without a fallback only on the two `OFFICIAL` tags.
- Part C: constraints on the bot's behaviour.
- Part D: weekly rules-change check spec, with the YAML baseline in D6.
- Part E: open questions.

## System design

`docs/system-flow.md` is the master reference for how the bot runs (setup, scheduler and failover, daily refresh, weekly plan, hit/injury/chip rules, submit, post-gameweek review, rules check, failure handling). Keep code consistent with it, and update it (with the owner's approval) when the design changes.

## Operating mode and constraints (from Part C1 of the rules file)

- Autonomous, no human veto: the bot logs into the owner's FPL account and makes transfers, lineup, captaincy and chip moves itself. Before every FPL write it commits a decision card (`.txt`, with full reasoning) to `decision-cards/` and pushes it; alerts go by ntfy.
- Runs only on the owner's machines (Windows primary, macOS backup), never from cloud servers. Never bypass CAPTCHAs, bot protection or other human checks; stop and alert instead.
- Credentials (FPL password, tokens, GitHub token) live in the OS keychain (or environment variables / a git-ignored secrets file); the signed-in browser profile lives in the local data folder. Never commit, log or expose any of them, including in decision cards.
- The repo must stay private: decision cards contain the team, strategy and FPL data.
- Keep API reads and writes low-frequency and cached; never hammer endpoints near deadlines; don't republish Game data.
- Money in integer tenths (1000 = £100.0m); use selling prices when computing funds.
- Read deadlines (`events[].deadline_time`, UTC) and `element_type` from the API each run; never compute deadlines locally.
- When live API values disagree with the rules file, trust the API for that run, raise a rules-change alert, and do not silently edit the file. Changes to the file go through a version bump and a Changelog entry (Part D4).
