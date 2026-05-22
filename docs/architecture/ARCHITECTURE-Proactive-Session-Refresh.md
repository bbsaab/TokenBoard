# ARCHITECTURE: Proactive Session Refresh

**Document Owner:** TokenBoard
**Version:** 1.0
**Date:** 2026-05-18
**Status:** Complete
**Related Documents:**
- [PROPOSAL-Proactive-Session-Refresh](../proposals/PROPOSAL-Proactive-Session-Refresh.md) — research, recommendation, June 15 2026 billing-split caveat.

---

## Overview

### Purpose
Make TokenBoard *proactive* about Claude Code 5-hour session windows. Two phases of work are designed here: a prerequisite hardening of the running container (Phase 0), and a notification-driven refresh feature that surfaces "window expired, click to start a new one" guidance to the user before they sit back down (Phase 1). Together these convert TokenBoard from a read-only dashboard into an active session-state assistant — without automating anything that depends on the pre-June-15 billing model.

### Goals
- Replace Flask's dev server (which silently ignores SIGTERM) with a production WSGI runner so container stop/restart is fast and clean.
- Detect the moment the user's current 5-hour window expires while they're idle, and surface a banner + browser notification recommending a refresh.
- Expose `GET /api/window-state` so the existing 60-second dashboard polling cycle can render the new banner without a parallel polling loop.
- Provide a small set of environment-tunable knobs (check interval, idle threshold, notifications on/off, quiet hours) without flooding the config surface.
- Document a new `docs/_references/ENVIRONMENT-VARIABLES.md` registry for future features.

### Non-Goals (Out of Scope)
- **No Phase 2 work.** Programmatic `claude -p` invocation, the `auto_refresh_log` table, Dockerfile changes to add Node + the Claude CLI, and the read/write `~/.claude` mount are all deferred. They will be revisited in a separate architecture document after June 15, 2026 once the Agent SDK billing split is measurable.
- **No multi-user or multi-instance support.** The single-process, single-user assumption (per [CLAUDE.md](../../CLAUDE.md)) is preserved.
- **No new persistence.** Phase 1 stores no state to SQLite. The window banner is derived purely from the OAuth metering response + JSONL-derived last-activity timestamp; reloading the dashboard is fine.
- **No mobile push notifications.** The Notification API targeted here is browser-only and only fires while a dashboard tab is open.
- **No multi-machine activity reconciliation.** If a second machine on the same Anthropic account is active, TokenBoard on the current machine may misclassify state as "idle." This is documented as an open question, not solved here.

---

## Existing Data Model References

