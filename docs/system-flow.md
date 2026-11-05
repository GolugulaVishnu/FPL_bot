# FPL bot system flow

Master reference for the bot's design. Approved 2026-10-30 (v0.3 of the reviewed flowchart); updated 2026-10-30 at the owner's request: no dry run, the bot plays from GW9, and data comes from the FPL API plus a public archive instead of Understat/FBref. Rules come from `docs/fpl-rules-context.md`; where this file and the rules file disagree, the rules file wins.

Summary: fully autonomous (no human veto) · Windows primary, macOS backup · Python + SQLite · free data only · decision cards as .txt files in this repo · ntfy push alerts · goal: maximise points and overall rank.

## 0. Overview

The bot is a short program that the operating system starts every 15 minutes. Each run checks what is due against the live FPL deadlines and does only that job, then exits. Moves can be committed at any point in the week, but every commit is preceded by a decision card, saved as a text file in the GitHub repo.

```mermaid
flowchart TD
  S1["1 One-time setup, smoke test, go-live from GW9"] --> T2["2 Scheduler tick every 15 min"]
  T2 --> KS{"Kill switch on?"}
  KS -- yes --> PZ["Pause: log, ntfy once, exit"]
  KS -- no --> DUE{"What is due now?"}
  DUE -- "once a day" --> D3["3 Daily refresh: data, prices, news"]
  DUE -- "deadline minus 24h" --> P4["4 Weekly plan + draft decision card"]
  DUE -- "deadline minus 2h" --> F6["6 Final run, final card, submit"]
  DUE -- "points final, 09:00 UK day after last match" --> R7["7 Post-gameweek review + retrain"]
  DUE -- "Tue 09:00 UK or news hit" --> C8["8 Rules-change check"]
  DUE -- "nothing" --> EX["Exit"]
  D3 -- "early-commit trigger" --> F6
  P4 --> RU5["5 Hit, injury and chip rules"]
  RU5 --> P4
  F6 --> RU5
  D3 -.-> E9["9 Failure handling"]
  P4 -.-> E9
  F6 -.-> E9
  R7 -.-> E9
  C8 -.-> E9
  R7 -- "model updated" --> D3
```

## 1. Setup and go-live

You created the FPL account for `soohzabimaru864@gmail.com` yourself on 2026-10-30, so the bot only ever logs in. There is no dry run: the bot plays from GW9 (deadline Sat 31 Oct 2026, 11:00 UTC). The go-live check is a smoke test that the whole workflow produces a valid team and decision card.

Automated login and submission can't be built and safely tested before the GW9 deadline, so GW9 is entered by you, by hand, exactly as the bot's decision card says. From GW10 the bot submits itself, after a check-only login run (log in and read the team, change nothing) proves the login works.

```mermaid
flowchart TD
  A["Install Python, bot and SQLite on Windows and macOS"] --> B["You: create a GitHub token for this repo (write cards)"]
  B --> C["You: install ntfy on phone, subscribe to the private topics the bot prints"]
  C --> D["You run the setup command on each machine: it asks for the FPL password and GitHub token, hidden, and saves them to the OS keychain"]
  D --> E["Load data: past seasons from the public FPL archive, this season from the FPL API (Opta xG and xA included)"]
  E --> F["Build expected-points model"]
  F --> G["Backtest on 2025-26, report accuracy"]
  G --> H["Smoke test: fplbot pick builds a valid GW9 team and decision card"]
  H --> V{"Team passes squad and lineup rules?"}
  V -- no --> J["Fix code or model"] --> H
  V -- yes --> Q["GW9: pick initial 15 with unlimited transfers before the team's first deadline"]
  Q --> R["GW9 final card pushed to repo; you enter the team by hand before the deadline"]
  R --> K["Before GW10: check-only login run with the password from the keychain"]
  K --> P["Login: PingOne OAuth with PKCE, tokens to keychain, record team ID, read team"]
  P --> M{"CAPTCHA or human check?"}
  M -- yes --> N["Pause, ntfy you to finish that one step by hand"] --> S
  M -- no --> S
  S["Live mode from GW10: bot submits itself, scheduler enabled on both machines"]
```

