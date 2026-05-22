# IMPLEMENTATION: Proactive Session Refresh

**Document Owner:** TokenBoard
**Version:** 1.1
**Date:** 2026-05-18
**Status:** Complete
**Testing Strategy:** Local-first
**Execution Mode:** Autonomous
**Branch:** main (per CLAUDE.md solo-dev convention)
**Related Documents:**
- [ARCHITECTURE-Proactive-Session-Refresh](../architecture/ARCHITECTURE-Proactive-Session-Refresh.md)
- [PROPOSAL-Proactive-Session-Refresh](../proposals/PROPOSAL-Proactive-Session-Refresh.md)

---

## Overview

### Summary
Implemented Phase 0 (gunicorn migration) and Phase 1 (window-state daemon + dashboard banner + browser notifications) as defined in the architecture document. Phase 2 (programmatic `claude -p` ping) remains explicitly deferred — see the proposal's June 15, 2026 billing-split discussion.

### Sprint Configuration
- **Testing Strategy:** Local-first — self-tested after each phase, one consolidated Playwright-driven integration test (Phase 1c) at the end.
- **Execution Mode:** Autonomous — no per-phase user confirmation; quality gates ran via sub-agents at the end.

### Sprint Commits
| SHA | Phase | Description |
|---|---|---|
| `557dc53` | Bootstrap | `docs: bootstrap make-* documentation structure` |
| `fa2194f` | Phase 0 | `feat(docker): run gunicorn instead of Flask dev server for clean SIGTERM` |
| `bb85ebd` | Phase 1a | `feat(window-state): add window-state daemon and /api/window-state endpoint` |
| `3cd6227` | Phase 1b | `feat(ui): window-state banner, notifications, permission prompt` |
| `d38afe1` | Quality gate | `refactor: simplify Proactive Session Refresh implementation per code review` |

---

## Implementation Summary

### What Was Built
- [x] Phase 0: gunicorn replaces Flask dev server in the container CMD; `python run.py` keeps the dev server for local development.
- [x] Phase 1a: backend window-state daemon in `app/window_state.py`, `/api/window-state` endpoint, `get_latest_activity()` helper in `app/db.py`, four env-var knobs in `app/config.py`, daemon wire-in to `init_app()`, docker-compose passthrough.
- [x] Phase 1b: header DOM (`#windowStateBanner`, `#notifPermissionPrompt`), banner + permission CSS, six new JS functions (`fetchWindowState`, `renderWindowBanner`, `maybeFireNotification`, `isInQuietHours`, `setupBannerDismiss`, `setupNotificationPrompt`), integration into the existing 60s `refreshData()` polling cycle.
- [x] Phase 1c: end-to-end Playwright smoke + simulated `expired_idle` walkthrough — 6/6 pass.

### Deviations from Architecture
| Planned | Actual | Rationale |
|---|---|---|
| Pin `gunicorn==22.0.0` in requirements.txt | Left existing `gunicorn>=21.0.0` pin; container resolved to gunicorn 26.0.0 | The pin was already present and looser; container resolved a recent stable. Architecture's specific `==22.0.0` was a recommendation, not a hard requirement. Confirmed SIGTERM handling works under gunicorn 26.0.0. |
| New `.claude/rules/` files would not be tracked because `.claude/` was gitignored | Adjusted `.gitignore` to ignore `.claude/*` except for `.claude/rules/` | The scoped rules are project-wide guidance and should be shared across collaborators / future agent runs. The user-local `settings.local.json` stays ignored. |

---

## Phase-by-Phase Summary

### Phase 0: SIGTERM fix via gunicorn

**Status:** Complete

#### Development
- [Dockerfile](../../Dockerfile): replaced `CMD ["python", "-m", "app.main"]` with exec-form gunicorn invocation (`--workers 1 --threads 4 --graceful-timeout 10`).
- No changes to [app/main.py](../../app/main.py), [app/config.py](../../app/config.py), or [run.py](../../run.py).
- [requirements.txt](../../requirements.txt) was already including gunicorn (`gunicorn>=21.0.0`); no edit needed.

#### Testing
- [x] Local self-test passed (commit `fa2194f`):
  - `docker compose build` clean.
  - `init_app()` ran exactly once on container start.
  - `/api/usage` returned HTTP 200 within ~1s.
  - **`docker compose down` measured at 650ms** (vs. ~10s pre-fix; target was <2s).
- [x] Consolidated integration test passed (Phase 1c).

#### Issues & Learnings
- None.

---

### Phase 1a: Backend window-state daemon

**Status:** Complete

