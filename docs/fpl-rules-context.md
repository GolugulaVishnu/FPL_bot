# FPL rules context for bot

```yaml
title: Fantasy Premier League rules knowledge base (Classic game, Classic and H2H leagues, cups)
version: v2.4
rules_baseline: "2026/27 season, verified 2026-10-29 at GW9 (GW8 finished; GW9 deadline 2026-10-31T11:00Z)"
authoritative_sources:
  - Official rules page, rendered in a browser 2026-10-29: https://fantasy.premierleague.com/help/rules
  - Official terms ("2026/27 Fantasy Premier League - Terms & Conditions"), rendered 2026-10-29: https://fantasy.premierleague.com/en/help/terms
  - Live game API, read 2026-10-29: https://fantasy.premierleague.com/api/bootstrap-static/
supporting_sources:
  - premierleague.com official FPL news articles (July 2026 rule explainers, 1 Oct 2026 Second Chance article)
  - Community analysis (Fantasy Football Scout, OneFPL, FPL Oracle, Draft Fantasy, open-source FPL clients)
time_convention: "All times UTC unless marked UK. UK = GMT (UTC+0) from 2026-10-25 to 2027-03-28, BST (UTC+1) otherwise."
```

**How to use this file.** This is the rules reference for the FPL bot. Part A holds the official rules and is the only part the bot may treat as fact; every line there comes from the rules page, the terms, or the live API. Part B holds mechanics FPL does not fully document; each item carries a confidence tag, and the bot should only lean on `[OFFICIAL-API]` and `[OFFICIAL-NEWS]` items without a fallback. Part C turns the rules into constraints on the bot's own behaviour, starting with the bot's operating mode (autonomous: it logs in and manages the team itself). Part D specifies the weekly check that detects rule changes and keeps this file current, with a YAML baseline to diff against. Part E lists what is still unconfirmed. When live API values disagree with this file, trust the API for that run, raise a rules-change alert, and do not silently patch the file. Source keys in square brackets (for example `[rules]`, `[api]`) resolve to URLs in the Sources section at the end.

---

## Part A. Official rules (2026/27)

### A1. Squad and budget

| Rule | Value | Source |
|---|---|---|
| Squad size | 15 players: 2 GK, 5 DEF, 5 MID, 3 FWD | [rules] [api] |
| Initial squad budget | £100.0m maximum (API `squad_total_spend: 1000`, units of £0.1m, `ui_currency_multiplier: 10`) | [rules] [api] |
| Club limit | Max 3 players from any one Premier League team (`squad_team_limit: 3`) | [rules] [api] |
| Position of a player | Fixed by the player's `element_type` in the API | [api] |

### A2. Starting XI, formation and bench

- Pick 11 starters (`squad_squadplay: 11`) in any formation with exactly 1 GK, at least 3 DEF and at least 1 FWD [rules].
- API position limits for the XI [api]:

| Position | Squad | Min in XI | Max in XI |
|---|---|---|---|
| GKP | 2 | 1 | 1 |
| DEF | 5 | 3 | 5 |
| MID | 5 | 2 | 5 |
| FWD | 3 | 1 | 3 |

- These limits allow eight formations: 3-4-3, 3-5-2, 4-3-3, 4-4-2, 4-5-1, 5-2-3, 5-3-2, 5-4-1 (derived from the table).
- The remaining 4 players form the bench. The GKP `element_type` has `sub_positions_locked: [12]`, so pick slot 12 (first bench slot) is always the reserve goalkeeper. Slots 13 to 15 are outfield substitutes in priority order [api].
- All changes to the XI, captaincy and bench order must be made before the gameweek deadline [rules].

### A3. Captain and vice-captain

- The captain's score is doubled [rules].
- "If your captain plays no minutes in the Gameweek, the captain will be changed to the vice-captain. If both captain and vice-captain play no minutes in a Gameweek, then no player's score will be doubled." [rules]
- Vice-captaincy is enabled (`sys_vice_captain_enabled: true`) [api].
- Triple Captain chip: captain's score is tripled instead of doubled (see A7) [rules].

### A4. Automatic substitutions and the meaning of "played"

- "Playing in a Gameweek means making an appearance on the pitch or receiving a yellow / red card." An unused substitute who is booked therefore counts as having played [rules].
- Substitutions are processed at the end of the gameweek, in bench priority order [rules].
- A goalkeeper who did not play is replaced only by the reserve goalkeeper, and only if the reserve played [rules].
- An outfield starter who did not play is replaced by the highest-priority outfield substitute who played and whose entry does not break the formation rules in A2 [rules].

### A5. Transfers and free transfers

| Rule | Value | Source |
|---|---|---|
| Before the first deadline of your season | Unlimited free transfers | [rules] |
| Free transfers (FT) after that | 1 per gameweek | [rules] |
| Unused FTs | Carry over; maximum 5 stored (API `max_extra_free_transfers: 4`, i.e. 1 + 4) | [rules] [api] |
| Each transfer beyond your FTs | -4 points, deducted from your total (Classic) and your match score (H2H) "at the start of the next Gameweek" | [rules] |
| Transfers per gameweek | Max 20 ("At other times you are limited to 20 transfers in any single Gameweek. This rule does not apply when playing a Wildcard or a Free Hit chip."); API `transfers_cap: 20` | [rules] [api] |
| FTs when playing Wildcard or Free Hit | "any saved free transfers are retained for the following Gameweek. If you had 2 saved FTs, you will still have 2 the Gameweek after." | [rules] |
| Like-for-like | Transfers keep the 2/5/5/3 squad shape, the club limit and the budget | [rules] [api] |

### A6. Player prices and selling price

- Prices do not change until the season starts. After that they change according to the popularity of the player in the transfer market [rules].
- Selling price = purchase price + half of any rise, rounded down to the nearest £0.1m. Rules page example: bought at £7.5m, now £7.8m, sells for £7.6m [rules]. API: `transfers_sell_on_fee: 0.5`, `element_sell_at_purchase_price: false` [api].
- A fall in price is passed on in full (falls are not halved; follows from `element_sell_at_purchase_price: false` and the official worked examples in [pl-transfers]).
- Price updates: API `game_config.settings.price_change_deadlines` lists one update per day at **00:00 UTC** (for example 2026-10-30T00:00:00Z, 2026-10-31T00:00:00Z, 2026-11-01T00:00:00Z). That is 00:00 UK in winter (GMT) and 01:00 UK during BST. `game_config.settings.timezone` is `"UTC"`. Last update seen: `price_change_last_updated` 2026-10-29T21:35Z [api].

### A7. Chips

One chip per gameweek. Eight chips: one of each type per half-season [rules] [api].

| API id | Chip (`name`) | Type | Window (API `start_event`-`stop_event`) | Effect | Cancel before deadline? |
|---|---|---|---|---|---|
| 1 | Wildcard 1 (`wildcard`) | transfer | GW2-19 | All transfers in the GW are free, including ones already made that GW | No, once played |
| 2 | Wildcard 2 (`wildcard`) | transfer | GW20-38 | As above | No, once played |
| 3 | Free Hit 1 (`freehit`) | transfer | GW2-19 | Unlimited free transfers for one GW; squad reverts at the next deadline | No, played on confirming transfers |
| 6 | Free Hit 2 (`freehit`) | transfer | GW20-38 | As above | No |
| 4 | Bench Boost 1 (`bboost`) | team | GW1-19 | Bench players' points count | Yes |
| 7 | Bench Boost 2 (`bboost`) | team | GW20-38 | As above | Yes |
| 5 | Triple Captain 1 (`3xc`) | team | GW1-19 | Captain scores x3 | Yes |
| 8 | Triple Captain 2 (`3xc`) | team | GW20-38 | As above | Yes |

Window and timing rules [rules]:

- First-half chips (set 1) are available from the start of your season (Wildcard and Free Hit from after your first gameweek) until the **GW19 deadline: Fri 1 Jan 2027 18:30 UTC (18:30 UK)**. API `deadline_time` for GW19 is 2027-01-01T18:30:00Z. Set 2 becomes available after that deadline.
- Free Hits cannot be played in consecutive gameweeks. Playing Free Hit 1 in GW19 means Free Hit 2 is not available until GW21.
- Free Hit cannot be played in your first gameweek (API window starts GW2).
- Weekly prizes: a manager who played Bench Boost, Free Hit, Triple Captain or Wildcard is not eligible for that week's prize [terms Cl.21].
- There is no Assistant Manager chip in 2026/27. The `mng_*` scoring keys are present in the API but all set to 0 [api].

### A8. Deadlines

- Deadline = 90 minutes before the first kick-off of the gameweek [rules].
- "A deadline will not change within 24 hours of the scheduled time." [rules]
- Transfers, starting XI, captain, vice-captain and bench order must all be saved by the deadline [rules].
- The rules page displays deadlines in the viewer's local time zone. The API `events[].deadline_time` is UTC and is the source of truth [api].

2026/27 deadlines from the API (read 2026-10-29). Deadlines move when fixtures are rescheduled; always re-read the API.

| GW | Deadline (UTC) | UK local | GW | Deadline (UTC) | UK local |
|---|---|---|---|---|---|
| 1 | 2026-08-21 17:30 | Fri 18:30 BST | 20 | 2027-01-05 18:00 | Tue 18:00 GMT |
| 2 | 2026-08-28 17:30 | Fri 18:30 BST | 21 | 2027-01-16 13:30 | Sat 13:30 GMT |
| 3 | 2026-09-04 17:30 | Fri 18:30 BST | 22 | 2027-01-23 13:30 | Sat 13:30 GMT |
| 4 | 2026-09-12 12:30 | Sat 13:30 BST | 23 | 2027-01-30 13:30 | Sat 13:30 GMT |
| 5 | 2026-09-18 17:30 | Fri 18:30 BST | 24 | 2027-02-06 13:30 | Sat 13:30 GMT |
| 6 | 2026-10-10 10:00 | Sat 11:00 BST | 25 | 2027-02-10 18:30 | Wed 18:30 GMT |
| 7 | 2026-10-17 10:00 | Sat 11:00 BST | 26 | 2027-02-20 13:30 | Sat 13:30 GMT |
| 8 | 2026-10-23 17:30 | Fri 18:30 BST | 27 | 2027-02-27 13:30 | Sat 13:30 GMT |
| 9 | 2026-10-31 11:00 | Sat 11:00 GMT | 28 | 2027-03-03 18:30 | Wed 18:30 GMT |
| 10 | 2026-11-06 18:30 | Fri 18:30 GMT | 29 | 2027-03-13 13:30 | Sat 13:30 GMT |
| 11 | 2026-11-21 11:00 | Sat 11:00 GMT | 30 | 2027-03-20 13:30 | Sat 13:30 GMT |
| 12 | 2026-11-27 18:30 | Fri 18:30 GMT | 31 | 2027-04-10 12:30 | Sat 13:30 BST |
| 13 | 2026-12-01 18:30 | Tue 18:30 GMT | 32 | 2027-04-17 12:30 | Sat 13:30 BST |
| 14 | 2026-12-05 11:00 | Sat 11:00 GMT | 33 | 2027-04-24 12:30 | Sat 13:30 BST |
| 15 | 2026-12-12 13:30 | Sat 13:30 GMT | 34 | 2027-05-01 12:30 | Sat 13:30 BST |
| 16 | 2026-12-19 11:00 | Sat 11:00 GMT | 35 | 2027-05-08 12:30 | Sat 13:30 BST |
| 17 | 2026-12-26 11:00 | Sat 11:00 GMT | 36 | 2027-05-15 12:30 | Sat 13:30 BST |
| 18 | 2026-12-29 18:00 | Tue 18:00 GMT | 37 | 2027-05-23 12:30 | Sun 13:30 BST |
| 19 | **2027-01-01 18:30** (chip set 1 expires) | Fri 18:30 GMT | 38 | 2027-05-30 13:30 | Sun 14:30 BST |

### A9. Scoring

Per player, per match [rules] [api]:

| Action | GK | DEF | MID | FWD |
|---|---|---|---|---|
| Played 1-59 min | 1 | 1 | 1 | 1 |
| Played 60+ min (excluding stoppage time) | 2 | 2 | 2 | 2 |
| Goal | 10 | 6 | 5 | 4 |
| Assist | 3 | 3 | 3 | 3 |
| Clean sheet | 4 | 4 | 1 | 0 |
| Every 3 saves | 1 | - | - | - |
| Defensive contribution (once per match, does not stack) | 0 | 2 at 10+ CBIT | 2 at 12+ CBIRT | 2 at 12+ CBIRT |
| Penalty save | 5 | - | - | - |
| Penalty miss | -2 | -2 | -2 | -2 |
| Bonus | 1 to 3 | 1 to 3 | 1 to 3 | 1 to 3 |
| Every 2 goals conceded | -1 | -1 | 0 | 0 |
| Yellow card | -1 | -1 | -1 | -1 |
| Red card | -3 | -3 | -3 | -3 |
| Own goal | -2 | -2 | -2 | -2 |

CBIT = clearances, blocks, interceptions, tackles. CBIRT = CBIT plus ball recoveries [rules].

Scoring conditions [rules]:

- Clean sheet: the player did not concede while on the pitch and played at least 60 minutes excluding stoppage time. Goals conceded after he is substituted off do not affect it.
- Red card: the player keeps being penalised for goals his team concedes after his dismissal. The -3 includes any yellow-card deduction (a second-yellow red is -3 in total, not -4).
- API `game_config.scoring` keys `bps`, `influence`, `creativity`, `threat`, `ict_index`, `tackles`, `clearances_blocks_interceptions`, `recoveries`, `starts`, `expected_*` and all `mng_*` are 0. `special_multiplier` is 1 [api].

### A10. Assists

From the rules page [rules]:

- Assists are reviewed with Opta. The assist goes to the final touch by an attacking player before the goal: a pass, any touch (including an inadvertent one), or a shot.
- If a shot is saved, blocked or hits the woodwork and is then scored, the shooter gets the assist. The shot need not be on target unless it was deflected.
- Winning a penalty or direct free kick (by being fouled or by a handball) that someone else scores earns an assist.
- No assist for winning a corner or throw-in.
- Own goals can earn assists.

### A11. Bonus points and the BPS

Top three BPS scorers in each match get 3, 2 and 1 bonus points [rules]. Ties [rules]:

| Situation | Bonus awarded |
|---|---|
| Tie for 1st | Both get 3; next player gets 1 |
| Tie for 2nd | 3; then 2 and 2 |
| Tie for 3rd | 3, 2; then 1 and 1 |

BPS table 2026/27 [rules]:

| Action | BPS |
|---|---|
| Playing 1-60 minutes | 3 |
| Playing over 60 minutes | 6 |
| Penalty goal (any position) | 12 |
| GK or DEF goal (non-penalty) | 12 |
| MID goal (non-penalty) | 18 |
| FWD goal (non-penalty) | 24 |
| Assist | 9 |
| GK or DEF clean sheet | 12 |
| Save | 2 |
| Save from a shot inside the box | +1 |
| Save from a big chance | +1 |
| Penalty save | 7 |
| Every 3 clearances, blocks and interceptions (CBI) | 1 |
| Every 3 recoveries | 1 |
| Chance created | 1 |
| Big chance created | 3 |
| Successful open-play cross | 1 |
| Successful tackle | 2 |
| Successful dribble | 1 |
| Scoring the winning goal | 3 |
| Goal-line clearance | 9 |
| Foul won | 1 |
| Shot on target | 2 |
| Pass completion 70-79% (30+ attempted) | 2 |
| Pass completion 80-89% (30+ attempted) | 4 |
| Pass completion 90%+ (30+ attempted) | 6 |
| GK or DEF goal conceded | -4 |
| Penalty conceded | -3 |
| Penalty missed | -6 |
| Yellow card | -3 |
| Red card | -9 |
| Own goal | -6 |
| Big chance missed | -3 |
| Error leading to goal | -3 |
| Error leading to attempt at goal | -1 |
| Foul conceded | -1 |
| Offside | -1 |
| Shot off target | -1 |