### Needed from you

- A GitHub fine-grained token limited to this one repo with Contents read and write, so the bot can push decision cards. Stored in the keychain, never in the repo.
- Run the bot's setup command once on each machine (Windows and Mac). It asks for the FPL password with hidden typing and saves it to the OS keychain; nothing is written to the repo. Under the hood this is the same as `python -m keyring set fpl-bot soohzabimaru864@gmail.com`.
- ntfy: install the free ntfy app (iOS or Android) and subscribe to two topic names the bot generates at setup: one for alerts, one for pause/resume commands. Topic names are long random strings, because anyone who knows a topic name can read it.

### Notes

- Secrets go in the OS keychain, which is a git-ignored store outside the repo, in line with CLAUDE.md.
- A CAPTCHA or other human check is never bypassed. The bot stops and asks you.
- The bot logs in from your home network only. FPL blocks cloud servers.

## 2. Scheduler and failover

Task Scheduler (Windows) and launchd (macOS) each start a run every 15 minutes. A short scheduled run survives reboots and crashes better than a long-running process. The Mac stays idle unless the Windows machine has gone quiet.

```mermaid
flowchart TD
  T["OS scheduler starts a run every 15 min"] --> W{"Which machine?"}
  W -- Windows --> HB["Post heartbeat to private ntfy topic"] --> LK
  W -- macOS --> CK{"Windows heartbeat in last 30 min?"}
  CK -- yes --> SB["Standby, exit"]
  CK -- no --> TO["ntfy: Windows silent, macOS taking over"] --> LK
  LK["Take local run lock"] --> KS{"Kill switch? flag file or pause message on ntfy control topic"}
  KS -- on --> PZ["Log, ntfy once, exit"]
  KS -- off --> CD["Load cached deadlines; re-read from FPL API if cache older than 6h"]
  CD --> DJ["Pick due jobs: daily, plan, final, post-GW, rules check"]
  DJ --> RJ["Run jobs in order, write log to SQLite"]
  RJ --> UL["Release lock, exit"]
```

### Why a double submit can't happen

- Before any write, the bot reads the current team from FPL and applies only the difference from its plan. If Windows already submitted, the Mac finds nothing to change.
- The heartbeat check means the Mac only acts when Windows has been silent for 30 minutes.

### Notes

- The heartbeat goes over ntfy. It's free and needs no shared drive.
- 15-minute tick and 30-minute failover window.

## 3. Daily refresh

Runs once a day after the 00:00 UTC price update. This is where an early commit can start: the bot may submit days before the deadline when waiting would cost money.

```mermaid
flowchart TD
  A["After 00:00 UTC price update"] --> B["Fetch FPL bootstrap-static and fixtures, cached"]
  B --> C["Fetch newly finished gameweeks from the FPL API, incl. Opta xG and xA"]
  C --> D["Read player news, status, chance of playing"]
  D --> E["Update SQLite"]
  E --> F["Re-project expected points for squad and shortlist"]
  F --> G{"Squad player newly injured, suspended or doubtful?"}
  G -- yes --> H["Mini re-plan using injury rules, section 5"]
  G -- no --> I
  H --> I{"Locked-in target near-certain to rise, or a player we are selling near-certain to fall, before next update?"}
  I -- yes --> J["Early commit: go to section 6 with reason: price"]
  I -- no --> K["Log, exit"]
```

### Notes

- Price signal: `price_change_percent` and `price_change_projections`, ignored while `price_change_calibrating` is true.
- A locked-in target is a player who appears in the plan's transfers in every one of the last 2 plan runs.
- Near-certain means a projected change at the next update with predictor progress of 100% or more.

## 4. Weekly plan (deadline minus 24h)

The full weekly plan, sent as a draft decision card. Nothing is submitted at this stage unless an early-commit trigger fires.

