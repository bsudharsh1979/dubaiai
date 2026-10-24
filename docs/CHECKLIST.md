# RainReady UAE — build checklist and assumptions

Status legend: `[x]` done and verified locally · `[~]` implemented, partially verified · `[ ]` not started · `[!]` blocked (external data / GPU / authorization)

## Repository assumptions (stage 1)

- The workspace `buildflow-ai` already contains an unrelated product (BuildFlow AI: `backend/`, `frontend/`). It is preserved untouched. RainReady lives entirely under `rainready/`.
- Toolchain found: Python 3.13.5 + uv 0.10, Node 22.17, npm 10.9, Modal CLI 1.5.2 (profile authenticated). Docker is **not** installed on this machine, so Compose/PostGIS is provided and documented but was not executed here; the local/no-key path runs on SQLite with the same ORM, migrations and tools. See `docs/RUN.md`.
- Geometry is stored as GeoJSON + bbox columns (works on SQLite and PostgreSQL). On PostgreSQL the migration also enables PostGIS and adds an indexed `geom` column populated from the GeoJSON. Spatial analytics run in Python (shapely/pyproj/rasterio) as versioned tools.
- All data is synthetic (`DATA_MODE=synthetic`), inference is deterministic (`MODEL_PROVIDER=demo`) and every connector is simulated unless configured otherwise. Nothing here implies agency endorsement or an existing integration.

## Stage 2 — database, deterministic tools, rainfall workflow
- [x] Settings with independent `DATA_MODE` / `MODEL_PROVIDER` / connector mode
- [x] ORM + Alembic migration (incidents, evidence, agent runs, tool results, model versions, policy decisions, proposals, approvals, work orders, dispatch receipts, audit events, field reports, scenarios, imports, assets, sensors, documents)
- [x] Provenance envelope on every record (source_id, observed/acquisition_at, available_at, received_at, CRS, units, resolution, quality flags, provenance URI, checksum, license, simulation status)
- [x] Hazard tools: rainfall/runoff water balance twin, waterlogging scenarios, SAR change screening, pressure/flow residuals, asset exposure, constrained routing
- [x] Rainfall incident created end to end through the graph (ingest → … → human review)

## Stage 3 — durable coordination, approvals, receipts
- [x] LangGraph graph with checkpointer (SQLite / Postgres) and `interrupt()` at human review
- [x] Eight personas with tool allowlists, limits and observable status
- [x] Evidence requests, bounded replanning (2 loops), urgent-human-review escalation
- [x] Approval gateway bound to incident id, proposal version, payload hash, tool, recipients, approver identity/role, expiry
- [x] Idempotency keys, optimistic concurrency, duplicate suppression, retry budget, escalation timers
- [x] Simulated action connectors with acknowledgement/completion distinct from physical state change

## Stage 4 — UI
- [x] Command, Digital twin, Agents & evidence, Incident & approvals, Field report, Assurance
- [x] MapLibre with local GeoJSON basemap (no external tiles), English/Arabic RTL
- [x] Leak / HSE branches and failure scenarios (stale evidence, malicious instruction)

## Stage 5 — providers, RAG, guards, raster import
- [x] Provider interfaces (text planning, embeddings, guard, visual, EO encoder) with demo / local_nim / approved_hosted adapters
- [x] Lexical retrieval with authorization filters; pgvector/sqlite-vec optional and labelled
- [x] Deterministic safety gate + optional NemoGuard / content-safety adapters
- [x] Sentinel-1 before/after GeoTIFF import with CRS/overlap/alignment/units/nodata validation

## Stage 6 — verification and demo
- [x] Automated checks: 27 pytest (API, guardrails, tools) — see `docs/TEST_RESULTS.md`
- [x] Browser smoke test: 3 Playwright tests (principal demo end-to-end, malicious report isolation, Arabic RTL), passing locally and against the hosted URL
- [x] Modal deployment (`deploy/modal_app.py`) — https://gamgn--rainready-uae-server-web.us-east.modal.run ; SQLite on a Volume, single container, embedded worker, hosted env flags
- [x] Deliverables: `.env.example`, Dockerfiles, `docker-compose.yml`, pinned lockfiles (`uv.lock`, `requirements.lock.txt`, `package-lock.json`), README, ARCHITECTURE, RUN, MODEL_CARDS, THREAT_MODEL, DATA_ACCESS, TEST_RESULTS, DEMO_SCRIPT, NARRATIVE, MODEL_RUNS
- [!] Competition gate — **not passed**: served-model discovery OK, chat completions **401 Unauthorized** with the stored `nvidia-api-key`; no persona has been executed by a real model. Path is implemented and reports its status truthfully. See `docs/MODEL_RUNS.md`
- [!] Docker Compose / PostGIS stack written but **not executed** (Docker unavailable here)
- [!] Guard-model, embedding, vision and EO-encoder adapters implemented but **not exercised** (no endpoints)
- [!] Every predictive metric: **not evaluated** (no labelled UAE flood/leak/forecast data)

## Definition of done — status
- [x] Fresh checkout runs the no-key demo (`docs/RUN.md` §1–2)
- [x] Scenario changes alter outcomes (A vs B vs B2 vs C vs D; twin controls) — tested
- [x] Approvals survive restart; prohibited actions blocked — tested
- [~] Real local-model path implemented; truthfully reports **not exercised** (hosted attempt failed with 401; no local NIM available)
