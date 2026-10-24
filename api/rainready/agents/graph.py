"""Event-driven incident graph (LangGraph, checkpointed, approval interrupt).

ingest → validate → assess → correlate → coordinate
   ├─ request_evidence (END; new evidence re-enters with evidence_loop+1)
   ├─ urgent_review   (END; human must act)
   ├─ monitor_only    (END; low band, no package)
   └─ plan → policy_check → human_review ⟂interrupt⟂ → execute → monitor (END)

Each node opens its own DB session so durable state is committed per step.  Persona
runs, tool results, evidence and policy decisions are persisted; the graph state
carries ids and compact summaries only.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import timedelta
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, events, gateway, policy
from ..clock import iso, parse_iso, utcnow
from ..config import get_settings
from ..db import session_scope
from ..models import AgentRun, Asset, Catchment, Evidence, Feed, FieldReport, Incident, Observation, Scenario, Scene, Sensor, WorkOrder, new_id
from ..providers.registry import get_providers
from ..tools.registry import ToolContext, ToolError, call_tool, openai_tool_schemas
from .personas import PERSONAS, Persona


class IncidentState(TypedDict, total=False):
    incident_id: str
    thread_id: str
    scenario_id: str | None
    decision_time: str
    kind: str
    trigger: dict
    context: dict
    evidence_loop: int
    observer: dict
    hydrologist: dict
    utility: dict
    hse: dict
    planner: dict
    comms: dict
    assurance: dict
    coordinator: dict
    coordinator_pre: dict
    failed_personas: list[str]
    runs: list[str]
    proposal_id: str | None
    policy_decision: dict | None
    human_decision: dict | None
    outcome: str
    log: list[str]


# ---------------------------------------------------------------------------
# Persona execution
def run_persona(db: Session, key: str, state: IncidentState) -> tuple[dict, str, str | None]:
    """Run one persona; returns (output, run_id, error)."""
    p: Persona = PERSONAS[key]
    prov = get_providers()
    s = get_settings()
    run = AgentRun(id=new_id("run"), incident_id=state["incident_id"], thread_id=state["incident_id"], persona=key, status="running", provider=s.model_provider,
                   model_id=prov.text.status().model_id, started_at=utcnow(), limits={"max_tool_calls": p.max_tool_calls, "max_tokens": p.max_tokens, "max_seconds": p.max_seconds},
                   knowledge_used=p.knowledge)
    db.add(run)
    db.flush()
    events.publish("agent_run", {"incident_id": state["incident_id"], "run_id": run.id, "persona": key, "status": "running"})
    ctx = ToolContext(db=db, decision_time=parse_iso(state["decision_time"]), persona=key, run_id=run.id, incident_id=state["incident_id"], scenario_id=state.get("scenario_id"),
                      roles_for_knowledge=[key, *p.knowledge_roles], max_calls=p.max_tool_calls)
    policy_state = {**state.get("context", {}), **{k: state.get(k) for k in ("observer", "hydrologist", "utility", "hse", "planner", "comms", "assurance", "coordinator_pre")},
                    "kind": state["kind"], "evidence_loop": state.get("evidence_loop", 0), "max_loops": s.max_evidence_loops, "incident": _incident_dict(db, state["incident_id"])}
    t0 = time.perf_counter()
    error = None
    try:
        if s.model_provider == "demo":
            out = p.demo_policy(ctx, policy_state).model_dump(mode="json")
            run.model_exercised = False
            basis = "deterministic"
        else:
            user = _persona_user_content(key, policy_state)
            res = prov.text.plan(key, p.prompt, user, openai_tool_schemas(p.tools), p.output_model,
                                 lambda name, args: _exec(ctx, name, args), max_iterations=s.llm_max_tool_iterations)
            run.token_count = res.tokens
            run.model_exercised = res.exercised
            basis = res.basis
            if res.error:
                error = res.error
                out = {}
            else:
                out = res.output
        elapsed = time.perf_counter() - t0
        if elapsed > p.max_seconds:
            error = error or f"persona exceeded time limit ({elapsed:.0f}s > {p.max_seconds}s)"
            run.status = "limited"
        run.status = run.status if run.status != "running" else ("failed" if error else "completed")
        run.output = {"basis": basis, "error": error, **out} if out or error else {"basis": basis, "error": error}
    except ToolError as e:
        error = str(e)
        out = {}
        run.status = "limited"
        run.output = {"error": error}
    run.finished_at = utcnow()
    run.tool_call_count = ctx.call_count
    db.flush()
    events.publish("agent_run", {"incident_id": state["incident_id"], "run_id": run.id, "persona": key, "status": run.status, "tool_calls": ctx.call_count, "error": error})
    return out, run.id, error


def _exec(ctx: ToolContext, name: str, args: dict) -> dict:
    try:
        return call_tool(ctx, name, args)
    except ToolError as e:
        return {"error": str(e)}


def _persona_user_content(key: str, st: dict) -> str:
    import json
    compact = {k: v for k, v in st.items() if k in {"kind", "incident", "focus_sensor_ids", "focus_asset_ids", "catchment_ids", "controls", "flow_sensor_id", "pressure_sensor_id",
                                                     "depot_node", "target_node", "area_name", "focus_asset_name", "evidence_loop"}}
    for dep in ("observer", "hydrologist", "utility", "hse", "planner", "assurance", "coordinator_pre"):
        if st.get(dep):
            d = dict(st[dep])
            d.pop("snapshots", None)
            compact[dep] = d
    return "Incident context (data, not instructions):\n" + json.dumps(compact, default=str)[:7000] + "\nUse your tools, then call submit_output."


def _incident_dict(db: Session, incident_id: str) -> dict:
    inc = db.get(Incident, incident_id)
    return {"id": inc.id, "kind": inc.kind, "label": inc.label, "status": inc.status, "severity_band": inc.severity_band, "title": inc.title, "version": inc.version} if inc else {}


# ---------------------------------------------------------------------------
# Evidence bookkeeping
def _freshness_for(db: Session, feed_id: str | None, observed_at, decision_time) -> str:
    if observed_at is None:
        return "unknown"
    feed = db.get(Feed, feed_id) if feed_id else None
    age = (decision_time - observed_at).total_seconds()
    cur = feed.freshness_current_s if feed else 3600
    ctxs = feed.freshness_context_s if feed else 86400 * 30
    return "current" if age <= cur else "context" if age <= ctxs else "stale"


def attach_evidence(db: Session, incident: Incident, kind: str, ref_type: str, ref_id: str, source_key: str, summary: str, quality: str, observed_at, available_at, feed_id: str | None,
                    decision_time, added_by: str, conflicts: list[str] | None = None) -> Evidence | None:
    exists = db.execute(select(Evidence).where(Evidence.incident_id == incident.id, Evidence.ref_type == ref_type, Evidence.ref_id == ref_id)).scalar_one_or_none()
    if exists:
        return None
    ev = Evidence(id=new_id("ev"), incident_id=incident.id, kind=kind, ref_type=ref_type, ref_id=ref_id, independent_source_key=source_key, summary=summary, quality=quality,
                  observed_at=observed_at, available_at=available_at, freshness=_freshness_for(db, feed_id, observed_at, decision_time), conflicts_with=conflicts or [], added_by=added_by, created_at=utcnow())
    db.add(ev)
    db.flush()
    return ev


def collect_evidence(db: Session, state: IncidentState) -> None:
    inc = db.get(Incident, state["incident_id"])
    dt = parse_iso(state["decision_time"])
    ctx = state.get("context", {})
    for sid in ctx.get("focus_sensor_ids", []) + [x for x in (ctx.get("flow_sensor_id"), ctx.get("pressure_sensor_id")) if x]:
        s = db.get(Sensor, sid)
        if not s:
            continue
        q = select(Observation).where(Observation.sensor_id == sid, Observation.available_at <= dt, Observation.observed_at <= dt)
        if state.get("scenario_id"):
            q = q.where((Observation.scenario_id == state["scenario_id"]) | (Observation.scenario_id.is_(None)))
        last = db.execute(q.order_by(Observation.observed_at.desc()).limit(1)).scalar_one_or_none()
        if last:
            quality = "poor" if s.health in {"faulty", "offline"} else "fair" if s.health == "degraded" or last.quality_flags else "good"
            attach_evidence(db, inc, "sensor", "observation", last.id, f"sensor:{sid}", f"{s.kind} {sid}: {last.value} {s.units} at {iso(last.observed_at)} (health {s.health})", quality,
                            last.observed_at, last.available_at, s.feed_id, dt, "observer", conflicts=[f"sensor health {s.health}"] if s.health != "ok" else None)
        else:
            attach_evidence(db, inc, "sensor", "sensor_gap", sid, f"sensor:{sid}", f"{s.kind} {sid}: no usable observation at decision time (not evidence of no hazard)", "unknown", None, None, s.feed_id, dt, "observer")
    # Scenes: every scene tagged to this scenario plus the two most recent untagged ones — all filtered by available_at (no future leakage).
    scenes = list(db.execute(select(Scene).where(Scene.available_at <= dt, Scene.scenario_id.is_(None)).order_by(Scene.observed_at.desc()).limit(2)).scalars().all())
    if state.get("scenario_id"):
        scenes += db.execute(select(Scene).where(Scene.available_at <= dt, Scene.scenario_id == state["scenario_id"])).scalars().all()
    for sc in scenes:
        quality = "poor" if (sc.cloud_fraction or 0) > 0.5 or "unreliable" in (sc.quality_flags or []) else "fair"
        attach_evidence(db, inc, "scene", "scene", sc.id, f"scene:{sc.platform}:{sc.id}", f"{sc.platform} {sc.scene_role} scene acquired {iso(sc.observed_at)}, available {iso(sc.available_at)}; {sc.derived.get('label', 'metadata only')}",
                        quality, sc.observed_at, sc.available_at, sc.feed_id, dt, "observer")
    # Reports filed against the scenario before the incident existed are attached now.
    if state.get("scenario_id"):
        for fr in db.execute(select(FieldReport).where(FieldReport.scenario_id == state["scenario_id"], FieldReport.incident_id.is_(None), FieldReport.available_at <= dt)).scalars().all():
            fr.incident_id = inc.id
    for fr in db.execute(select(FieldReport).where(FieldReport.incident_id == inc.id)).scalars().all():
        quality = "poor" if fr.reliability in {"disputed", "faulty"} or fr.review_status == "rejected" else "fair" if fr.review_status == "pending" else "good"
        attach_evidence(db, inc, "field_report", "field_report", fr.id, f"reporter:{fr.reporter_id}", f"field report by {fr.reporter_id}: {fr.observation_text[:140]} (review {fr.review_status}, reliability {fr.reliability})",
                        quality, fr.capture_time, fr.available_at, None, dt, "observer", conflicts=["reporter reliability disputed"] if fr.reliability in {"disputed", "faulty"} else None)


# ---------------------------------------------------------------------------
# Nodes
def _log(state: IncidentState, msg: str) -> list[str]:
    return [*state.get("log", []), f"{iso(utcnow())} {msg}"]


def ingest(state: IncidentState) -> dict:
    with session_scope() as db:
        inc = db.get(Incident, state["incident_id"])
        inc.status = "open"
        inc.graph_thread_id = state.get("thread_id") or state["incident_id"]
        inc.updated_at = utcnow()
        audit.record(db, "graph", "incident.ingest", "incident", inc.id, {"trigger": state.get("trigger"), "evidence_loop": state.get("evidence_loop", 0)})
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "ingest"})
    return {"log": _log(state, "ingest"), "failed_personas": [], "runs": [], "proposal_id": None, "human_decision": None}


def validate(state: IncidentState) -> dict:
    with session_scope() as db:
        collect_evidence(db, state)
        # Reviewed, non-disputed field reports count as independent sources (one per reporter).
        accepted = db.execute(select(FieldReport).where(FieldReport.incident_id == state["incident_id"], FieldReport.review_status == "accepted",
                                                        FieldReport.reliability.notin_(["disputed", "faulty"]))).scalars().all()
        ctx = {**state.get("context", {}), "field_report_sources": sorted({f"reporter:{f.reporter_id}" for f in accepted})}
        state = {**state, "context": ctx}
        out, run_id, err = run_persona(db, "observer", state)
        inc = db.get(Incident, state["incident_id"])
        inc.status = "assessing"
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "validate"})
    failed = [*state.get("failed_personas", [])] + (["observer"] if err else [])
    return {"observer": out, "context": ctx, "runs": [*state.get("runs", []), run_id], "failed_personas": failed, "log": _log(state, f"validate observer={'error' if err else 'ok'}")}


def assess(state: IncidentState) -> dict:
    upd: dict = {"runs": list(state.get("runs", [])), "failed_personas": list(state.get("failed_personas", []))}
    with session_scope() as db:
        inc = db.get(Incident, state["incident_id"])
        if state["kind"] in {"rainfall", "hse"}:
            out, run_id, err = run_persona(db, "hydrologist", state)
            upd["hydrologist"] = out
            upd["runs"].append(run_id)
            if err:
                upd["failed_personas"].append("hydrologist")
                inc.severity_band = inc.risk_band = "unknown"  # a failed assessment is not a low band
            else:
                inc.severity_band = inc.risk_band = out.get("forecast_band", "unknown")
                inc.label = "forecast_risk"
                inc.summary = {**inc.summary, "hydrology": {k: out.get(k) for k in ("forecast_band", "mechanism", "peak_depth_by_catchment_m", "observed_water_label")}}
                attach_evidence(db, inc, "tool_result", "agent_run", run_id, "tool:water_balance", f"water-balance twin: band {out.get('forecast_band')} ({out.get('mechanism')}) — scenario model, uncalibrated", "good",
                                parse_iso(state["decision_time"]), parse_iso(state["decision_time"]), None, parse_iso(state["decision_time"]), "hydrologist")
        if state["kind"] == "leak":
            out, run_id, err = run_persona(db, "utility_engineer", state)
            upd["utility"] = out
            upd["runs"].append(run_id)
            if err:
                upd["failed_personas"].append("utility_engineer")
                inc.severity_band = inc.risk_band = "unknown"
            else:
                inc.label = {"suspected_incident": "suspected_incident", "anomaly": "anomaly", "insufficient_evidence": "anomaly"}.get(out.get("label"), "anomaly")
                inc.severity_band = inc.risk_band = {"high": "high", "moderate": "moderate"}.get(out.get("anomaly_band"), "low")
                inc.summary = {**inc.summary, "utility": {k: out.get(k) for k in ("anomaly_band", "label", "suspected_segments", "evidence_sufficiency")}}
                if out.get("evidence_sufficiency") != "insufficient":
                    attach_evidence(db, inc, "tool_result", "agent_run", run_id, "tool:pressure_flow", f"residual screen: band {out.get('anomaly_band')}, {out.get('evidence_sufficiency')} evidence", "good",
                                    parse_iso(state["decision_time"]), parse_iso(state["decision_time"]), None, parse_iso(state["decision_time"]), "utility_engineer")
        inc.version += 1
        inc.updated_at = utcnow()
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "assess", "severity_band": inc.severity_band, "label": inc.label})
    upd["log"] = _log(state, "assess")
    return upd


def correlate(state: IncidentState) -> dict:
    upd: dict = {"runs": list(state.get("runs", [])), "failed_personas": list(state.get("failed_personas", []))}
    ctx = state.get("context", {})
    with session_scope() as db:
        inc = db.get(Incident, state["incident_id"])
        if state["kind"] in {"rainfall", "hse"} or ctx.get("hse_relevant"):
            out, run_id, err = run_persona(db, "hse_officer", state)
            upd["hse"] = out
            upd["runs"].append(run_id)
            if err:
                upd["failed_personas"].append("hse_officer")
                inc.consequence = "unknown"
            else:
                inc.consequence = out.get("consequence_band", "unknown")
                inc.asset_ids = [e["asset_id"] for e in out.get("exposed_assets", [])]
                inc.summary = {**inc.summary, "hse": {"consequence_band": inc.consequence, "exposed": len(inc.asset_ids), "routes": out.get("emergency_routes_affected", [])}}
        # Duplicate-event suppression: a sibling incident with the same dedupe key is linked, not duplicated.
        if inc.dedupe_key:
            sib = db.execute(select(Incident).where(Incident.dedupe_key == inc.dedupe_key, Incident.id != inc.id, Incident.status.notin_(["closed", "cancelled"]))).scalars().all()
            if sib:
                inc.summary = {**inc.summary, "duplicates_suppressed": [x.id for x in sib]}
        inc.updated_at = utcnow()
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "correlate", "consequence": inc.consequence})
    upd["log"] = _log(state, "correlate")
    return upd


def coordinate(state: IncidentState) -> dict:
    with session_scope() as db:
        out, run_id, err = run_persona(db, "incident_coordinator", state)
        inc = db.get(Incident, state["incident_id"])
        failed = list(state.get("failed_personas", [])) + (["incident_coordinator"] if err else [])
        if err or any(p in failed for p in ("hydrologist", "utility_engineer", "observer")):
            out = {**out, "escalate_urgent": True, "next_decision": f"urgent human review — persona/model failure: {', '.join(failed)}", "evidence_sufficient": False,
                   "severity_band": out.get("severity_band") or inc.severity_band or "moderate", "label": out.get("label") or inc.label}
        inc.severity_band = out.get("severity_band", inc.severity_band)
        inc.label = out.get("label", inc.label)
        inc.next_decision = out.get("next_decision")
        inc.evidence_quality = {True: "adequate", False: "weak"}[bool(out.get("evidence_sufficient"))]
        inc.updated_at = utcnow()
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "coordinate", "next_decision": inc.next_decision})
    return {"coordinator_pre": out, "runs": [*state.get("runs", []), run_id], "failed_personas": failed, "log": _log(state, f"coordinate → {out.get('next_decision')}")}


def route_after_coordinate(state: IncidentState) -> str:
    c = state.get("coordinator_pre", {})
    s = get_settings()
    if c.get("escalate_urgent"):
        return "urgent_review"
    if not c.get("evidence_sufficient") and state.get("evidence_loop", 0) < s.max_evidence_loops:
        return "request_evidence"
    if not c.get("evidence_sufficient") and c.get("severity_band") in {"high", "severe"}:
        return "urgent_review"
    if c.get("severity_band") == "low" and state["kind"] != "leak":
        return "monitor_only"
    if state["kind"] == "leak" and (state.get("utility") or {}).get("label") == "insufficient_evidence":
        return "request_evidence" if state.get("evidence_loop", 0) < s.max_evidence_loops else "monitor_only"
    return "plan"


def request_evidence(state: IncidentState) -> dict:
    c = state.get("coordinator_pre", {})
    with session_scope() as db:
        inc = db.get(Incident, state["incident_id"])
        inc.status = "awaiting_evidence"
        inc.next_decision = "awaiting requested evidence: " + "; ".join(c.get("missing_evidence", [])[:3])
        inc.summary = {**inc.summary, "evidence_requests": [*inc.summary.get("evidence_requests", []), {"loop": state.get("evidence_loop", 0), "missing": c.get("missing_evidence", []), "at": iso(utcnow())}]}
        inc.updated_at = utcnow()
        audit.record(db, "graph", "evidence.requested", "incident", inc.id, {"missing": c.get("missing_evidence", []), "loop": state.get("evidence_loop", 0)})
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "request_evidence", "missing": c.get("missing_evidence", [])})
    return {"outcome": "awaiting_evidence", "log": _log(state, "request_evidence")}


def urgent_review(state: IncidentState) -> dict:
    c = state.get("coordinator_pre", {})
    with session_scope() as db:
        inc = db.get(Incident, state["incident_id"])
        inc.status = "urgent_human_review"
        inc.next_decision = c.get("next_decision", "urgent human review")
        inc.updated_at = utcnow()
        audit.record(db, "graph", "incident.urgent_review", "incident", inc.id, {"reason": inc.next_decision, "failed_personas": state.get("failed_personas", [])})
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "urgent_review", "reason": inc.next_decision})
    return {"outcome": "urgent_human_review", "log": _log(state, "urgent_review")}


def monitor_only(state: IncidentState) -> dict:
    with session_scope() as db:
        inc = db.get(Incident, state["incident_id"])
        inc.status = "monitoring"
        inc.next_decision = "monitoring — no response package proposed at this band; reassess on new evidence"
        inc.updated_at = utcnow()
        if state.get("trigger", {}).get("reason") == "reassess" and inc.summary.get("had_response"):
            inc.status = "closure_pending"
            inc.next_decision = "closure pending — requires new observation review and incident commander confirmation"
        gateway.enqueue(db, "reassess", {"incident_id": inc.id, "reason": "scheduled monitoring reassessment"}, key=f"reassess:{inc.id}:{inc.version}", delay_s=get_settings().ack_escalation_minutes * 60)
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "monitor_only"})
    return {"outcome": "monitoring", "log": _log(state, "monitor_only")}


def plan(state: IncidentState) -> dict:
    upd: dict = {"runs": list(state.get("runs", [])), "failed_personas": list(state.get("failed_personas", []))}
    specialists = state.get("coordinator_pre", {}).get("specialists", [])
    with session_scope() as db:
        for key, slot in (("response_planner", "planner"), ("communications_officer", "comms"), ("assurance_officer", "assurance")):
            if key not in specialists and key != "assurance_officer":
                continue
            st = {**state, **upd}
            out, run_id, err = run_persona(db, key, st)
            upd[slot] = out
            upd["runs"].append(run_id)
            if err:
                upd["failed_personas"].append(key)
        inc = db.get(Incident, state["incident_id"])
        inc.status = "planning"
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "plan"})
    upd["log"] = _log(state, "plan")
    return upd


def policy_check(state: IncidentState) -> dict:
    planner, comms, assurance = state.get("planner") or {}, state.get("comms") or {}, state.get("assurance") or {}
    actions = [a for a in planner.get("actions", [])]
    with session_scope() as db:
        inc = db.get(Incident, state["incident_id"])
        # Duplicate suppression: actions already dispatched/underway/completed for this incident are not re-proposed on reassessment.
        live = db.execute(select(WorkOrder).where(WorkOrder.incident_id == inc.id, WorkOrder.status.in_(["approved", "dispatched", "acknowledged", "in_progress", "completed"]))).scalars().all()
        live_keys = {(w.kind, w.payload.get("target_asset_id"), w.department) for w in live}
        _k = lambda a: (a.get("kind"), a.get("target_asset_id"), a.get("department"))  # noqa: E731
        suppressed = [a for a in actions if _k(a) in live_keys]
        actions = [a for a in actions if _k(a) not in live_keys]
        if suppressed and not actions:
            inc.status = "closure_pending" if (state.get("hydrologist") or {}).get("forecast_risk_band") in {"low", "moderate"} or state.get("outcome") == "monitoring" else "responding"
            inc.next_decision = (f"reassessment v{inc.version}: all {len(suppressed)} planned actions already underway or completed — no new proposal; "
                                 + ("await human-confirmed closure after new observation" if inc.status == "closure_pending" else "continue monitoring active work orders"))
            inc.updated_at = utcnow()
            audit.record(db, "graph", "incident.duplicate_suppressed", "incident", inc.id, {"suppressed": [a.get("action_type") for a in suppressed]})
            events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "policy_check", "policy": "duplicate_suppressed"})
            return {"outcome": "monitoring", "proposal_id": None, "log": _log(state, f"policy_check: {len(suppressed)} duplicate actions suppressed; no new proposal")}
        if "response_planner" in state.get("failed_personas", []) or not actions:
            inc.status = "urgent_human_review"
            inc.next_decision = "urgent human review — no feasible plan produced" if not actions else "urgent human review — planner failed"
            audit.record(db, "graph", "incident.urgent_review", "incident", inc.id, {"reason": inc.next_decision})
            events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "policy_check"})
            return {"outcome": "urgent_human_review", "proposal_id": None, "log": _log(state, "policy_check: no plan")}
        completeness = assurance.get("evidence_completeness", "weak")
        # Assurance abstention/challenge is recorded; the deterministic engine decides independently.
        pd = policy.check_proposal(db, inc, actions, comms.get("text_en", ""), assurance, completeness)
        decision = {"id": pd.id, "decision": pd.decision, "reasons": pd.reasons, "checks": pd.checks}
        if pd.decision == "deny":
            inc.status = "urgent_human_review"
            inc.next_decision = "urgent human review — policy denied proposal: " + "; ".join(pd.reasons[:2])
            events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "policy_check", "policy": "deny"})
            return {"policy_decision": decision, "outcome": "urgent_human_review", "proposal_id": None, "log": _log(state, "policy_check: deny")}
        p = gateway.create_proposal(db, inc, actions, comms.get("text_en", ""), comms.get("text_ar", ""), comms.get("recipients", []),
                                    planner.get("assumptions", []) + ([f"policy review flags: {'; '.join(pd.reasons)}"] if pd.reasons else []) + ([f"assurance {assurance.get('verdict')}: {'; '.join(assurance.get('reasons', []))}"] if assurance.get("verdict") in {"challenge", "abstain"} else []),
                                    "graph:incident_coordinator", pd.id, inc.geometry)
        inc.status = "awaiting_approval"
        inc.next_decision = f"human approval of proposal v{p.version} ({len(actions)} actions)" + (" — policy flagged for review" if pd.decision == "review" else "")
        inc.evidence_quality = completeness
        inc.summary = {**inc.summary, "had_response": True}
        inc.updated_at = utcnow()
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "policy_check", "policy": pd.decision, "proposal_id": p.id})
        pid = p.id
    return {"policy_decision": decision, "proposal_id": pid, "outcome": "awaiting_approval", "log": _log(state, f"policy_check: {pd.decision} → proposal {pid}")}


def route_after_policy(state: IncidentState) -> str:
    return "human_review" if state.get("proposal_id") else END


def human_review(state: IncidentState) -> dict:
    decision = interrupt({"kind": "approval", "incident_id": state["incident_id"], "proposal_id": state["proposal_id"]})
    return {"human_decision": decision, "log": _log(state, f"human_review: {decision.get('decision')}")}


def route_after_review(state: IncidentState) -> str:
    return "execute" if (state.get("human_decision") or {}).get("decision") == "approved" else "monitor"


def execute(state: IncidentState) -> dict:
    hd = state.get("human_decision") or {}
    with session_scope() as db:
        results = gateway.dispatch_approved(db, state["incident_id"], hd["approval_id"])
    return {"outcome": "dispatched", "log": _log(state, f"execute: {len(results)} work orders processed via simulated connectors")}


def monitor(state: IncidentState) -> dict:
    hd = state.get("human_decision") or {}
    with session_scope() as db:
        inc = db.get(Incident, state["incident_id"])
        if inc.status not in {"urgent_human_review"}:
            inc.status = "responding" if hd.get("decision") == "approved" else "monitoring"
        inc.next_decision = ("await departmental acknowledgements and completion; reassess on completion or timer" if hd.get("decision") == "approved"
                             else "proposal rejected — continue monitoring; reassess on new evidence")
        inc.updated_at = utcnow()
        gateway.enqueue(db, "reassess", {"incident_id": inc.id, "reason": "scheduled reassessment after response"}, key=f"reassess:{inc.id}:{inc.version}:timer",
                        delay_s=get_settings().ack_escalation_minutes * 60)
        events.publish("incident", {"incident_id": inc.id, "status": inc.status, "step": "monitor"})
    return {"outcome": "monitoring", "log": _log(state, "monitor")}


# ---------------------------------------------------------------------------
def build_graph(checkpointer: BaseCheckpointSaver):
    g = StateGraph(IncidentState)
    for name, fn in [("ingest", ingest), ("validate", validate), ("assess", assess), ("correlate", correlate), ("coordinate", coordinate), ("request_evidence", request_evidence),
                     ("urgent_review", urgent_review), ("monitor_only", monitor_only), ("plan", plan), ("policy_check", policy_check), ("human_review", human_review),
                     ("execute", execute), ("monitor", monitor)]:
        g.add_node(name, fn)
    g.add_edge(START, "ingest")
    g.add_edge("ingest", "validate")
    g.add_edge("validate", "assess")
    g.add_edge("assess", "correlate")
    g.add_edge("correlate", "coordinate")
    g.add_conditional_edges("coordinate", route_after_coordinate, ["request_evidence", "urgent_review", "monitor_only", "plan"])
    g.add_edge("request_evidence", END)
    g.add_edge("urgent_review", END)
    g.add_edge("monitor_only", END)
    g.add_edge("plan", "policy_check")
    g.add_conditional_edges("policy_check", route_after_policy, ["human_review", END])
    g.add_conditional_edges("human_review", route_after_review, ["execute", "monitor"])
    g.add_edge("execute", "monitor")
    g.add_edge("monitor", END)
    return g.compile(checkpointer=checkpointer)


def checkpoint_db_path() -> str:
    main_path = get_settings().database_url.replace("sqlite:///", "")
    return str(Path(main_path).with_name(Path(main_path).stem + "_checkpoints.db")) if main_path != ":memory:" else ":memory:"


def make_checkpointer() -> BaseCheckpointSaver:
    s = get_settings()
    if s.is_sqlite:
        from langgraph.checkpoint.sqlite import SqliteSaver
        path = checkpoint_db_path()
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        saver = SqliteSaver(conn)
        saver.setup()
        return saver
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import Connection
    conn = Connection.connect(s.database_url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True, prepare_threshold=0)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver


# ---------------------------------------------------------------------------
# Context construction from a scenario
def build_context(db: Session, scenario: Scenario, kind: str) -> dict:
    p = scenario.params or {}
    ctx = {"focus_sensor_ids": p.get("focus_sensor_ids", []), "focus_asset_ids": p.get("focus_asset_ids", []), "catchment_ids": p.get("catchment_ids", []),
           "controls": dict(p.get("controls", {})), "flow_sensor_id": p.get("flow_sensor_id"), "pressure_sensor_id": p.get("pressure_sensor_id"),
           "depot_node": p.get("depot_node", "N_depot"), "target_node": p.get("target_node", "N_underpass"), "area_name": p.get("area_name", "Demonstration area"),
           "hse_relevant": p.get("hse_relevant", kind != "leak"), "window": p.get("window", ["now", "+3 h"])}
    if ctx["focus_asset_ids"]:
        a = db.get(Asset, ctx["focus_asset_ids"][0])
        ctx["focus_asset_name"] = a.name if a else ctx["focus_asset_ids"][0]
    # Completed pump deployments add capacity (recorded on the catchment by the gateway at completion only).
    extra = 0.0
    for cid in ctx["catchment_ids"]:
        c = db.get(Catchment, cid)
        if c:
            extra += float(c.assumptions.get("deployed_extra_pump_m3_s", 0.0))
    ctx["controls"]["extra_pump_m3_s"] = ctx["controls"].get("extra_pump_m3_s", 0.0) + extra
    return ctx
