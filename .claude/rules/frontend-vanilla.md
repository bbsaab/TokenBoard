# Frontend Rules (Jinja + Vanilla JS)

Applies to `templates/*.html`, `static/*.js`, `static/*.css`.

## No frameworks, no build step
- Plain Jinja templates rendered by Flask.
- Plain CSS in `static/style.css`. Custom properties (CSS variables) at the top, used throughout.
- Plain JavaScript in `static/dashboard.js`. ES2020+ is fine (modern browsers only).
- Do not introduce React / Vue / Alpine / htmx / webpack / vite without a proposal explaining why the no-build constraint must be relaxed.

## Size limits
- `templates/*.html`: < 300 lines. Extract Jinja includes/partials beyond that.
- `static/dashboard.js`: < 500 lines. Split into ES modules and import them via `<script type="module">` if it grows further.
- `static/style.css`: < 1000 lines. Split by section (header, cards, charts, …) with clear comment dividers.

## Style conventions
- Use existing CSS custom properties (`--bg-primary`, `--accent`, `--green`, etc.) — see [docs/_references/DESIGN-SYSTEM.md](../../docs/_references/DESIGN-SYSTEM.md).
- New colors only when adding a genuinely new semantic state; document the new token in DESIGN-SYSTEM.md when you add it.
- BEM-ish naming: `.card`, `.card-header`, `.card-body`, with status modifiers as `.card-green` etc.

## Data fetching
- The dashboard polls `/api/usage` every 60 seconds. Any new fetch joins the same polling cycle in `fetchUsage()` — do not introduce a parallel `setInterval`.
- Use `fetch()` with `await`. Handle errors by logging to the console and leaving the previous UI values rendered (no flicker, no modals).
- Show the connection state in `.calibration-status` (the existing slot).

## Time-zone handling
- Backend sends UTC ISO 8601 strings. Frontend converts to user-local via `new Date(iso).toLocaleString(...)` or `Intl.DateTimeFormat`.
- Never do TZ math in JavaScript with manual offsets — let the browser do it.

## Accessibility
- All interactive elements are `<button>` (not `<div onclick>`).
- Visible focus state required.
- Keep contrast within WCAG AA on the dark theme.

## When to refactor
- If `dashboard.js` is > 400 lines, plan a module split before adding more.
- If a card template has > 6 nested data fields, consider a sub-template.
