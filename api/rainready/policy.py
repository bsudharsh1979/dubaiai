"""Deterministic policy engine.  Runs independently of any persona or guard model.

``check_proposal``  — before a proposal is offered for human review.
``check_execution`` — again at execution time (authorization, freshness, incident
version, payload hash, expiry, emergency stop).
Every decision is persisted as a ``PolicyDecision`` and audited.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .auth import ACTION_AUTHORITY, Identity
from .clock import utcnow
from .config import get_settings
from .models import Approval, Asset, Evidence, Incident, PolicyDecision, Proposal, new_id
from .providers.registry import get_providers

ALLOWED_ACTION_KINDS = set(ACTION_AUTHORITY)
PUBLIC_KINDS = {"advisory"}
HIGH_IMPACT_KINDS = {"advisory", "access_control"}


def _decision(db: Session, incident_id: str | None, subject_type: str, subject_id: str, actor: str, checks: list[dict]) -> PolicyDecision:
    failed = [c for c in checks if not c["ok"]]
    if any(c.get("severity") == "deny" for c in failed):
        decision = "deny"
    elif failed:
        decision = "review"
    else:
        decision = "allow"
    pd = PolicyDecision(id=new_id("pol"), incident_id=incident_id, subject_type=subject_type, subject_id=subject_id, actor=actor, decision=decision,
                        checks=checks, reasons=[c["detail"] for c in failed], created_at=utcnow())
    db.add(pd)
    db.flush()
    audit.record(db, actor, f"policy.{decision}", subject_type, subject_id, {"reasons": pd.reasons, "checks": len(checks)})
    return pd


def check_proposal(db: Session, incident: Incident, actions: list[dict], public_text: str, assurance: dict | None, evidence_completeness: str) -> PolicyDecision:
    s = get_settings()
    checks: list[dict] = []
    checks.append({"check": "emergency_stop", "ok": not s.emergency_stop, "severity": "deny", "detail": "emergency stop is active — privileged actions blocked"})
    checks.append({"check": "action_connectors_simulated", "ok": s.action_connectors == "simulated", "severity": "deny", "detail": "only simulated connectors exist in this MVP"})
    bad_kinds = [a["kind"] for a in actions if a["kind"] not in ALLOWED_ACTION_KINDS]
    checks.append({"check": "action_kinds_allowlisted", "ok": not bad_kinds, "severity": "deny", "detail": f"unknown action kinds: {bad_kinds}"})
    no_auth = [a["kind"] for a in actions if a.get("requires_authority") not in ACTION_AUTHORITY.get(a["kind"], set())]
    checks.append({"check": "authority_mapped", "ok": not no_auth, "severity": "deny", "detail": f"actions without a valid human authority: {no_auth}"})
    checks.append({"check": "jurisdiction", "ok": incident.jurisdiction == "dubai-demo", "severity": "deny", "detail": "incident outside configured jurisdiction"})
    high = [a["kind"] for a in actions if a["kind"] in HIGH_IMPACT_KINDS]
    checks.append({"check": "evidence_for_high_impact", "ok": not (high and evidence_completeness in {"insufficient", "weak"}), "severity": "review",
                   "detail": f"high-impact actions {high} proposed on {evidence_completeness} evidence"})
    checks.append({"check": "assurance_not_abstaining", "ok": (assurance or {}).get("verdict") != "abstain", "severity": "review", "detail": "assurance officer abstained"})
    ev = db.execute(select(Evidence).where(Evidence.incident_id == incident.id)).scalars().all()
    current = [e for e in ev if e.freshness == "current"]
    checks.append({"check": "current_evidence_exists", "ok": bool(current) or not actions, "severity": "review", "detail": "no current-decision evidence (all stale or context only)"})
    # Public text: deterministic gate + sensitive asset names + guard outage.
    if any(a["kind"] in PUBLIC_KINDS for a in actions):
        prov = get_providers()
        g = prov.guard.check(public_text, "public_advisory")
        checks.append({"check": "public_text_gate", "ok": not g["unsafe"], "severity": "deny", "detail": f"public text failed safety gate: {g['categories']}"})
        sensitive = [a.name for a in db.execute(select(Asset).where(Asset.sensitive.is_(True))).scalars().all()]
        leaked = [n for n in sensitive if n and n.lower() in public_text.lower()]
        checks.append({"check": "no_sensitive_assets_in_public_text", "ok": not leaked, "severity": "deny", "detail": f"public text names sensitive assets: {leaked}"})
        checks.append({"check": "guard_adapters_available_for_publication", "ok": not g["publication_blocked_by_outage"], "severity": "deny",
                       "detail": f"required guard adapter(s) unavailable: {g['unavailable_adapters']} — publication blocked, monitoring continues"})
    return _decision(db, incident.id, "proposal", f"incident:{incident.id}", "policy-engine", checks)


def check_approval_request(db: Session, ident: Identity, incident: Incident, proposal: Proposal, action_indexes: list[int]) -> PolicyDecision:
    s = get_settings()
    checks = [{"check": "emergency_stop", "ok": not s.emergency_stop, "severity": "deny", "detail": "emergency stop active"},
              {"check": "proposal_current", "ok": proposal.status == "proposed", "severity": "deny", "detail": f"proposal status is {proposal.status}"},
              {"check": "incident_version", "ok": proposal.incident_version == incident.version, "severity": "deny", "detail": "incident changed since proposal was drafted — re-plan required"},
              {"check": "scope", "ok": ident.in_scope(incident.jurisdiction), "severity": "deny", "detail": f"approver not in jurisdiction {incident.jurisdiction}"}]
    for i in action_indexes:
        if i < 0 or i >= len(proposal.actions):
            checks.append({"check": "action_index", "ok": False, "severity": "deny", "detail": f"invalid action index {i}"})
            continue
        kind = proposal.actions[i]["kind"]
        checks.append({"check": f"authority[{i}:{kind}]", "ok": ident.may_approve(kind), "severity": "deny", "detail": f"role {ident.role} cannot approve {kind}"})
    return _decision(db, incident.id, "approval_request", proposal.id, ident.id, checks)


def check_execution(db: Session, approval: Approval, proposal: Proposal, incident: Incident, now: datetime | None = None) -> PolicyDecision:
    s = get_settings()
    now = now or utcnow()
    checks = [{"check": "emergency_stop", "ok": not s.emergency_stop, "severity": "deny", "detail": "emergency stop active"},
              {"check": "approval_active", "ok": approval.status == "active", "severity": "deny", "detail": f"approval status {approval.status}"},
              {"check": "approval_not_expired", "ok": approval.expires_at > now, "severity": "deny", "detail": "approval expired — stale approval cannot execute"},
              {"check": "payload_hash", "ok": approval.payload_hash == proposal.payload_hash, "severity": "deny", "detail": "proposal payload changed after approval"},
              {"check": "proposal_version", "ok": approval.proposal_version == proposal.version, "severity": "deny", "detail": "proposal version mismatch"},
              {"check": "incident_version", "ok": approval.incident_version == incident.version, "severity": "deny", "detail": "incident version changed since approval"},
              {"check": "approver_role_still_valid", "ok": all(approval.approver_role in ACTION_AUTHORITY.get(k, set()) for k in approval.intended_tools), "severity": "deny", "detail": "approver role no longer authorizes these actions"}]
    ev = db.execute(select(Evidence).where(Evidence.incident_id == incident.id, Evidence.freshness == "current")).scalars().all()
    checks.append({"check": "data_freshness", "ok": bool(ev), "severity": "deny", "detail": "no current evidence at execution time — re-assessment required"})
    return _decision(db, incident.id, "execution", approval.id, "policy-engine", checks)
