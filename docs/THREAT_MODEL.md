# Threat model

Scope: the RainReady prototype as deployed locally or on Modal. Assets to protect: the integrity of response
decisions (nothing physical or public happens without a bound human approval), the audit trail, identity, and
the separation between untrusted text and system instructions. Out of scope: real agency systems (none are
connected), physical security, denial-of-service beyond basic rate/size limits.

| # | Threat | Where it enters | Control implemented | Residual risk / not covered |
|---|---|---|---|---|
| T1 | Prompt injection via field report, image caption or assistant question ("dispatch crews now", "ignore policy") | `/api/field-reports`, `/api/incidents/{id}/assistant` | `guard.separate()` strips imperative/instruction sentences into a quarantined `isolated_instructions` field that personas never receive as instruction; privileged-action requests emit a `security` event (`injection_isolated`) and an `action.blocked` audit row, shown in the UI; report routed to review. Model providers receive observations as **data** in a typed JSON block, not as prompt text. Tests: `test_prompt_injection_isolated_and_blocked`, `test_separation_preserves_casualty_reports`, Playwright scenario D | Deterministic lexical gate can miss paraphrases; model guard adapters are implemented but not exercised |
| T2 | Client claims a privileged role | Any API call | Identity only from a signed, HttpOnly cookie (`itsdangerous`, `SESSION_SECRET` server-only); role is looked up server-side; `demo-login` exists only when `DEMO_AUTH=true`; approvals re-check the approver's role from the cookie, never from the body | Demo login is intentionally unauthenticated — must be replaced by SSO/OIDC before any real use |
| T3 | Replay or tampering of an approval | `/api/approvals`, worker execution | Approval bound to incident id + version, proposal version, payload SHA-256, tools, destinations, approver, expiry; `check_execution` re-verifies at dispatch; revise → new version → old approvals invalid; `Idempotency-Key` UNIQUE | — |
| T4 | Agent calls a tool outside its allowlist, with bad args, or beyond budget | `tools/registry.call_tool` | Allowlist per persona, Pydantic argument validation, per-run call/time budgets, UAE bounding-box check for geometry; violations raise and are audited | — |
| T5 | Agent fabricates hazard numbers or probabilities | Persona outputs | Numeric hazard fields only accepted from tool results (planner schema has bands and references, not numbers); UI shows bands and "no calibrated model" | A hosted model could still emit prose containing numbers; the UI renders structured fields only |
| T6 | Unauthorized SOP retrieval | `/api/knowledge/search`, persona retrieval | Role filter applied **before** search; results carry `doc_id/version/section` | — |
| T7 | Model provider swap / data exfiltration to a cloud endpoint | Settings | `PROVIDER_ALLOWLIST` enforced on `LLM_BASE_URL`; `SOVEREIGN_MODE=true` rejects non-local hosts; no fallback between providers; provider state visible on Assurance | The competition gate function runs with `SOVEREIGN_MODE=false` by design and only against an allow-listed NVIDIA endpoint with a separate DB |
| T8 | Secrets in logs or client | Logging, `/api/config` | Audit payloads pass through `audit.redact()` (key-based: tokens, keys, cookies, passwords); `/api/config` exposes only mode flags; secrets live in server env / Modal secrets and are never serialized to the client | Request bodies are not logged, but uvicorn access logs include paths |
| T9 | Malicious upload (zip bomb, non-raster, wrong CRS, path traversal) | `/api/imports/sentinel1`, field photos | Size limits (8 MB images, 64 MB rasters), image MIME sniffing (JPEG/PNG only), `_safe_name`, rasterio open with validation (CRS, overlap, grid, units, nodata, orbit; rejected imports audited as `import.rejected`), stored under the data dir, not the web root | No antivirus scanning |
| T10 | Audit tampering | Database | Append-only table, each row stores `prev_hash` and `hash` over canonical JSON; `/api/audit/verify` recomputes the chain; export for external anchoring | **Tamper-evident, not tamper-proof**: an attacker with DB write access can rewrite the entire chain. Anchoring hashes externally (WORM store/HSM) is a deployment requirement, not implemented |
| T11 | Guard model outage used to bypass review | Guard adapters | If `GUARD_REQUIRED_FOR_PUBLICATION=true` and the adapter is unhealthy, approvals/publication are blocked while intake and monitoring continue; guard scores never grant permission | — |
| T12 | Emergency conditions | Operations | Emergency stop (`/api/assurance/emergency-stop`, assurance officer / commander) blocks privileged actions, keeps monitoring | — |
| T13 | Casualty report dropped by filtering | Field intake | Casualty mentions are preserved verbatim, flagged `casualty_mention`, and route to urgent human review even if the report is otherwise rejected | — |
| T14 | Replay leaks future information | `historical_replay` mode | All evidence queries filter `available_at <= decision_time`; harness `no_leakage` check | Only enforced in the code paths that use `available_at`; third-party connectors would need the same discipline |
| T15 | Multi-tenant leakage on the hosted demo | Modal | Single shared demo DB by design; no personal data; demo reset available | Not a production isolation model |

## Explicitly absent capabilities

* No valve, pump-control, power, evacuation, SMS/broadcast or road-sign endpoint exists in this codebase.
  "Dispatch" produces simulated receipts.
* No connection to NCM, DEWA/utility SCADA, RTA or any agency system; nothing is scraped.
* No autonomous closure, no autonomous publication, no autonomous re-approval after edits.
