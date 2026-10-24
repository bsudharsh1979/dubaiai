# RainReady UAE — Sovereign Water & HSE Command (prototype)

A government decision-support **prototype** that combines satellite observations, forecasts, ground sensors,
utility telemetry and field reports to detect water anomalies, assess flood risk and coordinate a
**human-approved** response. All data is synthetic, every connector is simulated, and the system does not
imply endorsement by, or an existing integration with, any UAE authority.

> Hosted demo (no keys, synthetic data, demo provider): **https://gamgn--rainready-uae-server-web.us-east.modal.run**
> Sign in with any demo identity; the server assigns the role.

![RainReady UAE — what the agentic system does](docs/infographics/agentic-flow.svg)

## Key features at a glance

![Key features](docs/infographics/key-features.svg)

Executive summary: [`docs/EXECUTIVE_SUMMARY.md`](docs/EXECUTIVE_SUMMARY.md) (in-app: the first page opens with it as a flow-of-events illustration with a live marker for the selected incident; long form at `/how-it-works`; neither needs a sign-in) · Guardrail layers: [`docs/infographics/guardrails.svg`](docs/infographics/guardrails.svg) · Practices adapted from international emergency-management processes: [`docs/BEST_PRACTICES.md`](docs/BEST_PRACTICES.md)

### Process refinements adapted from international practice

| Practice | In RainReady |
|---|---|
| Common Alerting Protocol (CAP 1.2) fields | Advisory drafts carry urgency / severity / certainty / response type; certainty is mapped from evidence completeness, never a probability; hash-bound with the proposal |
| Three-tier public warning level | Advice · Watch and Act · Emergency Warning, derived from the hazard band |
| Flood-risk matrix (likelihood × impact) | Incident header shows the current cell on a 4×4 ordinal matrix |
| Incident briefing / SITREP (ICS-201 pattern) | One-click situation report from persisted state; copy as text for handover |
| Joint Decision Model | Workflow graph order: validate → assess → policy → plan → human review → execute → review |
| After-action review | Optional structured AAR stored at closure, included in the SITREP |
| Stand-down discipline | Closing an incident stands down open work orders (audited) |

## What runs now vs. what is simulated vs. what needs external access

| Area | State |
|---|---|
| Rainfall → assessment → proposal → approval → simulated dispatch → acknowledgement → completion → reassessment → human-confirmed closure | **Runs end-to-end** (API tests + browser smoke test, local and hosted) |
| Leak (residual method, competing explanations, planned-flushing branch) and HSE escalation | **Runs** as small extensions |
| Live twin controls (rain, blockage, pump availability, mobile pump, sensor outage, report reliability) | **Runs**; recomputed by the backend tool; baseline vs intervention |
| Eight personas (Observer … Incident Coordinator) with typed outputs, tool allowlists, limits | **Runs** on the deterministic *demo* provider (labelled "rehearsal — no inference") |
| Real model inference (`local_nim` / `approved_hosted`) with validated structured outputs | **Implemented**; exercised attempt documented in `docs/MODEL_RUNS.md` — **not passed** (hosted key rejected with 401; no self-hosted NIM available) |
| Sentinel-1 before/after import with CRS/overlap/alignment/units/nodata/orbit validation and change mask | **Runs** on synthetic GeoTIFF fixtures; licensed data instructions in `docs/DATA_ACCESS.md` |
| Dispatch, advisories, access control, utility/HSE work | **Simulated receipts only** — no valve/power/evacuation endpoint exists |
| NCM forecasts, utility SCADA, agency systems | **Requires authorized access** (shown as such; no endpoints invented) |
| Guard model adapters (Content Safety, JailbreakDetect), embeddings, vision, EO encoder | **Interfaces implemented, not exercised**; deterministic gate and lexical retrieval always on and labelled |
| PostgreSQL/PostGIS via Compose | **Migration written**, not executed here (Docker unavailable); SQLite path is tested |

See `docs/CHECKLIST.md` for the itemised, truthful status and `docs/TEST_RESULTS.md` for what was run.

## Quick start (fresh checkout, no keys, no GPU)

```powershell
# API (Python 3.12+/3.13, uv)
cd rainready/api
uv sync
uv run uvicorn rainready.main:app --port 8100          # migrates + seeds SQLite on first start

# Web (Node 22)
cd ../web
npm ci
npm run dev                                             # http://localhost:3100 → API at :8100
```

Or serve the exported UI from the API (what Modal does):

```powershell
cd rainready/web && npm run build
cd ../api; $env:STATIC_DIR="../web/out"; uv run uvicorn rainready.main:app --port 8100   # http://localhost:8100
```

Tests: `cd rainready/api && uv run pytest` (29 tests) · `cd rainready/web && npx playwright test` (4 browser smoke tests against a running server).
Full run instructions, Compose and Modal: `docs/RUN.md`.

## Repository layout

```
rainready/
  api/            FastAPI + Pydantic + SQLAlchemy/Alembic + LangGraph; hazard tools; personas; policy; gateway; audit
    rainready/agents      graph.py (workflow w/ approval interrupt), personas.py, runner.py
    rainready/tools       hydrology.py, sar.py, leak.py, exposure.py, routing.py, registry.py (allowlisted tool calls)
    rainready/providers   demo / OpenAI-compatible planner (NIM/hosted), guards, embeddings, vision, EO stub
    rainready/knowledge   demo SOP collection + authorization-filtered retrieval with citations
    rainready/seed        synthetic Demo Sector 7 fixtures + synthetic SAR pair
    rainready/evaluation  harness (IoU/P/R, leakage, partitions, agent ops) — reports "not evaluated" without labels
    tests/                 guardrail, branch, tool and end-to-end API tests
  web/            Next.js 16 / React 19 / Tailwind 4 / MapLibre (local GeoJSON basemap, no external tiles); EN + AR RTL
  deploy/         modal_app.py (single-container hosted deployment + competition-gate function)
  docs/           EXECUTIVE_SUMMARY, ARCHITECTURE, RUN, MODEL_CARDS (data & model cards), THREAT_MODEL, DATA_ACCESS,
                  TEST_RESULTS, MODEL_RUNS, DEMO_SCRIPT, NARRATIVE, CHECKLIST, infographics/*.svg
  docker-compose.yml, .env.example
```

## Six separate labels, ordinal bands, versioned tools

`observed_water` · `susceptibility` · `forecast_risk` · `anomaly` · `suspected_incident` · `confirmed_incident`
are never merged. Hazard numbers come only from versioned tools (`water_balance_twin/0.3.0`,
`sar_change_screen/0.2.0`, `pressure_flow_residual/0.2.0`, `asset_exposure/0.2.0`, `constrained_router/0.2.0`);
the planner never produces hazard numbers. No percentage probabilities are shown — there is no calibrated model,
so the UI shows "no calibrated model — ordinal bands only".

## Honesty notes

* No lives saved, losses avoided or accuracy percentages are claimed anywhere; the evaluation harness reports
  **not evaluated** for every metric that lacks labelled data.
* The audit log is a hash-linked, append-only chain that is **tamper-evident within the database**, not
  tamper-proof.
* The hosted deployment is a demo on the author's Modal account, not a government environment.