BPS data comes from Opta and is not changed after the gameweek is marked final [rules].

### A12. Points finalisation

- Points are "subject to change up to 9am UK time on the day after the final match of the Gameweek." After that there are no adjustments except in extraordinary circumstances [rules].
- The PL is the sole decision-maker on interpretation, points allocation and rankings, and its decisions are final [terms Cl.15].

### A13. Leagues: general settings

| Setting | Value | Source |
|---|---|---|
| Private (invitational) leagues a team can join | Up to 30 (`league_join_private_max: 30`) | [rules] [api] |
| Public leagues a team can join | Up to 5 (`league_join_public_max: 5`) | [rules] [api] |
| Teams in a private Classic league | No limit | [rules] |
| Public Classic league size | 20 (`league_max_size_public_classic`) | [api] |
| Public H2H league size | 20 (`league_max_size_public_h2h`) | [api] |
| Private H2H league size | 16 max (`league_max_size_private_h2h`) | [api] |
| Private H2H knockout rounds | Up to 3 (`league_max_ko_rounds_private_h2h`) | [rules] [api] |
| H2H knockout seeding | Random, not top-vs-second (`league_ko_first_instead_of_random: false`) | [api] |
| H2H points | Win 3, draw 1, loss 0 | [rules] [api] |
| H2H match tie-break stats | `["+goals_scored", "-goals_conceded"]` | [api] |
| Cup settings | `cup_start_event_id`, `cup_stop_event_id`, `cup_qualifying_method`, `cup_type` all `null` on 2026-10-29 | [api] |

Leagues every team is entered into automatically [rules]: Overall, Country, favourite club, the league for managers who started in the same gameweek, the Second Chance League ("starts in Gameweek 21" per the rules page; see Part E), and the Fantasy Cup. Qualifying global leagues: 1% League 25/26, 10% League 25/26 and the Rookie League [rules].

### A14. Classic leagues

- Ranked by total points [rules].
- Tie on points: the team that made fewer transfers ranks higher. Wildcard and Free Hit transfers are not counted [rules].
- A manager cannot leave a Classic league while still in that league's cup [rules].
- Monthly phases [rules]:

| Phase | Gameweeks |
|---|---|
| August | 1-2 |
| September | 3-5 |
| October | 6-9 |
| November | 10-12 |
| December | 13-18 |
| January | 19-23 |
| February | 24-27 |
| March | 28-30 |
| April | 31-33 |
| May | 34-38 |

- "Any transfer point deductions in the Gameweek before a phase starts won't be deducted from the phase score. For example, any transfers made in Gameweek 6 (preparing for Gameweek 7) won't be deducted from your October score." (verbatim; the example sits oddly with October starting at GW6, see Part E) [rules].

### A15. Head-to-head leagues

- Each gameweek a team plays one opponent. Match score = gameweek score minus transfer hits. Win 3, draw 1, loss 0 [rules].
- Fixtures are generated at the start of the league's first gameweek. After that the league is locked: no one can join or leave [rules].
- Odd number of teams: an AVERAGE team is added, scoring the gameweek average [rules].
- League table ties are broken by most total game points [rules].
- Optional knockout stage of up to 3 gameweeks, ending in the final gameweek. The AVERAGE team is excluded. Knockout tie-breaks: most goals scored in the GW, then fewest goals conceded in the GW, then a virtual coin toss [rules].

### A16. Cups

- Each cup round is a single gameweek. Opponents are drawn at random each round. The winner is the team with the higher gameweek score minus hits [rules].
- Tie-breaks: most goals scored in the GW, then fewest goals conceded in the GW, then a virtual coin toss [rules].
- Overall (Fantasy) Cup: starts GW15 and runs to GW38 per the rules page. The API cup fields were still `null` on 2026-10-29 [rules] [api].
- League Cups are created automatically for all invitational Classic leagues. They start in the second half of the season, at a gameweek that depends on league size, with the final in GW38 [rules].
- Fan League Cups and Country Cups also exist [rules].

### A17. Terms and conditions (verbatim-verified excerpts)

| Clause | Content | Source |
|---|---|---|
| 1 | Entry only online via premierleague.com or the Premier League App; a registered entrant is a "Player" | [terms] |
| 5 | "Registrations must not be made by agents or third parties." | [terms] |
| 6 | One registration per user; no multiple accounts; a Player may not give anyone else access to their account "to play the Game or otherwise" | [terms] |
| 7 | No registration closing date; PL publishes deadlines to qualify for points in a round | [terms] |
| 8, 30(d) | Optional two-factor authentication; the Player is responsible for securing credentials, including enabling 2FA where available | [terms] |
| 9 | PL can rename, suspend or delete teams or leagues with inappropriate names | [terms] |
| 13, 28(g) | No commercial mini-leagues (paid entry or entry conditional on a purchase) | [terms] |
| 14 | Game Rules form part of the Terms; PL may alter them at its absolute discretion; continued use means acceptance; Players are "advised to check the Game Rules regularly" | [terms] |
| 15 | PL is sole decision-maker on interpretation, points and rankings; decisions final | [terms] |
| 20 | Weekly prize eligibility requires registration before the season starts or at least 2 clear gameweeks before the winning week | [terms] |
| 21 | Playing BB, FH, TC or WC makes a Player ineligible for that week's prize | [terms] |
| 27 | Keep the password secure and change it often; a Player "shall not allow any other person access to your account nor share or transfer registration or control of your account with or to another person" | [terms] |
| 28(c) | No spamming or flooding | [terms] |
| 28(d) | A Player shall not "use automated systems to access the Game and extract information from the Game" | [terms] |
| 28(e) | No unauthorised access to other systems | [terms] |
| 29 | PL owns all IP including Game data; no use without written consent | [terms] |
| 35-37 | Breach of the Game Rules is a breach of the Terms; PL may refuse entry, disqualify, suspend or delete registration and data; barred Players may not re-enter under another identity | [terms] |
| 22-23 | Still cite 2026 dates (28 June 2026, 24 May 2026), apparently carried over from the 2025/26 text | [terms] |

The excerpts above are the terms as published. The account owner has decided to run the bot autonomously anyway and accepts the risk under Cl.35-37; see C1.

---

## Part B. Hidden and inferred mechanics

Tags: `[OFFICIAL-API]` = observed in live API data or config. `[OFFICIAL-NEWS]` = stated in an official premierleague.com article but not on the rules page. `[COMMUNITY]` = consistent across community analysis or working open-source code. `[SPECULATIVE]` = single source, inferred, or contested.

### B1. Price changes

- `[OFFICIAL-API]` Updates run once a day at 00:00 UTC (see A6). The PL article describes this as "00:00 UK time" [pl-changes]; the API array is in UTC, so read `price_change_deadlines` rather than hard-coding a clock time [api].
- `[OFFICIAL-API]` New per-player fields in 2026/27: `price_change_percent`, `price_change_hourly_rate`, `price_change_projections`, `price_change_locked_until`, `price_change_calibrating`, alongside `cost_change_event`, `cost_change_event_fall`, `cost_change_start`, `transfers_in_event`, `transfers_out_event` [api]. Field semantics (sign of `price_change_percent` for falls, what the hourly rate measures) are undocumented.
- `[OFFICIAL-NEWS]` The official Price Change Predictor shows progress toward a rise or fall [pl-changes].
- `[COMMUNITY]` The predictor refreshes about every 15 minutes, shows values only after a calibration period of at least one gameweek, and a reading above 100% means a change is expected at the next update but not guaranteed [draft].
- `[COMMUNITY]` A player moves at most £0.1m per daily update [draft] [oracle] [ffs-prices].
- `[SPECULATIVE]` A cap of £0.3m per gameweek in either direction. FFS and FPL Oracle state it [ffs-prices] [oracle]; OneFPL says there is no per-GW cap [onefpl-prices]. An older official article described £0.3m per GW as typical past behaviour, not a cap [pl-prices].
- `[COMMUNITY]` The threshold depends on net transfers relative to ownership; low-owned players need fewer net transfers. The formula is not published [oracle] [onefpl-prices].
- `[SPECULATIVE]` Wildcard transfers do not count toward price changes [ffs-prices]. OneFPL calls this community belief, not confirmed by FPL, and says nothing about Free Hit [onefpl-wc].
- `[COMMUNITY]` Some players are price-locked (often recent signings); lock windows are not uniform. `price_change_locked_until` now exposes the lock [oracle] [onefpl-prices] [api].
- `[COMMUNITY]` Prices keep updating nightly through international breaks, which concentrates movement [oracle]. Injury flags have no direct price effect [oracle].
- `[SPECULATIVE]` A price floor around £3.5m-£4.0m and a post-move "flag" or reset. Older lore, no 2026/27 source.

