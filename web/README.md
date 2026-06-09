# comprev web UI

A clean, minimal web app over the `comprev` compliance engine: upload a
mutual-fund marketing video, run the engine, watch staged progress, and read the
verdict in the browser. The backend reuses the engine functions unchanged; no
engine code is modified.

```
web/
  api/comprev_web/   FastAPI backend (jobs, models, app)
  ui/                Next.js (App Router) + shadcn/ui frontend
```

## Run it (two terminals)

**1. Backend** — from the repo root:

```bash
uv pip install -e ".[web]"          # add ,visual,audio for real (non-stub) runs
export ANTHROPIC_API_KEY=sk-...     # required for real runs (not stub)
uv run uvicorn comprev_web.app:app --reload --port 8000 --app-dir web/api
```

**2. Frontend** — from `web/ui`:

```bash
pnpm install
pnpm dev                            # http://localhost:3000
```

The frontend proxies `/api/*` to `http://localhost:8000` (override with
`BACKEND_URL`), so the browser stays same-origin — no CORS setup needed.

## Notes

- **Stub mode** (toggle in the upload dialog) skips all ML + the Claude API and
  returns every check as `uncertain` in milliseconds — ideal for a no-deps smoke
  test. The UI auto-enables it when `/api/health` reports no API key or missing
  ML extras.
- Reports persist to the repo's `out/` directory, shared with the CLI — existing
  CLI runs show up in the list immediately, and web runs are visible to the CLI.
- The engine runs in a one-worker process pool (runs are serialized); a second
  upload waits in the `queued` stage.
- Uploads land in `uploads/<job-id>/` (gitignored). Re-uploading a filename that
  already has a report returns a conflict prompt: view the existing report or
  re-run with overwrite.

## Endpoints

`POST /api/jobs` · `GET /api/jobs/{id}` · `GET /api/jobs/{id}/events` (SSE) ·
`GET /api/reports` · `GET /api/reports/{video_id}` ·
`GET /api/reports/{video_id}/markdown` · `GET /api/checks` · `GET /api/health`
