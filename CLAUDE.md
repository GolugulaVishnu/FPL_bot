# FPL bot

## Rules knowledge base

`docs/fpl-rules-context.md` is the authoritative FPL rules reference for this project (2026/27 season, v2.0, verified 2026-10-29 at GW9). Read the relevant part before writing or changing any logic that touches squads, transfers, prices, chips, deadlines, scoring, leagues or cups.

- Part A: official rules. The only part to treat as fact.
- Part B: undocumented mechanics, each tagged `[OFFICIAL-API]`, `[OFFICIAL-NEWS]`, `[COMMUNITY]` or `[SPECULATIVE]`. Rely without a fallback only on the two `OFFICIAL` tags.
- Part C: constraints on the bot's behaviour.
- Part D: weekly rules-change check spec, with the YAML baseline in D6.
- Part E: open questions.

## Operating mode and constraints (from Part C1 of the rules file)

- Autonomous: the bot logs into the owner's FPL account and makes transfers, lineup, captaincy and chip moves itself, recording each on a decision card.
- Credentials (password, session, tokens) may be stored but only in environment variables or a git-ignored secrets file; never commit, log or expose them.
- Keep API reads and writes low-frequency and cached; never hammer endpoints near deadlines; don't republish Game data.
- Money in integer tenths (1000 = £100.0m); use selling prices when computing funds.
- Read deadlines (`events[].deadline_time`, UTC) and `element_type` from the API each run; never compute deadlines locally.
- When live API values disagree with the rules file, trust the API for that run, raise a rules-change alert, and do not silently edit the file. Changes to the file go through a version bump and a Changelog entry (Part D4).