### B2. Selling price edge cases

- `[OFFICIAL-API]` In integer tenths: `sell = now if now <= bought else bought + (now - bought) // 2` [api] [rules].
- `[COMMUNITY]` Worked examples: £7.0m to £7.5m sells at £7.2m; £5.0m to £5.1m sells at £5.0m; two rises are needed to gain £0.1m [onefpl-prices] [oracle].
- `[COMMUNITY]` A Wildcard purchase is a normal permanent purchase and sets a new purchase price.
- `[SPECULATIVE]` Selling and re-buying a player resets his purchase price to the current price (follows from the formula).
- `[SPECULATIVE]` After a Free Hit the original squad keeps its original purchase prices, and Free Hit picks never generate profit.

### B3. Free-transfer accounting

- `[COMMUNITY]` Standard model outside chip weeks: `FT_next = min(5, max(0, FT_now - transfers_made) + 1)`. Transfers beyond `FT_now` cost 4 points each.
- `[COMMUNITY]` Wildcard or Free Hit week: banked FTs are kept and no FT is added for the chip week. The official example ("2 saved FTs, still 2 the Gameweek after") supports this [rules] [onefpl-chips].
- `[OFFICIAL-NEWS]` Activating a Wildcard removes hits already taken in that gameweek [pl-chips].
- `[OFFICIAL-NEWS]` No extra free transfers in December 2026; the 2025/26 AFCON top-up does not repeat because AFCON is not in the 2026/27 season [pl-changes].
- `[COMMUNITY]` The authenticated team endpoint reports `transfers.limit` as null when transfers are unlimited (pre-season, Wildcard) [fplbuddy].
- `[SPECULATIVE]` A team created mid-season gets unlimited free transfers until its first deadline (the rules page says "before the first deadline of your season", which suggests it).

### B4. Auto-subs, captaincy, doubles and blanks

- `[COMMUNITY]` Auto-sub algorithm: for each starter who did not play, try bench slots 13, 14, 15 in order; take the first unused substitute who played and keeps the XI within the A2 limits. Slot 1 (GK) can only be replaced by slot 12.
- `[COMMUNITY]` Double gameweek: a player who appears in either match has "played". The captain is not replaced if he plays in only one match, and his combined points are doubled (or tripled with TC) [ffs-tc].
- `[COMMUNITY]` Triple Captain: if the captain does not play, the vice-captain gets x3. If neither plays, the chip is used up with no effect [ffs-tc].
- `[COMMUNITY]` Bench Boost counts all 15 players, so no auto-subs apply.
- `[COMMUNITY]` A single-fixture player whose match is postponed scores 0 and is eligible for auto-sub. Postponed fixtures get `event: null` in the fixtures API until rescheduled, and a rescheduled fixture can create a double gameweek [api].
- `[SPECULATIVE]` Defensive contribution in a double gameweek is assessed per match, so up to 4 points are possible (follows from the "per match" cap) [pl-defcon].
- `[SPECULATIVE]` Abandoned matches: no 2026/27 source on whether stats stand or replays score.

### B5. Data timing and live data

- `[OFFICIAL-NEWS]` Projected bonus is added to live scores after 20 minutes of each match and moves during the match [pl-changes].
- `[OFFICIAL-NEWS]` Overall and mini-league ranks (including H2H and cups) update live [pl-changes].
- `[OFFICIAL-NEWS]` The 09:00 UK finalisation (new in 2026/27; previously one hour after the last whistle) exists so post-match Opta review can feed BPS and defensive contributions [pl-changes].
- `[OFFICIAL-NEWS]` Assist decisions are made by a Stockley Park team with Opta; unclear calls show as "TBC"; the Goal Accreditation Panel settles disputed scorers, and the assist follows [pl-assists]. The 2025/26 assist rewrite (handball "forced" element dropped, two defensive touches void the assist) still applies [pl-assists25].
- `[COMMUNITY]` `event/{gw}/live/` values are provisional until finalisation.
- `[COMMUNITY]` Each entry in the API `events` array carries status flags (finished, data checked). Prefer these over the clock for finalisation, but confirm the field names on the first run.

### B6. Player status and availability

- `[OFFICIAL-API]` Per-player fields: `status`, `chance_of_playing_this_round`, `chance_of_playing_next_round`, `news`, `news_added`, `can_transact`, `can_select`, `removed` [api].
- `[COMMUNITY]` Status codes: `a` available, `d` doubtful (25/50/75%), `i` injured, `s` suspended, `u` unavailable (left club or loaned out), `n` not eligible (for example a loanee facing his parent club). Chance values are 0, 25, 50, 75 or null [ffhub-flags].
- `[COMMUNITY]` FPL flags only on confirmed information from the player, manager or club [ffhub-flags].
- `[OFFICIAL-NEWS]` 11 players were reclassified to new positions for 2026/27; read `element_type` at run time [pl-changes].

### B7. Leagues and cups beyond the rules page

- `[OFFICIAL-API]` The Overall league is id 314, `scoring: "c"`, `start_event: 1`, `has_cup: true` [api-314]. Every league has a `start_event`; points count from that gameweek regardless of when a team joined.
- `[OFFICIAL-NEWS]` Classic ties on points and transfers share a rank. For official prizes the earlier-registered team (lower entry ID) wins the tie [pl-ties]. Mini-league prize ties are for members to settle.
- `[OFFICIAL-NEWS]` League Cup start by league size, counting back from a GW38 final: 1-2 teams GW38; 3-4 GW37; 5-8 GW36; 9-16 GW35; 17-32 GW34; 33-64 GW33; 65-128 GW32; 129-256 GW31; 257-512 GW30; 513-1,024 GW29; 1,025-2,048 GW28; 2,049-4,096 GW27; 4,097-8,192 GW26; 8,193-16,384 GW25; 16,385-32,768 GW24; up to 8,388,608 teams GW16. Byes go to the highest scorers in the qualifying gameweek. Admins enable it under Options > Administer > "Create League Cup" [pl-leaguecup]. Published in 2022; not re-confirmed for 2026/27.
- `[SPECULATIVE]` Chips apply in cup and H2H matches (cup score is GW score minus hits; no source restricts chips).
- `[OFFICIAL-NEWS]` Second Chance League 2026/27: scores from zero starting GW6 (deadline Sat 10 Oct 2026 11:00 BST), all managers entered, no cup [pl-scl]. Conflicts with the rules page's "starts in Gameweek 21" (Part E).
- `[OFFICIAL-NEWS]` UK residents are auto-entered into the Sky Sports Broadcaster League, which awards a monthly prize [pl-sky].
- `[COMMUNITY]` Mini-league admins can close the league and remove or block managers [ffhub-leagues].

### B8. Legacy API fields

- `[OFFICIAL-API]` `underdog_differential: 5` and the `mng_*` scoring keys are left over from the 2024/25 Assistant Manager chip [api] [pl-am]. All `mng_*` values are 0. A non-zero value would signal a manager-style chip returning.

### B9. API and access (context only)

