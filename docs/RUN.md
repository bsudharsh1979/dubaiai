# Running RainReady

## Prerequisites

* Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/) (lockfile: `api/uv.lock`; pip export: `api/requirements.lock.txt`)
* Node 22 and npm 10 (lockfile: `web/package-lock.json`)
* Optional: Docker (Compose stack with PostGIS), Modal CLI (hosted deployment)

No API keys, GPU or external network access are needed for the default demo.

## 1. Local development (two processes)

```powershell
cd rainready/api
copy ..\.env.example .env        # optional; defaults are the demo configuration
uv sync
uv run uvicorn rainready.main:app --port 8100 --reload
```

```powershell
cd rainready/web
npm ci
npm run dev                        # http://localhost:3100 (NEXT_PUBLIC_API_BASE=http://localhost:8100 from .env.development)
```

On first start the API runs Alembic migrations against `api/data/rainready.db`, seeds the synthetic Demo Sector 7
fixtures (including a synthetic Sentinel-1 before/after GeoTIFF pair) and starts the embedded worker.

## 2. Single process (API serves the exported UI)

```powershell
cd rainready/web && npm run build            # writes web/out
cd ../api
$env:STATIC_DIR = "..\web\out"
uv run uvicorn rainready.main:app --port 8100   # http://localhost:8100
```

## 3. Tests

```powershell
cd rainready/api && uv run pytest -q                       # 29 API/guardrail/tool tests (temporary SQLite DB)
cd rainready/web && npx playwright install chromium        # once
npx playwright test                                        # against http://127.0.0.1:8100 (set RR_BASE_URL to override)
```

## 4. Docker Compose (web, api, worker, PostGIS)

```bash
cd rainready
docker compose up --build          # web :3100, api :8100, db :5432
```

The API service runs migrations (adds PostGIS `geom` generated columns, GIST indexes and — when available —
pgvector); the worker service runs `python -m rainready.worker`. **This stack was not executed in the authoring
environment** (Docker unavailable); the SQLite path is what the automated tests exercise.

## 5. Modal (hosted demo)

```powershell
cd rainready/web && npm run build
modal secret create rainready SESSION_SECRET=<random 32+ chars>      # once
modal deploy rainready/deploy/modal_app.py
```

Single CPU container, SQLite on a Modal Volume (`rainready-uae-data`), `max_containers=1`, embedded worker,
`APP_ENV=hosted`, `COOKIE_SECURE=true`, `MODEL_PROVIDER=demo`, `ACTION_CONNECTORS=simulated`, `SOVEREIGN_MODE=true`.
Current deployment: https://gamgn--rainready-uae-server-web.us-east.modal.run

Competition gate (real inference through the allow-listed NVIDIA endpoint, separate throw-away DB, never touches
the public app):

```powershell
modal run rainready/deploy/modal_app.py::model_gate_check --list-only                 # served Nemotron ids
modal run rainready/deploy/modal_app.py::model_gate_check --model nvidia/nemotron-nano-3-30b-a3b
```

Requires the Modal secret `nvidia-api-key` to contain a valid `NVIDIA_API_KEY`. Results and status: `docs/MODEL_RUNS.md`.

## 6. Switching providers (never silent)

Set in `api/.env`:

```
MODEL_PROVIDER=local_nim
LLM_BASE_URL=http://nim-llm:8000/v1       # must match PROVIDER_ALLOWLIST
LLM_MODEL=<exact id from GET /v1/models>
```

The Assurance view shows `configured/healthy/exercised` per provider. If the endpoint is down, persona runs fail
visibly and the incident goes to urgent human review — fixtures are never relabelled as model output.

## 7. Resetting the demo

Assurance view → (demo mode only) `POST /api/demo/reset`, or delete `api/data/*.db`.
