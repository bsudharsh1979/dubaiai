"""Spatial asset exposure (shapely).  Flags *potential* exposure of electrical assets,
occupied worksites and emergency access routes to observed/forecast water.  It never
claims a confirmed electrical fault, casualty or safe route."""
from __future__ import annotations

from shapely.geometry import shape

from ..geo import to_metric

TOOL_VERSION = "asset_exposure/0.2.0"

CONSEQUENCE_BY_KIND = {
    "substation": ("electrical", "potential electrical hazard / supply interruption"),
    "underpass": ("transport", "potential vehicle entrapment / closure"),
    "worksite": ("occupancy", "potential risk to occupied worksite"),
    "hospital_access": ("emergency_access", "potential loss of emergency access route"),
    "pump_station": ("drainage", "potential loss of drainage capacity"),
    "pipe_segment": ("utility", "potential water-main involvement"),
    "road_link": ("transport", "potential road inundation"),
}
CRIT_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def assess(hazard_geojson: dict, hazard_label: str, assets: list[dict], buffer_m: float = 25.0, depth_by_asset: dict[str, float] | None = None,
           thresholds_m: dict[str, float] | None = None) -> dict:
    hz = to_metric(shape(hazard_geojson))
    hz_b = hz.buffer(buffer_m)
    exposed = []
    for a in assets:
        if not a.get("geometry"):
            continue
        g = to_metric(shape(a["geometry"]))
        d = g.distance(hz)
        if hz_b.intersects(g):
            cat, cons = CONSEQUENCE_BY_KIND.get(a["kind"], ("other", "potential exposure"))
            depth = (depth_by_asset or {}).get(a["id"])
            thr = (thresholds_m or {}).get(a["id"])
            over = (depth is not None and thr is not None and depth >= thr)
            exposed.append({"asset_id": a["id"], "name": a["name"], "kind": a["kind"], "criticality": a.get("criticality", "medium"),
                            "distance_m": round(d, 1), "category": cat, "potential_consequence": cons,
                            "synthetic_depth_m": depth, "synthetic_threshold_m": thr, "threshold_exceeded": over,
                            "sensitive": bool(a.get("sensitive"))})
    exposed.sort(key=lambda e: (-CRIT_RANK.get(e["criticality"], 1), e["distance_m"]))
    worst = max((CRIT_RANK.get(e["criticality"], 1) + (1 if e["threshold_exceeded"] else 0) for e in exposed), default=-1)
    consequence = "severe" if worst >= 3 else "major" if worst == 2 else "moderate" if worst == 1 else "minor"
    return {"tool_version": TOOL_VERSION, "hazard_label": hazard_label, "buffer_m": buffer_m, "exposed_assets": exposed,
            "consequence_band": consequence, "categories": sorted({e["category"] for e in exposed}),
            "caveats": ["Potential exposure only — not a confirmed fault, casualty or safe/unsafe route determination.",
                        "Synthetic assets; real sensitive infrastructure is not represented as verified."]}