- `[COMMUNITY]` Public read endpoints include `bootstrap-static/`, `fixtures/`, `element-summary/{id}/`, `event/{gw}/live/`, `entry/{id}/`, `entry/{id}/history/`, `leagues-classic/{id}/standings/` [fplbuddy] [plmcp]. FPL publishes no API documentation and no rate limits.
- `[COMMUNITY]` Since 2025/26, login uses PingOne (Ping Identity) OAuth 2.0 / OIDC with PKCE at account.premierleague.com, and authenticated calls carry a short-lived bearer token [fplbuddy] [plmcp].
- `[COMMUNITY]` Premier League's edge bot protection blocks cloud-provider IP ranges with empty 403 responses [fplbuddy].
- `[COMMUNITY]` Write endpoints exist (transfers and team selection), but no official specification exists and the community versions are reverse-engineered [fplbuddy]. The bot uses them to make its moves (C1); confirm request and response shapes against live traffic on the first authenticated run.

### B10. How rule changes arrive

- `[OFFICIAL-NEWS]` Season rule changes are announced in July on premierleague.com (2026/27: 20 Jul and 31 Jul 2026) [pl-changes] [ffs-changes].
- `[OFFICIAL-NEWS]` Mid-season changes also come via premierleague.com news, usually 1 to 6 weeks ahead: Second Chance League from GW6, announced 1 Oct 2026, 9 days before its first deadline [pl-scl]; the Assistant Manager chip, announced 12 Dec 2024, about 6 weeks before it went live [pl-am]; the 2025/26 AFCON transfer top-up, announced in July 2025 and re-explained 9 Dec 2025 [pl-afcon].
- `[COMMUNITY]` The 2019/20 COVID restart gave unlimited transfers with 9 days' notice [ffs-covid].
- `[OFFICIAL-API]` The API changes when a feature goes live (for example new entries in `chips`, or cup fields becoming non-null).

---

## Part C. Bot implications

### C1. Operating mode (read this first)

**Mode: autonomous.** The account owner has decided the bot runs the team by itself. Each gameweek it logs in, computes transfers, XI, bench order, captain, vice-captain and chip decision, and makes and confirms every move itself before the deadline. It writes each decision and action, with its reasoning, to a decision card for the owner to review. There is no human veto: the owner's role is to review cards and change the code to fix biases and wrong assumptions. The full run sequence is in `docs/system-flow.md`.

- The owner created the FPL account for `soohzabimaru864@gmail.com` on 2026-10-30. The bot only logs in; it never registers accounts. If login shows a CAPTCHA or other human check, the bot stops and asks the owner to complete that step; it never works around it. No squad is picked until go-live, after a 2-gameweek dry run.
- The bot runs on the owner's own machines: Windows primary, macOS backup. It never logs in from cloud servers.
- The bot may store the owner's password, session and tokens. The owner enters the FPL password once per machine through the bot's setup command, which saves it to the OS keychain (Windows Credential Manager, macOS Keychain). Secrets stay out of the repository (OS keychain, environment variables or a git-ignored secrets file) and never expose credentials or API keys in logs, decision cards or calls to anything other than the FPL login and Game endpoints.
- Login runs through PingOne OAuth 2.0 / OIDC with PKCE at account.premierleague.com (B9).
- Decision cards, gameweek reviews and rules-change reports are `.txt` files the bot commits and pushes to this repo (`decision-cards/`, `reviews/`, `rules-alerts/`). Alerts go by ntfy push notification. The repo is private (since 2026-10-30) so cards do not republish Game data (Cl.29); keep it private.

Risk accepted by the owner: the published terms (A17: Cl.5, 6, 27, 28(d)) prohibit third-party registration, account sharing and automated access, and Cl.35-37 allow suspension or deletion of the team. To keep the footprint small: keep reads and writes low-frequency, cache aggressively, never hammer endpoints around deadlines, and do not republish Game data (Cl.29).

### C2. Squad, budget and lineup

- The bot must do all money arithmetic in integer tenths (1000 = £100.0m) and use selling prices, not current prices, when computing funds.
- The bot must validate every proposed squad against 2/5/5/3, the 3-per-club limit and the budget, and every XI against the A2 min/max table.
- The bot must read each player's `element_type` from the API every run.
- The bot should order the bench by probability of playing first and expected points second, because bench order is the substitution order.
- The bot should treat a carded unused substitute as "played" when modelling auto-subs and vice-captaincy.

### C3. Captaincy

- The bot must name a vice-captain who is likely to play, because the vice only scores the multiplier if the captain plays no minutes.
- In a double gameweek the bot should prefer captains with two fixtures, since both matches count.

### C4. Transfers and free transfers

- The bot must track FTs (max 5) and price each extra transfer at -4. The bot should read FT count, bank and selling prices from the authenticated team endpoint each run rather than estimating them.
- The bot must not propose more than 20 transfers in a gameweek unless a Wildcard or Free Hit is played.
- The bot should assume no FT is added in a Wildcard or Free Hit week (B3) and verify the count from the team endpoint the following week.
- The bot should count hits as direct losses in H2H and cup matches, not only in total points.

### C5. Prices

- The bot should time recommended transfers relative to the next 00:00 UTC update in `price_change_deadlines` (00:00 UK in winter, 01:00 UK during BST).
- The bot should use `price_change_percent` and `price_change_projections` as the price signal and ignore them while `price_change_calibrating` is true.
- The bot must not assume a £0.3m per-GW cap or Wildcard exclusion when it matters to a decision (both `[SPECULATIVE]`).

### C6. Chips

- The bot must plan set-1 chips to be used by the GW19 deadline, 2027-01-01T18:30Z. Unused set-1 chips are lost.
- The bot must not recommend two Free Hits in consecutive gameweeks. Free Hit 1 in GW19 rules out Free Hit 2 in GW20.
- The bot must recommend only one chip per gameweek.
- The bot must treat Wildcard and Free Hit as irreversible: play them only after a final re-check of the plan, and record them on the decision card. Bench Boost and Triple Captain can be cancelled before the deadline.
- The bot should note that a chip week makes the team ineligible for the weekly prize (Cl.21).

### C7. Deadlines

- The bot must read `events[].deadline_time` (UTC) from the API every run and never compute deadlines locally.
- The bot can treat a deadline as fixed once it is within 24 hours.
- The bot should build its plan at least 24 hours before the deadline, refresh it after the last price update and team news, and submit its final moves with a safe margin before the deadline (then read the team back to confirm they saved).

### C8. Scoring, bonus and finalisation

- The bot should model expected points with the A9 table, including defensive contribution thresholds (DEF 10 CBIT, MID/FWD 12 CBIRT, GK none) and the 60-minute clean-sheet condition.
- The bot should project bonus with the A11 BPS table.
- The bot must treat gameweek points as provisional until 09:00 UK on the day after the final match, and run its post-gameweek evaluation after that.

### C9. Leagues and cups

- In H2H knockout and cup weeks the bot should weight avoiding hits more heavily, since one hit can decide a single-gameweek tie.
- The bot should read `cup_*` fields and the Overall league `has_cup` flag to know when cup rounds start rather than assuming GW15.
- The bot does not need to manage league membership; it is out of scope.

---

## Part D. Weekly rules-change check (spec)

Cl.14 of the terms says the PL can change the Game Rules at its discretion and advises Players to check them regularly. This check does that, using public read-only sources at low frequency, and produces a diff for a human to review.

### D1. Schedule

| Run | When | Purpose |
|---|---|---|
| Weekly | Tuesday 09:00 UK, after the previous gameweek's finalisation. If the latest finished event is not yet marked data-checked, retry once at 12:00 UK. | Main diff |
| Pre-season | 1 July, then again the day after premierleague.com publishes the season's "changes to FPL" article (historically mid to late July), then once the new season's `bootstrap-static` goes live | Rebase for the new season |
| Triggered | Within 24 hours of a news-scan hit (D2, item 4) | Catch mid-season changes, which have arrived with as little as 9 days' notice |

The news scan itself runs once a day. Everything else runs only on the schedule above.

### D2. Inputs (read-only, public)

