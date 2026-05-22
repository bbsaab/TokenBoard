# Design System

**Last Updated:** 2026-05-18
**Purpose:** Visual design language, component patterns, and interaction conventions for TokenBoard's dashboard UI.

> Source of truth for visual decisions. Maintain manually as choices are made. The values below were extracted from the current implementation in [static/style.css](../../static/style.css) and [templates/index.html](../../templates/index.html).

---

## Visual Foundation

### Colors (CSS custom properties)

Defined at the top of [static/style.css](../../static/style.css):

| Token | Value | Usage |
|---|---|---|
| `--bg-primary` | `#1a1a2e` | Page background (dark navy) |
| `--bg-secondary` | `#16213e` | Card background |
| `--bg-card` | `#16213e` | Card background (alias) |
| `--accent` | `#e94560` | Brand accent — coral/red |
| `--accent-light` | `#ff6b8a` | Hover/highlight on accent |
| `--text-primary` | `#ffffff` | Primary text on dark bg |
| `--text-secondary` | `#a0a0a0` | Secondary text / labels |
| `--text-muted` | `#6c6c8a` | Muted text / placeholders |
| `--green` | `#00c853` | "On track" / healthy status |
| `--yellow` | `#ffc107` | "Moderate usage" / warning |
| `--red` | `#e94560` | "High usage" / danger (same as accent) |

**Theme:** Single dark theme. No light mode today.

### Status Semantic Mapping

| State | Color | Use |
|---|---|---|
| Healthy / on track | `--green` | < 60% of limit |
| Moderate / approaching | `--yellow` | 60–85% of limit |
| Danger / over | `--red` | > 85% of limit |

Applied via classes: `.status-green`, `.status-yellow`, `.status-red`; `.card-green`, `.card-yellow`, `.card-red`; `.progress-green`, etc. Same naming convention everywhere.

### Typography
- System font stack (sans-serif). No custom font loaded today.
- Headings: `h1` for the page title ("TokenBoard"), `h2` for card titles ("5-Hour Window", "Weekly").
- Numeric usage values use a larger weight for the "current" figure and a smaller, muted weight for the "/ limit" denominator (`.usage-current` / `.usage-limit`).

### Spacing & Layout
- `--border-radius: 12px` — applied uniformly to cards.
- `--shadow: 0 4px 20px rgba(0, 0, 0, 0.3)` — card elevation.
- Cards live in `.cards-section` with a 4px colored left border (`border-left: 4px solid var(--{color})`) indicating status. Status color also tints the progress bar fill.
- Container is centered (`.container`); single-column layout.

---

## Component Patterns

### Header Block (`<header>` in index.html)

1. `h1` page title
2. `.subtitle` — short tagline
3. `.status-indicator` with a colored `.status-dot` + `.status-text` (e.g., "On Track")
4. `.calibration-status` — secondary line for OAuth connection state

This is the canonical insertion point for new status indicators (e.g., the Phase 1 auto-refresh banner from the active proposal). Add new lines below `.calibration-status` rather than overloading existing elements.

### Usage Card (`.card`)

```
.card  (left border = status color)
├── .card-header
│   ├── h2  (card title)
│   └── .refresh-time  (small, muted)
└── .card-body
    ├── .usage-display
    │   ├── .usage-current  (large)
    │   └── .usage-limit    (small, muted)
    ├── .progress-bar > .progress-fill  (color = status)
    ├── .percent-row  (official %)
    ├── .reset-info  (label + value)
    └── .forecast-grid  (3-column: blank / This Session / Historical)
```

Reuse this structure for any new usage-style card.

### Progress Bar

- Background `rgba(255, 255, 255, 0.1)`.
- Fill width transitions over 0.5s ease.
- Fill color comes from `.progress-{green|yellow|red}` modifier.

---

## Interaction Conventions

### Loading States
- Numeric placeholders: `--` for unknown values.
- Status text default: "Loading…" then transitions to "On Track" / "Moderate" / "High Usage".
- Calibration status starts as "Connecting…" then resolves to the OAuth status.

### Auto-refresh of UI
- Dashboard polls `/api/usage` every 60 seconds via [static/dashboard.js](../../static/dashboard.js).
- New UI status (e.g., window-state banner) should hook into the same polling cycle, not introduce a parallel `setInterval`.

### Error States
- Today: console errors only; no visible error banner.
- Convention going forward: if a fetch fails, the existing values stay rendered (no flicker), and the calibration status line shows a short error string. Do not block the dashboard or show modals.

### Responsive Behavior
- Single-column at all viewport widths today. No formal breakpoints.
- New components should remain readable at ≥ 360px wide.

---

## Accessibility Standards
- Target WCAG AA contrast on the dark theme. The current color tokens have not been formally audited — flag this if any new color is introduced.
- All actionable elements must be keyboard-reachable. Today the dashboard is read-only with no interactive controls; the Phase 1 banner from the proposal will be the first true control and should be a proper `<button>` with visible focus.

---

## Conventions for New UI

1. **Use existing CSS custom properties.** Don't introduce new hex codes unless adding a genuinely new semantic state — and if you do, add it to this doc.
2. **Match the status-color trio (green/yellow/red) for any thresholded indicator** — don't invent new color mappings.
3. **No build step.** All CSS stays in `static/style.css`. All JS stays in `static/dashboard.js` or a small set of additional ES modules.
4. **No frameworks.** Resist the urge to introduce React/Vue/Alpine. Vanilla JS + Jinja is sufficient for the dashboard's complexity.