```mermaid
flowchart TD
  A["Refresh all data"] --> B["Read team state from FPL: squad, selling prices, bank, free transfers, chips left"]
  B --> C["Choose horizon: adaptive 3 to 6 gameweeks"]
  C --> D["Project expected points per player per gameweek: minutes, xG, xA, form, fixture difficulty, clean-sheet odds, bonus via BPS"]
  D --> E["Compare with free public projections, log disagreements"]
  E --> F["Optimiser over horizon: transfers, hits, bank, rolled free transfers"]
  F --> G["Apply hit, injury and chip rules, section 5"]
  G --> H["Pick XI, bench order, captain, vice-captain"]
  H --> V{"Passes validation?"}
  V -- no --> F
  V -- yes --> K["Draft card: commit gwNN-draft.txt to decision-cards, push, ntfy summary"]
```

### Validation checks

- 15 players, 2/5/5/3, max 3 per club, budget computed from selling prices in tenths.
- Valid formation, reserve goalkeeper in bench slot 12.
- At most 20 transfers unless Wildcard or Free Hit is played; one chip per gameweek; no Free Hits in consecutive gameweeks.
- First-half chips used by the GW19 deadline, 1 Jan 2027 18:30 UTC.

### Where cards go

- `decision-cards/2026-27/gw10-draft.txt`, `gw10-final.txt`, plus `reviews/2026-27/gw10-review.txt` and `rules-alerts/`. The bot commits and pushes each one; ntfy carries a short summary and the file path.

### What a decision card contains

- Every move: transfers, hits, chip, XI, bench order, captain and vice-captain.
- For each move: the expected-points numbers behind it, the alternatives it beat and by how much, the assumptions it relies on (minutes, fixtures, injuries), and where the bot's projection differs from public projections.
- Confidence for each assumption, so you can see which ones to penalise in code if they turn out wrong.
- How the squad was built: the chain of reasoning from the goal and budget through spend by position, formation, club stacks, bench and captaincy (added 2026-10-30 at the owner's request).
- Why each player: his projection, minutes record, where his points come from (with per-90 evidence), his fixture run, his value rank in his position, and how he compares with the best similar-priced alternative.

## 5. Hit, injury and chip rules

Your rules as the bot applies them. The Triple Captain, Wildcard and Free Hit triggers are my proposals.

```mermaid
flowchart TD
  subgraph INJ["Injured or unavailable starter"]
    I1["Estimate gameweeks out from news and status"] --> I2{"Can a bench player cover without hurting the XI much?"}
    I2 -- yes --> I3{"Out only a short time?"}
    I3 -- yes --> I4["Bench the player, keep him"]
    I3 -- no --> I5["Treat as transfer candidate"]
    I2 -- no --> I5
  end
  subgraph HIT["Transfer and hit decision"]
    H1{"Free transfer available?"} -- yes --> H2["Use it on the best gain over the horizon"]
    H1 -- no --> H3{"Incoming player expected points over horizon minus outgoing player's above 4?"}
    H3 -- yes --> H4["Take the -4 hit"]
    H3 -- no --> H5["No transfer, roll the free transfer"]
  end
  subgraph CHIP["Chips, one per gameweek"]
    C1{"Bench four projected total at least 14.5?"} -- yes --> C2["Bench Boost"]
    C1 -- no --> C3{"Best captain is the top triple-captain week left in this chip window?"}
    C3 -- yes --> C4["Triple Captain"]
    C3 -- no --> C5{"Wildcard squad beats normal plan by a clear margin over horizon?"}
    C5 -- yes --> C6["Wildcard"]
    C5 -- no --> C7{"Blank or double gameweek where Free Hit gains a lot for one week?"}
    C7 -- yes --> C8["Free Hit"]
    C7 -- no --> C9["No chip"]
  end
  I5 --> H1
```

### Your rules

- Hit: only if the incoming player's expected points over the horizon beat the outgoing player's by more than 4.
- Late injury with no free transfers left: try the bench first, judged on expected time out.
- Bench Boost: when the four bench players' projected total for the gameweek is 14.5 or more.
- Triple Captain inputs: projected points, fixture difficulty, head-to-head history, form, xG, xA.

### My proposals

- If no Bench Boost week in the chip window reaches 14.5, use it in the highest week left before the window closes.
- Short time out means 2 gameweeks or fewer.
- Triple Captain when this week's best captain score is the highest projected for the rest of the chip window.
- Owner's Triple Captain rule (2026-11-05): play it when the captain projects 8+ points, judging the rest of the chip window (to GW19) over owned players and players affordable with one transfer. A later week justifies holding only if it is clearly better (more than 1 point, the bot's margin).
- Owner's transfer rules (2026-11-05): saving free transfers is the default (they cover later injuries, form dips and fixture swings without hits). A transfer is made when the incoming player projects 10+ points more over the 3-6 week horizon, or when the outgoing player is out long-term (no expected points in 3+ horizon weeks), in which case a smaller upgrade, even a bench one, is fine. Incoming players must be fully available. A hit needs the gain to beat 4 more.
- Owner's rules not yet built (2026-11-05): after a Wildcard, hold transfers for 3-6 weeks unless injuries, a major form dip, a fixture swing or a key teammate's absence (e.g. Palmer and Rogers with or without João Pedro) changes a player's outlook; with saved transfers, short-term punts before a Wildcard are fine; use midweek European and cup minutes to judge league starts; avoid incoming players likely to lose value or whose cost blocks a later upgrade. Chips after GW19 (blanks and doubles) follow the owner's later instructions.
- Wildcard when the unlimited-transfer squad beats the normal plan by 15 or more expected points over the horizon.
- Free Hit for blank or double gameweeks when it gains 10 or more expected points for that week.
- Order of checks when two chips qualify: Bench Boost, Triple Captain, Wildcard, Free Hit.