Fetch budget: about 8 requests per run, no retries faster than 1 hour, no runs inside the hour before a deadline.

1. `https://fantasy.premierleague.com/api/bootstrap-static/` (one request).
2. `https://fantasy.premierleague.com/api/leagues-classic/314/standings/` (one request; reads `has_cup`, `start_event`).
3. Rendered page text, hashed after normalisation: `/help/rules`, `/help/terms`, `/help/faqs`, `/prizes` on fantasy.premierleague.com. These pages are JavaScript-rendered. Capture them with a scripted load (one load per page per run) or a human saving the page text, then hash the saved text.
4. News scan of premierleague.com FPL news (a separate site from the Game). Keywords: "changes", "new", "chip", "free transfer", "rules", "Second Chance", "Cup", "deadline", "price", "bonus", "scoring". Optional secondary feed: Fantasy Football Scout.

Text normalisation before hashing: collapse whitespace, strip cookie banners and navigation, and remove date-time strings, because the rules page renders deadlines in the viewer's local time zone and deadline moves would otherwise trigger false alarms.

### D3. What to diff

Compare live values with the YAML baseline in D6.

| Area | Fields | Change class |
|---|---|---|
| Top level | Set of top-level keys in `bootstrap-static` | New or missing key = RULE |
| Settings | Every key in `game_settings`, and `game_config.rules` (expected to mirror it) | Any value change = RULE, except `cup_*` (below) |
| Cup | `cup_start_event_id`, `cup_stop_event_id`, `cup_qualifying_method`, `cup_type` going from null to a value; Overall league `has_cup` | DATA (expected before GW15); change after being set = RULE |
| Scoring | Every key and value in `game_config.scoring`, normalising scalars to per-position maps | Any change = RULE. Non-zero `mng_*` = RULE (new chip) |
| Chips | Count, `id`, `name`, `number`, `start_event`, `stop_event`, `chip_type` | Any change = RULE |
| Positions | `element_types[].squad_select`, `squad_min_play`, `squad_max_play`, `sub_positions_locked` | Any change = RULE |
| Events | Count of events (38); each `deadline_time` | Count change = RULE; deadline move = DATA |
| Phases | Count of phases; each phase's start and stop event | Any change = RULE |
| Price updates | Time of day and daily cadence of `price_change_deadlines` | Time or cadence change = RULE; dates advancing = ignore |
| Page hashes | `/help/rules`, `/help/terms`, `/help/faqs`, `/prizes` | Hash change = REVIEW (human reads the text diff) |
| News | Keyword hit in a new FPL article | REVIEW |

Ignore: `elements`, `teams`, `total_players`, `element_stats` values, event `finished`/`is_current` flags, and price-change dates (only time of day matters).

### D4. Actions on a change

1. Write a change report for the human: field, old value, new value, change class, and the bot logic affected (table below).
2. For DATA changes (deadline moves, cup fields filled): propose an updated table in this file and bump the minor version (v1.0 to v1.1).
3. For RULE changes: mark the affected bot logic as "rules changed, recompute before next deadline", propose edits to Part A (and Parts B/C if needed), and bump the major version (v1.x to v2.0). The bot should not execute chip or transfer plans that depend on a changed field until the human approves the update.
4. For REVIEW items: attach the text diff or article link; a human decides whether it is RULE, DATA or no change.
5. Every accepted change adds a Changelog entry: date, version, fields changed, source URL, bot logic flagged.
6. If a source cannot be fetched, report "not verified this week" for it. Never change the baseline on a failed read.

| Changed field | Bot logic to flag |
|---|---|
| `squad_*`, `element_types` | Squad validator, lineup validator, optimiser constraints |
| `max_extra_free_transfers`, `transfers_cap`, transfer hit cost | FT tracker, hit model, transfer planner |
| `transfers_sell_on_fee`, `element_sell_at_purchase_price` | Selling-price function, budget calculator |
| `game_config.scoring`, BPS text on /help/rules | Expected-points model, bonus projection |
| `chips` | Chip planner (windows, availability, deadlines) |
| `events[].deadline_time` | Scheduler, decision-card timing, chip-set expiry |
| `phases` | Monthly-league reporting |
| `league_*`, `cup_*`, `has_cup` | H2H and cup weighting in the hit model |
| `price_change_deadlines` timing | Transfer timing |
| /help/terms hash | C1 compliance review before the next run |

### D5. Baseline normalisation notes

On the first run, confirm the exact key spellings and value shapes of `game_config.scoring` and `phases` against the live API, record `phases_count`, and fill the page hashes. Record those as a v1.1 DATA entry, not as rule changes.

### D6. Baseline (machine-readable)

