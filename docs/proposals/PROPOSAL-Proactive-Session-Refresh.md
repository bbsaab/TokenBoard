# PROPOSAL: Proactive Session Refresh

**Document Owner:** TokenBoard
**Version:** 1.0
**Date:** May 18, 2026
**Status:** Approved

---

## Overview

Claude Code's 5-hour usage windows are activity-triggered: the clock starts on your first message and does **not** auto-roll once the window ends. If you walk away from the keyboard mid-window and return after the window has expired, your next prompt starts a brand-new 5-hour window from t=0 — there is no way to "carry forward" the unused time. This means the user is structurally penalized for inactivity: they pay (in wall-clock time) for an expired window they didn't fully use, and the next window they enter has its full 5 hours of burndown ahead of it, regardless of when they actually started working.

This proposal explores having TokenBoard monitor session state and, when it detects the user is inactive but eligible to start a fresh window (prior window has ended, no current Claude Code activity), proactively trigger a minimal Claude Code interaction so the new 5-hour clock begins ticking *before* the user sits down — letting them return to a window that is already partway through its 5 hours and a full token bucket they can spend on real work.

**Scope of this proposal:** confirm the underlying session-window behavior, evaluate mechanisms to trigger a refresh, identify integration points in TokenBoard's existing architecture, and surface a billing-policy change scheduled for June 15, 2026 that materially affects whether this feature works as intended. A go/no-go decision and a recommended path are included. Detailed architecture (file-by-file design, migrations, tests) is deferred to `/make:architect`.

---

## Table of Contents