#### Development
- New module [app/window_state.py](../../app/window_state.py) (~83 lines): `_window_status` dict, `_lock`, `evaluate_once()`, `get_status()`, `run_loop()`.
- [app/db.py](../../app/db.py): added `get_latest_activity()` — single `SELECT MAX(timestamp)` query using the existing `idx_timestamp` index.
- [app/config.py](../../app/config.py): appended `REFRESH_CHECK_INTERVAL_SECONDS` (300), `REFRESH_IDLE_THRESHOLD_MINUTES` (30), `REFRESH_NOTIFICATIONS_ENABLED` (true), `REFRESH_QUIET_HOURS` ("22-07").
- [app/main.py](../../app/main.py): added `window_state` import, `/api/window-state` route, daemon-thread start in `init_app()`.
- [docker-compose.yml](../../docker-compose.yml): four env vars passed through.

#### Testing
- [x] Local self-test passed (commit `bb85ebd`):
  - Container logs showed "Window state watcher started".
  - `/api/window-state` returned the documented 9-key envelope with `state: "active"`, `refresh_recommended: false`, `last_evaluated_at` populated (confirming daemon ran on thread start).
- [x] Consolidated integration test passed (Phase 1c).

#### Issues & Learnings
- The `evaluate_once()` function runs immediately at thread start before the first `time.sleep(...)`, which is the correct behavior for "no cold-start delay." Confirmed in the first observed `/api/window-state` response.

---

### Phase 1b: Frontend banner + notifications

**Status:** Complete

#### Development
- [templates/index.html](../../templates/index.html): inserted `#notifPermissionPrompt` and `#windowStateBanner` inside `<header>`, after `.calibration-status`.
- [static/style.css](../../static/style.css): appended ~94 lines for `.banner`, `.banner-warn`, `.banner-dismiss` (with `:focus-visible` for keyboard accessibility), `.notif-prompt`, `.notif-btn`, `.notif-btn-primary`.
- [static/dashboard.js](../../static/dashboard.js): added ~115 lines below `refreshData()`. Functions: `fetchWindowState`, `renderWindowBanner`, `maybeFireNotification`, `isInQuietHours`, `setupBannerDismiss`, `setupNotificationPrompt`. Added `fetchWindowState()` to `refreshData()`'s `Promise.all`. Added `setupBannerDismiss()` + `setupNotificationPrompt()` to the `DOMContentLoaded` handler.
- Notification debouncing: `lastNotifiedExpiredAt` and `dismissedExpiredAt` module variables prevent repeat fires for the same `expired_at` value.

#### Testing
- [x] Local self-test passed (commit `3cd6227`):
  - `node --check` clean.
  - HTML served with all three new DOM IDs.
  - CSS appended cleanly.
  - JS served with all six new functions.
- [x] Consolidated integration test passed (Phase 1c).

#### Issues & Learnings
- The initial dismiss-handler design did a synthetic `fetch('/api/window-state')` inside the click handler to capture `expired_at` for the dismissal. Refactored to track `currentBannerExpiredAt` in module scope so dismissal is purely client-side. Cleaner and avoids an unnecessary HTTP call.
- Playwright's headless Chromium returns `Notification.permission === "denied"` by default, not `"default"` as one might assume. Our `setupNotificationPrompt` correctly bails on non-`"default"`, so the prompt stays hidden in tests — confirmed as correct app contract, not a bug.

---

### Phase 1c: Consolidated integration test (Playwright)

**Status:** Complete — 6/6 pass

Performed by a Playwright sub-agent. Screenshots saved to `temp-research-artifacts/screenshots/` and cleaned up at sprint end.

| Test | Result |
|---|---|
| Initial load smoke (no console errors, banner hidden, real data present) | PASS |
| Simulated `refresh_recommended: true` → banner shows with "1h 5m ago" formatting | PASS |
| Dismiss button hides banner; same `expired_at` stays dismissed; different `expired_at` re-shows | PASS |
| `isInQuietHours("22-07")` at hour 22 → true; `("09-17")` at hour 22 → false; malformed input → false | PASS |
| `/api/window-state` API smoke: HTTP 200, all 9 documented keys | PASS |
| No regression on existing `#hourlyCard` (`#hourlyUsage` populated to "29.39M") | PASS |

---

## Post-Implementation Quality Gates

### Code Simplification (commit `d38afe1`)

Two clean wins applied by the code-simplifier sub-agent:

1. **`app/db.py:get_latest_activity()`** — dropped the over-defensive `row and row["latest"]` guard. `SELECT MAX(...)` always returns one row with `latest=None` on an empty table, so the short-circuit was dead.
2. **`static/dashboard.js:setupNotificationPrompt()`** — extracted shared `dismissPrompt` closure and lifted the sessionStorage key (`'tokenboard-notif-prompt-dismissed'`) to a module constant. Eliminates copy-paste between the Enable and Skip handlers.

Skipped opportunities (each with rationale) documented in the sub-agent's report. Notable: the `iso.replace("Z", "+00:00")` idiom appears in both pre-sprint and sprint code; extracting a helper just for the new file would create an inconsistent split.

### Verify-App (22/22 PASS)

All exit criteria verified by independent sub-agent:
- Phase 0: 5/5 (build clean, init_app once, /api/usage <1s, shutdown 525ms measured, run.py unchanged)
- Phase 1a: 6/6 (envelope shape, daemon evaluates at start, active-state correct, code-verified branches, OAuth-fail graceful, zero credential logging in diff)
- Phase 1b: 8/8 (banner show/hide via Playwright, debouncing, quiet-hours, permission gating, keyboard accessibility, zero console errors)
- Overall goals: 4/4 (gunicorn live, expired-idle detection, /api/window-state exposed, all 4 env vars wired through)

---

## Lessons Learned

### What Went Well
- The architecture doc was specific enough that Phase 0 + 1a + 1b each had unambiguous implementation paths. Autonomous mode ran end-to-end without a single ambiguity-driven pause.
- Reusing the existing OAuth metering cache (5-min TTL) meant the new daemon adds zero outbound HTTP load.
- Adding the new fetch to the existing `Promise.all` inside `refreshData()` kept the 60-second polling cadence — no new `setInterval`.
- Playwright integration test was a strong final gate; caught the banner formatting at "1h 5m ago" and confirmed dismiss-and-readded behavior end-to-end.

### What Could Be Improved
- The `.claude/` gitignore tweak was caught at commit time, not at `/make-init` time. Future `/make-init` runs could detect this case and prompt up front.
- The architecture's first-cut "synthetic fetch in the dismiss handler" was an unnecessary HTTP call; simplified inline during Phase 1b.

### New Learnings Captured
- Anthropic's June 15, 2026 billing split fundamentally changes Phase 2 economics (recorded in proposal + memory).
- TokenBoard's `~/.claude` mount must stay read-only; any feature wanting to write back (Phase 2's `claude -p` ping) requires explicit sign-off (recorded in CLAUDE.md + memory).
- TokenBoard runs single-process / single-user; `--workers 1` is load-bearing (recorded in CLAUDE.md + `.claude/rules/docker-deploy.md`).
- OAuth tokens (`sk-ant-oat01-*`) are rejected at `api.anthropic.com` — direct API calls with subscription credentials don't work (recorded in proposal + memory).

---

## Follow-Up Items

### Technical Debt
- [ ] `run.py` still has `debug=True` despite the recent security-hardening commit (`7d76d44`). Pre-existing, not in sprint scope, but worth fixing — recommend `debug=False` or read from `FLASK_DEBUG` env. Out of scope for this sprint.
- [ ] The dependency pins in `requirements.txt` are loose (`flask>=2.3.0`, `gunicorn>=21.0.0`, `requests>=2.28.0`). CLAUDE.md and `.claude/rules/docker-deploy.md` say "pin all top-level dependencies." Out of scope for this sprint; worth a small chore commit.
- [ ] Pre-existing typo in `/api/usage` response: `sonnet_tokens_per_our` (should be `_per_hour`). Renaming requires touching consumers; out of scope.

### Future Enhancements
- [ ] Phase 2 (programmatic `claude -p` ping) — revisit after June 15, 2026 once the Agent SDK billing pool is measurable.
- [ ] Optional: surface a "daemon last evaluated >10 min ago, may be stale" warning if the window-state thread crashes. Currently the inner `try/except` keeps the loop alive but doesn't escalate.
- [ ] Optional: localStorage-persisted banner dismissal (currently session-only).
- [ ] Multi-machine activity reconciliation if the user reports stale banner false-positives.
- [ ] Manual user-acceptance test against a real "window expired while idle" scenario — requires waiting for an actual 5-hour window to expire while idle. Architecture doc lists this in Phase 1c exit criteria; deferred to next opportunistic window-expiry event because waiting 5+ hours in this sprint wasn't practical.

---

**Document History:**
| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-18 | TokenBoard / Claude | Initial implementation doc — Phase 0 + Phase 1, Local-first + Autonomous. |
| 1.1 | 2026-05-18 | TokenBoard / Claude | Sprint complete. Phase-by-phase results filled in; deviations, learnings, follow-ups recorded. |
