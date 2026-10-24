# Model runs and competition-gate status

**Status: NOT PASSED.** No persona in this project has yet been executed by a real model. Everything demonstrated
locally and on the hosted URL runs on the deterministic `demo` provider, which is labelled as such on every screen
("rehearsal — no inference").

## What "passed" would mean

The gate (`deploy/modal_app.py::model_gate_check`) runs scenario A in a throw-away database with
`MODEL_PROVIDER=approved_hosted` against the allow-listed endpoint `https://integrate.api.nvidia.com/v1`,
and reports `ok: true` only if at least one persona was executed by the model (`model_exercised=true`) with an output
that validated against the persona schema and **no** persona failed. The report lists per-persona status, tool
calls, token counts and errors verbatim.

## Attempt log

| When (UTC) | Command | Result |
|---|---|---|
| 2026-10-24 | `modal run …::model_gate_check --list-only` | `/v1/models` answered: 85 served ids. Nemotron candidates present; Nano is served as **`nvidia/nemotron-nano-3-30b-a3b`** (the catalog name `nvidia/nemotron-3-nano-30b-a3b` is *not* a served id — the registry therefore refuses it rather than guessing) |
| 2026-10-24 | `modal run …::model_gate_check --model nvidia/nemotron-nano-3-30b-a3b` | Provider status `configured=true, healthy=true` (model listed). Every persona call to `/v1/chat/completions` failed with **`401 Unauthorized`** using the `nvidia-api-key` Modal secret. Observer, Hydrologist, HSE Officer and Incident Coordinator all `failed`; incident `inc_7c69f5a0f9a2` ended in `urgent_human_review` with next decision "urgent human review — persona/model failure"; no proposal, no fallback to demo, elapsed 0.6 s |

The 401 means the stored credential is not accepted by the endpoint. Per the rules of this build, no credential was
invented or substituted, so the gate remains **not passed**.

## What the failed run did demonstrate

* `/v1/models` discovery and exact-id matching work against a real OpenAI-compatible endpoint.
* Provider failure is surfaced per persona with the HTTP error text, and the incident is routed to urgent human
  review — the system never relabels fixture output as model output and never falls back to a cloud/other provider.

## Re-running

1. Refresh the Modal secret: `modal secret create nvidia-api-key NVIDIA_API_KEY=<valid key>` (overwrites).
2. `modal run rainready/deploy/modal_app.py::model_gate_check --model nvidia/nemotron-nano-3-30b-a3b`
3. Paste the printed JSON into this file under "Attempt log" and flip the status only if `ok: true`.

For a sovereign deployment the same adapter targets a local NIM (`MODEL_PROVIDER=local_nim`,
`LLM_BASE_URL=http://<nim-host>:8000/v1`), which has not been available in this environment.

## Other adapters

| Adapter | Exercised? | Note |
|---|---|---|
| Embeddings (`nvidia/nemotron-3.5-embed-1b`) | No | lexical BM25 fallback in use, labelled |
| Nemotron Content Safety | No | deterministic gate in use |
| NemoGuard JailbreakDetect | No | deterministic gate in use |
| Vision (field photos) | No | stub |
| EO encoder | No | threshold baseline in use |