- [Problem Statement](#problem-statement)
- [Research Findings](#research-findings)
  - [Current State: How TokenBoard already sees session windows](#current-state-how-tokenboard-already-sees-session-windows)
  - [Claude Code session mechanics (confirmed)](#claude-code-session-mechanics-confirmed)
  - [Mechanism comparison: how to trigger a refresh](#mechanism-comparison-how-to-trigger-a-refresh)
  - [The June 15, 2026 billing split (critical)](#the-june-15-2026-billing-split-critical)
  - [Terms-of-service framing](#terms-of-service-framing)
- [Recommendation](#recommendation)
- [Proposed Solution](#proposed-solution)
  - [Phase 0 (prerequisite): Fix SIGTERM handling](#phase-0-prerequisite-fix-sigterm-handling)
  - [Phase 1: Window-state intelligence + notification refresh](#phase-1-window-state-intelligence--notification-refresh)
  - [Phase 2 (optional, gated): Opt-in headless auto-ping](#phase-2-optional-gated-opt-in-headless-auto-ping)
- [Implementation Phases](#implementation-phases)
- [Risks & Mitigations](#risks--mitigations)
- [Open Questions](#open-questions)
- [Related Documents](#related-documents)
- [Document History](#document-history)

---

## Problem Statement

The user's day-to-day pattern looks like this:

1. Open Claude Code at 9:47 AM and start working. The 5-hour window opens at 09:47, expires at 14:47.
2. Wrap up around 1 PM. The window has ~1h 47m remaining when you stop.
3. Walk away. At 14:47 the window quietly expires.
4. Return at, say, 4 PM and send a new message. A fresh 5-hour window opens at 16:00 and expires at 21:00.
5. You now have the entire 5-hour quota ahead of you — but you also have only a few productive hours left in your day to use it. The "burn rate" math is unforgiving: a fresh window in late afternoon is functionally smaller than a fresh window at 9 AM.

The asymmetry: **inactivity wastes a window when you stop early, but does not earn you credit when you stop early.** A window started at 9 AM but only used for four hours is "wasted" relative to a window started at 11 AM that you could have fully used through the workday. The user wants TokenBoard to flatten this asymmetry by automatically opening windows during idle stretches, so that when they return to the keyboard the new window is *already running* — they enter with an unused token bucket and a partially-elapsed clock, which is the inverse of the "starting a fresh window late in the day" failure mode.

---

## Research Findings

### Current State: How TokenBoard already sees session windows

TokenBoard does not have to *infer* the current 5-hour window from JSONL timestamps. It already pulls the authoritative server-side reset time directly from Anthropic via the OAuth usage endpoint at [app/usage_api.py:fetch_oauth_usage()](../../app/usage_api.py#L49), and uses `five_hour.resets_at` to compute the window start at [app/main.py:87-95](../../app/main.py#L87):

```python
reset_time = datetime.fromisoformat(five_hour_resets.replace("Z", "+00:00"))
window_start = reset_time - timedelta(hours=5)
five_hour_since = window_start.isoformat()
```

This means TokenBoard already knows, at any moment, **(a)** when the current window expires, **(b)** how much of it has been consumed, and **(c)** when (per the JSONL files) the user's most recent activity was. This is a strong foundation: the detection half of the feature is essentially free — we already have the data.

TokenBoard's existing background architecture also lends itself to a third daemon thread without ceremony. Two threads exist today in [app/main.py:417-463](../../app/main.py#L417):

- A watchdog-based file watcher monitoring `~/.claude/projects/`.
- A 5-minute periodic re-importer.

Both follow the simple `threading.Thread(target=fn, daemon=True)` pattern with `while True: time.sleep(N)`. A new "auto-refresh" loop slots in at [app/main.py:466](../../app/main.py#L466) in `init_app()`. No scheduler library is needed.

### Claude Code session mechanics (confirmed)

The user's hypothesis is confirmed in all material respects:

| Question | Finding |
|---|---|
| What starts a window? | The first request to Anthropic — exact minute of the first message, UTC. Local-only CLI commands (`--version`, opening the REPL without sending) do not. |
| Do windows auto-roll? | **No.** If the window expires while you are inactive, no new window opens until you next interact. The next message starts a new window at *that* moment. |
| Do unused windows cost weekly quota? | No. Weekly quotas are consumption-based, not session-slot-based. A window that never opens consumes nothing. |
| Where is window state recorded on disk? | Not directly. JSONL files contain per-message records (no `windowStart` field). The authoritative readout is the `/usage` slash command (interactive) or the OAuth usage endpoint TokenBoard already calls. |

Sources: [Anthropic Help Center — Use Claude Code with Pro/Max](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan), [Usage limit best practices](https://support.claude.com/en/articles/9797557-usage-limit-best-practices), [ccusage blocks reports](https://ccusage.com/guide/blocks-reports), [GitHub issue #11917 — Expose Usage Metrics in Session JSON (closed not-planned)](https://github.com/anthropics/claude-code/issues/11917).

### Mechanism comparison: how to trigger a refresh

| Option | Uses Max 5h quota | Officially supported | Works in Docker | Tokens/refresh | Complexity |
|---|---|---|---|---|---|
| **A. Subprocess `claude -p "hi"`** | Pre-6/15: yes. **Post-6/15: no — see below.** | Yes (documented [headless mode](https://code.claude.com/docs/en/headless)) | Needs Node + CLI install in image; needs RW mount of `~/.claude` | ~1–3k in / <50 out (Claude Code system prompt overhead) | 1-line `subprocess.run()` |
| **B. Direct Messages API with OAuth token from `~/.claude/.credentials.json`** | **Rejected** — Anthropic blocks `sk-ant-oat01-*` at the API with "OAuth authentication is currently not supported." Issue [#37205](https://github.com/anthropics/claude-code/issues/37205) closed as not planned. | No | Yes | n/a | Medium |
| **C. Claude Agent SDK (Python)** | Same as A — SDK wraps the CLI under the hood. | Yes | Same Node/credential mount requirements as A. | Same as A. | Higher than A for zero gain. |
| **D. Driving an *interactive* terminal `claude` via `tmux`/`expect`** | Yes (interactive pool, even post-6/15) | No (undocumented) | Hard inside Docker | Same as A. | High, fragile. |
| **E. Don't auto-fire — surface a "Click to refresh now" UI prompt that the user (or a single click) acts on.** | Yes (interactive) | Yes (it's just normal usage) | N/A — UI only | 0 from TokenBoard itself | Low |

**Option B is eliminated** (it doesn't work). Direct API calls using the OAuth token are blocked by Anthropic; this is a dead end. Source: [issue #28091](https://github.com/anthropics/claude-code/issues/28091).

### The June 15, 2026 billing split (critical)

Per Anthropic's [June 15, 2026 announcement](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) (28 days from today, 2026-05-18), Max subscribers will get **two separate quota pools**:

1. **Interactive 5-hour pool** — terminal/IDE Claude Code, claude.ai. Behaves exactly as it does today.
2. **Agent SDK credit pool** — `claude -p`, the Claude Agent SDK, Claude Code GitHub Actions. Pre-loaded with a fixed credit allowance (\~$100 for Max 5x) and billed at **full API rates**, not against the 5-hour Max quota.

The crucial consequence for this proposal: **after June 15, a `claude -p "hi"` ping fired by TokenBoard will draw against the Agent SDK credit pool — it will NOT open or extend the user's interactive 5-hour window.** A timer-based auto-refresh built on Option A would still cost the user real dollars, but would no longer *do the thing it was designed to do* (pre-open the interactive window).

This finding inverts the original feature design. If we ship Option A as scoped, it works for ~4 weeks and then silently stops doing what it claims. (It would keep firing and keep costing money — which is worse than not shipping.)

The only options that consume the interactive pool post-6/15 are: **(D)** drive a real interactive Claude terminal (fragile, undocumented, against the spirit of the new policy), or **(E)** put a human (or a one-click action by the human) in the loop.

Sources: [Anthropic — Use Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), [The Decoder — Claude subscriptions get separate budgets for programmatic use](https://the-decoder.com/claude-subscriptions-get-separate-budgets-for-programmatic-use-billed-at-full-api-prices/), [Claude Code headless docs](https://code.claude.com/docs/en/headless).

### Terms-of-service framing

[Anthropic Consumer Terms § 3.7](https://www.anthropic.com/legal/consumer-terms) prohibits accessing the services "through automated or non-human means, whether through a bot, script, or otherwise" **except when accessing via an Anthropic API Key or where we otherwise explicitly permit it.** Claude Code Pro/Max is OAuth-authenticated, not API-key-authenticated. A cron-style script that fires `claude -p` on a schedule is, by the strict letter of § 3.7, prohibited — even though it's tolerated in community practice today, and even though the new Agent SDK pool partially formalizes a way to do this (at API prices).

No known enforcement actions have specifically targeted self-warmup scripts. The late-2025 enforcement wave was against *third-party harnesses* spoofing the Claude Code identity — not individual users running the official CLI on a schedule. Risk is best characterized as: **low likelihood, real-but-unspecified consequence, and inverts the user's intent** (the goal is to *use* the subscription more effectively, not to look like an abuser).

---

## Recommendation

**Ship Phase 1 (notification-driven refresh + window-state intelligence) and explicitly defer Phase 2 (automated headless ping) pending the June 15, 2026 billing split.**

The June 15 change makes a "fire-and-forget" auto-ping ineffective for its intended purpose: it won't open the interactive 5-hour window after that date. Building Phase 2 as scoped today would mean shipping a feature that breaks within weeks of merge. The honest design — and the one that respects both the ToS and the user's actual goal — is to keep the human in the loop:

- TokenBoard becomes the **early-warning system**: "Your previous window ended 23 minutes ago. Click to start a fresh one before you get pulled into something else."
- The refresh itself is performed by the user (one click → open Claude Code; or a one-liner the user runs by hand), which **(a)** unambiguously consumes the interactive pool, **(b)** does not violate § 3.7, and **(c)** continues to work after June 15.

Phase 2 (automated ping) is preserved as a documented future option, with a clear cost warning, in case the user accepts the post-June-15 dollar cost in exchange for full automation. It should not ship in the same release as Phase 1.

---

## Proposed Solution

### Phase 0 (prerequisite): Fix SIGTERM handling

Before adding a third background thread, fix a known issue: TokenBoard's container does not shut down cleanly on `docker stop` / `docker compose down`. Docker waits the full 10-second grace period and then `SIGKILL`s the process. The root cause is in the existing code, not in Docker:

- The Dockerfile entrypoint at [Dockerfile:29](../../Dockerfile#L29) is `CMD ["python", "-m", "app.main"]`. Exec-form CMD is correct — Python is PID 1 and *does* receive SIGTERM.
- But [app/main.py:502](../../app/main.py#L502) and [run.py:22-27](../../run.py#L22) both call `app.run(...)`, which is Flask's dev server (werkzeug). The dev server installs a SIGINT handler (so Ctrl+C works locally) but does **not** install a SIGTERM handler. SIGTERM is silently ignored.
- The two existing background threads ([app/main.py:417-463](../../app/main.py#L417)) are `daemon=True`, so they would die *if* the main thread exited — but the main thread is stuck inside werkzeug's `serve_forever()` and there is no signal-driven path out.
- The periodic-import loop's `while True: time.sleep(300)` at [app/main.py:442-463](../../app/main.py#L442) is benign here (daemon threads receive the EINTR on signals, and would unwind once the main thread exits), but worth bracketing in a `try`/`except` for cleanliness once a signal handler is in place.

There are three ways to fix this; **(A) is recommended:**

**(A) Swap the dev server for a production WSGI server.** Add `gunicorn` to [requirements.txt](../../requirements.txt) and change the Dockerfile CMD to:

```dockerfile
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", \
     "--graceful-timeout", "10", "app.main:app"]
```

Gunicorn handles SIGTERM correctly by default (graceful drain → exit) and is the standard production runner for Flask. `--workers 1` preserves the single-process assumption that today's daemon threads + in-memory `_import_status` rely on. `run.py` (local dev path) can keep using `app.run()` — Ctrl+C already works there.

**(B) Install an explicit signal handler in `app/main.py`** if you want to keep the dev server for both local and container runs:

```python
import signal, sys
def _shutdown(_sig, _frame):
    sys.exit(0)
signal.signal(signal.SIGTERM, _shutdown)
```

This is a one-line fix but leaves the dev server in production (not recommended long-term).

**(C) Set `STOPSIGNAL SIGINT` in the Dockerfile** so Docker sends the signal werkzeug already handles. This is a workaround, not a fix — it doesn't help anyone running TokenBoard outside Docker under a process supervisor that sends SIGTERM (systemd, k8s, etc.).

Pick (A). It's a four-line diff (one line in `requirements.txt`, one in `Dockerfile`, and the existing `app.run()` block stays for local `python run.py` development) and it makes the container actually obey `docker stop`.

This is independent of the rest of the proposal — it's worth doing on its own — but it becomes more important once a *third* background thread (the auto-refresh daemon) is added, because a misbehaving shutdown of a thread that's about to fire a `claude -p` ping (in Phase 2) could cause duplicated or hung pings.

### Phase 1: Window-state intelligence + notification refresh

What changes:

- **Backend.** Add a third daemon thread in [app/main.py:init_app()](../../app/main.py#L466) that runs every \~5 minutes. Each tick:
  1. Re-fetch (or read cached) OAuth window state via the existing [app/usage_api.py](../../app/usage_api.py) plumbing.
  2. Compute `window_state`: one of `active` / `expired_idle` / `no_window`.
  3. Compute `time_since_last_activity` from the most recent JSONL record across all projects.
  4. If `window_state == expired_idle` and user has been idle for more than a configurable threshold, set a flag the frontend can read.
- **New endpoint.** `GET /api/window-state` returns:
  ```json
  {
    "state": "expired_idle | active | no_window",
    "expired_at": "2026-05-18T19:47:00Z",
    "minutes_since_expiry": 23,
    "minutes_since_last_activity": 187,
    "refresh_recommended": true
  }
  ```
- **Frontend.** Add a status block near the existing calibration indicator in [templates/index.html:15-19](../../templates/index.html#L15). When `refresh_recommended` is true, show a banner: *"Window expired 23m ago. Open Claude Code now to start a fresh 5-hour clock."* with a copyable one-line command (`claude` or a shell-link, depending on platform).
- **Optional desktop notification.** On platforms that support it, fire a system notification when the state first transitions to `expired_idle` (with debounce — once per expiry event). This is the part that turns TokenBoard into a true "proactive" tool: even when the dashboard is in a background tab, the user gets a nudge.
- **Quiet hours.** A `REFRESH_NOTIFICATIONS_QUIET_HOURS` env var (default `22-07`) suppresses notifications overnight.

What this gets the user:

- They never miss the moment the prior window ended.
- The refresh action stays human-initiated, so it consumes the interactive pool both pre- and post-June-15.
- Zero ToS risk.
- Zero new dependencies (no Node, no CLI in container, no RW credential mount).

### Phase 2 (optional, gated): Opt-in headless auto-ping

Defer until the post-June-15 economics are understood. If shipped, gate behind a config flag `AUTO_REFRESH_ENABLED=true` (default false) and show a one-time confirmation dialog explaining:

- Before June 15, 2026: ping draws from your interactive 5-hour pool and will open a window.
- After June 15, 2026: ping draws from your Agent SDK credit pool at full API rates. Each ping costs \~$0.01–0.05 of Agent SDK credit and **does not open or extend your interactive 5-hour window** — i.e., the original goal of this feature is no longer achievable via this path.

If the user enables it anyway, the implementation is straightforward: `subprocess.run(["claude", "-p", "hi", "--output-format", "json"], timeout=60, capture_output=True)` from the new daemon thread, with results logged to a new `auto_refresh_log` table (created in [app/db.py:init_db()](../../app/db.py#L21)). Docker deployment requires updating the Dockerfile to install Node + `@anthropic-ai/claude-code` and changing the `~/.claude` mount from `:ro` to `:rw` (so the CLI can rotate its refresh token). Both are non-trivial changes.

#### Data Model Changes (Phase 1)

No schema changes for Phase 1 — the existing OAuth fetch and JSONL parsing are sufficient.

For Phase 2 only:

| Table: `auto_refresh_log` | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `fired_at` | TEXT (ISO 8601) | When the ping went out |
| `window_state_at_fire` | TEXT | `expired_idle` etc. |
| `minutes_since_expiry` | INTEGER | Audit |
| `status` | TEXT | `success` / `failed` / `skipped` |
| `cost_usd` | REAL | From `--output-format json` |

#### API Changes

Phase 1: one new endpoint, `GET /api/window-state` (above). Existing `/api/usage` is unchanged.
Phase 2: one new endpoint, `GET /api/auto-refresh-log?limit=20` for the audit view.

#### UX Changes

A small status block in the dashboard header showing window state, with a contextual banner when refresh is recommended. No mockups produced with this proposal; the visual treatment can follow `/make:architect` or be wireframed alongside that step if desired.

---

## Implementation Phases

| Phase | Scope | Estimated Effort | Risk Level |
|---|---|---|---|
| **Phase 0** | Swap dev server for gunicorn so SIGTERM is handled. Four-line diff (requirements.txt, Dockerfile, no app code changes). Prerequisite for safely adding a third daemon thread. | 30 min | Low |
| **Phase 1** | Daemon thread, `/api/window-state` endpoint, frontend banner, optional desktop notifications, quiet hours, no schema changes. | 1–2 days | Low |
| **Phase 1.5** | Decide whether to ship Phase 2 after the June 15, 2026 split lands and the cost-per-ping is measured. | 0 (decision point) | n/a |
| **Phase 2 (gated)** | Opt-in headless `claude -p` ping, `auto_refresh_log` table, Dockerfile changes (Node + CLI), `~/.claude` RW mount, cost-warning UX. | 2–3 days | Medium (Docker changes + post-6/15 economics) |

---

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| June 15, 2026 billing split eliminates Phase 2's effectiveness while keeping its cost | Phase 2 silently stops achieving its purpose | **Certain** (announced) | Defer Phase 2 until measured; document the post-6/15 cost explicitly in the opt-in dialog. |
| Headless `claude -p` ping is "automated means" under Consumer Terms § 3.7 | Possible account flag | Low (no known enforcement of self-pings; Anthropic targets third-party harnesses) | Gate behind explicit user opt-in; default off; document the policy text in-app. |
| Anthropic's OAuth endpoint format changes and TokenBoard misreads window state | Banner shows wrong info | Low | TokenBoard already depends on this endpoint for usage display; failure mode is no worse than today. |
| Notification spam if the daemon misreads activity and fires repeatedly | User annoyance | Medium | Debounce: one notification per `(expiry_timestamp, user_acknowledged)` pair; quiet hours; user can disable in env. |
| Docker image growth from adding Node + CLI (Phase 2 only) | Larger image, slower CI | Medium | Use a multi-stage build; or skip if Phase 2 is never shipped. |
| Phase 2 ping accidentally fires during the *current* window (extending its end-time?) | Wasted ping; possible quota dent | Medium | Pre-check `window_state == expired_idle` (not `active`); also pre-check `time_since_last_activity > N`. |
| ~~Token-cost of the ping is unknown~~ | Phase 2 only | Medium | First Phase 2 run uses `--output-format json` to measure `total_cost_usd`; surface real measured value in the UI. |

---

## Open Questions

- **Does activity by another concurrent Claude Code session (e.g., a second machine) start the window too?** Probably yes — the OAuth account is the unit, not the device. If the user has Claude Code running on a laptop and a desktop, TokenBoard on one host may misread the other's activity as "user is idle." Worth confirming during `/make:architect`.
- **Is there a way to query the Anthropic backend for "current window state" without spending a ping?** TokenBoard's existing `/api/oauth/usage` call already does this (free of quota). Phase 1 doesn't need to fire any ping; Phase 2 does. Confirm the OAuth endpoint isn't rate-limited in a way that punishes frequent polling.
- **Should the Phase 1 notification be configurable per "expected work hours"?** E.g., only nudge between 8 AM and 6 PM local. Quiet hours covers part of this; richer scheduling could be a follow-up.
- **For Phase 2: what model does `claude -p` actually invoke?** The user's default; this affects cost-per-ping. `claude -p "hi" --model haiku` might be cheaper if Haiku is allowed in the user's plan after 6/15.
- **Could a *real* interactive `tmux`/`expect`-driven `claude` survive post-6/15 to keep the interactive pool refresh working?** Possibly. Investigated briefly (Option D). Not recommended — fragile, against the spirit of the policy, and the human-in-the-loop model is strictly better.
- **What's the right "idle" threshold?** Probably at least 30 minutes since last JSONL write, to avoid double-firing while the user is mid-task. Configurable.

---

## Related Documents

- TokenBoard `README.md` — current behavior of the app
- Anthropic [Use Claude Code with Pro/Max](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan)
- Anthropic [Use the Claude Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) — the June 15, 2026 billing split
- Anthropic [Claude Code headless mode](https://code.claude.com/docs/en/headless)
- Anthropic [Consumer Terms § 3.7](https://www.anthropic.com/legal/consumer-terms)
- [ccusage — blocks/window inference reference implementation](https://ccusage.com/guide/blocks-reports)
- [GitHub issue #37205 — OAuth tokens for Messages API (closed, not planned)](https://github.com/anthropics/claude-code/issues/37205)

---

## Document History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-18 | TokenBoard / Claude | Initial proposal, with the June 15, 2026 billing-split caveat flagged as Phase 2 blocker. |
| 1.1 | 2026-05-18 | TokenBoard / Claude | Added Phase 0 (SIGTERM/dev-server fix) as a prerequisite cleanup before introducing a third daemon thread. |
