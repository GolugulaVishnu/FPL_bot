# FPL bot

An autonomous Fantasy Premier League bot that runs on your own machines. Design: `docs/system-flow.md`. Rules: `docs/fpl-rules-context.md`.

**Status:** setup, data capture, the 15-minute scheduled run, the data store, the expected-points model (with backtest), the squad optimiser and decision cards are built. The bot plays from GW9: it picks the team and writes the decision card, and GW9 is entered on the FPL site by hand. Automated login and submission come next (from GW10), so the scheduler is not switched on yet.

## First-time setup on Windows

Run these in **PowerShell**, one at a time.

1. Tell git who is committing (once per machine; use your own email or any placeholder):

   ```powershell
   git config --global user.name "FPL bot"
   git config --global user.email "you@example.com"
   ```

2. Clone the repo and go into it. Sign in to GitHub in the browser window if it asks:

   ```powershell
   git clone https://github.com/GolugulaVishnu/FPL_bot.git
   cd FPL_bot
   ```

3. Allow PowerShell to run the environment's activation script. This is needed once per Windows user; answer `Y` if asked:

   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

4. Create a private Python environment for the bot and install it. Check the prompt ends in `\FPL_bot>` first; these commands must run inside the repo folder:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -e .
   ```

   When it's active, the prompt starts with `(.venv)`. Run the activate line again whenever you open a new PowerShell window to use `fplbot`.

5. Run setup. It asks for the FPL password and the GitHub token with hidden typing and saves both to Windows Credential Manager. Nothing goes into the repo.

   ```powershell
   fplbot setup
   ```

   At the end it prints your ntfy topic names. In the ntfy phone app, tap **+** and subscribe to the **alerts** and **control** topics. You should get a test notification straight away.

6. Save a snapshot of live FPL data to the repo, so the model is built against real data:

   ```powershell
   fplbot capture --push
   ```

7. Check everything:

   ```powershell
   fplbot status
   ```

## Data and model

Run these after setup (inside `FPL_bot`, with `(.venv)` showing):

```powershell
fplbot data all
fplbot project --top 30
fplbot backtest --season 2025-26
```

- `fplbot data all` downloads the 2024-25 and 2025-26 seasons from the public FPL archive once, then loads this season from the FPL API (a few requests; finished gameweeks are cached for good).
- `fplbot project` prints expected points for the next 6 gameweeks. Add `--position MID` to filter, or `--horizon 3` for fewer weeks.
- `fplbot backtest` replays a past season week by week and compares the model with recent form and with FPL's own projection. Add `--save` to write the report to `reports/`.

## Picking this gameweek's team

```powershell
fplbot pick --push
```

Builds the best squad, starting XI, bench order, captain, vice-captain and chip decision for the next gameweek from live FPL data, checks it against the squad rules, and writes the decision card to `decision-cards/<season>/gwNN-final.txt` (`--push` commits and pushes it). Run it close to the deadline so it sees the latest team news and overnight price changes. Use `--kind draft` for an earlier look.

## Recording how the FPL site saves a team

Needed once, so the bot can learn to submit by itself. Install the browser recorder (once):

```powershell
pip install -e ".[record]"
python -m playwright install chromium
```

Then, when you enter a team by hand:

```powershell
fplbot record --push
```

A browser window opens on the FPL site. Log in, enter and save the team from the decision card, wait a few seconds, then close the window. The bot saves a cleaned record of the site's requests to `recordings/`: request addresses and data layout, player ids, captain flags and chip names. Passwords, cookies, login tokens and your email are removed, and the file is checked again for leaks before it is written. The browser profile is temporary, so nothing from the login is kept.

## Signing in (check only)

```powershell
fplbot login
```

Opens the FPL site in a browser window, signs in with the saved password, and prints the team: bank, free transfers, chips and players with selling prices. It changes nothing. If FPL shows a CAPTCHA, solve it in the window (the bot waits up to 5 minutes). The sign-in is remembered in a browser profile in the local data folder, so later runs rarely need the password.

If the automatic sign-in fails, run `fplbot login --manual`: you sign in yourself in the window and the bot just watches, recording the sign-in page's layout (field types and button labels, never what you type) so the automatic sign-in can be fixed.

`fplbot login --probe --push` also finds where the site keeps the token it needs to save a team. Follow the prompt (change the vice-captain and save, then change it back and save). Only names are recorded, never values.

## Everyday commands

| Command | What it does |
|---|---|
| `fplbot status` | Shows what is set up and the last runs |
| `fplbot pause` / `fplbot resume` | Pauses or resumes the bot on this machine. To pause both machines from your phone, send `pause` or `resume` to the control topic in ntfy |
| `fplbot setup --reset` | Re-enter the FPL password or GitHub token (for example after changing them) |
| `fplbot schedule install` / `remove` | Switch the 15-minute run on or off (not yet: this comes with automated submission) |

## Where things live

- **Repo:** code, docs, data snapshots (`samples/`) and, later, decision cards.
- **Credential Manager / Keychain:** FPL password and GitHub token.
- **Data folder** (`%LOCALAPPDATA%\fplbot` on Windows, `~/Library/Application Support/fplbot` on Mac): local settings, ntfy topic names, database, cache and logs. Never committed.

## For development

```bash
pip install -e ".[dev]"
python -m pytest
```