## 6. Final run and submit

Runs at deadline minus 2h, or earlier on an early-commit trigger. Moves are saved by deadline minus 90 minutes, then read back to confirm.

```mermaid
flowchart TD
  A["Start: deadline minus 2h, or early-commit trigger"] --> B["Refresh team news, prices, flags"]
  B --> C["Log in or refresh token"]
  C --> D["Read current team from FPL"]
  D --> E["Re-plan with sections 4 and 5"]
  E --> F["Final card: commit gwNN-final.txt, push, ntfy, before any FPL write"]
  F --> G["Diff plan against current team"]
  G --> H{"Anything to change?"}
  H -- no --> Z["ntfy: no changes needed, exit"]
  H -- yes --> I["Submit transfers, with chip if any"]
  I --> J["Submit XI, bench order, captain, vice-captain"]
  J --> K["Read team back from FPL"]
  K --> L{"Matches plan?"}
  L -- yes --> M["Append confirmed result to card, push, ntfy"]
  L -- no --> N["Section 9: retry up to 3 times"]
  N --> K
```

### Notes

- Late changes: if an early commit already happened, the final run still re-plans and can change the XI, captain and free transfers left.
- Wildcard and Free Hit can't be undone once played, so they are submitted only from the final run, never on an early commit.
- No human veto. The card explains the decision; it does not wait for a reply.

## 7. Post-gameweek review

Runs once points are final, at 09:00 UK on the day after the last match, and the gameweek is marked data-checked.

```mermaid
flowchart TD
  A["Points final and gameweek data-checked"] --> B["Fetch actual points, minutes, bonus, auto-subs"]
  B --> C["Compare predicted and actual: each player, captain, transfers, hits, chip"]
  C --> D["Compare own projections with public projections: who was closer"]
  D --> E["Bias report: assumptions that were wrong, by how much, how often"]
  E --> F["Recalibrate model weights on new data"]
  F --> G{"Recalibrated model beats current one on backtest?"}
  G -- yes --> H["Adopt new weights"]
  G -- no --> I["Keep current weights, log why"]
  H --> J["Commit gwNN-review.txt to reviews, push, ntfy: points, rank, accuracy, biases"]
  I --> J
```

### Your part

- Read the review and decision cards, then change the code to fix biases and penalise wrong assumptions. The bot only tunes model weights itself; code changes are yours.

## 8. Rules-change check

