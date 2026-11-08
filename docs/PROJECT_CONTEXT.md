# FPL bot: project context (master handover)

Last updated: 2026-11-08 (after GW10's deadline). Written for anyone, human or a new Claude session, picking this project up cold.

## 0. How to use this file

Read in this order:

1. **This file:** what exists, why, what was learned, what is unfinished.
2. **`CLAUDE.md`:** hard constraints that apply to every change.
3. **`docs/system-flow.md`:** the approved design, as flowcharts, plus the owner's rules and decisions.
4. **`docs/fpl-rules-context.md`:** FPL rules (2026/27). Part A is the only part to treat as fact.
5. **`README.md`:** setup and commands for the owner's machines.

Where this file and the design or rules files disagree, the design and rules files win; update this file to match them.

**Never put secrets in this repo.** That covers the FPL password, the GitHub token, ntfy topic names and login tokens. The owner once pasted the FPL password into chat. It must never be written anywhere, and the owner was advised to change it.

---

## 1. What the project is

An autonomous Fantasy Premier League bot for the owner's single team. It projects points with its own model, picks transfers, the XI, captain and chips, and is meant to submit them itself. Before every change it writes a **decision card**: a plain-text file with its full reasoning, committed to this repo for the owner to review and use to correct the code.

- **Goal:** maximise points, and with them overall rank and public-league rank.
- **No human veto.** The owner reviews cards afterwards and improves the code. The owner's rules are **guidance**: the bot may override them when its analysis shows a clearly better move, and must say so on the card (section 8).
- **Season:** 2026/27. The bot started at **GW9**.

## 2. Owner, account, machines

- **FPL account:** `soohzabimaru864@gmail.com`, created by the owner on 2026-10-30. Team name **xP Machine**, team (entry) ID **11204042**. The bot only signs in; it never creates accounts.
- **Owner time zone:** US Eastern. Always give deadlines in Eastern as well as UTC. GW deadlines from the API are UTC.
- **Machines:**
  - **Windows** is the primary: always on, sleep disabled, scheduler installed (`fplbot schedule install` was run on 2026-10-30).
  - **Mac** is the backup. Setup steps exist in the README ("Running on a Mac instead"), but as of this writing it has **not** been confirmed set up.
- **Repo:** `GolugulaVishnu/FPL_bot`. **Private** (made private 2026-10-30; it must stay private). The working branch `claude/clever-gauss-8fx1qn` is also the default branch.
- **Secrets:** in the OS keychain (Windows Credential Manager, macOS Keychain) under the service `fpl-bot`. The accounts are the FPL email (FPL password) and `github-token` (a fine-grained token for this repo only, Contents read/write). The owner regenerated the token on 2026-11-05 and must run `fplbot setup --reset` on each machine after any change. There's no GitHub username in the bot; pushes use `x-access-token` plus the token, passed through environment variables for one git command only.
- **Signed-in browser profile:** `<data folder>/browser-profile`. It sits outside the repo and holds session cookies.
- **Data folder** (never committed): `%LOCALAPPDATA%\fplbot` on Windows, `~/Library/Application Support/fplbot` on macOS. Holds `config.json` (role, email, ntfy topic names), the SQLite DB `fplbot.sqlite3`, the cache, logs (`logs/fplbot.log`, secrets scrubbed) and the `PAUSED` flag.
- **Notifications:** ntfy.sh, with three private topics generated at setup (alerts, control, heartbeat). The owner subscribes to alerts and control. Sending `pause` or `resume` to the control topic pauses or resumes both machines.

## 3. Status snapshot (2026-11-08)

| Area | State |
|---|---|
| Setup, keychain secrets, ntfy, scheduler (15-min tick), kill switch, Mac failover via heartbeat | Built; Windows scheduler running |
| Data store (past seasons from archive, current season from FPL API) | Built |
| Expected-points model and backtest | Built; backtest on 2025-26 |
| Squad optimiser (initial 15), transfer planner, chip check, captaincy, bench order, rule validation | Built |
| Decision cards with reasoning (squad story, clubs, per-player "why", transfers, second opinion) | Built |
| `fplbot record` (cleaned recording of the site's requests) | Built; 2 recordings captured |
| Browser sign-in (`fplbot login`, `--manual`, `--probe`) | Signs in and reads the team; **save token never captured** (see 9) |
| Automatic submission to FPL | **Not built**: blocked on the save token |
| Weekly plan / final run / post-GW review / rules-change check as scheduled jobs | **Placeholders**: they log "not built yet" and do not mark themselves done |
| Wildcard and Free Hit planner | Not built |
| Mac backup | Instructions only |

**Gameweeks played so far:** GW9 and GW10, each entered **by hand** by the owner from the bot's card (section 12).

## 4. Decision log (chronological)

- **2026-10-29:** Rules knowledge base committed (`docs/fpl-rules-context.md` v1.0). The owner then changed the operating mode to **autonomous**: the bot logs in and acts. The FPL terms (Cl.5, 6, 27, 28(d), 35-37) prohibit this; the owner accepts the risk. Part A17 keeps the published terms verbatim, and C1 records the owner's decision. The terms quotes were not falsified.
- **2026-10-29:** Design agreed through a reviewed flowchart and saved as `docs/system-flow.md`.
  - Python + SQLite; Windows primary, Mac backup.
  - Decision cards as `.txt` files in the repo (not email); ntfy for alerts.
  - Run times: plan at deadline −24h, final run −2h, submit by −90 min. Early commits only for near-certain price changes.
  - 3 retries, then alert and make no moves.
- **2026-10-30:**
  - Repo made private.
  - The owner created the FPL account themselves (the bot never signs up).
  - Data source change: the FPL API already carries Opta xG/xA, and past seasons come from the public vaastav/Fantasy-Premier-League archive (MIT). Understat and FBref are not used.
  - The dry run was dropped at the owner's request: the bot plays from GW9.
  - GW9 was entered by hand because sign-in and submission couldn't be built and tested before the deadline.
- **2026-10-30:** The owner asked for card reasoning ("why each player", chain of thought). Claims the code doesn't compute were removed; club ratings, the fixture-vs-form split and value by position were added as computed numbers.
- **2026-11-02 to 11-05:** Sign-in debugging on the real site (section 9).
- **2026-11-05:** The owner's transfer and Triple Captain rules were set (section 8). The owner also stated that the rules are guidance and the bot may override them with transparency, so the second-opinion mechanism was added.
- **2026-11-06:** GW10 entered by hand: no transfer, captain Gabriel.

## 5. Architecture

```
fplbot/
  cli.py          commands (see README); pick = build card; login/record = browser
  config.py       local settings (data folder, never repo)
  paths.py        repo root, data folder, cache, logs, DB, pause flag
  secret_store.py OS keychain (service "fpl-bot"); values registered with the log scrubber
  logs.py         rotating log + secret scrubbing; no console under pythonw
  notify.py       ntfy send/poll
  control.py      kill switch (flag file + ntfy control topic), run lock, failover decision
  schedule.py     which jobs are due (pure functions on API deadlines)
  tick.py         one scheduled run: heartbeat/failover, pause, due jobs (plan/final/post_gw/rules_check are placeholders)
  installer.py    Task Scheduler (Windows) / launchd (macOS) registration
  gitops.py       commit + pull --no-rebase + push, token via env-only http header
  fpl_api.py      public FPL API client, cached, 2s spacing; 403 = FplBlocked (never work around)
  capture.py      snapshot of bootstrap/fixtures/finished event lives into samples/<date>/
  data.py         load history (archive) and current season into the DB
  datastore.py    player_match / fixture / team tables
  sources/        history.py (archive CSVs), current.py (FPL API JSON incl. double-GW splitting)
  scoring.py      points table normalised per position; thresholds (60 min, 3 saves, DC 10/12)
  model/          ratings.py, players.py, availability.py, xp.py, project.py, backtest.py
  team.py         current team from public pages; selling price; free transfers; chips used; purchases ledger
  plan/           rules.py (validation), squad.py (MILP), chips.py, reasons.py, card.py
  fpl_session.py  browser sign-in (Playwright), in-page API calls from a quiet worker tab
  record/         recorder.py + sanitize.py: cleaned recordings, leak-checked
tests/            pytest; tests/test_session.py runs real Chromium against a fake FPL site (slow)
```

**Commands:**

| Command | What it does |
|---|---|
| `setup` | Keychain secrets, ntfy topics, optional scheduler |
| `capture --push` | Saves a data snapshot |
| `data all` | Loads past seasons and the current season |
| `project` | Prints projections |
| `backtest --season 2025-26 --save` | Runs the backtest and saves the report |
| `pick --push` | Builds the decision card. `--kind draft/final`, `--fresh` ignores the current team, `--snapshot`/`--at` for testing |
| `login [--manual] [--probe] [--push]` | Browser sign-in and team read; probe looks for the save token |
| `record --push` | Records the site's requests, cleaned |
| `status`, `pause`, `resume` | Show state, pause or resume |
| `schedule install/remove` | Switch the 15-minute run on or off |

**Dependencies:** requests, keyring, tzdata, numpy, scipy (HiGHS MILP). Optional extra `[record]`: playwright plus `python -m playwright install chromium`.

**Repo contents worth knowing:**

| Path | Contents |
|---|---|
| `samples/2026-10-30/` | Real API snapshot: bootstrap, fixtures, GW1-8 lives |
| `recordings/` | Two cleaned session recordings, plus save-token probes |
| `decision-cards/2026-27/` | gw09-final, gw10-final |
| `reports/backtest-2025-26.txt` | Backtest report |
| `team/purchases.json` | Purchase-price ledger; created when a final card includes transfers (none yet, so `INITIAL_PURCHASES` in `team.py` is used) |

## 6. The model

**Inputs:**
- Per-player, per-fixture rows: minutes, starts, goals, assists, xG, xA, xGC, clean sheets, goals conceded, saves, cards, bonus, BPS, defensive-contribution count, points.
- Two seasons: 2024-25 and 2025-26 (the archive), plus 2026-27 GW1+ from the FPL API.
- Players are matched across seasons by FPL `code`, and teams by team `code`.

**Components:**
- **Team ratings** (`ratings.py`): multiplicative xG model, league mean × attack × opponent defence × home factor.
  - Time decay with a half-life of 12 GWs; last season counts as further back.
  - A prior of 4 pseudo-matches. Promoted or unseen teams start at attack 0.85 / defence 1.15.
- **Player profile** (`players.py`):
  - **Minutes:** p_play and p60, from the last 15 team fixtures with a half-life of 4. Current season only once 3+ matches exist.
  - **Cautious prior for thin history:** p_play 0.3 / p60 0.2 with weight 1 match, fading to 0 by 5 matches.
  - **Per-90 rates** (xG, xA, saves, bonus, yellows): half-life 15 appearances; last season ×0.6; shrunk toward 0.8× the position average of regulars with 5 pseudo-90s.
  - **Defensive-contribution hit rate:** shrunk to the position prior, with k=4.
- **Availability** (`availability.py`):
  - Status a/d/i/s/u/n plus chance of playing.
  - Parses "Expected back DD Mon" and "until DD Mon".
  - Doubtful: chance, rising 25% per week ahead. Injured with no date: 0 / 25 / 50 / 75%. Suspended: 0 for the next GW. Unavailable: 0.
- **Per-fixture xP** (`xp.py`):
  - Appearance; goals and assists scaled by team xG for the fixture relative to the team average.
  - Clean sheet = p60 × exp(−opponent xG × share of 90).
  - Goals conceded and saves via Poisson floor expectations; DC = p60 × hit rate × 2; bonus per 90; yellow cards.
  - Doubles are summed; blanks are 0.
- **Projections** (`project.py`): a 6-GW horizon by default. Each projection also carries its fixtures, a "neutral opponent" projection (for the fixture effect) and evidence fields for the cards. `TeamContext` exposes the ratings.

**Backtest, 2025-26, walk-forward, GW2-38, about 28,500 player-weeks:**

| | Model | Recent form |
|---|---|---|
| Average error (MAE) | 1.00 | 1.05 |
| Correlation | 0.569 | 0.499 |
| Captain (avg actual pts) | 6.24 | 4.05 |
| Top-11 pick (pts per player) | 4.78 | 3.97 |

- FPL's own projection exists for only about 10 GWs in the archive. There FPL is better: MAE 1.36 vs 1.56, and captain 11.1 vs 9.0. The archive has no injury flags, which handicaps the model in this test. No leak was found in FPL's numbers.
- A tuning attempt (first half to tune, second half to check) did not generalise; the original settings were kept.

**Known weaknesses:**
- Projections are fairly **flat** week to week; top-end players are compressed (about 5-6 xP).
- It once captained a defender (Gabriel) over Haaland on a small margin.
- **Not modelled yet:**
  - teammate effects (e.g. Palmer and Rogers with or without João Pedro);
  - midweek European and cup minutes (rotation);
  - price-change risk;
  - set-piece duties beyond what xG captures;
  - injury news beyond the FPL flags.
- The 2026-27 data loaded so far is GW1-9.

## 7. Planning logic

- **Optimiser** (`plan/squad.py`), a HiGHS MILP through scipy:
  - Maximises weighted xP over the horizon (weight ×0.85 per later week). XI and captain are chosen per GW; bench points count ×0.1.
  - Constraints: budget, 2/5/5/3, max 3 per club, formation limits, transfer cap.
  - Shortlist: the top 45 per position plus the 8 cheapest playing.
- **Transfer mode:**
  - Owned players are valued at their **selling price**: `sell = now if now ≤ bought else bought + (now − bought)//2`, in integer tenths.
  - Budget = bank + selling prices. Each transfer beyond the free ones costs a 4-point hit (`HIT_COST`).
- **Free transfers** (`team.py`): the first GW is unlimited, then 1. They roll over to a max of 5, and a Wildcard or Free Hit week keeps the count (rules B3).
- **Bench order:** likeliest to play first, then xP. The reserve keeper always takes slot 12.
- **Captain:** highest xP in the XI. Vice: next highest with 60+ expected minutes.
- **Validation** (`plan/rules.py`) runs before any card is written. Rules are read from the API with the baseline as fallback.
- **Purchase prices are not public.** The ledger starts from the 2026-10-30 entry-create recording (`INITIAL_PURCHASES`) and is updated when a final card contains transfers. Manual deviations by the owner are not tracked; an unknown player gets "assumed today's price" plus a note.

## 8. The owner's rules (guidance) and how they are implemented

All are guidance; see the second opinion below.

| Rule (owner's words, condensed) | Implementation |
|---|---|
| Hit only if the incoming player's xP gain beats 4; an injury late with no free transfers: prefer the bench, judge by time out | `HIT_COST = 4`; bench cover is natural in the MILP; the availability model handles time out |
| Bench Boost when the 4 bench players project ≥ 14.5 total | `BENCH_BOOST_THRESHOLD = 14.5` (played GW9: bench 15.1) |
| Triple Captain at 8+ projected points, judging every GW to GW19 including possible transfers in; may hold or play by judgement | `TRIPLE_CAPTAIN_MIN_XP = 8`; compares owned players plus those affordable with one transfer to GW19; holds only if a later week beats this one by more than `TRIPLE_CAPTAIN_MARGIN = 1.0` (the bot's margin) |
| Saving free transfers is the default; transfer if the incoming player gains 10+ points over the 3-6 GW horizon, or the outgoing player is long-term injured (any upgrade, even bench); incoming must not lose value or have bad fixtures (unless bench fodder) and must not block future upgrades | `TRANSFER_GAIN_BAR = 10` (unweighted, scaled to the weighted objective); long-term out = not available and under 0.5 xP in 3+ horizon weeks (`LONG_INJURY_WEEKS = 3`); incoming must be status `a`; fixtures are in xP; **value-loss and future-budget checks not built** |
| Wildcard dead-ending: hold transfers 3-6 GWs after a Wildcard unless injury, form dip, fixture swing or key-teammate absence; short-term punts before a Wildcard are fine; use European and cup minutes to judge starts | **Not built** (needs the Wildcard planner, a teammate-effect analysis and a European fixtures source) |
| After GW19, blanks and doubles: the owner will instruct | Waiting |
| Rules are guidance; the bot may do better and must say so on the card | **Second opinion**: also plans with a free transfer worth `FT_VALUE = 2` points; adopts that plan if it is ≥ `OVERRIDE_MARGIN = 3` weighted points better, marked "OVERRIDES YOUR GUIDANCE"; otherwise shows it. Chips are not overridden yet |

Wildcard and Free Hit checks are "not built yet, held" on cards.

## 9. FPL website findings (from the owner's recordings)

- **Sign-in:** PingOne DaVinci OAuth with PKCE at `account.premierleague.com`, behind **Cloudflare** (a `cdn-cgi/challenge-platform` call, `cf_clearance`) and **DataDome** (cookie `datadome`).
  - The site's JS keeps the OIDC user in localStorage under the key `oidc.user:https://account.premierleague.com/as:<client id>`.
  - Game API calls send **`x-api-authorization`** (the login token). Writes also send **`x-csrftoken`**, whose source is **unknown**.
- **Endpoints seen:**

  | Request | Purpose |
  |---|---|
  | `GET /api/me/` | `player.entry` gives the team ID |
  | `POST /api/entry-create/` | Body: email, favourite_team, name, terms_agreed, `picks: [{element, purchase_price}]` |
  | `GET /api/my-team/{entry}/` | Picks with selling and purchase price; chips with `status_for_entry`; `transfers: {cost, status, limit, made, bank, value}` |
  | `POST /api/my-team/{entry}/` | Body: `{"chip": null or "bboost" etc, "picks": [{element, position 1-15, is_captain, is_vice_captain}]}`; repeat saves are allowed |

  Transfers endpoint: **not yet recorded**.
- **Sign-in debugging history:**
  1. Automatic sign-in clicked "Join MyPL" (sign-up). Fixed: it now presses Enter in the password field, never clicks Join or Register, and stops on sign-up pages.
  2. "Execution context was destroyed": the site redirects after sign-in. Fixed with retries.
  3. A redirect loop: the bot navigated the main tab back mid-refresh. Fixed: the bot never steers the main tab and makes requests from a separate **worker tab** parked on `/api/me/`.
  4. `fplbot login --manual` now signs in and reads the team.
- **Save-token probe:** four runs (2026-11-05, 11-06, 11-07) all report `save_token_seen: False`. Either the owner's saves weren't captured, or the header capture misses them. It was switched to `all_headers()` on 11-05, and the later runs still show False. **This blocks automatic submission.** Next ideas:
  - run `fplbot record --push` while saving, and check whether `x-csrftoken` appears in the request headers there (it did on 10-30);
  - check whether the save goes from a different frame or service worker;
  - check whether the token is derived from a cookie that isn't readable from JS.
- **Never** work around CAPTCHAs or bot protection. Stop, send an ntfy alert, and ask the owner.

## 10. Scheduler, failover and notifications

- The OS starts `fplbot tick` every 15 minutes. Job windows, from `schedule.py`:

  | Job | When |
  |---|---|
  | Daily refresh | After 00:30 UTC |
  | Plan | Deadline −24h to −2h |
  | Final | Deadline −2h to −90 min |
  | Post-GW review | Once the GW is finished and data-checked |
  | Rules check | Tuesday 09:00 UK |

  Only the daily refresh does real work. The others are placeholders and deliberately do **not** mark themselves done, so they will run for real once built.
- **Failover:** the primary posts a heartbeat to ntfy; the backup acts only after 30 minutes of silence. Before any write, the bot reads the team back from FPL, so a double submit is harmless.
- **Failure policy:** 3 retries, then an alert and no moves. A failed git push never blocks FPL moves; it pushes on a later run.

## 11. Decision cards

`decision-cards/<season>/gwNN-<draft|final>.txt`. Sections:

- **Header**
- **Summary**
- **Transfers** (transfer mode)
- **Second opinion**
- **How the squad was built:** goal, top players, biggest spend, money by position, value by position, defensive-contribution share, formation, club stacks, bench, captain rule
- **Starting XI and bench,** with an xP breakdown per player
- **Captaincy:** top 4
- **Chips**
- **Clubs in the squad:** attack and defence ratings, opponents' averages
- **Why each player:** projection, minutes record, point sources with per-90 evidence, fixture run, fixture effect vs a neutral opponent, value rank, best similar-priced alternative
- **Best players left out**
- **Assumptions and confidence,** plus a "not modelled yet" list
- **How this gameweek gets entered:** manual steps until submission is automated

Cards only contain claims computed by the code. Uncomputed claims were removed on 2026-10-30 at the owner's challenge, and that standard holds.

## 12. Gameweek log

- **GW9** (deadline Sat 31 Oct 11:00 UTC): the initial squad, entered by hand.
  - **XI:** Raya; Van Hecke, Gabriel (V), Silva, Hill; Mbeumo, Tavernier, Le Fée, Rudoni; Haaland (C), Barry.
  - **Bench:** Trafford, Calvert-Lewin, Ødegaard, De Cuyper.
  - **Chip:** Bench Boost played.
  - Cost £98.9m, bank £1.1m. Element IDs: 1, 112, 4, 566, 60, 427, 68, 542, 183, 411, 249, 385, 346, 15, 115.
- **GW10** (deadline Fri 6 Nov 18:30 UTC): no transfer (1 free transfer saved, so 2 next week). No chip (Triple Captain held: Gabriel 6.1 is under 8).
  - **XI:** Raya; Gabriel (C), Van Hecke, De Cuyper, Silva; Mbeumo, Tavernier, Le Fée, Ødegaard; Haaland (V), Barry.
  - **Bench:** Trafford, Hill, Rudoni, Calvert-Lewin (75% doubtful).
  - The owner confirmed the plan, but whether it was saved exactly as the card says has not been verified from FPL data.
- **The post-GW review isn't built,** so GW9 and GW10 have no review cards yet.

## 13. Caveats and risks

- **Terms of service:** automated sign-in and moves breach FPL's published terms. The owner accepted the risk, which includes suspension or deletion of the team. Keep requests low-frequency and cached, never hammer endpoints near deadlines, and never republish Game data (the repo is private).
- **This cloud session can't reach FPL, Understat, etc.** (proxy and FPL bot protection). Everything live runs on the owner's machines; Claude works from pushed snapshots and recordings.
- **The model is new and only lightly validated.** FPL's own projections were better on comparable weeks. Treat captaincy edges under about 1 xP as coin flips.
- **Selling prices** depend on the purchases ledger; transfers made by hand outside the card aren't tracked.
- **Free-transfer count** is computed from history using the rules in B3 (some parts tagged COMMUNITY). Verify it against `my-team` `transfers.limit` once sign-in works.
- **Rules file:** v2.6. The first-run baseline check (v2.4) matched the live API. Page hashes are still unset, and the rules-change check job isn't built.

## 14. Next steps (in priority order)

1. **Save token** (section 9), then **automatic submission:** lineup, captain and chip via `POST /api/my-team/`; record the transfers endpoint; read back after every write. Then a dry submission (show what would be sent), then switch on the plan and final jobs in `tick.py`.
2. **Post-gameweek review job:** predicted vs actual per player, captain, transfers and chips; FPL's projection as a benchmark; a bias report committed to `reviews/`; recalibration adopted only if it beats the backtest.
3. **Rules-change check job** (rules file Part D).
4. **Wildcard and Free Hit planner,** with the owner's dead-end rules.
5. **Owner rules still open:** value-loss and future-budget checks; teammate effects; European and cup minutes (needs a free fixtures source); price-drop risk.
6. **Mac backup:** confirm setup, paste the Windows topics, and test failover.
7. **Model:** better top-end separation (the flat-projection issue); FPL's `ep_next` as an extra benchmark in live reviews.

## 15. Working agreements with the owner

- **Clarify, then act.** Ask clarifying questions before big designs; once answered, act.
- **Commands:** give step-by-step commands, each in its own code block, with Eastern times.
- **Commit and push after every meaningful change,** on `claude/clever-gauss-8fx1qn`. Don't open PRs unless asked.
- **Honesty:** state honestly what is untested, and what was learned from the owner's runs.
- **Ask for approval** before changing the agreed design (`docs/system-flow.md`); record the owner's decisions there with dates.
- **Never ask for or accept secrets in chat.** Point to `fplbot setup --reset` instead.
