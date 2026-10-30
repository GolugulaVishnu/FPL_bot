# FPL bot

An autonomous Fantasy Premier League bot that runs on your own machines. Design: `docs/system-flow.md`. Rules: `docs/fpl-rules-context.md`.

**Status:** setup, data capture and the 15-minute scheduled run are built. Planning, submitting and reviews are still to come, so the scheduler is not switched on yet.

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

3. Create a private Python environment for the bot and install it:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -e .
   ```

   If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, answer `Y`, then try again.

4. Run setup. It asks for the FPL password and the GitHub token with hidden typing and saves both to Windows Credential Manager. Nothing goes into the repo.

   ```powershell
   fplbot setup
   ```

   At the end it prints your ntfy topic names. In the ntfy phone app, tap **+** and subscribe to the **alerts** and **control** topics. You should get a test notification straight away.

5. Save a snapshot of live FPL data to the repo, so the model is built against real data:

   ```powershell
   fplbot capture --push
   ```

6. Check everything:

   ```powershell
   fplbot status
   ```

## Everyday commands

| Command | What it does |
|---|---|
| `fplbot status` | Shows what is set up and the last runs |
| `fplbot pause` / `fplbot resume` | Pauses or resumes the bot on this machine. To pause both machines from your phone, send `pause` or `resume` to the control topic in ntfy |
| `fplbot setup --reset` | Re-enter the FPL password or GitHub token (for example after changing them) |
| `fplbot schedule install` / `remove` | Switch the 15-minute run on or off (not yet: this comes with the dry run) |

## Where things live

- **Repo:** code, docs, data snapshots (`samples/`) and, later, decision cards.
- **Credential Manager / Keychain:** FPL password and GitHub token.
- **Data folder** (`%LOCALAPPDATA%\fplbot` on Windows, `~/Library/Application Support/fplbot` on Mac): local settings, ntfy topic names, database, cache and logs. Never committed.

## For development

```bash
pip install -e ".[dev]"
python -m pytest
```