| Model | Location | Fields Used |
|-------|----------|-------------|
| `usage_records` (SQLite table) | [app/db.py:25-46](../../app/db.py#L25) | `timestamp` (ISO 8601 UTC), `session_id`, `model`, token columns — read-only for this feature. A new helper `get_latest_activity()` will be added that does `SELECT MAX(timestamp) FROM usage_records`. |
| OAuth metering response | [app/usage_api.py:fetch_oauth_usage()](../../app/usage_api.py#L49) | `five_hour.utilization`, `five_hour.resets_at`, `seven_day.utilization`, `seven_day.resets_at`. Cached for 5 min by `get_oauth_usage_cached()` ([app/usage_api.py:86](../../app/usage_api.py#L86)); 10-min error backoff on 429. |
| `_import_status` (in-memory dict) | [app/main.py:14-20](../../app/main.py#L14) | Reference pattern for the new in-memory `_window_status` dict that the API endpoint reads from. |

## Schema Changes Proposed

**None — using existing schema only.**

Phase 1's banner state is computed on demand from cached OAuth data + a single `MAX(timestamp)` query on `usage_records`. No new tables, no new columns, no migration. The new `get_latest_activity()` helper in [app/db.py](../../app/db.py) is a query, not a schema change.

The deferred Phase 2 *would* add an `auto_refresh_log` table; that's scoped to a future architecture doc.

---

## Environment Variables

> New env vars approved by user. Documented here and registered in [docs/_references/ENVIRONMENT-VARIABLES.md](../_references/ENVIRONMENT-VARIABLES.md).

| Variable | Default | Type | Purpose |
|---|---|---|---|
| `REFRESH_CHECK_INTERVAL_SECONDS` | `300` | int | How often the new daemon thread re-evaluates window state. Default matches the existing periodic-importer cadence ([app/main.py:439](../../app/main.py#L439)). |
| `REFRESH_IDLE_THRESHOLD_MINUTES` | `30` | int | How long the user must have been inactive (no new JSONL writes) before a banner / notification fires. Below 30 min you risk firing while the user is mid-task. |
| `REFRESH_NOTIFICATIONS_ENABLED` | `true` | bool | Master switch for browser desktop notifications. The banner always renders when state is `expired_idle`; this only governs the system notification. |
| `REFRESH_QUIET_HOURS` | `22-07` | string `HH-HH` | Window during which notifications are suppressed (banner still renders). Stored in local time on the *server*, which on a single-user laptop deployment is the user's wall clock. |

The Phase 0 work introduces no new env vars (gunicorn config goes in the Dockerfile CMD, not env).

---

## Domain-Specific Reality Check

Pulling from [CLAUDE.md](../../CLAUDE.md):

```
[x] Inventory existing models — confirmed: one table `usage_records`. No new tables in Phase 1.
[x] Confirm field names — confirmed via direct read of app/db.py:25-46.
[x] No migrations needed — additive change to add a query helper is not a schema change.
[x] Confirm API routes via reading app/main.py — confirmed 8 existing routes; new `/api/window-state` follows the same `@app.route` + `jsonify` pattern.
[x] OAuth metering response shape stable — confirmed: response uses `five_hour.{utilization, resets_at}` and `seven_day.{utilization, resets_at}`. Phase 1 reads these only; June 15, 2026 may add new keys (Agent SDK pool) but won't break what we read.
[x] Read-only ~/.claude mount preserved — Phase 1 does not touch ~/.claude; OAuth credentials read path is unchanged.
[x] OAuth credentials never logged — confirmed: new code adds no logging of tokens.
[x] Single-process / in-memory state assumption holds — new daemon thread runs in the same process; new _window_status dict mirrors existing _import_status pattern.
[x] UTC storage, local-time display — backend returns UTC ISO 8601 strings; frontend uses existing formatTime() helper at static/dashboard.js:33-40 for local rendering.
[x] Stay under file size limits — main.py changes ~70 lines added; well under the 500-line module cap.
[x] Phase 0 obeys docker-deploy rule on exec-form CMD — confirmed: new gunicorn CMD is exec form.
[x] Phase 0 preserves --workers 1 — confirmed: gunicorn config keeps single-process assumption.
```

---

## Technical Design

### System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                  Container (gunicorn, 1 worker)                     │
│                                                                     │
│  ┌──────────────┐    ┌─────────────────┐    ┌──────────────────┐   │
│  │ File watcher │    │ Periodic import │    │ NEW: Window watch│   │
│  │  (daemon)    │    │   (daemon)      │    │     (daemon)     │   │
│  │              │    │  every 300s     │    │  every 300s      │   │
│  └──────┬───────┘    └────────┬────────┘    └────────┬─────────┘   │
│         │ inserts             │ inserts              │ updates      │
│         ▼                     ▼                      ▼              │
│  ┌──────────────────────────────────┐    ┌─────────────────────┐   │
│  │      SQLite (usage_records)      │    │  _window_status     │   │
│  │      WAL mode, single writer     │    │  (in-memory dict)   │   │
│  └──────────────────────────────────┘    └──────────┬──────────┘   │
│                                                      │              │
│  ┌──────────────────────────────────────────────────┴──────────┐   │
│  │  Flask routes (gunicorn handler threads)                    │   │
│  │  /api/usage, /api/history, ..., NEW /api/window-state       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  OAuth metering cache (5-min TTL, 10-min error backoff)      │  │
│  │  Reads ~/.claude/.credentials.json (read-only mount)         │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ HTTP (browser)
┌─────────────────────────────────────────────────────────────────────┐
│  Dashboard (templates/index.html + static/dashboard.js)             │
│                                                                     │
│  refreshData() — every 60s, Promise.all of fetchUsage,              │
│  fetchForecast, fetchHistory, fetchCalibration, NEW fetchWindowState│
│                                                                     │
│  When state = expired_idle:                                         │
│    1. Render banner in header (above .calibration-status)           │
│    2. If permissions granted + not in quiet hours + first fire:     │
│       fire Notification("TokenBoard: window expired")               │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 0: SIGTERM fix — gunicorn migration

**Dockerfile change** ([Dockerfile:29](../../Dockerfile#L29)):

```dockerfile
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--threads", "4", \
     "--graceful-timeout", "10", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app.main:app"]
```

**requirements.txt addition:**
```
gunicorn==22.0.0
```

(Pin to a specific 22.x release. Use whatever is current at implementation time — 22.0.0 was stable as of late 2024.)

**`run.py` is unchanged.** Local dev (`python run.py`) keeps using Flask's dev server because Ctrl+C works there. Only the container path moves to gunicorn.

**Why `--workers 1`:** TokenBoard's three daemon threads, the OAuth cache, and the `_import_status` / `_window_status` in-memory dicts all assume single-process. `--threads 4` gives request concurrency without forking.

**Why `--graceful-timeout 10`:** Matches Docker's default 10s SIGTERM-to-SIGKILL grace period, so a clean shutdown completes before the kill.

No `app/main.py` change is strictly needed for Phase 0 — gunicorn imports `app.main:app` directly, which still triggers `init_app()` via the `with app.app_context(): init_app()` block at [app/main.py:497-498](../../app/main.py#L497).

### Phase 1: Window-state intelligence + notification

#### New module: `app/window_state.py`

A single module containing the daemon-thread loop and the state-computation logic, keeping `app/main.py` focused on Flask bootstrap.

```python
"""Detect 'expired idle' Claude session windows and expose state for the UI."""

import threading
import time
from datetime import datetime, timezone
from typing import Optional

from . import config, db, usage_api

# Module-level in-memory state, mirroring _import_status pattern in main.py
_window_status: dict = {
    "state": "unknown",            # 'active' | 'expired_idle' | 'no_data' | 'unknown'
    "expired_at": None,            # ISO 8601 UTC — when the prior window ended (or None)
    "next_resets_at": None,        # ISO 8601 UTC — for active windows
    "minutes_since_expiry": None,  # int — null when state != expired_idle
    "minutes_since_last_activity": None,
    "refresh_recommended": False,
    "last_evaluated_at": None,     # ISO 8601 UTC — when the daemon last ran
}
_lock = threading.Lock()


def evaluate_once() -> dict:
    """Compute the current window state. Pure: reads cache + DB, writes module state, returns snapshot."""
    now = datetime.now(timezone.utc)
    oauth = usage_api.get_oauth_usage_cached()
    last_activity_iso = db.get_latest_activity()

    snapshot = {
        "state": "unknown",
        "expired_at": None,
        "next_resets_at": None,
        "minutes_since_expiry": None,
        "minutes_since_last_activity": None,
        "refresh_recommended": False,
        "last_evaluated_at": now.isoformat(),
    }

    if last_activity_iso:
        last_activity = datetime.fromisoformat(last_activity_iso.replace("Z", "+00:00"))
        snapshot["minutes_since_last_activity"] = int((now - last_activity).total_seconds() / 60)

    if oauth and oauth.get("five_hour", {}).get("resets_at"):
        resets_at = datetime.fromisoformat(oauth["five_hour"]["resets_at"].replace("Z", "+00:00"))
        snapshot["next_resets_at"] = resets_at.isoformat()
        utilization = oauth["five_hour"].get("utilization", 0)

        if resets_at > now and utilization > 0:
            snapshot["state"] = "active"
        elif resets_at <= now:
            snapshot["state"] = "expired_idle"
            snapshot["expired_at"] = resets_at.isoformat()
            snapshot["minutes_since_expiry"] = int((now - resets_at).total_seconds() / 60)

            idle_min = snapshot["minutes_since_last_activity"] or 0
            if idle_min >= config.REFRESH_IDLE_THRESHOLD_MINUTES:
                snapshot["refresh_recommended"] = True
        else:
            snapshot["state"] = "no_data"

    with _lock:
        _window_status.update(snapshot)
    return snapshot


def get_status() -> dict:
    """Thread-safe read of the current snapshot."""
    with _lock:
        return dict(_window_status)


def run_loop() -> None:
    """Daemon-thread entry point. Re-evaluates every REFRESH_CHECK_INTERVAL_SECONDS."""
    while True:
        try:
            evaluate_once()
        except Exception as e:
            print(f"window_state evaluation error: {e}", flush=True)
        time.sleep(config.REFRESH_CHECK_INTERVAL_SECONDS)
```

#### New helper in `app/db.py`

```python
def get_latest_activity() -> Optional[str]:
    """Return the max(timestamp) from usage_records, or None if empty."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT MAX(timestamp) AS latest FROM usage_records"
        ).fetchone()
        return row["latest"] if row and row["latest"] else None
    finally:
        conn.close()
```

The existing `idx_timestamp` index ([app/db.py:39](../../app/db.py#L39)) makes this O(1) — SQLite reads the rightmost B-tree leaf.

#### New env vars in `app/config.py`

Appended to the bottom of [app/config.py](../../app/config.py):

```python
# Proactive session refresh (Phase 1 of PROPOSAL-Proactive-Session-Refresh)
REFRESH_CHECK_INTERVAL_SECONDS = int(os.environ.get("REFRESH_CHECK_INTERVAL_SECONDS", 300))
REFRESH_IDLE_THRESHOLD_MINUTES = int(os.environ.get("REFRESH_IDLE_THRESHOLD_MINUTES", 30))
REFRESH_NOTIFICATIONS_ENABLED = os.environ.get("REFRESH_NOTIFICATIONS_ENABLED", "true").lower() in ("true", "1", "yes")
REFRESH_QUIET_HOURS = os.environ.get("REFRESH_QUIET_HOURS", "22-07")
```

#### `app/main.py` integration

In `init_app()` ([app/main.py:466](../../app/main.py#L466)), after the existing thread starts:

```python
# Start window-state watcher thread
from . import window_state
window_thread = threading.Thread(target=window_state.run_loop, daemon=True)
window_thread.start()
print("Window state watcher started", flush=True)
```

And a new route:

```python
@app.route("/api/window-state")
def api_window_state():
    """Return current 5-hour window state and refresh recommendation."""
    from . import window_state
    snapshot = window_state.get_status()
    snapshot["quiet_hours"] = config.REFRESH_QUIET_HOURS
    snapshot["notifications_enabled"] = config.REFRESH_NOTIFICATIONS_ENABLED
    return jsonify(snapshot)
```

#### `docker-compose.yml` additions

```yaml
environment:
  # ... existing ...
  - REFRESH_CHECK_INTERVAL_SECONDS=300
  - REFRESH_IDLE_THRESHOLD_MINUTES=30
  - REFRESH_NOTIFICATIONS_ENABLED=true
  - REFRESH_QUIET_HOURS=22-07
```

### API Endpoints

| Method | Endpoint | Description | Request | Response (200) |
|---|---|---|---|---|
| `GET` | `/api/window-state` | Current 5-hour window state and refresh recommendation. Read from in-memory `_window_status` updated by the daemon. | — | See below. |

```json
{
  "state": "active | expired_idle | no_data | unknown",
  "expired_at": "2026-05-18T19:47:00+00:00",
  "next_resets_at": null,
  "minutes_since_expiry": 23,
  "minutes_since_last_activity": 187,
  "refresh_recommended": true,
  "last_evaluated_at": "2026-05-18T20:10:12+00:00",
  "quiet_hours": "22-07",
  "notifications_enabled": true
}
```

Conventions confirmed against existing endpoints (`/api/usage`, `/api/calibration`, `/api/status` per the codebase exploration): snake_case keys, ISO 8601 UTC timestamps, `null` for missing values, no top-level `error` field (errors surface via HTTP status).

### Data Flow

1. Daemon `window_state.run_loop()` ticks every 300s.
2. It calls `usage_api.get_oauth_usage_cached()` — hits Anthropic only every 5 min thanks to the existing cache; otherwise free.
3. It calls `db.get_latest_activity()` — single indexed `MAX(timestamp)` query.
4. It computes the snapshot and writes it to `_window_status` under a lock.
5. Browser polls `/api/window-state` every 60s as part of `refreshData()`'s `Promise.all`.
6. JS reads `state` and `refresh_recommended`:
   - If `refresh_recommended` is true → render the banner.
   - If `refresh_recommended` flipped from false→true *and* `notifications_enabled` *and* current local hour is outside `quiet_hours` *and* notification permission is granted → fire `new Notification(...)` and record the dismissal locally so it doesn't re-fire on subsequent polls for the same `expired_at`.
7. When state returns to `active` (the user has refreshed), the banner clears on the next poll.

---

## UI/UX Design

> Reference: [docs/_references/DESIGN-SYSTEM.md](../_references/DESIGN-SYSTEM.md) — uses existing color tokens and the established `.status-indicator` / `.calibration-status` header convention.

### User Flow

1. User finishes a Claude Code session at 12:30 PM (5-hour window opened at 09:47, expires at 14:47).
2. User walks away. At 14:47 the window quietly expires.
3. At 15:17 (30 min after expiry — `REFRESH_IDLE_THRESHOLD_MINUTES` threshold met), the daemon flips `refresh_recommended` to true.
4. On the next 60-second poll, the dashboard renders a coral banner: *"Your 5-hour window expired 30 minutes ago. Open Claude Code now to start a fresh one before you sit back down."* with a "Got it" dismiss button.
5. If the user has the dashboard tab open and granted notification permission, a system notification fires once: *"TokenBoard: Window expired — refresh now."*
6. User opens a terminal, runs `claude` (or whatever their normal flow is), sends a message. The window resets server-side. On the next 60-second poll the banner disappears.

### Components

| Component | Purpose | Location |
|---|---|---|
| `#windowStateBanner` (new) | Coral banner under `.calibration-status` showing "expired N minutes ago, refresh now" | [templates/index.html](../../templates/index.html) — insert at line 19, before `</header>` |
| `.banner` / `.banner-warn` (new CSS classes) | Banner styles, using `var(--accent)` / `var(--accent-light)` for the warn variant. Includes dismiss button styling. | [static/style.css](../../static/style.css) — append at end |
| `fetchWindowState()` (new) | Polls `/api/window-state` as part of the 60s `refreshData()` `Promise.all` | [static/dashboard.js](../../static/dashboard.js) |
| `renderWindowBanner(data)` (new) | Pure DOM update: show/hide banner, format the "N minutes ago" string via existing `formatTime()` patterns. | [static/dashboard.js](../../static/dashboard.js) |
| `maybeFireNotification(data)` (new) | Side-effect: fire `new Notification(...)` once per `expired_at`, respecting quiet hours and `Notification.permission`. Tracks last-fired-`expired_at` in a module-level variable (not localStorage — refreshing the page is allowed to re-notify). | [static/dashboard.js](../../static/dashboard.js) |

### Notification permission UX

On the first dashboard load after the feature ships, render an unobtrusive prompt above the banner area:

> *"Enable browser notifications to be alerted when your Claude window expires? [Enable] [Skip]"*

Only show this if `Notification.permission === "default"`. Once the user clicks Enable or Skip (or rejects in the browser dialog), the prompt is gone for that browser. We do not call `Notification.requestPermission()` without an explicit user gesture (Chrome/Firefox both require this and may auto-deny otherwise).

---

## Implementation Plan

### Timeline Overview

| Phase | Scope | Traditional | AI-Assisted | Risk |
|---|---|---|---|---|
| Phase 0 | Gunicorn migration: 4-line diff + verification of clean SIGTERM. | 0.5 day | 15 min | Low |
| Phase 1a | Backend: `window_state.py`, `db.get_latest_activity()`, config additions, `init_app()` thread, `/api/window-state` route, docker-compose env passthrough. | 1 day | 30 min | Low |
| Phase 1b | Frontend: `fetchWindowState()`, `renderWindowBanner()`, `maybeFireNotification()`, permission-prompt UX, CSS, header DOM insert. | 1 day | 45 min | Low |
| Phase 1c | Manual integration testing using the CLAUDE.md checklist + a deliberately-expired-window walkthrough. | 0.5 day | 30 min | Low |
| **Total** | | **3 days** | **~2 hours** | — |

> **AI-Assisted Timeline Tracking**

| Phase | Estimated | Actual | Delta | Notes |
|---|---|---|---|---|
| Phase 0 | 15 min | — | — | |
| Phase 1a | 30 min | — | — | |
| Phase 1b | 45 min | — | — | |
| Phase 1c | 30 min | — | — | |

### Phase 0: SIGTERM fix via gunicorn

**Scope:**
- Add `gunicorn==22.0.0` to [requirements.txt](../../requirements.txt).
- Replace the CMD in [Dockerfile](../../Dockerfile) with the gunicorn exec-form command shown above.
- No changes to `app/main.py`, `app/config.py`, or `run.py`.

**Exit Criteria:**
- [ ] `docker compose build` completes without warnings.
- [ ] `docker compose up -d` starts cleanly; `docker compose logs` shows `init_app()` output once (not duplicated across workers).
- [ ] `curl http://localhost:8080/api/usage` returns valid JSON within 1 s of container start.
- [ ] `docker compose down` completes in **under 2 seconds** (was ~10 s before).
- [ ] `python run.py` still works locally for dev (Ctrl+C exits cleanly).

**Estimated Time:** Traditional 0.5 day | AI-Assisted 15 min

### Phase 1a: Backend window-state daemon

**Scope:**
- New file [app/window_state.py](../../app/window_state.py) (~70 lines).
- Add `get_latest_activity()` to [app/db.py](../../app/db.py).
- Append 4 env vars to [app/config.py](../../app/config.py).
- Wire daemon into `init_app()` in [app/main.py](../../app/main.py).
- Add `/api/window-state` route to [app/main.py](../../app/main.py).
- Update [docker-compose.yml](../../docker-compose.yml) with the 4 new env vars.

**Exit Criteria:**
- [ ] `curl http://localhost:8080/api/window-state` returns the documented JSON envelope with `state`, `last_evaluated_at`, etc.
- [ ] After container start, `last_evaluated_at` updates within 5 minutes (300s default).
- [ ] When the OAuth metering call succeeds and `five_hour.resets_at` is in the future, `state` is `active`.
- [ ] When `resets_at` is in the past *and* `MAX(timestamp)` is more than 30 min ago, `state` is `expired_idle` and `refresh_recommended` is `true`.
- [ ] When the OAuth call fails or returns no data, `state` is `unknown` and the endpoint still returns 200 (no crash).
- [ ] No new logging of any token, credential, or OAuth secret. Confirmed by grep on the diff.

**Estimated Time:** Traditional 1 day | AI-Assisted 30 min

### Phase 1b: Frontend banner + notifications

**Scope:**
- New JS functions `fetchWindowState()`, `renderWindowBanner(data)`, `maybeFireNotification(data)` in [static/dashboard.js](../../static/dashboard.js).
- Add `fetchWindowState()` to the `Promise.all` inside `refreshData()`.
- DOM additions to [templates/index.html](../../templates/index.html): `#windowStateBanner`, `#notifPermissionPrompt`.
- CSS additions in [static/style.css](../../static/style.css): `.banner`, `.banner-warn`, `.banner-dismiss`, `.notif-prompt`.
- Quiet-hours check uses the browser's local hour (`new Date().getHours()`) against `REFRESH_QUIET_HOURS` from the API response.

**Exit Criteria:**
- [ ] Banner appears within 60 s of the daemon flipping `refresh_recommended` to `true`.
- [ ] Banner disappears within 60 s of `state` returning to `active`.
- [ ] Notification fires at most once per `expired_at` value (tracked in JS module scope).
- [ ] Notification does not fire when current local hour is inside `REFRESH_QUIET_HOURS` (banner still appears).
- [ ] Notification does not fire when `notifications_enabled` is `false` server-side.
- [ ] Permission prompt only shows when `Notification.permission === "default"`; never re-shows after user choice.
- [ ] Banner is keyboard-accessible: dismiss button is a real `<button>` with visible focus.
- [ ] Console has zero errors on a clean page load.

**Estimated Time:** Traditional 1 day | AI-Assisted 45 min

### Phase 1c: Manual integration test

**Scope:**
- Walk through the CLAUDE.md domain-specific testing checklist.
- Test the "expired window" flow end-to-end with a deliberately-shifted system clock or a manually-edited cache.
- Verify behavior across the OAuth failure path (disconnect network, confirm `state=unknown` and the dashboard does not crash).
- Verify the banner CSS at typical viewport widths (mobile ≥ 360px, desktop ≥ 1280px).

**Exit Criteria:**
- [ ] Full CLAUDE.md testing checklist passes.
- [ ] At least one full "window expired → banner → notification → user refreshes → banner clears" cycle observed end-to-end.
- [ ] No console errors during the cycle.

**Estimated Time:** Traditional 0.5 day | AI-Assisted 30 min

---

## Testing Strategy

> TokenBoard has no automated test suite today (per CLAUDE.md). Tests added here are optional, not required.

### Unit Tests (optional, suggested)
- [ ] `window_state.evaluate_once()` against a fixture OAuth dict + a fixture "last activity" timestamp; assert each branch (`active`, `expired_idle` with idle threshold met, `expired_idle` with idle threshold not met, `no_data`, `unknown`).
- [ ] `db.get_latest_activity()` against an empty table (returns `None`) and a populated one (returns the max).

### Integration Tests (optional)
- [ ] Spin up the Flask app via Werkzeug test client, hit `/api/window-state`, assert response shape.

### Manual Testing
- [ ] Phase 0: confirm `docker compose down` < 2s.
- [ ] Phase 1: full flow (see Phase 1c exit criteria).
- [ ] Verify the OAuth cache still hits when the new daemon is running — i.e., `get_oauth_usage_cached()` is not bypassed.

### Domain-Specific Testing (from CLAUDE.md)
```
[ ] Dashboard loads at http://localhost:8080 with no console errors
[ ] /api/usage returns valid JSON within 1 second
[ ] 5-hour window math matches Claude Code's /usage output
[ ] docker compose up clean start, no warnings in logs
[ ] docker compose down completes within ~2 seconds (Phase 0 regression check)
[ ] If OAuth call changed: confirm graceful fallback when ~/.claude/.credentials.json is missing or token is expired
[ ] If display TZ-touched: spot-check that timestamps render in local time, not UTC
```

---

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Gunicorn change breaks something subtle (Flask context, init_app() ordering) in the container path. | Low | Medium | Phase 0 exit criteria explicitly include "init_app() runs exactly once" and "/api/usage works." Keep [run.py](../../run.py) on the dev server so a local fallback is always available. |
| OAuth metering response format changes around June 15, 2026 (Agent SDK pool split). | Medium | Low–Med | The daemon only reads existing keys (`five_hour.{utilization,resets_at}`); new keys won't break it. If the existing keys are removed, `state` falls back to `unknown` and the banner stays hidden — graceful degradation. Re-evaluate after June 15. |
| User has the dashboard tab open AND a second machine is also active on the same account. The "last activity" timestamp from this machine's JSONLs is stale, but the OAuth `resets_at` reflects the *account-wide* state, leading to false `expired_idle` classification. | Medium | Low | Document as a known limitation in the in-app banner copy and the open questions below. A future enhancement could reconcile via the OAuth response if Anthropic adds a `last_activity_at` field. |
| Browser denies notification permission silently; user never knows the feature exists beyond the banner. | Medium | Low | The banner itself is the primary surface; notifications are an enhancement, not the core. The first-load permission prompt is a one-time, non-blocking UX. |
| Daemon thread crashes silently and `last_evaluated_at` stops updating. | Low | Medium | The `try/except` around `evaluate_once()` ensures the loop continues. The endpoint exposes `last_evaluated_at`; the dashboard can show a warning if it's > 10 min stale. (Not in scope for Phase 1 MVP; flag for a follow-up.) |
| User sets `REFRESH_IDLE_THRESHOLD_MINUTES=0`, causing immediate banner the moment a window expires while they're actively typing. | Low | Low | Document the rationale for the 30-min default in [docs/_references/ENVIRONMENT-VARIABLES.md](../_references/ENVIRONMENT-VARIABLES.md). |

---

## Dependencies

### Blocked By
- [ ] Phase 0 must merge and verify clean shutdown before Phase 1a deploys (adding a third daemon thread on top of a process that doesn't shut down cleanly is a recipe for stuck containers during iteration).

### External Dependencies
- `gunicorn==22.0.0` (pinned). Pure-Python, no native compile, MIT-licensed.
- Browser `Notification` API — universal support in modern browsers; permission flow is well-understood.
- Anthropic's OAuth metering endpoint — already a dependency today; this feature does not deepen reliance on it.

---

## Open Questions

- [ ] **Multi-machine activity**: should the daemon try to reconcile the "this machine's JSONLs say idle, but the account may be active elsewhere" case? For now we accept the false positive. Worth revisiting if the user reports stale banners.
- [ ] **Quiet-hours semantics**: should quiet hours suppress the *banner* too, or only the notification? Current design suppresses only the notification. Open to flipping if the user finds the banner intrusive overnight.
- [ ] **Banner dismissal persistence**: should a dismissed banner stay dismissed across page reloads (localStorage) or only within the session? Current design is session-only.
- [ ] **What's a sensible value for `REFRESH_IDLE_THRESHOLD_MINUTES`?** 30 is a guess; first-week of use will tell us if 15 or 60 is better. The env var makes this tunable.
- [ ] **Should the dashboard surface "last_evaluated_at is stale" warnings?** Deferred to a follow-up; the Phase 1 banner is already enough information density.
- [ ] **Post-June-15 behavior**: do nothing automatic about it. Phase 1 keeps working (it's read-only on the OAuth response). The Phase 2 architecture document, when written, will revisit.

---

**Document History:**
| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-18 | TokenBoard / Claude | Initial draft. Phase 0 (gunicorn) + Phase 1 (window-state daemon + banner + notifications). Phase 2 explicitly deferred. |
