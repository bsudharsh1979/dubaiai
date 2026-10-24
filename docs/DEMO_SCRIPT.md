# Four-minute demo script

Setup (before the clock): open https://gamgn--rainready-uae-server-web.us-east.modal.run (or `http://localhost:8100`),
Assurance → **Reset demo**, sign in as **Observer**. Language EN; switch to AR once at the end.
The first page opens with the executive overview drawn as a flow of events (nine steps with lanes and guardrails);
point at it for 20 seconds, then click **Hide overview** so the map fills the screen. As the incident progresses the
overview's live marker moves with the persisted status (e.g. onto "A human approves" while awaiting approval).
**How it works** (`/how-it-works`) is the long form with live server status; neither needs a sign-in.

| t | View | Say | Do / show |
|---|---|---|---|
| 0:00 | Command | "RainReady is decision support for water anomalies and flood risk. Everything on screen is synthetic and every connector is simulated — the mode bar says so. Nothing physical happens without a human approval bound to the exact proposal." | Point at the mode bar (Data **synthetic** · Model **demo** · Connectors **simulated** · **sovereign**). Map shows Demo Sector 7 with sensors and assets; no external tiles. |
| 0:30 | Command | "Scenario A: intense rainfall over the underpass catchment." | Click **Run** on *A — Intense rainfall*. The incident appears with label **forecast_risk**, a severity **band** (no percentages), and a next-decision line. |
| 0:50 | Agents | "Eight personas, each with typed outputs and a tool allowlist. The hydrologist cannot invent numbers — it calls the water-balance twin, version 0.3.0, labelled *scenario model — uncalibrated*." | Persona cards: Observer validated feeds; Hydrologist ran `water_balance_twin/0.3.0` — note **flash flood** upstream vs **waterlogging** at the underpass; Utility Engineer *skipped (not relevant)*; Assurance Officer checked the policy. Tool list shows versions and citations `SOP-FLOOD-TRIAGE v0.3-demo §2`. |
| 1:30 | Incidents | "The planner proposes; the policy engine decides who may approve. I'm an observer, so the approve button is disabled server-side, not just in the UI. The advisory draft already carries CAP-style urgency, severity and certainty — and certainty is mapped from evidence, not a probability." | Point at the **risk matrix** (current cell) and the **Structured alert** chips on the advisory action. Show proposal actions and the policy decision. Try Approve → 403. Switch identity to **Incident Commander** → Approve. Approval shows incident version, payload hash, expiry. |
| 2:05 | Incidents | "A shift handover takes one click: the SITREP is assembled from stored state only." | Click **Generate SITREP** → sections 1–7; **Copy as text**. |
| 2:10 | Incidents | "Dispatch is a simulated receipt. Acknowledgement changes nothing physically — only completion does, and completion triggers reassessment." | Work order: **Acknowledge** → twin state unchanged; **Complete** → pump effect applied, reassessment job queued, new incident version. |
| 2:40 | Twin | "Operators can ask what-if questions. Raising drain blockage increases the underpass peak; adding a mobile pump lowers it. Horizons +30/+60/+180 are simulation horizons, not forecasts." | Drag **Blockage** up → peak depth rises; toggle **Extra mobile pump** → falls; compare panel shows baseline vs intervention bands. |
| 3:10 | Field | "Field reports are untrusted text. Scenario D hides an instruction to dispatch crews. It is quarantined and can never become an action." | Run scenario D (or submit the prefilled report): the **Isolated instructions** box shows the stripped sentence; a security event appears; no proposal is created from it. Casualty mentions would be preserved and escalated. |
| 3:35 | Assurance | "Everything is in a hash-linked audit chain — tamper-evident, not tamper-proof — with an emergency stop that halts privileged actions while monitoring continues. Providers show *configured / healthy / exercised*: the real-model path exists and truthfully reports it has not been exercised here." | Click **Verify chain** → OK. Point at providers table and evaluation panel ("not evaluated"). |
| 3:50 | Any | "And the same interface in Arabic, right-to-left, fully offline." | Toggle **AR**. End. |

Fallbacks: if the hosted container is cold, the first request takes a few seconds; if a step fails, the incident
goes to urgent human review — show that, it is the designed behaviour.