```yaml
baseline_version: v1.0
season: "2026/27"
verified_at: "2026-10-29"
verified_next_gw: 9
bootstrap_static_url: https://fantasy.premierleague.com/api/bootstrap-static/

top_level_keys: [chips, events, game_settings, game_config, phases, teams, total_players, element_stats, element_types, elements]

game_settings:            # game_config.rules expected to mirror these
  squad_squadsize: 15
  squad_squadplay: 11
  squad_team_limit: 3
  squad_total_spend: 1000
  ui_currency_multiplier: 10
  max_extra_free_transfers: 4
  transfers_cap: 20
  transfers_sell_on_fee: 0.5
  element_sell_at_purchase_price: false
  sys_vice_captain_enabled: true
  league_join_private_max: 30
  league_join_public_max: 5
  league_max_size_private_h2h: 16
  league_max_size_public_classic: 20
  league_max_size_public_h2h: 20
  league_max_ko_rounds_private_h2h: 3
  league_ko_first_instead_of_random: false
  league_points_h2h_win: 3
  league_points_h2h_draw: 1
  league_points_h2h_lose: 0
  league_h2h_tiebreak_stats: ["+goals_scored", "-goals_conceded"]
  cup_start_event_id: null
  cup_stop_event_id: null
  cup_qualifying_method: null
  cup_type: null
  stats_form_days: 30
  underdog_differential: 5
  timezone: "UTC"         # game_config.settings.timezone

scoring:                  # game_config.scoring, normalised to {GKP, DEF, MID, FWD}. Confirmed 2026-10-30: the API gives a plain number when all positions score the same, and a {DEF, FWD, GKP, MID} map otherwise
  short_play:             {GKP: 1,  DEF: 1,  MID: 1,  FWD: 1}
  long_play:              {GKP: 2,  DEF: 2,  MID: 2,  FWD: 2}
  goals_scored:           {GKP: 10, DEF: 6,  MID: 5,  FWD: 4}
  assists:                {GKP: 3,  DEF: 3,  MID: 3,  FWD: 3}
  clean_sheets:           {GKP: 4,  DEF: 4,  MID: 1,  FWD: 0}
  goals_conceded:         {GKP: -1, DEF: -1, MID: 0,  FWD: 0}
  saves:                  {GKP: 1,  DEF: 0,  MID: 0,  FWD: 0}
  penalties_saved:        {GKP: 5,  DEF: 0,  MID: 0,  FWD: 0}
  penalties_missed:       {GKP: -2, DEF: -2, MID: -2, FWD: -2}
  yellow_cards:           {GKP: -1, DEF: -1, MID: -1, FWD: -1}
  red_cards:              {GKP: -3, DEF: -3, MID: -3, FWD: -3}
  own_goals:              {GKP: -2, DEF: -2, MID: -2, FWD: -2}
  defensive_contribution: {GKP: 0,  DEF: 2,  MID: 2,  FWD: 2}
  bonus:                  {GKP: 1,  DEF: 1,  MID: 1,  FWD: 1}
  special_multiplier: 1
  must_be_zero: [bps, influence, creativity, threat, ict_index, tackles, clearances_blocks_interceptions, recoveries, starts, "expected_*", "mng_*"]

rules_page_thresholds:    # not in the API; check against /help/rules text
  long_play_minutes: 60
  saves_per_point: 3
  goals_conceded_per_deduction: 2
  defcon_def_cbit: 10
  defcon_mid_fwd_cbirt: 12
  hit_cost: 4
  max_stored_ft: 5
  deadline_minutes_before_kickoff: 90
  deadline_freeze_hours: 24
  points_final: "09:00 UK on the day after the final match of the GW"

chips:
  - {id: 1, name: wildcard, start_event: 2,  stop_event: 19, chip_type: transfer}
  - {id: 2, name: wildcard, start_event: 20, stop_event: 38, chip_type: transfer}
  - {id: 3, name: freehit,  start_event: 2,  stop_event: 19, chip_type: transfer}
  - {id: 6, name: freehit,  start_event: 20, stop_event: 38, chip_type: transfer}
  - {id: 4, name: bboost,   start_event: 1,  stop_event: 19, chip_type: team}
  - {id: 7, name: bboost,   start_event: 20, stop_event: 38, chip_type: team}
  - {id: 5, name: 3xc,      start_event: 1,  stop_event: 19, chip_type: team}
  - {id: 8, name: 3xc,      start_event: 20, stop_event: 38, chip_type: team}
chip_count: 8

element_types:
  - {id: 1, short: GKP, squad_select: 2, squad_min_play: 1, squad_max_play: 1, sub_positions_locked: [12]}
  - {id: 2, short: DEF, squad_select: 5, squad_min_play: 3, squad_max_play: 5, sub_positions_locked: []}
  - {id: 3, short: MID, squad_select: 5, squad_min_play: 2, squad_max_play: 5, sub_positions_locked: []}
  - {id: 4, short: FWD, squad_select: 3, squad_min_play: 1, squad_max_play: 3, sub_positions_locked: []}

events:
  count: 38
  deadlines_utc:
    1: "2026-08-21T17:30:00Z"
    2: "2026-08-28T17:30:00Z"
    3: "2026-09-04T17:30:00Z"
    4: "2026-09-12T12:30:00Z"
    5: "2026-09-18T17:30:00Z"
    6: "2026-10-10T10:00:00Z"
    7: "2026-10-17T10:00:00Z"
    8: "2026-10-23T17:30:00Z"
    9: "2026-10-31T11:00:00Z"
    10: "2026-11-06T18:30:00Z"
    11: "2026-11-21T11:00:00Z"
    12: "2026-11-27T18:30:00Z"
    13: "2026-12-01T18:30:00Z"
    14: "2026-12-05T11:00:00Z"
    15: "2026-12-12T13:30:00Z"
    16: "2026-12-19T11:00:00Z"
    17: "2026-12-26T11:00:00Z"
    18: "2026-12-29T18:00:00Z"
    19: "2027-01-01T18:30:00Z"
    20: "2027-01-05T18:00:00Z"
    21: "2027-01-16T13:30:00Z"
    22: "2027-01-23T13:30:00Z"
    23: "2027-01-30T13:30:00Z"
    24: "2027-02-06T13:30:00Z"
    25: "2027-02-10T18:30:00Z"
    26: "2027-02-20T13:30:00Z"
    27: "2027-02-27T13:30:00Z"
    28: "2027-03-03T18:30:00Z"
    29: "2027-03-13T13:30:00Z"
    30: "2027-03-20T13:30:00Z"
    31: "2027-04-10T12:30:00Z"
    32: "2027-04-17T12:30:00Z"
    33: "2027-04-24T12:30:00Z"
    34: "2027-05-01T12:30:00Z"
    35: "2027-05-08T12:30:00Z"
    36: "2027-05-15T12:30:00Z"
    37: "2027-05-23T12:30:00Z"
    38: "2027-05-30T13:30:00Z"

phases_monthly:           # from /help/rules
  August: [1, 2]
  September: [3, 5]
  October: [6, 9]
  November: [10, 12]
  December: [13, 18]
  January: [19, 23]
  February: [24, 27]
  March: [28, 30]
  April: [31, 33]
  May: [34, 38]
phases_count: 11          # confirmed 2026-10-30: "Overall" (1-38) plus the 10 monthly phases

price_changes:
  time_of_day_utc: "00:00:00"
  cadence: daily

overall_league:
  id: 314
  start_event: 1
  has_cup: true
  overall_cup_start_gw_rules_page: 15

page_hashes_sha256:       # fill on first run from normalised text
  help_rules: null
  help_terms: null
  help_faqs: null
  prizes: null

news_keywords: [changes, new, chip, "free transfer", rules, "Second Chance", Cup, deadline, price, bonus, scoring]
```

---

## Part E. Open questions and unconfirmed items

1. **Second Chance League start.** The rules page says it "starts in Gameweek 21". The 1 Oct 2026 PL article says scoring started from zero in GW6, with no cup [pl-scl]. Unknown whether both exist or one source is stale.
2. **Overall Cup start.** Rules page says GW15; API `cup_*` fields were still null on 2026-10-29.
3. **Price update clock.** The API lists 00:00 UTC; the PL article says "00:00 UK time" [pl-changes]. They agree in winter. Behaviour during BST (00:00 UTC = 01:00 UK, or 23:00 UTC) cannot be checked from current data. Read `price_change_deadlines`.
4. **£0.3m per-gameweek price cap.** Sources disagree (B1).
5. **Wildcard and Free Hit transfers in the price algorithm.** Unconfirmed (B1).
6. **FT gain in a chip week.** The official example implies no +1; verify from the team endpoint after the next chip week.
7. **Mid-season entrant transfers.** Unlimited until the first deadline is implied, not stated.
8. **Triple Captain passing to the vice-captain.** Community-sourced, not on the rules page.
9. **Defensive contribution in double gameweeks.** Per-match assessment is inferred.
10. **League Cup start-by-size table.** From a 2022 article; not confirmed for 2026/27.
11. **Abandoned matches.** No 2026/27 source.
12. **Phase-start hit wording.** The rules page example (transfers made in GW6 "preparing for Gameweek 7" not deducted from the October score) conflicts with the phase table (October starts GW6). Likely a stale example from a season where October started at GW7. The bot does not rely on it.
13. **Terms clauses 22-23** still cite 2026 dates. Likely a carry-over; recheck on the next terms hash change.
14. **Status code legend** (`a`, `d`, `i`, `s`, `u`, `n`) is community knowledge, not official.
15. **Price floor and post-move protection.** No 2026/27 source.
16. **API scoring key shapes** and `phases` count: confirm on first run (D5).
17. **/help/faqs and /prizes** were not read for this version; their baseline hashes are unset.

---

## Changelog

| Version | Date | Change |
|---|---|---|
| v2.4 | 2026-10-30 | DATA (D5 first-run check) against the live snapshot in `samples/2026-10-30/`: every `game_settings` value, chip window, position limit, deadline and scoring value matches the baseline; all must-be-zero scoring keys are 0. Recorded `phases_count: 11` (includes Overall) and the scoring value shapes. `game_config.rules` mirrors `game_settings` except `timezone`. Page hashes still unset. |
| v2.3 | 2026-10-30 | Repo made private; C1 note updated. |
| v2.2 | 2026-10-30 | Owner created the FPL account; the bot logs in only and never signs up. Password entry via the setup command into the OS keychain. |
| v2.1 | 2026-10-30 | C1 updated with the owner's setup decisions: account created by the bot at go-live for soohzabimaru864@gmail.com, runs on the owner's Windows machine with macOS backup, password in the OS keychain, no human veto, decision cards as .txt files in the repo, ntfy alerts. Points to `docs/system-flow.md`. |
| v2.0 | 2026-10-29 | Operating mode changed by the account owner from human-confirmed decision support to autonomous: the bot logs in and makes moves itself. Rewrote C1, C4, C6, C7, B9, D2 and E6 to match. A17 terms excerpts left verbatim, with a note that the owner accepts the risk. |
| v1.0 | 2026-10-29 | First version. Rules baseline for 2026/27 verified at GW9 against the rendered rules page, the rendered terms and live `bootstrap-static`. Corrected the first-half chip deadline to Fri 1 Jan 2027 18:30 UTC (earlier secondary sources said Sat 2 Jan 13:30). Terms excerpts now verbatim-verified. Full official BPS table added. Second Chance League start left flagged as conflicting. Price updates recorded as 00:00 UTC per the API. |

