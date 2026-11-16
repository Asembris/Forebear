# Forebear: rules for every task

## Git workflow (permanent)
- Start every task from the latest `origin/main` on a NEW branch named `feat/...`, `fix/...` or `chore/...`:
  `git fetch origin; git switch -c <type>/<name> origin/main`
- Never develop or commit directly on `main`.
- Make small, logically atomic commits as work progresses; each commit is one coherent change.
- Commit messages are exactly ONE line: a descriptive Conventional Commit subject, e.g. `chore: configure project safeguards`.
  No body, bullets, AI attribution, `Co-Authored-By`, Claude-Session URL or any other trailer.
- Before committing: run the relevant checks (below), review `git diff --staged`, and confirm no secrets are staged.
- Push ONLY the working branch: `git push -u origin <branch>`.
- NEVER create, approve, merge or close a pull request. The maintainer opens, reviews and merges every PR.
- Never force-push, rewrite published history, discard unrelated changes, or commit credentials (`.env`, keys, tokens).

## Enforcement
- `.githooks/commit-msg` rejects anything but a one-line Conventional Commit. Activate it once per clone:
  `git config core.hooksPath .githooks`
- `.claude/settings.json` disables commit/PR attribution and session-link trailers.

## Checks (Windows, PowerShell, from the repo root)
- Tests: `.venv\Scripts\python.exe -m pytest`
- Frontend build: `cd web; npm ci; npm run build` (commit the updated `web/dist` when the UI changes)
- Offline graph rebuild: `.venv\Scripts\python.exe scripts\build_graph.py`

## Project facts
- FastAPI backend in `forebear/`, React + Vite UI in `web/`, Relate store `data/forebear.rl` rebuilt offline from `data/raw/`.
- `data/raw/` is the committed, reproducible FDA cache; only `scripts/fetch_data.py` writes it. `data/live/` is gitignored.
- The API is the single writer to the `.rl` file; stop the app before opening it with the Relate CLI.
