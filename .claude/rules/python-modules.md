# Python Module Rules

Applies to all `app/*.py` and `run.py`.

## Size limits (hard)
- Modules: < 500 lines of code (excluding blank lines and comments).
- Functions: < 50 lines.
- If you're about to push a file past these limits, split it instead of appending.

## Layering
- `app/main.py` — Flask app, routes, bootstrap (`init_app()`), background-thread setup. Keep business logic out.
- `app/db.py` — All SQLite access. No HTTP, no parsing, no business calculations.
- `app/parser.py` — JSONL parsing. No DB writes (returns records to `main.py` or `watcher.py` for insertion).
- `app/watcher.py` — watchdog file events. Calls into `parser.py` and back to `main.py` via callback.
- `app/usage_api.py` — Calls to Anthropic's OAuth metering endpoint. Sole owner of `~/.claude/.credentials.json` reads.
- `app/forecaster.py` — Pure functions for burn-rate forecasting. No I/O.
- `app/config.py` — Env-var loading. Module-level constants only; no functions with side effects.

Do not let route handlers in `main.py` do SQL, file I/O, or HTTP directly — delegate.

## Background threads
- One named function per daemon thread. No inline lambdas in `threading.Thread(target=...)`.
- Threads loop with `while True: <work>; time.sleep(N)`. Wrap `<work>` in `try/except` so a single error doesn't kill the thread silently.
- All thread-start calls live in `init_app()` in `app/main.py`. Don't spawn threads from request handlers.

## Time handling
- All timestamps stored / passed between modules are **UTC, ISO 8601** (with `Z` or `+00:00`).
- Use `datetime.now(timezone.utc)` — never bare `datetime.now()`.
- TZ conversion for display happens in JavaScript, not Python.

## Sensitive data
- Never log `accessToken`, `refreshToken`, or full credential JSON.
- If you must reference a token in an error path, mask: `token[:8] + "..." + token[-4:]`.
- Don't persist credentials in SQLite.

## SQLite
- Schema lives in `app/db.py:init_db()` using `CREATE TABLE IF NOT EXISTS`. Additive changes (new tables) are safe.
- Column changes to `usage_records` need a hand-written migration script. There is no Alembic / no migration framework.
- Keep WAL mode enabled (recent commit `b90107a` turned it on; don't revert).
- Always use parameterized queries. Never f-string SQL.

## Imports
- Standard lib → third-party → first-party (`from app import ...`). One blank line between groups.
- If a module has > 20 imports, it's a code smell — the module is probably doing too much.
