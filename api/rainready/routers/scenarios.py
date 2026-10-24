"""Scenarios, live twin controls and twin simulation.  Sliders recompute through the
backend water-balance tool and (optionally) re-enter the incident graph."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, events, gateway
from ..agents import runner
from ..auth import Identity, current_identity, require
from ..clock import iso, to_dubai, utcnow
from ..db import get_db
from ..models import Asset, Catchment, Incident, Scenario, Sensor, TwinRun, new_id
from ..schemas import ScenarioRunIn, TwinControls, TwinSimulateIn
from ..tools import hydrology
from ..tools.registry import ToolContext, load_catchment_specs, rain_series_for

router = APIRouter(prefix="/api", tags=["scenarios", "twin"])


def _scenario_dict(sc: Scenario, db: Session) -> dict:
    open_inc = db.execute(select(Incident).where(Incident.scenario_id == sc.id, Incident.status.notin_(["closed", "cancelled"])).order_by(Incident.created_at.desc())).scalars().all()
    return {"id": sc.id, "name": sc.name, "kind": sc.kind, "description": sc.description, "params": sc.params, "decision_time": iso(sc.decision_time),
            "decision_time_dubai": to_dubai(sc.decision_time).isoformat(), "status": sc.status, "data_mode": sc.data_mode, "open_incidents": [i.id for i in open_inc]}


@router.get("/scenarios")
def list_scenarios(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    return [_scenario_dict(s, db) for s in db.execute(select(Scenario).order_by(Scenario.id)).scalars().all()]


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    return _scenario_dict(sc, db)


def apply_scenario_environment(db: Session, sc: Scenario) -> None:
    """Sensor health and pump availability are shared physical state; a scenario sets them explicitly when it starts."""
    p = sc.params or {}
    health = dict(p.get("sensor_health", {}))
    for sid in (p.get("controls", {}).get("sensor_outage") or []):
        health[sid] = "offline"
    for s in db.execute(select(Sensor)).scalars().all():
        s.health = health.get(s.id, "ok")
    ps = db.get(Asset, "PS7")
    if ps:
        ps.attributes = {**ps.attributes, "availability": float(p.get("controls", {}).get("pump_availability", 1.0))}
    for c in db.execute(select(Catchment)).scalars().all():
        if "deployed_extra_pump_m3_s" in c.assumptions and p.get("reset_deployments", True):
            c.assumptions = {k: v for k, v in c.assumptions.items() if k != "deployed_extra_pump_m3_s"}
    for m in db.execute(select(Asset).where(Asset.kind == "mobile_pump")).scalars().all():
        m.attributes = {**m.attributes, "status": "available"}


@router.post("/scenarios/{scenario_id}/run")
def run_scenario(scenario_id: str, body: ScenarioRunIn | None = None, ident: Identity = Depends(require("scenario:run")), db: Session = Depends(get_db)):
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    # Duplicate-event suppression: one open incident per scenario focus.
    existing = db.execute(select(Incident).where(Incident.scenario_id == scenario_id, Incident.status.notin_(["closed", "cancelled"]))).scalars().first()
    if existing:
        return {"incident_id": existing.id, "duplicate_suppressed": True, "detail": "an open incident already exists for this scenario; reassess it instead of creating a duplicate"}
    apply_scenario_environment(db, sc)
    sc.status = "running"
    kind = (body.kind if body and body.kind else sc.kind)
    if kind not in {"rainfall", "leak", "hse"}:
        kind = "rainfall"
    audit.record(db, ident.id, "scenario.run", "scenario", sc.id, {"kind": kind})
    db.commit()
    incident_id = runner.start_incident(scenario_id, kind, ident.id, title=body.title if body else None)
    return {"incident_id": incident_id, "duplicate_suppressed": False}


@router.post("/scenarios/{scenario_id}/controls")
def set_controls(scenario_id: str, controls: TwinControls, ident: Identity = Depends(require("twin:control")), db: Session = Depends(get_db)):
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    n = int(sc.params.get("controls_revision", 0)) + 1
    sc.params = {**sc.params, "controls": controls.model_dump(), "reset_deployments": False, "controls_revision": n}
    apply_scenario_environment(db, sc)
    audit.record(db, ident.id, "twin.controls_changed", "scenario", sc.id, controls.model_dump())
    events.publish("twin", {"scenario_id": sc.id, "controls": controls.model_dump()})
    open_inc = db.execute(select(Incident).where(Incident.scenario_id == sc.id, Incident.status.notin_(["closed", "cancelled"]))).scalars().all()
    for inc in open_inc:
        gateway.enqueue(db, "reassess", {"incident_id": inc.id, "reason": f"twin controls changed by {ident.id}"}, key=f"reassess:{inc.id}:controls:{n}")
    return {"ok": True, "controls": controls.model_dump(), "reassess_queued_for": [i.id for i in open_inc]}


def _simulate(db: Session, sc: Scenario, controls: TwinControls, horizon: int) -> dict:
    specs, thresholds = load_catchment_specs(db, (sc.params or {}).get("catchment_ids") or None)
    if not specs:
        raise HTTPException(400, "scenario has no catchments (twin applies to rainfall scenarios)")
    ctx = ToolContext(db=db, decision_time=sc.decision_time, persona="twin_ui", scenario_id=sc.id, max_calls=99)
    dt, steps = 5, horizon // 5
    rain = {s.id: rain_series_for(ctx, db.get(Catchment, s.id), steps, dt) for s in specs}
    # Sensor outage affects evidence, not physics; pump availability and blockage do.
    c = hydrology.Controls(rain_multiplier=controls.rain_multiplier, drain_blockage=controls.drain_blockage, pump_availability=controls.pump_availability, extra_pump_m3_s=controls.extra_pump_m3_s)
    res = hydrology.simulate(specs, rain, c, dt_min=dt, horizon_min=horizon, asset_thresholds_m=thresholds)
    res["forecast_total_mm"] = {cid: round(sum(v) * dt / 60, 1) for cid, v in rain.items()}
    res["asset_thresholds_m"] = thresholds
    res["evidence_effects"] = {"sensor_outage": controls.sensor_outage, "report_reliability": controls.report_reliability,
                               "note": "Sensor outage and report reliability change evidence quality and the agents' next tools, not the physics."}
    return res


@router.post("/twin/simulate")
def twin_simulate(body: TwinSimulateIn, ident: Identity = Depends(require("twin:control")), db: Session = Depends(get_db)):
    sc = db.get(Scenario, body.scenario_id)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    intervention = _simulate(db, sc, body.controls, body.horizon_min)
    if body.baseline_controls is not None:
        base_controls = body.baseline_controls
    else:
        saved = {k: v for k, v in ((sc.params or {}).get("controls") or {}).items() if k in TwinControls.model_fields}
        base_controls = TwinControls(**saved)
    baseline = _simulate(db, sc, base_controls, body.horizon_min)
    cmp = hydrology.compare(baseline, intervention)
    tr = TwinRun(id=new_id("twin"), scenario_id=sc.id, controls=body.controls.model_dump(), result={"overall_band": intervention["overall_band"], "totals_m3": intervention["totals_m3"], "snapshots": intervention["snapshots"]},
                 tool_version=hydrology.TOOL_VERSION, created_at=utcnow())
    db.add(tr)
    audit.record(db, ident.id, "twin.simulated", "scenario", sc.id, {"controls": body.controls.model_dump(), "overall_band": intervention["overall_band"], "persist": body.persist_to_scenario})
    out = {"twin_run_id": tr.id, "baseline": baseline, "intervention": intervention, "comparison": cmp, "label": "scenario model — uncalibrated"}
    if body.persist_to_scenario:
        out["persisted"] = set_controls(sc.id, body.controls, ident, db)
    return out


@router.get("/twin/{scenario_id}/state")
def twin_state(scenario_id: str, ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    cats = db.execute(select(Catchment)).scalars().all()
    runs = db.execute(select(TwinRun).where(TwinRun.scenario_id == scenario_id).order_by(TwinRun.created_at.desc()).limit(10)).scalars().all()
    ps = db.get(Asset, "PS7")
    return {"scenario": _scenario_dict(sc, db), "controls": (sc.params or {}).get("controls", {}),
            "catchments": [{"id": c.id, "name": c.name, "area_m2": c.area_m2, "runoff_coefficient": c.runoff_coefficient, "storage_area_m2": c.storage_area_m2, "drain_capacity_m3_s": c.drain_capacity_m3_s,
                            "pump_asset_id": c.pump_asset_id, "downstream_id": c.downstream_id, "travel_minutes": c.travel_minutes, "protects": c.protects_asset_ids, "assumptions": c.assumptions, "geometry": c.geometry} for c in cats],
            "pump_station": ps.attributes if ps else None, "sensors": [{"id": s.id, "kind": s.kind, "health": s.health} for s in db.execute(select(Sensor)).scalars().all()],
            "recent_runs": [{"id": r.id, "controls": r.controls, "result": r.result, "created_at": iso(r.created_at)} for r in runs]}
