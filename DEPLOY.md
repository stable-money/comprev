# Deploying comprev (whole app, one host)

comprev is **not** Vercel-deployable: the backend runs heavy ML (PaddleOCR,
faster-whisper), keeps a warm model pool + in-memory job state across requests,
writes reports to a persistent `out/` directory, and a single review can take
minutes. That needs a long-running container with a disk — not serverless.

This repo ships a `docker compose` stack that runs **both** services on any one
Docker host (a VM, Fly.io, Railway, Render, etc.).

```
frontend (Next.js :3000)  ──/api/*──►  backend (FastAPI + ML :8000)
                                          └─ writes → /app/out (volume)
```

## Run it on any Docker host

```bash
# 1. Provide the API key (read from .env, never baked into the image)
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 2. Build + start (first backend build is large & slow — pulls paddlepaddle)
docker compose up --build -d      # or: docker-compose up --build -d

# 3. Open the app
open http://localhost:3000
```

Data persists in named volumes: `reports` (the report store), `uploads`, and
`paddle` (cached OCR models so restarts don't re-download them).

## Notes / gotchas

- **Architecture:** build on the *target* arch. On Apple Silicon, build for an
  amd64 host with `docker build --platform linux/amd64 ...` (paddlepaddle has the
  widest wheel coverage on linux/amd64).
- **First request is slow:** PaddleOCR downloads ~200 MB of models into the
  `paddle` volume on the first real review, then stays warm.
- **Resources:** give the backend container ≥ 4 GB RAM (the server OCR model is
  memory-heavy). One review runs at a time (`max_workers=1`).
- **`BACKEND_URL`** is baked into the frontend's `/api` rewrite at build time and
  also read at runtime. Compose sets both to the internal service URL
  (`http://backend:8000`); change the build arg + env if you split hosts.

## Deploying to a managed platform

The Dockerfiles are platform-agnostic. On Fly.io / Railway / Render, create
**two services** from `Dockerfile.backend` and `web/ui/Dockerfile`, attach a
**persistent volume** to the backend at `/app/out`, set `ANTHROPIC_API_KEY` on the
backend, and point the frontend's `BACKEND_URL` at the backend's internal URL.
