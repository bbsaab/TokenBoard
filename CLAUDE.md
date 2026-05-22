# Project: TokenBoard

## Overview
TokenBoard is a personal dashboard for tracking Claude (Anthropic) token consumption across 5-hour rolling windows and weekly limits. It reads JSONL session files from the user's local `~/.claude` directory, persists usage records to SQLite, and surfaces real-time burn-down + forecasting in a browser dashboard. Single-user, single-process, runs locally or in Docker.

## Tech Stack

**Backend:** Python 3.11, Flask (dev server today — see Phase 0 in proposal), SQLite (WAL mode), watchdog for file events, requests for OAuth metering calls.
**Frontend:** Server-rendered Jinja templates + vanilla JS in `static/dashboard.js`. No framework, no build step.
**Infrastructure:** Docker (single container, `python -m app.main`), or local via `python run.py`. SQLite file in `data/`. The user's `~/.claude` is mounted **read-only** into the container.

## Key Commands

```bash
# Local dev (no Docker)
python run.py                       # http://localhost:8080

# Docker
docker compose up -d
docker compose logs -f
docker compose down                 # Note: SIGTERM ignored today; takes 10s

# DB sanity check
sqlite3 data/usage.db "SELECT COUNT(*) FROM usage_records;"
```

## Branching Convention
- Single branch `main` for solo work. Use feature branches when a change is large or risky.
- PRs are optional — direct commits to `main` are fine for routine fixes.

## Commit Message Format
- `feat(area): add new capability`
- `fix(area): correct specific issue`
- `chore(area): non-functional change`
- Area is roughly the file/module: `parser`, `watcher`, `usage_api`, `db`, `docker`, `ui`, `docs`.

## Schema Reality Check
Before implementing any feature, verify:
- Inventory existing models in [app/db.py](app/db.py) — there is one table today: `usage_records`.
- Confirm field names: `id, timestamp, session_id, model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens` with `UNIQUE(timestamp, session_id)`.
- No migration tooling exists — schema is created via `CREATE TABLE IF NOT EXISTS` in [app/db.py:init_db()](app/db.py). Additive changes (new tables) are safe; column changes to `usage_records` require a manual migration script.
- Confirm API routes by reading [app/main.py](app/main.py) — Flask routes are colocated, not blueprinted.
- The OAuth metering response shape from `/api/oauth/usage` is read in [app/usage_api.py](app/usage_api.py); document any changes here when the shape evolves (notably the June 15, 2026 billing split may change it).

## File Size Limits (enforce strictly)
- Python modules: max 500 lines of code (excluding comments/blanks).
- Functions: max 50 lines.
- Templates (Jinja): max 300 lines — extract partials beyond that.
- `static/dashboard.js`: max 500 lines — split into ES modules if it grows further.
- If a file you're editing already exceeds the limit, refactor as part of the change rather than appending.

## Before Adding Code to an Existing File
- Grep for similar functionality first. The codebase is small; duplication is rarely warranted.
- If adding > 30 lines to a file, evaluate whether a new module is warranted.
- `app/main.py` is the Flask app + bootstrap. Resist adding business logic to it — push to `app/db.py`, `app/usage_api.py`, `app/parser.py`, `app/forecaster.py`, or a new module.
- If copy-pasting > 5 lines, extract a shared utility.

## Decomposition Rules
- Background daemon threads live in `app/main.py:init_app()`. Each thread should be a single named function — no inline lambdas.
- HTTP handling (Flask routes) stays in `app/main.py`. Data access stays in `app/db.py`. Network calls to Anthropic stay in `app/usage_api.py`. Don't cross the layers.
- The OAuth metering call has retry / rate-limit logic — reuse it; don't add a parallel HTTP client.

## Domain-Specific Rules

### Critical safety rules (never violate without explicit sign-off)

1. **`~/.claude` is mounted read-only** in the Docker container ([docker-compose.yml](docker-compose.yml)). Any feature that wants to write back (e.g., shelling out to `claude` CLI which rotates the OAuth refresh token) must be flagged in the proposal and approved before the mount is changed. Default is and stays `:ro`.
2. **OAuth credentials are user-sensitive.** TokenBoard reads `~/.claude/.credentials.json` (the `accessToken` field). Never log it, never persist it to the database, never transmit it anywhere except the official Anthropic metering endpoint. Mask in any debug output (first 8 + last 4 chars max).
3. **Single-process, single-user assumption.** TokenBoard runs one process, one user, one instance. In-memory state (`_import_status` dict, daemon threads) assumes this. Any proposal that scales horizontally (multi-worker gunicorn, k8s replicas, multi-user mode) must call this out explicitly and design around it — don't sneak it in.

### Time-zone handling

- **Storage is UTC.** All `timestamp` columns in SQLite, all JSONL parsing, all OAuth response parsing must produce/consume UTC ISO 8601 (with `Z` or `+00:00` suffix).
- **Display is user-local.** Conversion happens in the frontend (JavaScript `Date` / `Intl.DateTimeFormat`), not in the backend. The backend returns UTC ISO strings; the JS formats them.
- **Never mix.** Recent commit `cccb1fa fix: rate limit API polling and correct timezone display` is the precedent. If you're tempted to do TZ math in Python for display, stop — push the UTC string to JS and format there.

### Claude Code session window semantics (this is the product's whole point)

- 5-hour windows are activity-triggered (first request opens the window) and do **not** auto-roll. See [docs/proposals/PROPOSAL-Proactive-Session-Refresh.md](docs/proposals/PROPOSAL-Proactive-Session-Refresh.md) for the authoritative writeup.
- The authoritative `resets_at` for the current window comes from Anthropic's OAuth metering endpoint via [app/usage_api.py:fetch_oauth_usage()](app/usage_api.py) — do not infer windows from JSONL timestamps when the OAuth call is available.
- Weekly quotas are *separate* from 5-hour windows. Don't conflate them in display or math.
- **June 15, 2026 watch item:** Anthropic is splitting subscription billing into an interactive pool and an Agent SDK pool. Any feature that does programmatic Claude calls must read the proposal's "Mechanism comparison" table before designing.

## Feedback Domains
For future `/make-feedback` use: `watcher`, `parser`, `usage-api`, `db`, `forecaster`, `dashboard-ui`, `docker`, `docs`.

## Domain-Specific Testing Checklist

Before merging any non-trivial change:

```
[ ] Manual: dashboard loads at http://localhost:8080 with no console errors
[ ] Manual: /api/usage returns valid JSON within 1 second
[ ] Manual: 5-hour window math matches Claude Code's /usage output
[ ] Manual: docker compose up clean start, no warnings in logs
[ ] Manual: docker compose down completes within ~2 seconds (regression check for Phase 0 SIGTERM fix)
[ ] If parser changed: re-import against a copy of ~/.claude and diff record counts
[ ] If schema changed: confirm `CREATE TABLE IF NOT EXISTS` still works on a fresh data/ directory AND on an existing one
[ ] If OAuth call changed: confirm graceful fallback when ~/.claude/.credentials.json is missing or token is expired
[ ] If display TZ-touched: spot-check that timestamps render in local time, not UTC
```

There are no automated tests today. Adding pytest for new modules is encouraged; not strictly required for backfilling existing code.

## Compact Instructions
When compacting context, always preserve:
- Current implementation phase number and status (Phase 0 / 1 / 1.5 / 2 of the Proactive Session Refresh proposal, if active)
- Whether the SIGTERM/gunicorn migration (Phase 0) has shipped
- The June 15, 2026 billing-split watch item — this is load-bearing for any "trigger Claude programmatically" discussion
- Active architecture document reference
