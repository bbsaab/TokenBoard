# Docker & Deploy Rules

Applies to `Dockerfile`, `docker-compose.yml`, `requirements.txt`.

## Safety rules (never violate without explicit sign-off)
1. **`~/.claude` mount stays read-only.** `docker-compose.yml` mounts the user's Claude directory as `:ro`. Do not change this to `:rw` in passing — it is a security boundary. Any feature requiring RW (e.g., `claude` CLI shelled from inside the container, which rotates the OAuth refresh token) must be flagged in a proposal and approved.
2. **No credentials in the image.** Don't `COPY` `.credentials.json`, `.env`, or any token into the image. Credentials come from the runtime mount only.
3. **No secrets in `docker-compose.yml`.** Environment variables for tokens / API keys come from `.env` or the host environment, never literal values in the compose file.

## Process model
- Container runs **one** process (`python -m app.main` today). Single-user, single-process is a load-bearing assumption — daemon threads and in-memory state rely on it.
- If a future change introduces a production WSGI server (e.g., the Phase 0 gunicorn migration in [PROPOSAL-Proactive-Session-Refresh](../../docs/proposals/PROPOSAL-Proactive-Session-Refresh.md)), keep `--workers 1`. Multi-worker breaks the in-memory `_import_status` dict.

## Signal handling
- The CMD must be exec form (`["python", "-m", "app.main"]`), not shell form (`python -m app.main`). Exec form makes Python PID 1 and ensures SIGTERM reaches it.
- The process must install a SIGTERM handler (or use a server like gunicorn that does so by default). Today's Flask dev server does not — see Phase 0 of the active proposal for the fix plan.

## Image hygiene
- Stay on `python:3.11-slim`. Don't upgrade Python without a proposal — package compatibility (watchdog, requests) is tested on 3.11.
- Pin all top-level dependencies in `requirements.txt`. Don't add unpinned packages.
- If you add a system dependency in the Dockerfile, add a comment explaining why.
- The image is currently node-free. If a future phase needs Node + the `@anthropic-ai/claude-code` CLI, that's a multi-step change that requires touching `Dockerfile` + image-size baseline + the RW mount discussion above.

## Volumes
- `./data:/app/data` — SQLite database. Persists across container restarts.
- `${CLAUDE_DATA_DIR:-~/.claude}:/claude-data:ro` — user's Claude directory, **read-only**.
- Do not add new volumes silently. Any new mount is a deployment surface and gets called out in the proposal/architecture doc.

## Environment variables
- New env vars are documented in the README and added to `docker-compose.yml` with a sensible default.
- The `docs/_references/ENVIRONMENT-VARIABLES.md` file is the registry once it exists; `/make-architect` will create it on first env-var-adding feature.

## Verifying changes
After a Docker change, the deployment checklist is:
```
[ ] docker compose build completes without warnings
[ ] docker compose up -d starts cleanly
[ ] docker compose logs shows no exception traces in the first 10 seconds
[ ] curl http://localhost:8080/api/usage returns valid JSON
[ ] docker compose down completes in < 2 seconds (Phase 0 regression check)
```
