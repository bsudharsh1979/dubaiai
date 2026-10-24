"""Approval-bound action gateway — the single server-side path for any action.

* Proposals are immutable; a revision creates a new version and invalidates approvals.
* An approval binds incident id + version, proposal id + version, canonical payload
  hash, intended action kinds, destinations, approver identity/role and expiry.
* Work orders are created per approved action with a unique idempotency key, so
  retries, double clicks and process restarts cannot create duplicates.
* Dispatch is simulated (receipts are generated locally).  There is no endpoint
  that controls a valve, breaker or evacuation.
* Acknowledgement ≠ completion: a department acknowledging a work order never changes
  the modelled physical state; only a completion record applies ``physical_effect``.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit, events, policy
from .audit import payload_hash
from .auth import Identity
from .clock import iso, utcnow
from .config import get_settings
from .models import Approval, Asset, Catchment, DispatchReceipt, Incident, Job, Proposal, WorkOrder, new_id


class GatewayError(Exception):
    def __init__(self, status: int, detail: str, code: str = "gateway"):
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


def proposal_payload(actions: list[dict], text_en: str, text_ar: str, recipients: list[str], area: dict | None) -> dict:
    return {"actions": actions, "public_text_en": text_en, "public_text_ar": text_ar, "recipients": recipients, "area": area}


def create_proposal(db: Session, incident: Incident, actions: list[dict], text_en: str, text_ar: str, recipients: list[str], assumptions: list[str],
                    created_by: str, policy_decision_id: str | None, area: dict | None = None) -> Proposal:
    prev = db.execute(select(Proposal).where(Proposal.incident_id == incident.id).order_by(Proposal.version.desc()).limit(1)).scalar_one_or_none()
    version = (prev.version + 1) if prev else 1
    if prev and prev.status == "proposed":
        prev.status = "superseded"
        for ap in db.execute(select(Approval).where(Approval.proposal_id == prev.id, Approval.status == "active")).scalars().all():
            ap.status = "invalidated"
    p = Proposal(id=new_id("prop"), incident_id=incident.id, version=version, incident_version=incident.version, status="proposed", actions=actions,
                 public_text_en=text_en, public_text_ar=text_ar, recipients=recipients, assumptions=assumptions,
                 payload_hash=payload_hash(proposal_payload(actions, text_en, text_ar, recipients, area)), created_by=created_by, created_at=utcnow(),
                 policy_decision_id=policy_decision_id, geometry=area)
    db.add(p)
    db.flush()
    audit.record(db, created_by, "proposal.created", "proposal", p.id, {"incident_id": incident.id, "version": version, "payload_hash": p.payload_hash, "actions": [a["kind"] for a in actions]})
    events.publish("proposal", {"incident_id": incident.id, "proposal_id": p.id, "version": version, "status": "proposed"})
    return p


def revise_proposal(db: Session, ident: Identity, proposal: Proposal, text_en: str | None, text_ar: str | None, recipients: list[str] | None, drop_action_indexes: list[int]) -> Proposal:
    incident = db.get(Incident, proposal.incident_id)
    actions = [a for i, a in enumerate(proposal.actions) if i not in set(drop_action_indexes)]
    new = create_proposal(db, incident, actions, text_en if text_en is not None else proposal.public_text_en, text_ar if text_ar is not None else proposal.public_text_ar,
                          recipients if recipients is not None else proposal.recipients, proposal.assumptions + [f"revised by {ident.role} {ident.id}"], ident.id, proposal.policy_decision_id, proposal.geometry)
    new.translation_status = "draft-unreviewed" if text_ar is not None else proposal.translation_status
    audit.record(db, ident.id, "proposal.revised", "proposal", new.id, {"supersedes": proposal.id, "invalidated_approvals": True})
    return new


def approve(db: Session, ident: Identity, proposal_id: str, action_indexes: list[int] | None, decision: str, note: str, idempotency_key: str) -> dict:
    s = get_settings()
    existing = db.execute(select(Approval).where(Approval.idempotency_key == idempotency_key)).scalar_one_or_none()
    if existing:
        return {"approval_id": existing.id, "status": existing.status, "decision": existing.decision, "idempotent_replay": True,
                "work_orders": [w.id for w in db.execute(select(WorkOrder).where(WorkOrder.approval_id == existing.id)).scalars().all()]}
    proposal = db.get(Proposal, proposal_id)
    if not proposal:
        raise GatewayError(404, "proposal not found")
    incident = db.get(Incident, proposal.incident_id)
    idx = action_indexes if action_indexes is not None else [i for i, a in enumerate(proposal.actions) if ident.may_approve(a["kind"])]
    if not idx:
        raise GatewayError(403, f"role {ident.role} has no approval authority over any action in this proposal", "no_authority")
    pd = policy.check_approval_request(db, ident, incident, proposal, idx)
    if pd.decision != "allow":
        raise GatewayError(403, "; ".join(pd.reasons), "policy_denied")
    kinds = [proposal.actions[i]["kind"] for i in idx]
    ap = Approval(id=new_id("apr"), incident_id=incident.id, proposal_id=proposal.id, proposal_version=proposal.version, incident_version=incident.version,
                  payload_hash=proposal.payload_hash, intended_tools=kinds, destinations=[proposal.actions[i].get("department") for i in idx] + (proposal.recipients if "advisory" in kinds else []),
                  approver_id=ident.id, approver_role=ident.role, decision=decision, note=note or "", expires_at=utcnow() + timedelta(minutes=s.approval_ttl_minutes),
                  status="active", idempotency_key=idempotency_key, created_at=utcnow())
    db.add(ap)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        # Lost a race with an identical request (double click / retry): return the stored outcome.
        db.expunge(ap)
        existing = db.execute(select(Approval).where(Approval.idempotency_key == idempotency_key)).scalar_one()
        return {"approval_id": existing.id, "status": existing.status, "decision": existing.decision, "idempotent_replay": True,
                "work_orders": [w.id for w in db.execute(select(WorkOrder).where(WorkOrder.approval_id == existing.id)).scalars().all()]}
    audit.record(db, ident.id, f"approval.{decision}", "approval", ap.id, {"proposal_id": proposal.id, "proposal_version": proposal.version, "payload_hash": proposal.payload_hash,
                                                                         "incident_version": incident.version, "actions": kinds, "expires_at": iso(ap.expires_at), "role": ident.role})
    wo_ids = []
    if decision == "approved":
        for i in idx:
            a = proposal.actions[i]
            key = f"{proposal.id}:{i}"
            if db.execute(select(WorkOrder).where(WorkOrder.idempotency_key == key)).scalar_one_or_none():
                continue
            wo = WorkOrder(id=new_id("wo"), incident_id=incident.id, proposal_id=proposal.id, approval_id=ap.id, action_index=i, kind=a["kind"], department=a.get("department", ""),
                           connector="simulated", status="approved", payload={"summary": a.get("summary"), "target_asset_id": a.get("target_asset_id"), "crew_id": a.get("crew_id"),
                                                                              "route": a.get("route"), "public_text_en": proposal.public_text_en if a["kind"] == "advisory" else None,
                                                                              "public_text_ar": proposal.public_text_ar if a["kind"] == "advisory" else None,
                                                                              "recipients": proposal.recipients if a["kind"] == "advisory" else None},
                           idempotency_key=key, physical_effect=a.get("physical_effect") or {}, created_at=utcnow())
            db.add(wo)
            wo_ids.append(wo.id)
        db.flush()
        remaining = [i for i, a in enumerate(proposal.actions) if not db.execute(select(WorkOrder).where(WorkOrder.idempotency_key == f"{proposal.id}:{i}")).scalar_one_or_none()]
        if not remaining:
            proposal.status = "approved"
        incident.status = "awaiting_execution"
        enqueue(db, "resume_graph", {"incident_id": incident.id, "decision": "approved", "approval_id": ap.id}, key=f"resume:{ap.id}")
    else:
        rejected_all = all(not ident.may_approve(a["kind"]) or i in idx for i, a in enumerate(proposal.actions))
        if rejected_all and len(idx) == len(proposal.actions):
            proposal.status = "rejected"
        incident.status = "monitoring"
        enqueue(db, "resume_graph", {"incident_id": incident.id, "decision": "rejected", "approval_id": ap.id}, key=f"resume:{ap.id}")
    incident.updated_at = utcnow()  # approvals do not bump the incident version; evidence/plan changes do
    events.publish("approval", {"incident_id": incident.id, "proposal_id": proposal.id, "decision": decision, "approval_id": ap.id, "work_orders": wo_ids})
    return {"approval_id": ap.id, "status": ap.status, "decision": decision, "work_orders": wo_ids, "expires_at": iso(ap.expires_at), "payload_hash": ap.payload_hash}


def enqueue(db: Session, kind: str, payload: dict, key: str | None = None, delay_s: int = 0) -> Job | None:
    if key and db.execute(select(Job).where(Job.idempotency_key == key)).scalar_one_or_none():
        return None
    j = Job(id=new_id("job"), kind=kind, payload=payload, status="queued", run_at=utcnow() + timedelta(seconds=delay_s), idempotency_key=key, created_at=utcnow(),
            max_attempts=get_settings().retry_budget)
    db.add(j)
    db.flush()
    return j


def dispatch_approved(db: Session, incident_id: str, approval_id: str) -> list[dict]:
    """Execution step (called by the graph after human approval).  Re-checks policy, then
    emits a *simulated* dispatch receipt per work order.  Idempotent per work order."""
    s = get_settings()
    ap = db.get(Approval, approval_id)
    incident = db.get(Incident, incident_id)
    if not ap or not incident:
        raise GatewayError(404, "approval or incident not found")
    proposal = db.get(Proposal, ap.proposal_id)
    pd = policy.check_execution(db, ap, proposal, incident)
    results = []
    orders = db.execute(select(WorkOrder).where(WorkOrder.approval_id == ap.id)).scalars().all()
    if pd.decision != "allow":
        for wo in orders:
            if wo.status == "approved":
                wo.status = "failed"
                wo.payload = {**wo.payload, "failure": pd.reasons}
        ap.status = "invalidated" if "expired" not in " ".join(pd.reasons) else "expired"
        incident.status = "urgent_human_review"
        audit.record(db, "gateway", "execution.blocked", "approval", ap.id, {"reasons": pd.reasons})
        events.publish("execution_blocked", {"incident_id": incident.id, "approval_id": ap.id, "reasons": pd.reasons})
        return [{"work_order_id": wo.id, "status": wo.status, "reasons": pd.reasons} for wo in orders]
    for wo in orders:
        if wo.status != "approved":
            results.append({"work_order_id": wo.id, "status": wo.status, "note": "already processed (idempotent)"})
            continue
        receipt = {"connector": "simulated", "simulated": True, "department": wo.department, "message_id": f"sim-{wo.id}", "accepted_at": iso(utcnow()),
                   "note": "No external system was contacted. This receipt is generated locally."}
        db.add(DispatchReceipt(id=new_id("rcpt"), work_order_id=wo.id, connector="simulated", status="accepted", receipt=receipt, created_at=utcnow()))
        wo.status = "dispatched"
        wo.dispatched_at = utcnow()
        wo.escalation_due_at = utcnow() + timedelta(minutes=s.ack_escalation_minutes)
        audit.record(db, "gateway", "workorder.dispatched", "work_order", wo.id, {"kind": wo.kind, "department": wo.department, "connector": "simulated"})
        results.append({"work_order_id": wo.id, "status": wo.status, "receipt": receipt})
    ap.status = "consumed"
    ap.consumed_at = utcnow()
    incident.status = "responding"
    incident.updated_at = utcnow()
    events.publish("dispatch", {"incident_id": incident.id, "work_orders": [r["work_order_id"] for r in results]})
    return results


VALID_TRANSITIONS = {
    "dispatched": {"acknowledged", "rejected", "failed", "expired", "cancelled"},
    "acknowledged": {"in_progress", "completed", "rejected", "cancelled"},
    "in_progress": {"completed", "failed", "cancelled"},
}


def transition_work_order(db: Session, actor: str, wo: WorkOrder, new_status: str, note: str = "", simulated: bool = True) -> WorkOrder:
    allowed = VALID_TRANSITIONS.get(wo.status, set())
    if new_status not in allowed:
        raise GatewayError(409, f"cannot move work order from {wo.status} to {new_status}", "invalid_transition")
    wo.status = new_status
    now = utcnow()
    if new_status == "acknowledged":
        wo.acknowledged_at = now
        wo.escalation_due_at = None
    if new_status == "completed":
        wo.completed_at = now
        apply_physical_effect(db, wo)
    wo.payload = {**wo.payload, "last_note": note, "last_actor": actor, "simulated_department_response": simulated}
    audit.record(db, actor, f"workorder.{new_status}", "work_order", wo.id, {"note": note, "simulated": simulated, "physical_effect_applied": new_status == "completed" and bool(wo.physical_effect)})
    events.publish("work_order", {"incident_id": wo.incident_id, "work_order_id": wo.id, "status": new_status})
    if new_status in {"completed", "rejected", "failed"}:
        enqueue(db, "reassess", {"incident_id": wo.incident_id, "reason": f"work order {wo.id} {new_status}"}, key=f"reassess:{wo.id}:{new_status}")
    return wo


def apply_physical_effect(db: Session, wo: WorkOrder) -> None:
    """Only completed work changes modelled capacity (pump deployment adds mobile capacity to the catchment)."""
    eff = wo.physical_effect or {}
    if not eff:
        return
    if "extra_pump_m3_s" in eff and eff.get("catchment_id"):
        c = db.get(Catchment, eff["catchment_id"])
        if c:
            c.assumptions = {**c.assumptions, "deployed_extra_pump_m3_s": float(c.assumptions.get("deployed_extra_pump_m3_s", 0.0)) + float(eff["extra_pump_m3_s"])}
        if wo.payload.get("target_asset_id"):
            a = db.get(Asset, wo.payload["target_asset_id"])
            if a:
                a.attributes = {**a.attributes, "status": "deployed", "deployed_to": eff["catchment_id"]}
    audit.record(db, "gateway", "physical_effect.applied", "work_order", wo.id, eff)
