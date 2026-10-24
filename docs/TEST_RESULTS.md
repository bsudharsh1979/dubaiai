# Test results

Last run: 2026-10-24 (author's Windows workstation, Python 3.13.5 / uv 0.10.10, Node 22.17.1, Chromium via
Playwright 1.64.1). No accuracy, recall or calibration figures exist for any predictive component — see
`docs/MODEL_CARDS.md`; the evaluation endpoint reports **not evaluated** for them.

## Backend — `uv run pytest tests -q` → **29 passed** (≈14 s, temporary SQLite)

| File | Tests | What they prove |
|---|---|---|
| `tests/test_rainfall_flow.py` (4) | `test_health_and_modes`, `test_unauthenticated_blocked`, `test_rainfall_end_to_end`, `test_twin_controls_change_outcome` | Modes exposed; 401 without cookie; scenario A runs ingest → personas → proposal → approval (commander) → simulated dispatch → ack has **no** physical effect → completion applies effect → reassessment; twin controls change bands and outcome |
| `tests/test_guardrails.py` (12) | `test_unauthorized_roles_cannot_approve_or_control`, `test_edit_after_approval_invalidates_and_hash_binding`, `test_stale_approval_cannot_execute`, `test_restart_and_double_click_idempotency`, `test_prompt_injection_isolated_and_blocked`, `test_separation_preserves_casualty_reports`, `test_tool_allowlist_enforced`, `test_model_outage_without_cloud_fallback`, `test_guard_outage_blocks_publication_but_not_monitoring`, `test_emergency_stop_blocks_privileged_actions`, `test_audit_chain_verifies_and_detects_tamper`, `test_nim_planner_never_relabels_fixture` | Roles enforced server-side (client role ignored); revise invalidates approval and payload hash is checked; stale approval blocked at execution; approvals and idempotency survive an app restart (new app instance on same DB) and double-clicks; scenario D instruction isolated, no action created; casualty text preserved and routed to urgent review; out-of-allowlist / out-of-bounds / invalid-argument / over-budget tool calls rejected; unreachable model → visible failure, no cloud fallback; guard adapter outage blocks publication while intake continues; emergency stop blocks approvals; audit chain verifies and a modified row is detected; the NIM planner raises instead of relabelling a fixture when the endpoint fails |
| `tests/test_branches_and_tools.py` (13) | `test_leak_flow_suspected_then_confirmation_required`, `test_leak_alternative_branch_planned_flushing_changes_outcome`, `test_unreliable_evidence_requests_more_then_escalates`, `test_unreliable_evidence_resolves_with_reviewed_report`, `test_closure_requires_new_observation_and_commander`, `test_structured_alert_sitrep_and_after_action_review`, `test_audit_chain_survives_concurrent_appends`, `test_mass_balance_and_units`, `test_no_future_information_leakage`, `test_routing_excludes_flooded_and_reports_unresolved`, `test_raster_import_validation_and_mask`, `test_retrieval_authorization_and_citations`, `test_evaluation_summary_is_honest` | Leak stays `suspected` until confirmation; B2 planned-flushing record changes the outcome; scenario C requests evidence twice then escalates to urgent human review, then resolves with a reviewed report; closure needs a newer observation **and** commander role; advisory action carries a CAP-aligned structured alert (severity/certainty/message level mapped from bands, "not a probability") inside the hashed payload, SITREP is built from persisted state and matches the proposal hash, after-action review is stored at closure and open work orders are stood down; four threads appending audit events concurrently leave the hash chain linear (the append path takes the writer lock before reading the head — without it the test reproduces a fork); twin conserves mass (assert), flash-flood vs waterlogging mechanisms differ; replay uses only `available_at <= decision_time`; router excludes flooded links and reports "no verified route"; raster import rejects CRS mismatch / wrong units / misaligned grid and produces the labelled change mask with class fractions; SOP retrieval filtered by role with doc/version/section citations; evaluation summary contains "not evaluated" |

## Browser smoke — `npx playwright test` → **4 passed**

Run twice: against the local single-process server (`http://127.0.0.1:8100`) and against the Modal deployment
(`https://gamgn--rainready-uae-server-web.us-east.modal.run`), both 3/3.

1. **Principal rainfall demo end-to-end through the UI** (≈46 s hosted): reset → sign in → run scenario A → agents
   view shows persona statuses and tool calls → incident view → switch identity to incident commander → approve →
   work order ack (state unchanged) → complete (effect applied, reassessment queued) → bounded assistant answers
   with citations → twin: raising blockage increases peak depth → assurance view shows modes, providers, audit
   verify OK.
   Also asserts the risk-matrix current cell, the CAP-aligned structured alert ("not a probability", message
   level) and a SITREP generated from persisted state. On the first page, asserts the executive overview renders
   nine flow-of-events cards with no live marker before an incident exists, and that after scenario A the marker
   sits on "A human approves" with the persisted status "Awaiting approval".
2. **Malicious field report**: scenario D report submitted via the form; isolated instruction shown in the
   quarantine box; no proposal/action path created; security event visible.
3. **How it works** (no sign-in): executive summary page renders stages, adapted practices, live server status
   (worker alive, provider exercised flag), "not claimed" list, locally served infographic, Arabic toggle.
4. **Arabic RTL**: toggle → `<html dir="rtl" lang="ar">`, navigation and chips rendered in Arabic.

## Hosted health (after redeploy, 2026-10-24 19:05 UTC)

`/api/health` → `ok: true`, modes `synthetic / demo / simulated / sovereign / hosted`, worker alive, SQLite migrated,
deterministic guard gate active, `/api/incidents` without cookie → 401.

## Competition gate (real model inference)

**Not passed.** Served-model discovery against the allow-listed NVIDIA endpoint succeeded (85 models listed,
Nemotron Nano served as `nvidia/nemotron-nano-3-30b-a3b`); chat completions returned **401 Unauthorized** with the
stored credential, so no persona was ever executed by a real model. The system behaved as designed: all personas
failed visibly, the incident went to `urgent_human_review`, no fallback occurred. Details: `docs/MODEL_RUNS.md`.

## Not executed

* Docker Compose stack with PostGIS (Docker not installed on the authoring machine). Migration and Dockerfiles are
  written; untested.
* Guard model adapters, embedding model, vision adapter, EO encoder (no endpoint configured).
* Any evaluation against real labelled flood, leak or forecast data (none available).
