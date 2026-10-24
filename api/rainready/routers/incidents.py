"""Incidents, proposals, approvals, work orders, assistant and closure."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, events, gateway
from ..agents import runner
from ..agents.personas import persona_cards
from ..auth import Identity, current_identity, require
from ..clock import iso, to_dubai, utcnow
from ..config import get_settings
from ..db import get_db
from ..models import (AgentRun, Approval, DispatchReceipt, Evidence, FieldReport, Incident, Observation, PolicyDecision, Proposal, ToolResult, WorkOrder)
from ..providers.guard import separate
from ..schemas import ApprovalIn, AssistantIn, CloseIncidentIn, ProposalReviseIn, WorkOrderTransitionIn

router = APIRouter(prefix="/api", tags=["incidents"])


def inc_dict(i: Incident) -> dict:
    return {"id": i.id, "version": i.version, "scenario_id": i.scenario_id, "kind": i.kind, "title": i.title, "title_ar": i.title_ar, "label": i.label, "status": i.status,
            "severity_band": i.severity_band, "risk_band": i.risk_band, "consequence": i.consequence, "evidence_quality": i.evidence_quality, "calibrated_probability": i.calibrated_probability,
            "probability_note": "no calibrated model — ordinal bands only" if i.calibrated_probability is None else None, "asset_ids": i.asset_ids, "jurisdiction": i.jurisdiction,
            "summary": i.summary, "next_decision": i.next_decision, "geometry": i.geometry, "created_at": iso(i.created_at), "updated_at": iso(i.updated_at),
            "created_at_dubai": to_dubai(i.created_at).isoformat(), "closed_at": iso(i.closed_at), "closed_by": i.closed_by}


@router.get("/incidents")
def list_incidents(ident: Identity = Depends(current_identity), db: Session = Depends(get_db), include_closed: bool = False):
    q = select(Incident).order_by(Incident.created_at.desc())
    rows = [i for i in db.execute(q).scalars().all() if ident.in_scope(i.jurisdiction) and (include_closed or i.status not in {"closed", "cancelled"})]
    return [inc_dict(i) for i in rows]


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    i = db.get(Incident, incident_id)
    if not i or not ident.in_scope(i.jurisdiction):
        raise HTTPException(404, "incident not found")
    ev = db.execute(select(Evidence).where(Evidence.incident_id == i.id).order_by(Evidence.created_at)).scalars().all()
    runs = db.execute(select(AgentRun).where(AgentRun.incident_id == i.id).order_by(AgentRun.started_at)).scalars().all()
    tools = db.execute(select(ToolResult).where(ToolResult.incident_id == i.id).order_by(ToolResult.created_at)).scalars().all()
    props = db.execute(select(Proposal).where(Proposal.incident_id == i.id).order_by(Proposal.version)).scalars().all()
    aps = db.execute(select(Approval).where(Approval.incident_id == i.id).order_by(Approval.created_at)).scalars().all()
    wos = db.execute(select(WorkOrder).where(WorkOrder.incident_id == i.id).order_by(WorkOrder.created_at)).scalars().all()
    pds = db.execute(select(PolicyDecision).where(PolicyDecision.incident_id == i.id).order_by(PolicyDecision.created_at)).scalars().all()
    frs = db.execute(select(FieldReport).where(FieldReport.incident_id == i.id)).scalars().all()
    receipts = {r.work_order_id: r.receipt for r in db.execute(select(DispatchReceipt).where(DispatchReceipt.work_order_id.in_([w.id for w in wos]))).scalars().all()} if wos else {}
    pending = runner.pending_interrupt(i.id, i.graph_thread_id or i.id)
    return {**inc_dict(i), "pending_interrupt": pending,
            "evidence": [{"id": e.id, "kind": e.kind, "ref_type": e.ref_type, "ref_id": e.ref_id, "source_key": e.independent_source_key, "summary": e.summary, "quality": e.quality, "freshness": e.freshness,
                          "observed_at": iso(e.observed_at), "available_at": iso(e.available_at), "conflicts_with": e.conflicts_with, "added_by": e.added_by} for e in ev],
            "independent_sources": len({e.independent_source_key for e in ev}),
            "agent_runs": [{"id": r.id, "persona": r.persona, "status": r.status, "provider": r.provider, "model_id": r.model_id, "model_exercised": r.model_exercised, "started_at": iso(r.started_at), "finished_at": iso(r.finished_at),
                            "tool_call_count": r.tool_call_count, "token_count": r.token_count, "limits": r.limits, "output": r.output, "knowledge_used": r.knowledge_used, "thread_id": r.thread_id} for r in runs],
            "tool_results": [{"id": t.id, "run_id": t.run_id, "persona": t.persona, "tool": t.tool, "version": t.tool_version, "args": t.args, "ok": t.ok, "duration_ms": t.duration_ms, "created_at": iso(t.created_at),
                              "result": _trim(t.result)} for t in tools],
            "proposals": [prop_dict(p) for p in props],
            "approvals": [{"id": a.id, "proposal_id": a.proposal_id, "proposal_version": a.proposal_version, "incident_version": a.incident_version, "payload_hash": a.payload_hash, "intended_tools": a.intended_tools,
                           "destinations": a.destinations, "approver_id": a.approver_id, "approver_role": a.approver_role, "decision": a.decision, "note": a.note, "expires_at": iso(a.expires_at), "status": a.status,
                           "consumed_at": iso(a.consumed_at), "created_at": iso(a.created_at)} for a in aps],
            "work_orders": [wo_dict(w, receipts.get(w.id)) for w in wos],
            "policy_decisions": [{"id": p.id, "subject_type": p.subject_type, "subject_id": p.subject_id, "actor": p.actor, "decision": p.decision, "reasons": p.reasons, "checks": p.checks, "created_at": iso(p.created_at)} for p in pds],
            "field_reports": [fr_dict(f) for f in frs]}


def _trim(result: dict) -> dict:
    out = dict(result)
    if "series" in out:
        out["series"] = {k: v[:12] for k, v in out["series"].items()} if isinstance(out["series"], dict) else out["series"]
    return out


def prop_dict(p: Proposal) -> dict:
    return {"id": p.id, "incident_id": p.incident_id, "version": p.version, "incident_version": p.incident_version, "status": p.status, "actions": p.actions, "public_text_en": p.public_text_en,
            "public_text_ar": p.public_text_ar, "translation_status": p.translation_status, "recipients": p.recipients, "assumptions": p.assumptions, "payload_hash": p.payload_hash,
            "created_by": p.created_by, "created_at": iso(p.created_at), "policy_decision_id": p.policy_decision_id, "area": p.geometry}


def wo_dict(w: WorkOrder, receipt: dict | None = None) -> dict:
    return {"id": w.id, "incident_id": w.incident_id, "proposal_id": w.proposal_id, "approval_id": w.approval_id, "action_index": w.action_index, "kind": w.kind, "department": w.department, "connector": w.connector,
            "status": w.status, "payload": w.payload, "retry_count": w.retry_count, "dispatched_at": iso(w.dispatched_at), "acknowledged_at": iso(w.acknowledged_at), "completed_at": iso(w.completed_at),
            "escalation_due_at": iso(w.escalation_due_at), "physical_effect": w.physical_effect, "physical_effect_applied": w.status == "completed" and bool(w.physical_effect), "receipt": receipt, "created_at": iso(w.created_at)}


def fr_dict(f: FieldReport) -> dict:
    return {"id": f.id, "reporter_id": f.reporter_id, "scenario_id": f.scenario_id, "incident_id": f.incident_id, "capture_time": iso(f.capture_time), "created_at": iso(f.created_at), "description": f.description,
            "observation_text": f.observation_text, "isolated_instructions": f.isolated_instructions, "has_photo": bool(f.photo_path), "photo_mime": f.photo_mime, "photo_sha256": f.photo_sha256,
            "reliability": f.reliability, "review_status": f.review_status, "safety_flags": f.safety_flags, "reviewed_by": f.reviewed_by, "geometry": f.geometry, "quality_flags": f.quality_flags}


# ---------------------------------------------------------------------------
@router.post("/approvals")
def create_approval(body: ApprovalIn, ident: Identity = Depends(current_identity), db: Session = Depends(get_db), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    key = idempotency_key or f"auto-{ident.id}-{body.proposal_id}-{body.decision}-{uuid.uuid4().hex[:8]}"
    try:
        res = gateway.approve(db, ident, body.proposal_id, body.action_indexes, body.decision, body.note, key)
    except gateway.GatewayError as e:
        raise HTTPException(e.status, e.detail)
    db.commit()
    return res


@router.post("/proposals/{proposal_id}/revise")
def revise(proposal_id: str, body: ProposalReviseIn, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    p = db.get(Proposal, proposal_id)
    if not p:
        raise HTTPException(404, "proposal not found")
    if not any(ident.may_approve(a["kind"]) for a in p.actions):
        raise HTTPException(403, "only a role with approval authority over the proposal may revise it")
    if p.status not in {"proposed"}:
        raise HTTPException(409, f"proposal is {p.status}; only proposed versions can be revised")
    inc = db.get(Incident, p.incident_id)
    inc.version += 1  # edits change the decision basis; approvals bound to the old version/hash become invalid
    new = gateway.revise_proposal(db, ident, p, body.public_text_en, body.public_text_ar, body.recipients, body.drop_action_indexes)
    inc.next_decision = f"human approval of revised proposal v{new.version}"
    # The graph stays parked at its approval interrupt; approving the new version resumes it with the new approval id.
    return prop_dict(new)


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    p = db.get(Proposal, proposal_id)
    if not p:
        raise HTTPException(404, "proposal not found")
    return prop_dict(p)


@router.get("/work-orders")
def list_work_orders(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    rows = db.execute(select(WorkOrder).order_by(WorkOrder.created_at.desc()).limit(200)).scalars().all()
    return [wo_dict(w) for w in rows]


@router.post("/work-orders/{wo_id}/transition")
def transition(wo_id: str, body: WorkOrderTransitionIn, ident: Identity = Depends(require("workorder:ack")), db: Session = Depends(get_db)):
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "work order not found")
    try:
        gateway.transition_work_order(db, ident.id, wo, body.status, body.note, simulated=True)
    except gateway.GatewayError as e:
        raise HTTPException(e.status, e.detail)
    return wo_dict(wo)


@router.post("/incidents/{incident_id}/reassess")
def reassess(incident_id: str, ident: Identity = Depends(require("scenario:run")), db: Session = Depends(get_db)):
    i = db.get(Incident, incident_id)
    if not i:
        raise HTTPException(404, "incident not found")
    if i.status in {"closed", "cancelled"}:
        raise HTTPException(409, f"incident is {i.status}")
    n = int(i.summary.get("manual_reassess_requests", 0)) + 1
    i.summary = {**i.summary, "manual_reassess_requests": n}
    job = gateway.enqueue(db, "reassess", {"incident_id": i.id, "reason": f"manual reassessment by {ident.id}"}, key=f"reassess:{i.id}:manual:{n}")
    return {"queued": True, "job_id": job.id if job else None}


@router.post("/incidents/{incident_id}/close")
def close_incident(incident_id: str, body: CloseIncidentIn, ident: Identity = Depends(require("incident:close")), db: Session = Depends(get_db)):
    i = db.get(Incident, incident_id)
    if not i:
        raise HTTPException(404, "incident not found")
    if i.status not in {"closure_pending", "monitoring", "responding"}:
        raise HTTPException(409, f"incident in status {i.status} cannot be closed; a reassessment must bring it to monitoring/closure_pending first")
    # Require a *new* observation newer than the last response action, authored by a non-agent source.
    ref = body.new_observation_ref
    newer_than = max([w.completed_at or w.dispatched_at or w.created_at for w in db.execute(select(WorkOrder).where(WorkOrder.incident_id == i.id)).scalars().all()] + [i.created_at])
    obs = db.get(Observation, ref)
    fr = db.get(FieldReport, ref)
    candidate_time = (obs.available_at if obs else None) or (fr.available_at if fr else None)
    if candidate_time is None or candidate_time < newer_than:
        raise HTTPException(409, "closure requires a new observation or reviewed field report received after the last response action")
    if fr and fr.review_status != "accepted":
        raise HTTPException(409, "the field report used for closure must be reviewed and accepted")
    i.status, i.closed_at, i.closed_by = "closed", utcnow(), ident.id
    i.next_decision = "closed by incident commander after new observation review"
    i.version += 1
    if body.after_action is not None:
        aar = body.after_action.model_dump()
        i.summary = {**i.summary, "after_action_review": {**aar, "recorded_by": ident.id, "recorded_at": iso(utcnow())}}
    # Stand down any work order still open: a closed incident must not leave live tasking behind (simulated connectors only).
    stood_down = []
    for w in db.execute(select(WorkOrder).where(WorkOrder.incident_id == i.id, WorkOrder.status.in_(["approved", "dispatched", "acknowledged", "in_progress"]))).scalars().all():
        w.status = "cancelled"
        w.payload = {**w.payload, "stood_down_at_closure": True}
        stood_down.append(w.id)
    if stood_down:
        audit.record(db, ident.id, "workorder.stood_down", "incident", i.id, {"work_orders": stood_down, "reason": "incident closed by commander"})
        events.publish("work_order", {"incident_id": i.id, "stood_down": stood_down})
    audit.record(db, ident.id, "incident.closed", "incident", i.id, {"note": body.confirmation_note, "observation_ref": ref, "after_action_review": body.after_action is not None})
    events.publish("incident", {"incident_id": i.id, "status": "closed"})
    return inc_dict(i)


@router.get("/incidents/{incident_id}/sitrep")
def sitrep(incident_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    """Situation report assembled only from persisted state (incident, evidence, proposals, approvals, work
    orders).  Section layout is adapted from the incident-briefing pattern used in incident command systems
    (situation, evidence, decisions, resources, open items, operational period, caveats).  Nothing is inferred."""
    i = db.get(Incident, incident_id)
    if not i or not ident.in_scope(i.jurisdiction):
        raise HTTPException(404, "incident not found")
    ev = db.execute(select(Evidence).where(Evidence.incident_id == i.id)).scalars().all()
    props = db.execute(select(Proposal).where(Proposal.incident_id == i.id).order_by(Proposal.version)).scalars().all()
    aps = db.execute(select(Approval).where(Approval.incident_id == i.id)).scalars().all()
    wos = db.execute(select(WorkOrder).where(WorkOrder.incident_id == i.id).order_by(WorkOrder.created_at)).scalars().all()
    frs = db.execute(select(FieldReport).where(FieldReport.incident_id == i.id)).scalars().all()
    runs = db.execute(select(AgentRun).where(AgentRun.incident_id == i.id)).scalars().all()
    now = utcnow()
    hyd, hse, util = i.summary.get("hydrology") or {}, i.summary.get("hse") or {}, i.summary.get("utility") or {}
    latest = props[-1] if props else None
    open_wos = [w for w in wos if w.status in {"approved", "dispatched", "acknowledged", "in_progress"}]
    report = {
        "incident_id": i.id, "version": i.version, "generated_at": iso(now), "generated_at_dubai": to_dubai(now).isoformat(), "generated_by": ident.id,
        "basis": "persisted state only — no model narration",
        "operational_period": {"start": iso(i.created_at), "start_dubai": to_dubai(i.created_at).isoformat(), "elapsed_minutes": int((now - i.created_at).total_seconds() // 60),
                               "status": i.status, "closed_at": iso(i.closed_at)},
        "situation": {"title": i.title, "title_ar": i.title_ar, "label": i.label, "severity_band": i.severity_band, "consequence_band": i.consequence, "evidence_quality": i.evidence_quality,
                      "mechanism": hyd.get("mechanism"), "observed_water": hyd.get("observed_water_label"), "forecast_band": hyd.get("forecast_band"),
                      "anomaly_band": util.get("anomaly_band"), "exposed_assets": i.asset_ids, "emergency_routes_affected": hse.get("routes", []),
                      "probability_note": "no calibrated model — ordinal bands only"},
        "evidence": {"items": len(ev), "independent_sources": len({e.independent_source_key for e in ev}), "stale": [e.id for e in ev if e.freshness == "stale"],
                     "conflicts": [e.id for e in ev if e.conflicts_with], "poor_quality": [e.id for e in ev if e.quality == "poor"],
                     "field_reports": {"total": len(frs), "accepted": sum(1 for f in frs if f.review_status == "accepted"), "pending": sum(1 for f in frs if f.review_status == "pending"),
                                       "with_isolated_instructions": sum(1 for f in frs if f.isolated_instructions)},
                     "persona_failures": sorted({r.persona for r in runs if r.status == "failed"})},
        "decisions": {"proposals": len(props), "latest_proposal": ({"id": latest.id, "version": latest.version, "status": latest.status, "actions": [a.get("kind") for a in latest.actions],
                                                                      "payload_hash": latest.payload_hash} if latest else None),
                      "approvals": [{"decision": a.decision, "status": a.status, "approver_role": a.approver_role, "expires_at": iso(a.expires_at)} for a in aps]},
        "resources": [{"id": w.id, "kind": w.kind, "department": w.department, "status": w.status, "connector": w.connector, "physical_effect_applied": w.status == "completed" and bool(w.physical_effect),
                       "escalation_due_at": iso(w.escalation_due_at)} for w in wos],
        "open_items": ([i.next_decision] if i.status not in {"closed", "cancelled"} else []) + [f"work order {w.id} ({w.kind}) is {w.status}" for w in open_wos]
                      + [f"field report {f.id} awaiting review" for f in frs if f.review_status == "pending"],
        "caveats": ["All data synthetic; connectors simulated; advisory drafts require human approval.", "Hazard numbers come from versioned tools labelled 'scenario model — uncalibrated'.",
                    "Acknowledgement of a work order does not change physical state; only completion does."],
        "after_action_review": i.summary.get("after_action_review"),
    }
    audit.record(db, ident.id, "sitrep.generated", "incident", i.id, {"version": i.version})
    return report


@router.post("/incidents/{incident_id}/cancel")
def cancel_incident(incident_id: str, ident: Identity = Depends(require("incident:cancel")), db: Session = Depends(get_db)):
    i = db.get(Incident, incident_id)
    if not i:
        raise HTTPException(404, "incident not found")
    i.status = "cancelled"
    i.version += 1
    for a in db.execute(select(Approval).where(Approval.incident_id == i.id, Approval.status == "active")).scalars().all():
        a.status = "invalidated"
    for w in db.execute(select(WorkOrder).where(WorkOrder.incident_id == i.id, WorkOrder.status.in_(["approved", "dispatched", "acknowledged", "in_progress"]))).scalars().all():
        w.status = "cancelled"
    audit.record(db, ident.id, "incident.cancelled", "incident", i.id, {})
    events.publish("incident", {"incident_id": i.id, "status": "cancelled"})
    return inc_dict(i)


@router.get("/agents/personas")
def personas(ident: Identity = Depends(current_identity)):
    return persona_cards()


@router.post("/incidents/{incident_id}/assistant")
def assistant(incident_id: str, body: AssistantIn, ident: Identity = Depends(require("assistant:ask")), db: Session = Depends(get_db)):
    """Bounded incident assistant: explains why an area was flagged using *stored* evidence and
    tool results only.  It has no tools that change state and no action authority; imperative
    content in the question is isolated and reported."""
    i = db.get(Incident, incident_id)
    if not i or not ident.in_scope(i.jurisdiction):
        raise HTTPException(404, "incident not found")
    sep = separate(body.question)
    ev = db.execute(select(Evidence).where(Evidence.incident_id == i.id)).scalars().all()
    tools = db.execute(select(ToolResult).where(ToolResult.incident_id == i.id, ToolResult.ok.is_(True)).order_by(ToolResult.created_at.desc())).scalars().all()
    hyd = i.summary.get("hydrology") or {}
    util = i.summary.get("utility") or {}
    lines = [f"{i.title} is labelled '{i.label.replace('_', ' ')}' at band '{i.severity_band}' (consequence '{i.consequence}', evidence '{i.evidence_quality}')."]
    if hyd:
        lines.append(f"The water-balance twin (scenario model — uncalibrated) projects band {hyd.get('forecast_band')} via a {hyd.get('mechanism')} mechanism; peak synthetic depths: {hyd.get('peak_depth_by_catchment_m')}. Observed-water status: {hyd.get('observed_water_label')}.")
    if util:
        lines.append(f"The residual screen reports anomaly band {util.get('anomaly_band')} with {util.get('evidence_sufficiency')} evidence; suspected segments {util.get('suspected_segments')}.")
    lines.append(f"Evidence attached: {len(ev)} items from {len({e.independent_source_key for e in ev})} independent sources; stale: {[e.id for e in ev if e.freshness == 'stale']}; conflicts: {[e.id for e in ev if e.conflicts_with]}.")
    lines.append(f"Next decision: {i.next_decision}")
    cited = [{"type": "evidence", "id": e.id, "summary": e.summary, "freshness": e.freshness} for e in ev[:8]] + [{"type": "tool_result", "id": t.id, "tool": t.tool, "version": t.tool_version} for t in tools[:6]]
    if sep.instructions:
        audit.record(db, ident.id, "assistant.instruction_isolated", "incident", i.id, {"instructions": sep.instructions})
    audit.record(db, ident.id, "assistant.asked", "incident", i.id, {"question": sep.observations[:200]})
    return {"answer": " ".join(lines), "basis": "deterministic summary of stored evidence and tool results (demo provider)" if get_settings().model_provider == "demo" else "stored evidence summary (model narration not enabled for the assistant)",
            "cited_inputs": cited, "isolated_instructions": sep.instructions, "authority": "none — the assistant cannot approve, dispatch or publish",
            "note": "Instructions embedded in the question were isolated and not acted upon." if sep.instructions else None}
