# Competition narrative

> **Proposed positioning.** The headings below are how *we* propose the project be read. They are not official
> judging criteria, and nothing here implies endorsement by, or an existing integration with, any UAE authority.

## The problem, stated carefully

Heavy rainfall in the UAE produces two different failure modes — fast-rising flash flows in steep or paved
catchments, and slow-draining waterlogging in low points such as underpasses — and both compete for the same
scarce resources (mobile pumps, crews, closures) under time pressure. Water-utility leaks look similar to
legitimate flushing or demand events in telemetry. Field reports arrive as free text that may be wrong, stale or
hostile. Decision-makers need the evidence organised, the options bounded, and the authority to act kept firmly
human.

## What RainReady proposes

1. **Two brains, one gate.** Perception and hazard physics live in versioned, deterministic tools; coordination,
   knowledge and access control live in a typed agent workflow. Between them and the world sits a single
   server-side gateway that executes only hash-bound, role-checked, unexpired human approvals.
2. **Six labels that never merge.** Observed water, susceptibility, forecast risk, anomaly, suspected incident and
   confirmed incident are separate fields with separate provenance. A SAR change mask is "candidate inundation at
   acquisition time", not "flood".
3. **Bands, not probabilities.** Without calibration data there is no honest probability. The UI says so.
4. **Evidence loops with a ceiling.** Unreliable evidence (stale scenes, flagged sensors, disputed reports) triggers
   at most two evidence requests, then urgent human review.
5. **Acknowledgement is not action.** Only completion changes the twin's state; timers and new observations
   re-enter the workflow; closure requires a new observation and an authorized reviewer.
6. **Sovereign by configuration.** Provider allowlists, no cloud fallback, server-only secrets, local basemap, and a
   `local_nim` path for in-country GPUs.

## What is real in this submission

* A runnable prototype (local and hosted) covering the full rainfall workflow, leak and HSE extensions, four
  scenarios with different outcomes, a what-if twin, Sentinel-1 import validation, EN/AR UI, 28 API tests and a
  4-scenario browser smoke test.
* Guardrails implemented in code and tested: RBAC from signed identity, bound approvals, idempotency, tool
  allowlists, instruction/observation separation, read-only tools, upload validation, redacted audit, hash-linked
  audit chain, emergency stop, guard-outage behaviour, casualty preservation, no future-information leakage.

## What is not (yet) real

* No real data, no connected agency, no exercised model inference (the hosted credential was rejected; the path
  is implemented and reports its own status truthfully), no evaluated predictive skill, no tamper-proof storage,
  no production identity provider, no PostGIS run in this environment.
* No claims of lives saved, losses avoided or accuracy.

## Why this shape is worth building on

A government buyer can read `docs/DATA_ACCESS.md` and see exactly which agreements unlock which label; an auditor
can read `docs/THREAT_MODEL.md` and see which controls exist and which are deployment requirements; an ML team
can plug a regionally adapted model into the `EOEncoderProvider` or `local_nim` interfaces and the evaluation
harness will stop saying "not evaluated" only when real labels are supplied. The architecture keeps the humans,
the physics and the audit trail in charge while the models improve.
