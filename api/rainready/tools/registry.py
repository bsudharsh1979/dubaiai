"""Typed, read-only analytical tools with per-persona allowlists.

Every call: allowlist check → argument validation → decision-time filtering
(``available_at <= decision_time``) → execution → persisted ``ToolResult`` →
SSE event.  Tools never write operational state; state changes happen only in
the graph/gateway under policy.  Tool responses are *data*: nothing a tool
returns is interpreted as an instruction.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events
from ..audit import canonical
from ..clock import iso, utcnow
from ..models import (Asset, Catchment, Crew, Document, Evidence, Feed, Forecast, Incident, Observation, RoadLink, Scene, Sensor, ToolResult,
                      UtilityEvent, new_id)
from . import exposure as exposure_tool
from . import hydrology, leak
from . import routing as routing_tool


class ToolError(Exception):
    pass


class ToolNotAllowed(ToolError):
    pass


@dataclass
class ToolContext:
    db: Session
    decision_time: datetime
    persona: str
    run_id: str | None = None
    incident_id: str | None = None
    scenario_id: str | None = None
    jurisdiction: str = "dubai-demo"
    roles_for_knowledge: list[str] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)
    call_count: int = 0
    max_calls: int = 12


@dataclass
class ToolSpec:
    name: str
    version: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[ToolContext, BaseModel], dict]
    personas: set[str]


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, version: str, description: str, personas: set[str]):
    def deco(fn_args_model):
        args_model, fn = fn_args_model
        REGISTRY[name] = ToolSpec(name, version, description, args_model, fn, personas)
        return fn
    return deco


def register(name: str, version: str, description: str, personas: set[str], args_model: type[BaseModel]):
    def deco(fn):
        REGISTRY[name] = ToolSpec(name, version, description, args_model, fn, personas)
        return fn
    return deco


def allowed_tools(persona: str) -> list[str]:
    return sorted(n for n, s in REGISTRY.items() if persona in s.personas or "*" in s.personas)


def openai_tool_schemas(names: list[str]) -> list[dict]:
    out = []
    for n in names:
        s = REGISTRY[n]
        out.append({"type": "function", "function": {"name": n, "description": s.description, "parameters": s.args_model.model_json_schema()}})
    return out


def call_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict:
    spec = REGISTRY.get(name)
    if spec is None:
        raise ToolError(f"unknown tool {name!r}")
    if ctx.persona not in spec.personas and "*" not in spec.personas:
        _persist(ctx, name, spec.version, args, {"error": "tool not in persona allowlist"}, ok=False, duration_ms=0)
        raise ToolNotAllowed(f"persona {ctx.persona!r} may not call {name!r}")
    if ctx.call_count >= ctx.max_calls:
        raise ToolError(f"tool-call budget exhausted ({ctx.max_calls})")
    try:
        parsed = spec.args_model.model_validate(args or {})
    except ValidationError as e:
        _persist(ctx, name, spec.version, args, {"error": "invalid arguments", "detail": json.loads(e.json())}, ok=False, duration_ms=0)
        raise ToolError(f"invalid arguments for {name}: {e.errors()[0].get('msg')}")
    t0 = time.perf_counter()
    ctx.call_count += 1
    try:
        result = spec.fn(ctx, parsed)
        ok = True
    except ToolError as e:
        result, ok = {"error": str(e)}, False
    duration = int((time.perf_counter() - t0) * 1000)
    result.setdefault("tool", name)
    result.setdefault("tool_version", spec.version)
    _persist(ctx, name, spec.version, parsed.model_dump(mode="json"), result, ok=ok, duration_ms=duration)
    return result


def _persist(ctx: ToolContext, name: str, version: str, args: Any, result: dict, ok: bool, duration_ms: int) -> None:
    args_json = json.loads(json.dumps(args, default=str))
    tr = ToolResult(id=new_id("tr"), run_id=ctx.run_id, incident_id=ctx.incident_id, persona=ctx.persona, tool=name, tool_version=version,
                    args=args_json, args_hash=hashlib.sha256(canonical(args_json).encode()).hexdigest()[:16],
                    result=json.loads(json.dumps(result, default=str)), ok=ok, duration_ms=duration_ms, created_at=utcnow())
    ctx.db.add(tr)
    ctx.db.flush()
    entry = {"tool": name, "version": version, "ok": ok, "duration_ms": duration_ms, "args": args_json, "result_id": tr.id,
             "summary": {k: result.get(k) for k in ("label", "status", "overall_band", "anomaly_band", "consequence_band", "freshness", "error") if k in result}}
    ctx.log.append(entry)
    events.publish("tool_call", {"incident_id": ctx.incident_id, "persona": ctx.persona, **entry})


# ---------------------------------------------------------------------------
# Helpers
def _freshness(feed: Feed, observed_at: datetime | None, available_at: datetime | None, now: datetime) -> str:
    if observed_at is None:
        return "unknown"
    if available_at and available_at > now:
        return "not_yet_available"
    age = (now - observed_at).total_seconds()
    if age <= feed.freshness_current_s:
        return "current"
    if age <= feed.freshness_context_s:
        return "context"
    return "stale"


def _asset_dicts(db: Session, jurisdiction: str) -> list[dict]:
    rows = db.execute(select(Asset).where(Asset.jurisdiction == jurisdiction)).scalars().all()
    return [{"id": a.id, "name": a.name, "kind": a.kind, "criticality": a.criticality, "geometry": a.geometry, "sensitive": a.sensitive, "attributes": a.attributes} for a in rows]


# ---------------------------------------------------------------------------
# OBSERVER tools
class SensorWindowArgs(BaseModel):
    sensor_id: str = Field(..., max_length=40)
    minutes: int = Field(60, ge=5, le=24 * 60)


@register("read_sensor_window", "1.1.0", "Read a sensor's observations in the window ending at decision time (only values already available).",
          {"observer", "hydrologist", "utility_engineer", "assurance_officer", "incident_coordinator"}, SensorWindowArgs)
def read_sensor_window(ctx: ToolContext, a: SensorWindowArgs) -> dict:
    s = ctx.db.get(Sensor, a.sensor_id)
    if not s:
        raise ToolError(f"unknown sensor {a.sensor_id}")
    feed = ctx.db.get(Feed, s.feed_id)
    start = ctx.decision_time - timedelta(minutes=a.minutes)
    q = select(Observation).where(Observation.sensor_id == a.sensor_id, Observation.observed_at >= start, Observation.observed_at <= ctx.decision_time,
                                  Observation.available_at <= ctx.decision_time)
    if ctx.scenario_id:
        q = q.where((Observation.scenario_id == ctx.scenario_id) | (Observation.scenario_id.is_(None)))
    rows = ctx.db.execute(q.order_by(Observation.observed_at)).scalars().all()
    vals = [r.value for r in rows if r.value is not None]
    last = rows[-1] if rows else None
    return {"sensor_id": s.id, "kind": s.kind, "units": s.units, "health": s.health, "feed": feed.name, "cadence_s": feed.cadence_s, "typical_latency_s": feed.typical_latency_s,
            "n": len(rows), "values": [{"observed_at": iso(r.observed_at), "available_at": iso(r.available_at), "value": r.value, "quality_flags": r.quality_flags} for r in rows][-48:],
            "latest": last.value if last else None, "latest_observed_at": iso(last.observed_at) if last else None,
            "max": max(vals) if vals else None, "mean": round(sum(vals) / len(vals), 3) if vals else None,
            "freshness": _freshness(feed, last.observed_at if last else None, last.available_at if last else None, ctx.decision_time),
            "quality_flags": sorted({f for r in rows for f in (r.quality_flags or [])}),
            "simulation_status": last.simulation_status if last else "n/a", "note": "no usable observation" if not rows else None}


class SceneArgs(BaseModel):
    scene_id: str | None = None
    platform: str | None = Field(None, pattern="^(sentinel-1|sentinel-2)$")


@register("inspect_scene_metadata", "1.0.0", "Inspect satellite scene provenance, acquisition/availability times, quality masks and derived candidate-water summary.",
          {"observer", "hydrologist", "assurance_officer", "incident_coordinator", "hse_officer"}, SceneArgs)
def inspect_scene_metadata(ctx: ToolContext, a: SceneArgs) -> dict:
    q = select(Scene).where(Scene.available_at <= ctx.decision_time)
    if a.scene_id:
        q = q.where(Scene.id == a.scene_id)
    if a.platform:
        q = q.where(Scene.platform == a.platform)
    if ctx.scenario_id:
        q = q.where((Scene.scenario_id == ctx.scenario_id) | (Scene.scenario_id.is_(None)))
    rows = ctx.db.execute(q.order_by(Scene.observed_at.desc())).scalars().all()
    out = []
    for s in rows[:6]:
        feed = ctx.db.get(Feed, s.feed_id)
        out.append({"scene_id": s.id, "platform": s.platform, "role": s.scene_role, "acquisition_at": iso(s.observed_at), "available_at": iso(s.available_at),
                    "latency_s": int((s.available_at - s.observed_at).total_seconds()) if s.available_at and s.observed_at else None,
                    "crs": s.crs, "resolution": s.resolution, "orbit": s.orbit, "preprocessing": s.preprocessing, "cloud_fraction": s.cloud_fraction,
                    "quality_flags": s.quality_flags, "freshness": _freshness(feed, s.observed_at, s.available_at, ctx.decision_time),
                    "derived": s.derived, "license_class": s.license_class, "simulation_status": s.simulation_status, "checksum": s.checksum, "provenance_uri": s.provenance_uri})
    return {"scenes": out, "note": None if out else "no usable observation (no scene available at decision time)"}


class RelatedArgs(BaseModel):
    radius_m: float = Field(1500, ge=50, le=20000)
    hours: int = Field(72, ge=1, le=24 * 30)


@register("find_related_incidents", "1.0.0", "Find open or recent incidents near the current incident (duplicate/correlation check).",
          {"observer", "incident_coordinator", "assurance_officer", "response_planner"}, RelatedArgs)
def find_related_incidents(ctx: ToolContext, a: RelatedArgs) -> dict:
    from ..geo import distance_m
    me = ctx.db.get(Incident, ctx.incident_id) if ctx.incident_id else None
    since = ctx.decision_time - timedelta(hours=a.hours)
    rows = ctx.db.execute(select(Incident).where(Incident.created_at >= since, Incident.jurisdiction == ctx.jurisdiction)).scalars().all()
    out = []
    for r in rows:
        if me and r.id == me.id:
            continue
        d = distance_m(me.geometry, r.geometry) if (me and me.geometry and r.geometry) else None
        if d is None or d <= a.radius_m:
            out.append({"incident_id": r.id, "kind": r.kind, "label": r.label, "status": r.status, "severity_band": r.severity_band, "distance_m": round(d, 0) if d is not None else None, "title": r.title})
    return {"related": out, "count": len(out)}


class FreshnessArgs(BaseModel):
    feed_ids: list[str] = Field(default_factory=list)


@register("check_feed_freshness", "1.0.0", "Report latest availability, latency and freshness class for feeds (current-decision vs context vs stale).",
          {"observer", "hydrologist", "assurance_officer", "incident_coordinator", "utility_engineer"}, FreshnessArgs)
def check_feed_freshness(ctx: ToolContext, a: FreshnessArgs) -> dict:
    feeds = ctx.db.execute(select(Feed)).scalars().all()
    out = []
    for f in feeds:
        if a.feed_ids and f.id not in a.feed_ids:
            continue
        latest = None
        for model in (Observation, Forecast, Scene):
            q = select(model).where(model.feed_id == f.id, model.available_at <= ctx.decision_time)
            if ctx.scenario_id and hasattr(model, "scenario_id"):
                q = q.where((model.scenario_id == ctx.scenario_id) | (model.scenario_id.is_(None)))
            r = ctx.db.execute(q.order_by(model.observed_at.desc()).limit(1)).scalar_one_or_none()
            if r and (latest is None or (r.observed_at and r.observed_at > latest.observed_at)):
                latest = r
        out.append({"feed_id": f.id, "name": f.name, "kind": f.kind, "status": f.status, "access_classification": f.access_classification,
                    "cadence_s": f.cadence_s, "typical_latency_s": f.typical_latency_s,
                    "latest_observed_at": iso(latest.observed_at) if latest else None, "latest_available_at": iso(latest.available_at) if latest else None,
                    "freshness": _freshness(f, latest.observed_at if latest else None, latest.available_at if latest else None, ctx.decision_time) if latest else "no_data",
                    "freshness_rule_s": {"current": f.freshness_current_s, "context": f.freshness_context_s}})
    return {"feeds": out, "decision_time": iso(ctx.decision_time)}


# ---------------------------------------------------------------------------
# HYDROLOGIST tools
class WaterBalanceArgs(BaseModel):
    catchment_ids: list[str] = Field(default_factory=list, description="Empty = all catchments in the scenario")
    rain_multiplier: float = Field(1.0, ge=0, le=5)
    drain_blockage: float = Field(0.0, ge=0, le=1)
    pump_availability: float = Field(1.0, ge=0, le=1)
    extra_pump_m3_s: float = Field(0.0, ge=0, le=5)
    horizon_min: int = Field(180, ge=30, le=360)
    upstream_delay_enabled: bool = True


def rain_series_for(ctx: ToolContext, catchment: Catchment, steps: int, dt_min: int) -> list[float]:
    """Forecast rain-rate series (mm/h) per step from forecasts issued/available at or before decision time."""
    q = select(Forecast).where(Forecast.variable == "rain_rate_mm_h", Forecast.available_at <= ctx.decision_time, Forecast.valid_at > ctx.decision_time)
    if ctx.scenario_id:
        q = q.where((Forecast.scenario_id == ctx.scenario_id) | (Forecast.scenario_id.is_(None)))
    rows = ctx.db.execute(q.order_by(Forecast.issued_at.desc(), Forecast.valid_at)).scalars().all()
    # latest issuance only
    if rows:
        latest_issue = max(r.issued_at for r in rows)
        rows = [r for r in rows if r.issued_at == latest_issue and r.attributes.get("catchment_id") in (catchment.id, None)]
    series = [0.0] * steps
    for r in rows:
        idx = int((r.valid_at - ctx.decision_time).total_seconds() // (dt_min * 60)) - 1
        if 0 <= idx < steps:
            series[idx] = max(series[idx], float(r.value or 0.0))
    return series


def load_catchment_specs(db: Session, catchment_ids: list[str] | None, scenario_params: dict | None = None) -> tuple[list[hydrology.CatchmentSpec], dict[str, float]]:
    q = select(Catchment)
    if catchment_ids:
        q = q.where(Catchment.id.in_(catchment_ids))
    rows = db.execute(q).scalars().all()
    specs, thresholds = [], {}
    for c in rows:
        pump_cap = 0.0
        if c.pump_asset_id:
            pump = db.get(Asset, c.pump_asset_id)
            if pump:
                pump_cap = float(pump.attributes.get("capacity_m3_s", 0.0)) * float(pump.attributes.get("availability", 1.0))
        specs.append(hydrology.CatchmentSpec(id=c.id, name=c.name, area_m2=c.area_m2, runoff_coefficient=c.runoff_coefficient, storage_area_m2=c.storage_area_m2,
                                             drain_capacity_m3_s=c.drain_capacity_m3_s, pump_capacity_m3_s=pump_cap, downstream_id=c.downstream_id, travel_minutes=c.travel_minutes,
                                             max_storage_m3=c.assumptions.get("max_storage_m3"), protects_asset_ids=list(c.protects_asset_ids or []),
                                             mechanism=c.assumptions.get("mechanism", "waterlogging")))
        for aid in c.protects_asset_ids or []:
            a = db.get(Asset, aid)
            if a and "flood_threshold_m" in a.attributes:
                thresholds[aid] = float(a.attributes["flood_threshold_m"])
    return specs, thresholds


@register("run_water_balance", hydrology.TOOL_VERSION.split("/")[1], "Run the uncalibrated rainfall→runoff→storage scenario twin for +30/+60/+180 min using forecasts available at decision time.",
          {"hydrologist", "response_planner", "incident_coordinator"}, WaterBalanceArgs)
def run_water_balance(ctx: ToolContext, a: WaterBalanceArgs) -> dict:
    specs, thresholds = load_catchment_specs(ctx.db, a.catchment_ids or None)
    if not specs:
        raise ToolError("no catchments found")
    dt = 5
    steps = a.horizon_min // dt
    rain = {s.id: rain_series_for(ctx, _catchment(ctx.db, s.id), steps, dt) for s in specs}
    if all(sum(v) == 0 for v in rain.values()):
        forecast_note = "no rainfall forecast available at decision time — twin run with zero rain; this is NOT evidence of no hazard"
    else:
        forecast_note = None
    controls = hydrology.Controls(rain_multiplier=a.rain_multiplier, drain_blockage=a.drain_blockage, pump_availability=a.pump_availability,
                                  extra_pump_m3_s=a.extra_pump_m3_s, upstream_delay_enabled=a.upstream_delay_enabled)
    res = hydrology.simulate(specs, rain, controls, dt_min=dt, horizon_min=a.horizon_min, asset_thresholds_m=thresholds)
    res["forecast_note"] = forecast_note
    res["forecast_total_mm"] = {cid: round(sum(v) * dt / 60, 1) for cid, v in rain.items()}
    res["series"] = {cid: s[::3] for cid, s in res["series"].items()}  # thin for transport (every 15 min)
    return res


def _catchment(db: Session, cid: str) -> Catchment:
    c = db.get(Catchment, cid)
    if not c:
        raise ToolError(f"unknown catchment {cid}")
    return c


class WaterChangeArgs(BaseModel):
    scene_id: str | None = None


@register("satellite_water_change", "1.0.0", "Return the derived candidate-inundation summary for the latest usable Sentinel-1 pair (observed water at acquisition time, not current state).",
          {"hydrologist", "observer", "assurance_officer", "incident_coordinator"}, WaterChangeArgs)
def satellite_water_change(ctx: ToolContext, a: WaterChangeArgs) -> dict:
    q = select(Scene).where(Scene.platform == "sentinel-1", Scene.scene_role == "after", Scene.available_at <= ctx.decision_time)
    if a.scene_id:
        q = q.where(Scene.id == a.scene_id)
    if ctx.scenario_id:
        q = q.where((Scene.scenario_id == ctx.scenario_id) | (Scene.scenario_id.is_(None)))
    s = ctx.db.execute(q.order_by(Scene.observed_at.desc()).limit(1)).scalar_one_or_none()
    if not s:
        return {"status": "no usable observation", "label": "observed water: unknown", "note": "No Sentinel-1 pair available at decision time. Absence of observation is not absence of hazard."}
    feed = ctx.db.get(Feed, s.feed_id)
    return {"scene_id": s.id, "label": "candidate inundation at acquisition time", "acquisition_at": iso(s.observed_at), "available_at": iso(s.available_at),
            "freshness": _freshness(feed, s.observed_at, s.available_at, ctx.decision_time), "derived": s.derived, "quality_flags": s.quality_flags,
            "simulation_status": s.simulation_status, "caveat": "Intermittent evidence; cannot establish depth or current extent."}


# ---------------------------------------------------------------------------
# UTILITY ENGINEER tools
class PressureFlowArgs(BaseModel):
    flow_sensor_id: str
    pressure_sensor_id: str
    minutes: int = Field(120, ge=30, le=720)


@register("assess_pressure_flow", leak.TOOL_VERSION.split("/")[1], "Residual-based flow/pressure anomaly screen with competing explanations (planned ops, demand, rainfall, sensor health).",
          {"utility_engineer", "incident_coordinator"}, PressureFlowArgs)
def assess_pressure_flow(ctx: ToolContext, a: PressureFlowArgs) -> dict:
    fs, ps = ctx.db.get(Sensor, a.flow_sensor_id), ctx.db.get(Sensor, a.pressure_sensor_id)
    if not fs or not ps:
        raise ToolError("unknown sensor")
    start = ctx.decision_time - timedelta(minutes=a.minutes)

    def series(sensor: Sensor):
        q = select(Observation).where(Observation.sensor_id == sensor.id, Observation.observed_at >= start, Observation.observed_at <= ctx.decision_time, Observation.available_at <= ctx.decision_time)
        if ctx.scenario_id:
            q = q.where((Observation.scenario_id == ctx.scenario_id) | (Observation.scenario_id.is_(None)))
        rows = ctx.db.execute(q.order_by(Observation.observed_at)).scalars().all()
        return [r.value for r in rows if r.value is not None], [float(r.attributes.get("expected", r.value or 0)) for r in rows if r.value is not None]

    f_obs, f_exp = series(fs)
    p_obs, p_exp = series(ps)
    evq = select(UtilityEvent).where(UtilityEvent.available_at <= ctx.decision_time)
    if ctx.scenario_id:
        evq = evq.where((UtilityEvent.scenario_id == ctx.scenario_id) | (UtilityEvent.scenario_id.is_(None)))
    evs = [{"kind": e.kind, "description": e.description, "segment_id": e.segment_id} for e in ctx.db.execute(evq).scalars().all()
           if (e.starts_at is None or e.starts_at <= ctx.decision_time) and (e.ends_at is None or e.ends_at >= start)]
    rain_mm = 0.0
    for g in ctx.db.execute(select(Sensor).where(Sensor.kind == "rain_gauge")).scalars().all():
        w = _rain_window(ctx, g.id, 180)
        rain_mm = max(rain_mm, (w.get("mean") or 0.0) * 3.0)  # mean mm/h over 3 h → mm
    segment = fs.attributes.get("segment_id") or ps.attributes.get("segment_id")
    res = leak.assess(f_obs, f_exp, p_obs, p_exp, float(fs.attributes.get("noise_sd", 1.0)), float(ps.attributes.get("noise_sd", 0.2)), evs,
                      {fs.id: fs.health, ps.id: ps.health}, rain_mm, [segment] if segment else [])
    res["flow_units"], res["pressure_units"], res["samples"] = fs.units, ps.units, {"flow": len(f_obs), "pressure": len(p_obs)}
    return res


def _rain_window(ctx: ToolContext, sensor_id: str, minutes: int) -> dict:
    start = ctx.decision_time - timedelta(minutes=minutes)
    q = select(Observation).where(Observation.sensor_id == sensor_id, Observation.observed_at >= start, Observation.observed_at <= ctx.decision_time, Observation.available_at <= ctx.decision_time)
    if ctx.scenario_id:
        q = q.where((Observation.scenario_id == ctx.scenario_id) | (Observation.scenario_id.is_(None)))
    vals = [r.value for r in ctx.db.execute(q).scalars().all() if r.value is not None]
    return {"mean": sum(vals) / len(vals) if vals else 0.0, "n": len(vals)}


class UtilityEventsArgs(BaseModel):
    hours: int = Field(24, ge=1, le=24 * 14)


@register("list_utility_events", "1.0.0", "List planned operations, maintenance, demand changes and meter-health events known at decision time.",
          {"utility_engineer", "incident_coordinator", "assurance_officer"}, UtilityEventsArgs)
def list_utility_events(ctx: ToolContext, a: UtilityEventsArgs) -> dict:
    since = ctx.decision_time - timedelta(hours=a.hours)
    q = select(UtilityEvent).where(UtilityEvent.available_at <= ctx.decision_time)
    if ctx.scenario_id:
        q = q.where((UtilityEvent.scenario_id == ctx.scenario_id) | (UtilityEvent.scenario_id.is_(None)))
    rows = [e for e in ctx.db.execute(q).scalars().all() if (e.ends_at is None or e.ends_at >= since)]
    return {"events": [{"id": e.id, "kind": e.kind, "segment_id": e.segment_id, "starts_at": iso(e.starts_at), "ends_at": iso(e.ends_at), "description": e.description, "source_id": e.source_id} for e in rows]}


# ---------------------------------------------------------------------------
# HSE OFFICER / PLANNER tools
class ExposureArgs(BaseModel):
    hazard_geometry: dict | None = Field(None, description="GeoJSON; defaults to the incident geometry")
    hazard_label: str = Field("forecast risk", max_length=60)
    buffer_m: float = Field(25.0, ge=0, le=500)
    depth_by_asset: dict[str, float] = Field(default_factory=dict)


@register("assess_asset_exposure", exposure_tool.TOOL_VERSION.split("/")[1], "Overlay a hazard footprint with synthetic assets, worksites and emergency access routes; returns potential exposure (not confirmed consequences).",
          {"hse_officer", "response_planner", "incident_coordinator", "hydrologist"}, ExposureArgs)
def assess_asset_exposure(ctx: ToolContext, a: ExposureArgs) -> dict:
    from ..geo import validate_geometry
    geom = a.hazard_geometry
    if geom is None and ctx.incident_id:
        inc = ctx.db.get(Incident, ctx.incident_id)
        geom = inc.geometry if inc else None
    if geom is None:
        raise ToolError("no hazard geometry")
    problems = validate_geometry(geom)
    if problems:
        raise ToolError("; ".join(problems))
    assets = _asset_dicts(ctx.db, ctx.jurisdiction)
    thresholds = {x["id"]: float(x["attributes"].get("flood_threshold_m")) for x in assets if x["attributes"].get("flood_threshold_m") is not None}
    res = exposure_tool.assess(geom, a.hazard_label, assets, a.buffer_m, a.depth_by_asset or None, thresholds)
    # Emergency routes are road links flagged as such.
    links = ctx.db.execute(select(RoadLink).where(RoadLink.emergency_route.is_(True))).scalars().all()
    from shapely.geometry import shape
    from ..geo import to_metric
    hz = to_metric(shape(geom)).buffer(a.buffer_m)
    res["emergency_routes_potentially_affected"] = [{"link_id": l.id, "name": l.name, "status": l.status} for l in links if l.geometry and hz.intersects(to_metric(shape(l.geometry)))]
    for e in res["exposed_assets"]:
        if e.get("sensitive"):
            e["name"] = "[sensitive asset — details restricted]"
    return res


class CrewArgs(BaseModel):
    capability: str = Field(..., max_length=40)


@register("check_crew_availability", "1.0.0", "List crews with a capability and their current assignment status.",
          {"response_planner", "incident_coordinator"}, CrewArgs)
def check_crew_availability(ctx: ToolContext, a: CrewArgs) -> dict:
    rows = ctx.db.execute(select(Crew)).scalars().all()
    crews = [{"crew_id": c.id, "name": c.name, "department": c.department, "status": c.status, "assigned_incident_id": c.assigned_incident_id, "location": c.geometry}
             for c in rows if a.capability in (c.capability or [])]
    return {"capability": a.capability, "crews": crews, "available": [c for c in crews if c["status"] == "available"]}


class PumpArgs(BaseModel):
    catchment_id: str


@register("check_pump_capacity", "1.0.0", "Report installed, available and deployable (mobile) pump capacity for a catchment.",
          {"response_planner", "incident_coordinator", "hydrologist"}, PumpArgs)
def check_pump_capacity(ctx: ToolContext, a: PumpArgs) -> dict:
    c = _catchment(ctx.db, a.catchment_id)
    installed = avail = 0.0
    station = None
    if c.pump_asset_id:
        p = ctx.db.get(Asset, c.pump_asset_id)
        if p:
            installed = float(p.attributes.get("capacity_m3_s", 0))
            avail = installed * float(p.attributes.get("availability", 1.0))
            station = {"asset_id": p.id, "name": p.name, "availability": p.attributes.get("availability", 1.0), "status": p.attributes.get("status", "unknown")}
    mobile = ctx.db.execute(select(Asset).where(Asset.kind == "mobile_pump")).scalars().all()
    return {"catchment_id": c.id, "drain_capacity_m3_s": c.drain_capacity_m3_s, "pump_station": station, "installed_pump_m3_s": installed, "available_pump_m3_s": avail,
            "mobile_units": [{"asset_id": m.id, "name": m.name, "capacity_m3_s": m.attributes.get("capacity_m3_s"), "status": m.attributes.get("status", "available")} for m in mobile]}


class RouteArgs(BaseModel):
    from_node: str
    to_node: str
    allow_unknown: bool = False


@register("plan_route", routing_tool.TOOL_VERSION.split("/")[1], "Shortest responder route on the seeded road graph excluding flooded/closed links; returns a candidate route requiring verification or 'no verified route'.",
          {"response_planner", "incident_coordinator"}, RouteArgs)
def plan_route(ctx: ToolContext, a: RouteArgs) -> dict:
    links = [{"id": l.id, "from_node": l.from_node, "to_node": l.to_node, "length_m": l.length_m, "status": l.status, "name": l.name}
             for l in ctx.db.execute(select(RoadLink)).scalars().all()]
    res = routing_tool.shortest_path(links, a.from_node, a.to_node, a.allow_unknown)
    names = {l["id"]: l["name"] for l in links}
    res["path_names"] = [names.get(p, p) for p in res["path_links"]]
    return res


class CompetingArgs(BaseModel):
    pass


@register("list_competing_incidents", "1.0.0", "List other open incidents competing for crews and pumps.", {"response_planner", "incident_coordinator"}, CompetingArgs)
def list_competing_incidents(ctx: ToolContext, a: CompetingArgs) -> dict:
    rows = ctx.db.execute(select(Incident).where(Incident.status.notin_(["closed", "cancelled"]), Incident.jurisdiction == ctx.jurisdiction)).scalars().all()
    return {"incidents": [{"incident_id": r.id, "kind": r.kind, "severity_band": r.severity_band, "status": r.status} for r in rows if r.id != ctx.incident_id]}


# ---------------------------------------------------------------------------
# KNOWLEDGE tools
class ProcedureArgs(BaseModel):
    query: str = Field(..., min_length=3, max_length=300)
    collection: str | None = Field(None, max_length=60)
    k: int = Field(3, ge=1, le=6)


@register("retrieve_procedure", "1.0.0", "Retrieve demonstration SOP sections (authorization-filtered) with document id, version and section citations.",
          {"hse_officer", "utility_engineer", "hydrologist", "communications_officer", "assurance_officer", "incident_coordinator", "response_planner"}, ProcedureArgs)
def retrieve_procedure(ctx: ToolContext, a: ProcedureArgs) -> dict:
    from ..knowledge.retrieval import retrieve
    hits = retrieve(ctx.db, a.query, roles=ctx.roles_for_knowledge or [ctx.persona], collection=a.collection, k=a.k)
    if not hits:
        return {"status": "no approved evidence", "hits": [], "note": "No authorized procedure matched. Request human review — do not improvise a procedure."}
    return {"status": "ok", "hits": hits, "retrieval": hits[0].get("method") if hits else None}


class EvidenceSummaryArgs(BaseModel):
    pass


@register("evidence_summary", "1.0.0", "Summarise evidence attached to the incident: kinds, independent sources, freshness, conflicts.",
          {"assurance_officer", "incident_coordinator", "communications_officer", "hse_officer", "response_planner"}, EvidenceSummaryArgs)
def evidence_summary(ctx: ToolContext, a: EvidenceSummaryArgs) -> dict:
    if not ctx.incident_id:
        raise ToolError("no incident in context")
    rows = ctx.db.execute(select(Evidence).where(Evidence.incident_id == ctx.incident_id)).scalars().all()
    independent = {r.independent_source_key for r in rows}
    stale = [r.id for r in rows if r.freshness == "stale"]
    conflicts = [{"evidence_id": r.id, "conflicts_with": r.conflicts_with} for r in rows if r.conflicts_with]
    return {"count": len(rows), "independent_sources": len(independent), "kinds": sorted({r.kind for r in rows}),
            "stale": stale, "conflicts": conflicts, "poor_quality": [r.id for r in rows if r.quality == "poor"],
            "items": [{"id": r.id, "kind": r.kind, "summary": r.summary, "quality": r.quality, "freshness": r.freshness, "source_key": r.independent_source_key} for r in rows]}


class DocArgs(BaseModel):
    doc_id: str


@register("read_document_section", "1.0.0", "Read a specific demonstration document section by id (authorization-filtered).", {"*"}, DocArgs)
def read_document_section(ctx: ToolContext, a: DocArgs) -> dict:
    d = ctx.db.get(Document, a.doc_id)
    if not d:
        raise ToolError("unknown document")
    roles = set(ctx.roles_for_knowledge or [ctx.persona])
    if d.access_roles and not (roles & set(d.access_roles)):
        raise ToolError("not authorized for this document")
    return {"doc_id": d.doc_id, "version": d.version, "section": d.section, "title": d.title, "body": d.body, "collection": d.collection}
