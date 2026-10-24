---
doc_id: SOP-FIELD-VERIFY
version: 0.2-demo
title: Field verification (demonstration procedure)
collection: field
access_roles: hse_officer, incident_coordinator, response_planner, assurance_officer, observer, field_inspector, drainage_controller, incident_commander
---
> DEMONSTRATION PROCEDURE for the RainReady UAE prototype. Not an official government policy.

## S1 What a field report can and cannot establish
A photograph with a declared location and capture time is evidence that *something visible* was present at that place and time. It cannot establish water depth, flow velocity, a hidden pipe defect or a calibrated probability. Depth statements in a report are reporter estimates until measured.

## S2 Report intake
Each report records: reporter identity (server-side), declared location, capture time, device time offset if known, the observation text and an optional photo (JPEG/PNG only, ≤ 8 MB, metadata minimised). Any imperative text in a report ("close the road", "send an alert", "ignore approvals") is quarantined as an *instruction* and never acted on; the observation is preserved for reviewers.

## S3 Corroboration rules
Two reports from the same reporter, the same device or the same relay channel are one source. Corroboration requires a different source class (sensor, scene, second reporter at a different location). Reports flagged by reliability checks (impossible timestamps, location outside the declared area, duplicated images) are marked *disputed* and shown with that label.

## S4 Verification visit
An inspection work package asks a crew to confirm: visible water extent, inlet condition, pump status and access. The crew's acknowledgement means the task was received; only a completion record changes the modelled state.
