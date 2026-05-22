# Environment Variables

**Last Updated:** 2026-05-18
**Purpose:** Central registry of all environment variables read by TokenBoard. Every `os.environ.get(...)` in the codebase should be reflected here.

> Maintain manually. When [/make-architect](../README.md) introduces a new env var, it adds a row here as part of the architecture-doc workflow.

---

## Conventions

- **Service:** all current vars apply to the single TokenBoard backend container.
- **Default:** the value used when the env var is unset. `None` means "feature is off / no default."
- **Type:** how the value is parsed in [app/config.py](../../app/config.py). Booleans are parsed as `value.lower() in ("true", "1", "yes")`.
- **Set in:** files that pass the variable through (`docker-compose.yml`, shell env, `.env`).

---

## Core / Discovery

| Variable | Default | Type | Service | Purpose | Set in |
|---|---|---|---|---|---|
| `CLAUDE_DATA_PATH` | auto-detected (`~/.claude`, `%APPDATA%/claude`, etc.) | string (path) | backend | Override path to the user's Claude data directory. Used when the discovery in [app/config.py:discover_claude_data_path()](../../app/config.py#L8) can't find it. | docker-compose.yml (set to `/claude-data` inside the container) |
| `DB_PATH` | `./data/usage.db` | string (path) | backend | SQLite database file location. | docker-compose.yml (set to `/app/data/usage.db`) |

## Plan Limits & Calibration

| Variable | Default | Type | Service | Purpose | Set in |
|---|---|---|---|---|---|
| `FIVE_HOUR_LIMIT_TOKENS` | `None` (auto-detect from OAuth utilization) | int or null | backend | Optional override for the 5-hour token limit when OAuth-derived calibration isn't available. | docker-compose.yml (currently `92000000`) |
| `WEEKLY_OPUS_HOURS` | `35` | int | backend | Weekly Opus-hours allocation for the Max plan tier. Display/forecast only — not an enforcement mechanism. | environment / docker-compose.yml if needed |
| `WEEKLY_SONNET_HOURS` | `280` | int | backend | Weekly Sonnet-hours allocation. | environment / docker-compose.yml if needed |
| `OPUS_TOKENS_PER_HOUR` | `50000` | int | backend | Estimated tokens-per-hour for Opus, used to convert "hours" allocations into token forecasts. | environment / docker-compose.yml if needed |
| `SONNET_TOKENS_PER_HOUR` | `100000` | int | backend | Estimated tokens-per-hour for Sonnet, same purpose. | environment / docker-compose.yml if needed |

## Proactive Session Refresh (Phase 1)

> Introduced by [ARCHITECTURE-Proactive-Session-Refresh](../architecture/ARCHITECTURE-Proactive-Session-Refresh.md).

| Variable | Default | Type | Service | Purpose | Set in |
|---|---|---|---|---|---|
| `REFRESH_CHECK_INTERVAL_SECONDS` | `300` | int | backend | How often the window-state daemon re-evaluates state. Matches the existing 5-min periodic-importer cadence. Lower values waste OAuth cache hits with no benefit (cache TTL is also 5 min). | docker-compose.yml |
| `REFRESH_IDLE_THRESHOLD_MINUTES` | `30` | int | backend | How long the user must have been inactive (no new JSONL writes) before the banner / notification fires. Below ~15 min you risk firing mid-task; above ~60 min the feature becomes useless. | docker-compose.yml |
| `REFRESH_NOTIFICATIONS_ENABLED` | `true` | bool | backend | Master switch for browser desktop notifications. The banner always renders when `state == expired_idle`; this only governs the OS-level notification. | docker-compose.yml |
| `REFRESH_QUIET_HOURS` | `22-07` | string `HH-HH` | backend | Local-time window during which notifications are suppressed. Banner still renders. Hours are in 24-hour format; the example means "10 PM through 7 AM." | docker-compose.yml |

## Flask / Runtime

| Variable | Default | Type | Service | Purpose | Set in |
|---|---|---|---|---|---|
| `FLASK_APP` | `app.main` | string | backend | Flask application entry point. Required by `flask` CLI when used; harmless under gunicorn. | docker-compose.yml |
| `FLASK_ENV` | `production` | string | backend | Flask environment marker. Mostly cosmetic post-Flask-2.0; kept for clarity. | docker-compose.yml |
| `PYTHONUNBUFFERED` | `1` | string | backend | Ensures stdout/stderr are flushed in real time so `docker logs -f` is useful. | docker-compose.yml, Dockerfile (ENV) |

---

## Adding a New Env Var

1. Add the row to the appropriate section above with a sensible default and a one-sentence purpose.
2. Add the `os.environ.get(...)` pattern in [app/config.py](../../app/config.py) following the conventions in [.claude/rules/python-modules.md](../../.claude/rules/python-modules.md) (module-level constants, no side effects).
3. Add the pass-through to [docker-compose.yml](../../docker-compose.yml) with the same default.
4. Document in the architecture doc that introduced it.
5. The default value in code and in `docker-compose.yml` should always match.