---

## Sources

Official (authoritative)

- [rules]: https://fantasy.premierleague.com/help/rules (rendered 2026-10-29)
- [terms]: https://fantasy.premierleague.com/en/help/terms (rendered 2026-10-29)
- [api]: https://fantasy.premierleague.com/api/bootstrap-static/
- [api-314]: https://fantasy.premierleague.com/api/leagues-classic/314/standings/
- [api-fix]: https://fantasy.premierleague.com/api/fixtures/?event=9

Official premierleague.com articles

- [pl-changes]: https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627
- [pl-chips]: https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627
- [pl-team]: https://www.premierleague.com/en/news/2174899
- [pl-transfers]: https://premierleague.com/news/2174907
- [pl-leagues]: https://www.premierleague.com/en/news/2174934
- [pl-scl]: https://www.premierleague.com/en/news/4726899/second-chance-league-offers-chance-to-win-premier-league-tickets
- [pl-defcon]: https://www.premierleague.com/en/news/4361991/whats-happening-with-defensive-contribution-points-in-202627-fantasy
- [pl-assists]: https://www.premierleague.com/en/news/4499344
- [pl-assists25]: https://www.premierleague.com/en/news/4362187
- [pl-bps25]: https://www.premierleague.com/en/news/4362127/whats-new-in-202526-fantasy-changes-to-bonus-points-system
- [pl-ties]: https://www.premierleague.com/news/1210781
- [pl-leaguecup]: https://premierleague.com/news/2368337
- [pl-cup26]: https://www.premierleague.com/en/news/4486696
- [pl-prices]: https://www.premierleague.com/en/news/2858775
- [pl-2526]: https://www.premierleague.com/en/news/4362211
- [pl-2425]: https://www.premierleague.com/en/news/4058895
- [pl-am]: https://www.premierleague.com/news/4193484
- [pl-afcon]: https://www.premierleague.com/en/news/4461660/fpl-managers-to-have-five-free-transfers-on-saturday-all-you-need-to-know
- [pl-sky]: https://www.premierleague.com/en/terms-and-conditions/2026-27/sky-sports-broadcaster-league

Community and secondary

- [ffs-prices]: https://www.fantasyfootballscout.co.uk/2026/07/20/how-do-fpl-price-changes-work
- [ffs-changes]: https://www.fantasyfootballscout.co.uk/2026/07/20/fpl-2026-27-5-rule-changes-new-features-announced
- [ffs-bps]: https://www.fantasyfootballscout.co.uk/2026/07/21/how-fpls-new-bonus-points-system-tweaks-would-have-affected-2025-26
- [ffs-tc]: https://www.fantasyfootballscout.co.uk/2026/07/20/what-is-an-fpl-triple-captain-chip
- [ffs-covid]: https://www.fantasyfootballscout.co.uk/2020/06/08/fpl-relaunches-with-unlimited-transfers-for-all-managers
- [onefpl-prices]: https://onefpl.com/fpl-price-changes
- [onefpl-wc]: https://onefpl.com/blog/do-wildcard-transfers-affect-fpl-price-changes
- [onefpl-chips]: https://onefpl.com/blog/fpl-chips-free-transfers-rules
- [onefpl-prizes]: https://onefpl.com/blog/fpl-weekly-monthly-prizes-2026-27
- [onefpl-cup]: https://onefpl.com/blog/fpl-cup-explained-byes-tiebreakers
- [oracle]: https://fploracle.team/blog/fpl-price-changes-explained
- [draft]: https://www.draftfantasy.com/blog/fpl-price-change-predictor
- [ffhub-flags]: https://www.fantasyfootballhub.co.uk/articles/unavailable-players-in-fantasy-premier-league
- [ffhub-leagues]: https://www.fantasyfootballhub.co.uk/articles/mini-leagues-in-fantasy-premier-league
- [fplbuddy]: https://github.com/jishnuap/fpl-buddy
- [plmcp]: https://github.com/rishijatia/fantasy-pl-mcp/
- [pft]: https://www.premierfantasytools.com/legit-fpl-analytics-tools-vs-game-cheats-why-only-one-gets-you-banned/

[rules]: https://fantasy.premierleague.com/help/rules
[terms]: https://fantasy.premierleague.com/en/help/terms
[api]: https://fantasy.premierleague.com/api/bootstrap-static/
[api-314]: https://fantasy.premierleague.com/api/leagues-classic/314/standings/
[api-fix]: https://fantasy.premierleague.com/api/fixtures/?event=9
[pl-changes]: https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627
[pl-chips]: https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627
[pl-team]: https://www.premierleague.com/en/news/2174899
[pl-transfers]: https://premierleague.com/news/2174907
[pl-leagues]: https://www.premierleague.com/en/news/2174934
[pl-scl]: https://www.premierleague.com/en/news/4726899/second-chance-league-offers-chance-to-win-premier-league-tickets
[pl-defcon]: https://www.premierleague.com/en/news/4361991/whats-happening-with-defensive-contribution-points-in-202627-fantasy
[pl-assists]: https://www.premierleague.com/en/news/4499344
[pl-assists25]: https://www.premierleague.com/en/news/4362187
[pl-bps25]: https://www.premierleague.com/en/news/4362127/whats-new-in-202526-fantasy-changes-to-bonus-points-system
[pl-ties]: https://www.premierleague.com/news/1210781
[pl-leaguecup]: https://premierleague.com/news/2368337
[pl-cup26]: https://www.premierleague.com/en/news/4486696
[pl-prices]: https://www.premierleague.com/en/news/2858775
[pl-2526]: https://www.premierleague.com/en/news/4362211
[pl-2425]: https://www.premierleague.com/en/news/4058895
[pl-am]: https://www.premierleague.com/news/4193484
[pl-afcon]: https://www.premierleague.com/en/news/4461660/fpl-managers-to-have-five-free-transfers-on-saturday-all-you-need-to-know
[pl-sky]: https://www.premierleague.com/en/terms-and-conditions/2026-27/sky-sports-broadcaster-league
[ffs-prices]: https://www.fantasyfootballscout.co.uk/2026/07/20/how-do-fpl-price-changes-work
[ffs-changes]: https://www.fantasyfootballscout.co.uk/2026/07/20/fpl-2026-27-5-rule-changes-new-features-announced
[ffs-bps]: https://www.fantasyfootballscout.co.uk/2026/07/21/how-fpls-new-bonus-points-system-tweaks-would-have-affected-2025-26
[ffs-tc]: https://www.fantasyfootballscout.co.uk/2026/07/20/what-is-an-fpl-triple-captain-chip
[ffs-covid]: https://www.fantasyfootballscout.co.uk/2020/06/08/fpl-relaunches-with-unlimited-transfers-for-all-managers
[onefpl-prices]: https://onefpl.com/fpl-price-changes
[onefpl-wc]: https://onefpl.com/blog/do-wildcard-transfers-affect-fpl-price-changes
[onefpl-chips]: https://onefpl.com/blog/fpl-chips-free-transfers-rules
[onefpl-prizes]: https://onefpl.com/blog/fpl-weekly-monthly-prizes-2026-27
[onefpl-cup]: https://onefpl.com/blog/fpl-cup-explained-byes-tiebreakers
[oracle]: https://fploracle.team/blog/fpl-price-changes-explained
[draft]: https://www.draftfantasy.com/blog/fpl-price-change-predictor
[ffhub-flags]: https://www.fantasyfootballhub.co.uk/articles/unavailable-players-in-fantasy-premier-league
[ffhub-leagues]: https://www.fantasyfootballhub.co.uk/articles/mini-leagues-in-fantasy-premier-league
[fplbuddy]: https://github.com/jishnuap/fpl-buddy
[plmcp]: https://github.com/rishijatia/fantasy-pl-mcp/
[pft]: https://www.premierfantasytools.com/legit-fpl-analytics-tools-vs-game-cheats-why-only-one-gets-you-banned/
