"""Health, config, assurance, audit export, emergency stop, SSE and demo reset."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from .. import audit, events
from ..auth import Identity, current_identity, require
from ..clock import iso, to_dubai, utcnow
from ..config import get_settings
from ..db import get_db
from ..models import AuditEvent, Feed, Job, ModelVersion, PolicyDecision
from ..providers.registry import get_providers
from ..schemas import EmergencyStopIn, GenericOk, HealthOut
from .. import worker as worker_mod

router = APIRouter(prefix="/api", tags=["system"])


def modes() -> dict:
    s = get_settings()
    return {"data_mode": s.data_mode, "model_provider": s.model_provider, "action_connectors": s.action_connectors, "sovereign_mode": s.sovereign_mode,
            "demo_identity_switcher": s.demo_identity_switcher_enabled, "emergency_stop": s.emergency_stop, "app_env": s.app_env}


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)):
    s = get_settings()
    prov = get_providers()
    feeds = db.execute(select(Feed)).scalars().all()
    integrations = [{"feed_id": f.id, "name": f.name, "kind": f.kind, "status": f.status, "access_classification": f.access_classification, "cadence_s": f.cadence_s, "typical_latency_s": f.typical_latency_s} for f in feeds]
    integrations.append({"feed_id": "action_connectors", "name": "Dispatch / advisory / access-control connectors", "kind": "action", "status": s.action_connectors,
                         "access_classification": "simulated receipts only — no real valve/power/evacuation endpoint exists", "cadence_s": None, "typical_latency_s": None})
    queued = db.execute(select(func.count()).select_from(Job).where(Job.status == "queued")).scalar_one()
    now = utcnow()
    return {"ok": True, "modes": modes(), "database": {"dialect": "sqlite" if s.is_sqlite else "postgresql", "migrated": True},
            "worker": {"enabled": s.worker_enabled, "alive": worker_mod.is_alive(), "queued_jobs": queued, "last_tick": worker_mod.last_tick()},
            "providers": prov.statuses(), "integrations": integrations,
            "guard_gate": {"deterministic_gate": "active", "guard_adapters_required_for_publication": s.guard_required_for_publication,
                           "text_provider_healthy": prov.text_available(), "privileged_actions_blocked": s.emergency_stop},
            "time": {"utc": iso(now), "dubai": to_dubai(now).isoformat(), "display_tz": "Asia/Dubai", "storage_tz": "UTC"}}


@router.get("/config")
def config():
    s = get_settings()
    return {"app_name": s.app_name, "modes": modes(), "approval_ttl_minutes": s.approval_ttl_minutes, "ack_escalation_minutes": s.ack_escalation_minutes, "max_evidence_loops": s.max_evidence_loops,
            "labels": ["observed_water", "susceptibility", "forecast_risk", "anomaly", "suspected_incident", "confirmed_incident"],
            "architecture": ["Signals and systems of record", "Brain 1: perception and hazard tools", "Brain 2: agent coordination, knowledge and access control", "Departments and engagement", "Acknowledgements, observations and reassessment"]}


@router.get("/assurance")
def assurance(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    prov = get_providers()
    pds = db.execute(select(PolicyDecision).order_by(PolicyDecision.created_at.desc()).limit(40)).scalars().all()
    models = db.execute(select(ModelVersion)).scalars().all()
    chain = audit.verify_chain(db)
    from ..evaluation.harness import summary as eval_summary
    return {"modes": modes(), "providers": prov.statuses(), "policy_decisions": [{"id": p.id, "incident_id": p.incident_id, "subject_type": p.subject_type, "subject_id": p.subject_id, "actor": p.actor, "decision": p.decision, "reasons": p.reasons, "created_at": iso(p.created_at)} for p in pds],
            "model_versions": [{"id": m.id, "kind": m.kind, "name": m.name, "version": m.version, "card_uri": m.card_uri, "calibrated": m.calibrated, "notes": m.notes} for m in models],
            "audit_chain": chain, "evaluation": eval_summary(db), "worker": {"alive": worker_mod.is_alive(), "last_tick": worker_mod.last_tick()}}


@router.get("/audit/verify")
def audit_verify(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    return audit.verify_chain(db)


@router.get("/audit/export")
def audit_export(ident: Identity = Depends(require("audit:export")), db: Session = Depends(get_db), limit: int = 2000):
    rows = db.execute(select(AuditEvent).order_by(AuditEvent.seq.asc()).limit(limit)).scalars().all()
    chain = audit.verify_chain(db)
    audit.record(db, ident.id, "audit.exported", "audit", "chain", {"events": len(rows)})
    return {"exported_at": iso(utcnow()), "exported_by": ident.id, "verification": chain,
            "events": [{"seq": r.seq, "ts": iso(r.ts), "actor": r.actor, "action": r.action, "subject_type": r.subject_type, "subject_id": r.subject_id, "payload": r.payload, "prev_hash": r.prev_hash, "hash": r.hash} for r in rows]}


@router.get("/audit/recent")
def audit_recent(ident: Identity = Depends(current_identity), db: Session = Depends(get_db), limit: int = 60, subject_id: str | None = None):
    q = select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)
    if subject_id:
        q = select(AuditEvent).where((AuditEvent.subject_id == subject_id) | (AuditEvent.payload["incident_id"].as_string() == subject_id)).order_by(AuditEvent.seq.desc()).limit(limit)
    rows = db.execute(q).scalars().all()
    return [{"seq": r.seq, "ts": iso(r.ts), "actor": r.actor, "action": r.action, "subject_type": r.subject_type, "subject_id": r.subject_id, "payload": r.payload} for r in rows]


@router.post("/assurance/emergency-stop", response_model=GenericOk)
def emergency_stop(body: EmergencyStopIn, ident: Identity = Depends(require("emergency_stop")), db: Session = Depends(get_db)):
    s = get_settings()
    s.emergency_stop = body.active
    audit.record(db, ident.id, "emergency_stop." + ("activated" if body.active else "cleared"), "system", "emergency_stop", {"reason": body.reason})
    events.publish("system", {"emergency_stop": body.active, "by": ident.id})
    return GenericOk(detail={"emergency_stop": body.active, "effect": "privileged actions and publication blocked; monitoring and intake continue" if body.active else "cleared"})


@router.get("/events")
async def sse(request: Request, since: int = 0):
    return EventSourceResponse(events.sse_generator(request.is_disconnected, since))


@router.post("/demo/reset", response_model=GenericOk)
def demo_reset(ident: Identity = Depends(current_identity)):
    s = get_settings()
    if not s.demo_identity_switcher_enabled:
        raise HTTPException(status_code=403, detail="reset only available in demo mode")
    from ..bootstrap import reset_database
    reset_database()
    audit_note = {"by": ident.id}
    events.publish("system", {"reset": True, **audit_note})
    return GenericOk(detail="database re-seeded; sign in again")
