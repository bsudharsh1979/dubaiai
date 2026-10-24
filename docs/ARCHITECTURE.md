# Architecture

```
Signals & systems of record ──► Brain 1: perception & hazard tools ──► Brain 2: agent coordination,
(sensors, forecasts, SAR/optical     (SAR change screen, water-balance twin,   knowledge & access control
 scenes, utility telemetry, field     residual leak screen, exposure overlay,  (LangGraph workflow, 8 personas,
 reports — all with provenance)       constrained router — versioned, typed)   policy engine, RBAC, retrieval)
                                                                                     │
        ┌────────────────────────────────────────────────────────────────────────────┘
        ▼
Departments & engagement ──► Acknowledgements, observations & reassessment ──► human-confirmed closure
(simulated connectors, work orders)   (ack ≠ completion; completion changes state; timers; new evidence re-enters)
```

The strip above is rendered in the UI footer and on the Agents view.

## Components

| Component | Technology | Notes |
|---|---|---|
| `web/` | Next.js 16 (static export), React 19, Tailwind 4, MapLibre GL 6 | Six views; EN/AR with RTL; local GeoJSON basemap (`/api/geo/basemap`, `/api/geo/uae`) — no external tiles, fonts or CDN; MapLibre worker self-hosted |
| `api/` | FastAPI 0.162, Pydantic 2, SQLAlchemy 2.1, Alembic | Typed API, generated OpenAPI at `/docs`; single server-side action gateway; SSE at `/api/events` |
| Workflow | LangGraph 1.2 `StateGraph` with `interrupt()` | Checkpoints in a separate SQLite/Postgres saver; thread per incident version |
| Worker | In-process thread (or standalone `python -m rainready.worker`) | Job queue with idempotency keys, retry budget, escalation timers, approval expiry |
| Storage | SQLite (tests, local, Modal) or PostgreSQL + PostGIS (Compose) | Geometry stored as GeoJSON + bbox; PG migration adds generated `geom` + GIST and optional pgvector |
| Rasters | rasterio / shapely / pyproj, local files | Sentinel-1 before/after validation + change mask |

## Workflow graph (`api/rainready/agents/graph.py`)

```
ingest → validate(observer) → assess(hydrologist | utility engineer) → correlate(HSE officer, dedupe)
      → coordinate(incident coordinator pre-check)
            ├─ request_evidence  (≤ MAX_EVIDENCE_LOOPS, then urgent review)       → END (re-enters on new evidence)
            ├─ urgent_review     (persona failure / policy deny / unresolved high consequence)
            ├─ monitor_only      (low band, or reassessment with nothing new → closure_pending)
            └─ plan(response planner, communications officer, assurance officer)
                 → policy_check (deterministic engine; duplicate suppression)
                 → human_review  (interrupt — bound approval)
                 → execute (gateway re-checks policy; simulated dispatch)
                 → monitor (timers → reassess)
```

Every node writes to the database inside its own session; the graph state carries ids and structured summaries only
(never chain-of-thought). Reassessment creates a new thread (`incident#vN`) and bumps the incident version, which
invalidates any approval bound to the previous version.

## Personas (`api/rainready/agents/personas.py`)

Observer, Hydrologist, Utility Engineer, HSE Officer, Response Planner, Communications Officer, Assurance Officer,
Incident Coordinator. Each has: typed input (state slice), typed output (Pydantic model → JSON schema), tool
allowlist (enforced by `tools/registry.py`), knowledge roles (filter applied **before** retrieval), limits
(`max_tool_calls`, `max_tokens`, `max_seconds`), and prohibitions shown on the persona card. Irrelevant specialists
are skipped (e.g. Utility Engineer in a rainfall incident). The demo provider executes each persona's deterministic
policy; the model providers execute the same tools via validated tool calls and a mandatory `submit_output`.

## Deterministic authority (`policy.py`, `gateway.py`, `auth.py`)

* **Roles** come only from the signed server cookie (`itsdangerous`). The client never sends a role.
* **Approval authority per action kind** (`ACTION_AUTHORITY`): e.g. `pump_deployment` → drainage controller or
  incident commander; `advisory` → incident commander only.
* **Approval binding**: incident id + version, proposal version, payload hash, intended tools, destinations,
  approver identity/role, expiry (`APPROVAL_TTL_MINUTES`). Revising a proposal bumps the incident version and
  supersedes the proposal; `check_execution` re-verifies everything at dispatch time.
* **Idempotency**: `Idempotency-Key` on approvals and transitions; UNIQUE constraints; replays return the original.
* **States**: proposed → approved → dispatched → acknowledged → in_progress → completed (plus rejected/failed/
  expired/cancelled). Only `completed` applies a physical effect (`apply_physical_effect`).
* **Closure**: requires an observation or reviewed field report newer than the last response action **and**
  the incident-commander role.
* **Emergency stop**: blocks approvals/dispatch/publication; intake, monitoring and reassessment continue.
* **Audit**: every decision appended to a hash-linked chain (`audit.record`, `verify_chain`).

## Guards (`providers/guard.py`)

A deterministic gate is always on: `separate()` isolates imperative instructions from observations in untrusted
text (field reports, assistant questions), flags casualty mentions (preserved, never dropped, routed to urgent
review), and detects privileged-action attempts. Optional model adapters (Nemotron Content Safety,
NemoGuard JailbreakDetect) add classifications; **guard scores never grant permission** — they can only add
review flags or block publication when `GUARD_REQUIRED_FOR_PUBLICATION=true` and the adapter is unhealthy.

## Providers (`providers/registry.py`, `providers/nim.py`)

One shared text-inference service for all personas. `demo` is deterministic and labelled; `local_nim` and
`approved_hosted` use the OpenAI-compatible contract, discover served ids via `/v1/models`, require the configured
id to be present, validate structured outputs against the persona schema, and report failures visibly. The base
URL must match `PROVIDER_ALLOWLIST`; there is no fallback between providers and never a cloud fallback in sovereign
mode. Embeddings fall back to lexical BM25 (labelled). Vision and EO-encoder interfaces exist and are reported as
"not exercised".

## Data model highlights (`models.py`)

Every observation-like record carries provenance: `source_id`, `observed_at`, `available_at`, `received_at`,
geometry/CRS, `units`, `resolution`, `quality_flags`, `provenance_uri`, `checksum`, `license_class`,
`simulation_status`; forecasts add `issued_at`/`valid_at`. All timestamps are stored UTC and displayed Asia/Dubai.
Replay/decision-time filtering uses `available_at` so nothing unavailable at decision time can be used.