Part D of the rules file. Weekly on Tuesday 09:00 UK, plus a daily news scan.

```mermaid
flowchart TD
  A["Tuesday 09:00 UK, pre-season dates, or news-scan hit"] --> B["Fetch bootstrap-static, Overall league 314, rules, terms, FAQ, prizes pages"]
  B --> C["Diff against the YAML baseline in D6"]
  C --> D{"Change class?"}
  D -- none --> E["Log: verified this week"]
  D -- DATA --> F["Propose table update, minor version bump"]
  D -- RULE --> G["Hold moves that depend on the changed rule"]
  G --> H["Commit change report txt, push, ntfy: old and new values, affected logic"]
  D -- REVIEW --> H
  F --> H
  H --> I["You approve rules-file update"]
  I --> J["Release held logic"]
```

## 9. Failure handling

Applies to every stage. The safe default is to make no moves: FPL keeps the previous team.

```mermaid
flowchart TD
  A["Any step fails"] --> B["Retry up to 3 times with backoff"]
  B --> C{"Succeeded?"}
  C -- yes --> D["Continue"]
  C -- no --> E{"What failed?"}
  E -- "login or token" --> F["Fresh login once"]
  F --> G{"CAPTCHA, block or 403?"}
  G -- yes --> H["ntfy: needs you, do not work around it"]
  G -- no --> I["Make no moves, alert"]
  E -- "data source down" --> J{"Cached data under 24h old?"}
  J -- yes --> K["Continue on cache, mark card"]
  J -- no --> I
  E -- "submit" --> L{"Partly saved?"}
  L -- yes --> M["Urgent alert: what saved and what did not"]
  L -- no --> I
  E -- "machine missed a run" --> N["Mac takes over or alert on next run"]
  E -- "git push" --> P["Keep commit locally, push on next run, ntfy; FPL moves still go ahead"]
```

## Approved decisions

These were the review items on the flowchart, approved as written.

1. No dry run (changed 2026-10-30): the bot plays from GW9. GW9 is entered by hand from the decision card; automated submission starts at GW10 after a check-only login run.
2. The FPL account was created by the owner on 2026-10-30; the bot logs in and never signs up.
3. Secrets are stored in the Windows Credential Manager and macOS Keychain.
4. Card file layout under `decision-cards/`, `reviews/` and `rules-alerts/`, and that a failed git push never blocks FPL moves.
5. Failover: a 15-minute tick, and the Mac takes over after 30 minutes without a Windows heartbeat, sent over ntfy.
6. Early commits only for price moves. Wildcard and Free Hit only in the final run.
7. The thresholds in section 5: 2 gameweeks as a short absence, Wildcard at 15+ points over the horizon, Free Hit at 10+ points in the week, and the Triple Captain and Bench Boost fallbacks.
8. The bot adopts recalibrated model weights only when they beat the current model on backtest. Code changes stay with you.
9. The repo is private (since 2026-10-30), so decision cards are not published. Keep it private.
11. Signing in (added 2026-10-30): the bot signs in through a real browser on the owner's machine, because FPL's login runs behind Cloudflare and DataDome bot checks. It makes its requests from inside the page using the login token the site itself creates, held in memory only. The browser profile (session cookies) lives in the local data folder, never the repo, so sign-ins are rare. A CAPTCHA or other human check stops the bot and alerts the owner.
10. Data sources (changed 2026-10-30): the FPL API (which carries Opta xG and xA per player per match) and the public vaastav/Fantasy-Premier-League archive (MIT licence) for past seasons. Understat and FBref are not used.

## Schedule

| Timing | What happens |
|---|---|
| Every 15 min | Scheduler run, heartbeat, kill-switch check |
| Daily after 00:00 UTC | Data refresh, price watch, possible early commit |
| Deadline − 24h | Weekly plan, draft card pushed to repo |
| Deadline − 2h | Final run, final card, submit by deadline − 90 min |
| 09:00 UK day after last match | Post-gameweek review and recalibration |
| Tuesday 09:00 UK | Rules-change check |
