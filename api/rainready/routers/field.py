"""Field reports (upload hardening + observation/instruction separation), raster imports, knowledge, geo."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, events, gateway
from ..auth import Identity, current_identity, require
from ..clock import iso, parse_iso, utcnow
from ..config import get_settings
from ..db import get_db
from ..geo import DEMO_BOUNDS, UAE_BOUNDS, apply_bbox, point, validate_geometry
from ..knowledge.retrieval import retrieve
from ..models import Asset, Catchment, FieldReport, Incident, RasterImport, RoadLink, Scenario, Scene, Sensor, new_id
from ..providers.guard import separate
from ..providers.registry import get_providers
from ..schemas import FieldReportReviewIn, ImportMetadata
from ..tools import sar
from .incidents import fr_dict

router = APIRouter(prefix="/api", tags=["field", "imports", "knowledge", "geo"])

ALLOWED_IMAGE = {"image/jpeg": ".jpg", "image/png": ".png"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_RASTER_BYTES = 64 * 1024 * 1024


def _safe_name(ext: str) -> str:
    return f"{uuid.uuid4().hex}{ext}"


def _sniff_image(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


@router.post("/field-reports")
async def submit_report(description: str = Form(..., max_length=2000), lat: float = Form(...), lon: float = Form(...), capture_time: str = Form(...), incident_id: str | None = Form(None),
                        scenario_id: str | None = Form(None), photo: UploadFile | None = File(None), ident: Identity = Depends(require("field_report:submit")), db: Session = Depends(get_db)):
    s = get_settings()
    try:
        cap = parse_iso(capture_time)
    except Exception:
        raise HTTPException(422, "capture_time must be ISO 8601")
    geom = point(lon, lat)
    problems = validate_geometry(geom)
    if problems:
        raise HTTPException(422, "; ".join(problems))
    now = utcnow()
    flags: list[str] = []
    if cap > now + timedelta(minutes=5):
        flags.append("capture_time_in_future")
    if now - cap > timedelta(hours=6):
        flags.append("capture_time_stale")
    if not (DEMO_BOUNDS["minx"] <= lon <= DEMO_BOUNDS["maxx"] and DEMO_BOUNDS["miny"] <= lat <= DEMO_BOUNDS["maxy"]):
        flags.append("location_outside_demo_area")
    sep = separate(description)
    photo_path = photo_mime = photo_hash = None
    if photo is not None and photo.filename:
        data = await photo.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "photo exceeds 8 MB")
        sniffed = _sniff_image(data)
        if sniffed is None or sniffed not in ALLOWED_IMAGE:
            raise HTTPException(415, "photo must be JPEG or PNG (content-sniffed)")
        photo_mime = sniffed
        photo_hash = hashlib.sha256(data).hexdigest()
        # Metadata minimisation: we store the raw bytes under a random name and never read EXIF; location/time come from the declared fields.
        Path(s.attachments_dir).mkdir(parents=True, exist_ok=True)
        dest = Path(s.attachments_dir) / _safe_name(ALLOWED_IMAGE[sniffed])
        dest.write_bytes(data)
        photo_path = str(dest)
        dup = db.execute(select(FieldReport).where(FieldReport.photo_sha256 == photo_hash)).scalar_one_or_none()
        if dup:
            flags.append(f"duplicate_photo_of:{dup.id}")
    reliability = "disputed" if any(f.startswith(("capture_time", "location_outside", "duplicate_photo")) for f in flags) else "unverified"
    inc = db.get(Incident, incident_id) if incident_id else None
    if incident_id and not inc:
        raise HTTPException(404, "incident not found")
    fr = FieldReport(id=new_id("fr"), reporter_id=ident.id, scenario_id=scenario_id or (inc.scenario_id if inc else None), incident_id=inc.id if inc else None, capture_time=cap, created_at=now,
                     description=description, observation_text=sep.observations or "(no observation text — report contained only instructions)", isolated_instructions=sep.instructions,
                     photo_path=photo_path, photo_mime=photo_mime, photo_sha256=photo_hash, reliability=reliability, review_status="pending", safety_flags=sep.flags + flags,
                     source_id=f"field:{ident.id}", observed_at=cap, available_at=now, received_at=now, units=None, quality_flags=flags, provenance_uri="app://field-report",
                     checksum=photo_hash or hashlib.sha256(description.encode()).hexdigest()[:16], license_class="internal", simulation_status="live-demo-input")
    apply_bbox(fr, geom)
    db.add(fr)
    db.flush()
    guard = get_providers().guard.check(description, "field_report")
    audit.record(db, ident.id, "field_report.submitted", "field_report", fr.id, {"incident_id": fr.incident_id, "flags": fr.safety_flags, "instructions_isolated": len(sep.instructions), "guard": guard["categories"]})
    if sep.privileged_action_attempt:
        audit.record(db, "gateway", "action.blocked", "field_report", fr.id, {"reason": "privileged instruction embedded in untrusted report; no action path exists from reports", "instructions": sep.instructions})
        events.publish("security", {"kind": "injection_isolated", "field_report_id": fr.id, "incident_id": fr.incident_id, "instructions": sep.instructions})
    if sep.casualty_mention and inc:
        inc.status = "urgent_human_review" if inc.status not in {"closed", "cancelled"} else inc.status
        inc.next_decision = "urgent human review — field report mentions possible casualties (preserved for reviewer; not auto-published)"
        audit.record(db, "gateway", "incident.urgent_review", "incident", inc.id, {"reason": "casualty mention in field report", "field_report_id": fr.id})
    events.publish("field_report", {"field_report_id": fr.id, "incident_id": fr.incident_id, "flags": fr.safety_flags})
    if inc and inc.status not in {"closed", "cancelled", "urgent_human_review"}:
        gateway.enqueue(db, "reassess", {"incident_id": inc.id, "reason": f"new field report {fr.id}"}, key=f"reassess:{inc.id}:fr:{fr.id}")
    return {**fr_dict(fr), "guard": guard, "note": "Instructions inside the report were isolated and will not be executed." if sep.instructions else None}


@router.get("/field-reports")
def list_reports(ident: Identity = Depends(current_identity), db: Session = Depends(get_db), incident_id: str | None = None):
    q = select(FieldReport).order_by(FieldReport.created_at.desc()).limit(100)
    if incident_id:
        q = select(FieldReport).where(FieldReport.incident_id == incident_id).order_by(FieldReport.created_at.desc())
    return [fr_dict(f) for f in db.execute(q).scalars().all()]


@router.post("/field-reports/{report_id}/review")
def review_report(report_id: str, body: FieldReportReviewIn, ident: Identity = Depends(require("field_report:review")), db: Session = Depends(get_db)):
    fr = db.get(FieldReport, report_id)
    if not fr:
        raise HTTPException(404, "report not found")
    fr.review_status = body.review_status
    if body.reliability:
        fr.reliability = body.reliability
    fr.reviewed_by = ident.id
    if body.attach_incident_id:
        inc = db.get(Incident, body.attach_incident_id)
        if not inc:
            raise HTTPException(404, "incident not found")
        fr.incident_id = inc.id
    audit.record(db, ident.id, "field_report.reviewed", "field_report", fr.id, {"review_status": fr.review_status, "reliability": fr.reliability, "incident_id": fr.incident_id})
    events.publish("field_report", {"field_report_id": fr.id, "incident_id": fr.incident_id, "review_status": fr.review_status})
    if fr.incident_id:
        gateway.enqueue(db, "reassess", {"incident_id": fr.incident_id, "reason": f"field report {fr.id} reviewed: {fr.review_status}"}, key=f"reassess:{fr.incident_id}:frrev:{fr.id}:{fr.review_status}")
    return fr_dict(fr)


# ---------------------------------------------------------------------------
# Sentinel-1 import
def _write_upload(data: bytes, name: str) -> str:
    s = get_settings()
    d = Path(s.rasters_dir) / "imports"
    d.mkdir(parents=True, exist_ok=True)
    if data[:4] not in (b"II*\x00", b"MM\x00*"):
        raise HTTPException(415, f"{name}: not a TIFF (magic bytes)")
    p = d / _safe_name(".tif")
    p.write_bytes(data)
    return str(p)


def run_import(db: Session, ident_id: str, before_path: str, after_path: str, meta: ImportMetadata, simulation_status: str, permanent_water: str | None = None, shadow: str | None = None) -> RasterImport:
    s = get_settings()
    val = sar.validate_pair(before_path, after_path, meta.before.model_dump(), meta.after.model_dump())
    imp = RasterImport(id=new_id("imp"), kind="sentinel1_pair", status="validated" if val["ok"] else "rejected", created_by=ident_id, created_at=utcnow(), validation=val, result={}, simulation_status=simulation_status)
    db.add(imp)
    db.flush()
    if not val["ok"]:
        audit.record(db, ident_id, "import.rejected", "raster_import", imp.id, {"problems": val["problems"]})
        return imp
    out = str(Path(s.rasters_dir) / "imports" / f"{imp.id}_change_mask.tif")
    res = sar.change_mask(before_path, after_path, out, permanent_water, shadow)
    derived = {k: res[k] for k in ("label", "summary", "unknown_fraction", "evidence_quality", "candidate_bounds_wgs84", "footprint_wgs84", "thresholds", "caveats")}
    derived["mask_path"] = out
    common = dict(feed_id="sentinel1", platform="sentinel-1", crs=val["raster"]["crs"], resolution=f"{val['raster']['pixel_size_m']} m" if val["raster"]["pixel_size_m"] else None, units="dB",
                  preprocessing=meta.after.preprocessing, orbit=meta.after.orbit, license_class=meta.after.license_class, simulation_status=simulation_status, scenario_id=meta.scenario_id)
    fp = res.get("footprint_wgs84")
    geom = {"type": "Polygon", "coordinates": [[[fp[0], fp[1]], [fp[2], fp[1]], [fp[2], fp[3]], [fp[0], fp[3]], [fp[0], fp[1]]]]} if fp else None
    b = Scene(id=new_id("scn"), scene_role="before", source_id=meta.before.source_id, observed_at=meta.before.acquisition_at, available_at=meta.before.available_at, received_at=utcnow(), file_path=before_path,
              checksum=sar.sha256_file(before_path), provenance_uri=meta.before.provenance_uri, quality_flags=val["warnings"], derived={}, **common)
    a = Scene(id=new_id("scn"), scene_role="after", source_id=meta.after.source_id, observed_at=meta.after.acquisition_at, available_at=meta.after.available_at, received_at=utcnow(), file_path=after_path,
              checksum=sar.sha256_file(after_path), provenance_uri=meta.after.provenance_uri, quality_flags=val["warnings"], derived=derived, **common)
    for sc in (b, a):
        apply_bbox(sc, geom)
        db.add(sc)
    imp.before_scene_id, imp.after_scene_id, imp.status, imp.result = b.id, a.id, "processed", derived
    audit.record(db, ident_id, "import.processed", "raster_import", imp.id, {"after_scene_id": a.id, "unknown_fraction": res["unknown_fraction"], "label": res["label"]})
    events.publish("import", {"import_id": imp.id, "status": imp.status})
    return imp


def _imp_dict(i: RasterImport) -> dict:
    return {"id": i.id, "kind": i.kind, "status": i.status, "created_by": i.created_by, "created_at": iso(i.created_at), "validation": i.validation, "result": i.result, "before_scene_id": i.before_scene_id,
            "after_scene_id": i.after_scene_id, "simulation_status": i.simulation_status}


@router.post("/imports/sentinel1")
async def import_sentinel1(before: UploadFile = File(...), after: UploadFile = File(...), metadata: str = Form(...), ident: Identity = Depends(require("import:raster")), db: Session = Depends(get_db)):
    try:
        meta = ImportMetadata.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(422, f"metadata invalid: {e}")
    bdata, adata = await before.read(), await after.read()
    if len(bdata) > MAX_RASTER_BYTES or len(adata) > MAX_RASTER_BYTES:
        raise HTTPException(413, "raster exceeds 64 MB (use the local file import path for larger scenes)")
    bp, ap = _write_upload(bdata, "before"), _write_upload(adata, "after")
    imp = run_import(db, ident.id, bp, ap, meta, meta.after.simulation_status)
    return _imp_dict(imp)


@router.post("/imports/sentinel1/fixture")
def import_fixture(ident: Identity = Depends(require("import:raster")), db: Session = Depends(get_db), scenario_id: str | None = None, misaligned: bool = False):
    """Generate an explicitly synthetic before/after pair and run the import path (demo button + tests)."""
    s = get_settings()
    d = Path(s.rasters_dir) / "fixtures" / uuid.uuid4().hex[:8]
    paths = sar.write_synthetic_pair(d, size=96, pixel_m=10.0, origin_xy=(530_000.0, 2_786_000.0))
    if misaligned:
        bad = sar.write_synthetic_pair(d / "bad", size=96, pixel_m=10.0, origin_xy=(530_005.0, 2_786_000.0))
        paths["after"] = bad["after"]
    now = utcnow()
    meta = ImportMetadata(before={"source_id": "synthetic-fixture-before", "acquisition_at": now - timedelta(days=6), "available_at": now - timedelta(days=6, hours=-6), "orbit": "rel-130-desc", "polarisation": "VV",
                                  "preprocessing": "synthetic calibrated dB", "provenance_uri": f"file://{paths['before']}", "license_class": "synthetic-demo"},
                          after={"source_id": "synthetic-fixture-after", "acquisition_at": now - timedelta(hours=10), "available_at": now - timedelta(hours=4), "orbit": "rel-130-desc", "polarisation": "VV",
                                 "preprocessing": "synthetic calibrated dB", "provenance_uri": f"file://{paths['after']}", "license_class": "synthetic-demo"}, scenario_id=scenario_id)
    imp = run_import(db, ident.id, paths["before"], paths["after"], meta, "synthetic", paths["permanent_water"], paths["shadow"])
    return _imp_dict(imp)


@router.get("/imports")
def list_imports(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    return [_imp_dict(i) for i in db.execute(select(RasterImport).order_by(RasterImport.created_at.desc()).limit(50)).scalars().all()]


@router.get("/scenes")
def list_scenes(ident: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    rows = db.execute(select(Scene).order_by(Scene.observed_at.desc()).limit(50)).scalars().all()
    return [{"id": s.id, "platform": s.platform, "role": s.scene_role, "scenario_id": s.scenario_id, "acquisition_at": iso(s.observed_at), "available_at": iso(s.available_at), "crs": s.crs, "resolution": s.resolution,
             "orbit": s.orbit, "cloud_fraction": s.cloud_fraction, "quality_flags": s.quality_flags, "derived": s.derived, "license_class": s.license_class, "simulation_status": s.simulation_status, "geometry": s.geometry} for s in rows]


# ---------------------------------------------------------------------------
@router.get("/knowledge/search")
def knowledge_search(q: str, ident: Identity = Depends(require("knowledge:read")), db: Session = Depends(get_db), collection: str | None = None, k: int = 5):
    if len(q) < 3:
        raise HTTPException(422, "query too short")
    emb = get_providers().embeddings
    qe = None
    vecs = emb.embed([q]) if emb.status().configured else None
    if vecs:
        qe = vecs[0]
    hits = retrieve(db, q, roles=[ident.role, "*"], collection=collection, k=k, query_embedding=qe)
    return {"query": q, "hits": hits, "retrieval": emb.status().__dict__, "label": "demonstration procedures — not official policy"}


# ---------------------------------------------------------------------------
@router.get("/geo/basemap")
def basemap(db: Session = Depends(get_db)):
    """Local attributed basemap: synthetic sector outline, roads, assets and catchments.  No external tiles."""
    assets = db.execute(select(Asset)).scalars().all()
    cats = db.execute(select(Catchment)).scalars().all()
    links = db.execute(select(RoadLink)).scalars().all()
    sensors = db.execute(select(Sensor)).scalars().all()
    scenes = db.execute(select(Scene).where(Scene.derived.isnot(None))).scalars().all()
    feats = lambda rows, props: {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": r.geometry, "properties": props(r)} for r in rows if r.geometry]}
    return {"attribution": "RainReady synthetic basemap — Demo Sector 7 outline, roads and assets are invented for demonstration; no external tiles or real sensitive infrastructure.",
            "center": [55.3100, 25.1900], "zoom": 14.2,
            "assets": feats(assets, lambda a: {"id": a.id, "kind": a.kind, "name": a.name, "name_ar": a.name_ar, "criticality": a.criticality, "sensitive": a.sensitive, **{k: v for k, v in a.attributes.items() if k in {"flood_threshold_m", "capacity_m3_s", "availability", "status"}}}),
            "catchments": feats(cats, lambda c: {"id": c.id, "name": c.name, "mechanism": c.assumptions.get("mechanism"), "travel_minutes": c.travel_minutes}),
            "roads": feats(links, lambda l: {"id": l.id, "name": l.name, "status": l.status, "emergency_route": l.emergency_route}),
            "sensors": feats(sensors, lambda s: {"id": s.id, "kind": s.kind, "health": s.health, "units": s.units}),
            "scene_candidates": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": _bounds_poly(s.derived.get("candidate_bounds_wgs84")), "properties": {"scene_id": s.id, "label": s.derived.get("label"), "acquisition_at": iso(s.observed_at), "scenario_id": s.scenario_id}}
                                                                           for s in scenes if s.derived.get("candidate_bounds_wgs84")]},
            "sector": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[55.292, 25.177], [55.324, 25.177], [55.324, 25.202], [55.292, 25.202], [55.292, 25.177]]]}, "properties": {"name": "Demo Sector 7 (synthetic)"}}}


def _bounds_poly(b):
    if not b:
        return None
    return {"type": "Polygon", "coordinates": [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]]}


@router.get("/geo/uae")
def uae_outline():
    """Coarse, hand-simplified UAE outline for the overview map (schematic, not authoritative)."""
    coords = [[51.58, 24.26], [52.6, 24.15], [53.6, 24.1], [54.3, 24.3], [54.6, 24.6], [55.0, 24.95], [55.3, 25.25], [55.6, 25.55], [56.0, 25.95], [56.35, 26.05], [56.4, 25.6], [56.35, 25.0], [56.1, 24.75], [56.0, 24.2], [55.8, 23.9], [55.6, 22.95], [55.2, 22.7], [52.6, 22.95], [51.6, 24.0], [51.58, 24.26]]
    return {"type": "FeatureCollection", "attribution": "Schematic UAE outline (hand-simplified, not authoritative)",
            "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]}, "properties": {"name": "United Arab Emirates (schematic)"}},
                         {"type": "Feature", "geometry": {"type": "Point", "coordinates": [55.31, 25.19]}, "properties": {"name": "Dubai demonstration sector", "kind": "demo_area"}},
                         {"type": "Feature", "geometry": {"type": "Point", "coordinates": [54.37, 24.45]}, "properties": {"name": "Abu Dhabi (reference)", "kind": "reference"}},
                         {"type": "Feature", "geometry": {"type": "Point", "coordinates": [55.39, 25.35]}, "properties": {"name": "Sharjah (reference)", "kind": "reference"}}]}
