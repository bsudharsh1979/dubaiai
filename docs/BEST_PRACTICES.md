# Practices adapted from international emergency-management processes

These are publicly documented practices that the prototype adapts into its own process. Referencing them does
not imply endorsement by, cooperation with, or integration with any of the organisations concerned, and none of
the adaptations claims conformance certification. Each row names what was adopted, how it is implemented, and
what was deliberately *not* carried over.

| Practice (origin) | Adopted into RainReady | Where | Deliberately not adopted |
|---|---|---|---|
| **Common Alerting Protocol** (OASIS CAP 1.2 — the international alert-interchange standard used by many national warning systems) | The communications persona emits a `StructuredAlert` with CAP-aligned `urgency`, `severity`, `certainty`, `response_type`, `event`, `instruction` (EN/AR), `expires`. It travels inside the advisory action so it is covered by the proposal's payload hash and the human approval. `certainty` is mapped from evidence completeness (independent sources, staleness, conflicts) and carries `certainty_basis: "… not a probability"`. | `agents/personas.py::structured_alert`, `graph.policy_check`, UI "Structured alert" chips | No CAP XML emission, no distribution to any alerting network; the `sender` field states "not an official warning authority" |
| **Three-tier public warning levels** (pattern used by national warning systems, e.g. Australia's Advice / Watch and Act / Emergency Warning) | `message_level` follows the hazard band — severe → Emergency Warning, high → Watch and Act, otherwise Advice — so the public message and the call to action are consistent and colour-coded. | Structured alert | Official icons/wording of any specific country |
| **Flood-risk matrix** (likelihood × impact, as in the UK Flood Guidance Statement) | The incident header shows a 4×4 likelihood-band × consequence-band matrix with the current cell highlighted. Likelihood = hydrologist severity band, consequence = HSE consequence band — both ordinal outputs of versioned tools. | Incident & approvals → Risk matrix | Percent likelihoods, five-day outlooks, or any calibrated colour thresholds |
| **Incident briefing / situation report** (incident command systems; ICS-201 pattern) | `GET /api/incidents/{id}/sitrep` assembles a SITREP from persisted state only: situation, evidence, decisions, resources, open items, operational period, caveats (+ after-action review when present). One click in the UI; "copy as text" for shift handover. Every generation is audited. | `routers/incidents.py::sitrep`, UI "Situation report" | Model-written narrative; ICS forms, roles or org charts |
| **Joint Decision Model** (UK JESIP: gather information → assess risk → consider powers/policy → identify options → take action and review) | The workflow graph already follows this order: validate → assess/correlate → policy check → plan → human review → execute → monitor/reassess. The How-it-works page documents the mapping so operators recognise the loop. | `agents/graph.py`, How-it-works | JESIP terminology inside the UI |
| **After-action review** (used by many national emergency agencies) | Optional structured AAR at closure: expected, happened, went well, improve, follow-ups. Stored on `incident.summary.after_action_review` with reviewer and timestamp; appears in the SITREP. | `schemas.AfterActionReview`, close endpoint, UI closure form | Mandatory AAR (it is optional in the prototype) |
| **Stand-down discipline** (closing an operation closes its tasking) | Closing an incident stands down any work order still `approved/dispatched/acknowledged/in_progress` (status `cancelled`, payload flag `stood_down_at_closure`) and records `workorder.stood_down` in the audit chain. | close endpoint | — |
| **Common operating picture with explicit data modes** | Mode bar (data / model / connectors / sovereign) on every screen; the How-it-works page shows live server status so no screen can be mistaken for live operations. | Shell, How-it-works | — |
| **Pre-agreed action timelines** (e.g. Japan's disaster "timeline" planning) | Not implemented. The twin's +30/+60/+180 min horizons are simulation horizons; converting them into pre-agreed trigger timelines needs real forecasts and agency agreement. | — | Listed here as a candidate, not a feature |

## Usability refinements made alongside

* Executive summary page (`/how-it-works`) readable without signing in; EN/AR; infographics served locally.
* Demo reset made robust on Windows (SQLite file locked by the worker thread → drop-all-tables fallback).
* Closure form now carries the AAR; the stored AAR is displayed on the incident after closure.
* Open work orders no longer survive closure (previously they stayed `dispatched`).

## Verification

`tests/test_branches_and_tools.py::test_structured_alert_sitrep_and_after_action_review` (API) and the Playwright
principal demo (risk matrix, structured alert, SITREP) + How-it-works test (browser). See `TEST_RESULTS.md`.
