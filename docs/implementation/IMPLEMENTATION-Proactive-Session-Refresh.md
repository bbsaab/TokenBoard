# IMPLEMENTATION: Proactive Session Refresh

**Document Owner:** TokenBoard
**Version:** 1.0
**Date:** 2026-05-18
**Status:** In Progress
**Testing Strategy:** Local-first
**Execution Mode:** Autonomous
**Branch:** main (per CLAUDE.md solo-dev convention)
**Related Documents:**
- [ARCHITECTURE-Proactive-Session-Refresh](../architecture/ARCHITECTURE-Proactive-Session-Refresh.md)
- [PROPOSAL-Proactive-Session-Refresh](../proposals/PROPOSAL-Proactive-Session-Refresh.md)

---

## Overview

### Summary
Implement Phase 0 (gunicorn migration for clean SIGTERM handling) and Phase 1 (window-state daemon, `/api/window-state` endpoint, dashboard banner, browser notifications) as defined in the architecture document. Phase 2 (programmatic `claude -p` ping) is explicitly deferred — see proposal.

### Sprint Configuration
- **Testing Strategy:** Local-first — self-test after each phase, one consolidated integration test at the end. TokenBoard has no staging environment.
- **Execution Mode:** Autonomous — work through all phases without per-phase user confirmation; pause only on hard-stop conditions (build failure, ambiguity, context exhaustion).

---

## Implementation Summary

### What Was Built
- [ ] Phase 0: gunicorn replaces Flask dev server in container CMD
- [ ] Phase 1a: backend window-state daemon, `/api/window-state` endpoint, config knobs
- [ ] Phase 1b: dashboard banner, JS polling integration, browser notification UX
- [ ] Phase 1c: consolidated integration test

### Deviations from Architecture
*(To be filled at completion.)*

---

## Phase-by-Phase Summary

### Phase 0: SIGTERM fix via gunicorn

**Status:** Pending

#### Development
*(Pending)*

#### Testing
- [ ] Local self-test: `docker compose build`, `up`, curl, `down` < 2s
- [ ] Consolidated integration test (end of sprint)

#### Issues & Learnings
*(Pending)*

---

### Phase 1a: Backend window-state daemon

**Status:** Pending

#### Development
*(Pending)*

#### Testing
- [ ] Local self-test: `/api/window-state` returns documented JSON envelope
- [ ] Consolidated integration test (end of sprint)

#### Issues & Learnings
*(Pending)*

---

### Phase 1b: Frontend banner + notifications

**Status:** Pending

#### Development
*(Pending)*

#### Testing
- [ ] Local self-test: banner toggles correctly when `refresh_recommended` flips
- [ ] Consolidated integration test (end of sprint)

#### Issues & Learnings
*(Pending)*

---

### Phase 1c: Consolidated integration test

**Status:** Pending

#### Testing checklist (from ARCHITECTURE + CLAUDE.md)
- [ ] `docker compose build` no warnings
- [ ] `docker compose up -d` clean start
- [ ] `docker compose logs` shows `init_app()` once + "Window state watcher started"
- [ ] `curl /api/usage` returns valid JSON < 1 s
- [ ] `curl /api/window-state` returns documented envelope
- [ ] `docker compose down` < 2 s
- [ ] Dashboard loads with no console errors
- [ ] Banner renders correctly when state == `expired_idle`
- [ ] Permission prompt shows once for `Notification.permission === "default"`
- [ ] Backend timestamps are UTC; frontend renders local
- [ ] No token / credential logging in any new code path

---

## Autonomous Mode Pause Points

*(To be filled if any hard stops are hit.)*

---

## Lessons Learned

*(To be filled at completion.)*

---

## Follow-Up Items

*(To be filled at completion.)*

---

**Document History:**
| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-18 | TokenBoard / Claude | Initial implementation doc — Phase 0 + Phase 1, Local-first + Autonomous. |
