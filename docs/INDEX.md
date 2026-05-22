# Documentation Index

**Last Updated:** 2026-05-18
**Purpose:** Central registry of all TokenBoard documentation.

---

## Product Requirements

*(PRDs will be added here)*

---

## Proposals

- **[PROPOSAL-Proactive-Session-Refresh](proposals/PROPOSAL-Proactive-Session-Refresh.md)** — Have TokenBoard nudge (or, optionally, auto-trigger) a fresh Claude 5-hour window during periods of inactivity. Flags the June 15, 2026 Agent SDK billing split as a Phase 2 blocker. Includes a Phase 0 prerequisite to fix SIGTERM handling.
  *Status: Complete (Phase 0 + Phase 1; Phase 2 deferred) | Date: 2026-05-18*

---

## Active Architecture (Planning)

**Purpose:** Documents that define what we will build.

*(No active architecture documents. Proactive-Session-Refresh shipped — see Recently Completed.)*

---

## Active Implementation (Execution)

**Purpose:** Documents that summarize what is being built.

*(No active implementations.)*

---

## Recently Completed

**Purpose:** Shipped features with full documentation (< 30 days).

- **[IMPLEMENTATION-Proactive-Session-Refresh](implementation/IMPLEMENTATION-Proactive-Session-Refresh.md)** — Phase 0 (gunicorn migration; shutdown went from ~10 s to ~525 ms) + Phase 1 (window-state daemon, `/api/window-state` endpoint, dashboard banner + browser notifications). Phase 2 (programmatic `claude -p` ping) deferred pending June 15, 2026 billing-split outcome.
  *Status: Complete | Date: 2026-05-18 | Architecture: [ARCHITECTURE-Proactive-Session-Refresh](architecture/ARCHITECTURE-Proactive-Session-Refresh.md)*

---

## Archived Documentation

See [archive/](archive/) for older features (summaries only).

---

## Debugging Guides

*(Debugging guides will be added as needed.)*

---

## Feedback Analysis

*(Feedback analysis documents will be added here.)*

---

## Documentation Standards

- **[README](README.md)** — Documentation guide and /make-* commands
- **[Design System](_references/DESIGN-SYSTEM.md)** — Visual design language reference
- **[Environment Variables](_references/ENVIRONMENT-VARIABLES.md)** — Central registry of all env vars
- **[CLAUDE.md](../CLAUDE.md)** — Project context (auto-loaded by Claude)
