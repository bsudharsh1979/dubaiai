"""Rainfall → runoff → storage water-balance twin.  *Scenario model — uncalibrated.*

Dimensional conventions (SI):
    rainfall intensity   mm/h
    inflow               m³ per step = (mm/h / 1000) * (dt_min / 60) * area_m2 * runoff_coefficient
    drain / pump outflow m³/s  → m³ per step = rate * dt_min * 60
    storage              m³;  synthetic depth = storage / storage_area_m2 (explicit footprint assumption)

Two visibly different mechanisms:
* **Flash-flood catchments** (upstream, ``storage_area_m2`` small, ``downstream_id`` set) hold
  little water: runoff that exceeds local drainage *spills downstream* after
  ``travel_minutes`` (explicit scenario assumption, counted exactly once).
* **Waterlogging basins** (underpass / low point) accumulate whatever drainage and pumps
  cannot remove.  Available outflow is capped by what is physically present.

Mass balance is asserted every step: rain_in == drained + stored + in_transit + spilled_out
(within floating tolerance).  Negative storage or discharging more than is present is impossible
by construction.  Outputs use ordinal bands, never probabilities.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

TOOL_VERSION = "water_balance_twin/0.3.0"

BANDS = ["low", "moderate", "high", "severe"]


@dataclass
class CatchmentSpec:
    id: str
    name: str
    area_m2: float
    runoff_coefficient: float
    storage_area_m2: float
    drain_capacity_m3_s: float
    pump_capacity_m3_s: float = 0.0
    downstream_id: str | None = None
    travel_minutes: float = 0.0
    max_storage_m3: float | None = None   # spill level for basins; None = unbounded ponding
    protects_asset_ids: list[str] = field(default_factory=list)
    mechanism: str = "waterlogging"  # or "flash_flood"


@dataclass
class Controls:
    rain_multiplier: float = 1.0        # scales the forecast intensity series
    drain_blockage: float = 0.0         # 0..1 fraction of drain capacity lost
    pump_availability: float = 1.0      # 0..1 fraction of installed pump capacity available
    extra_pump_m3_s: float = 0.0        # deployed mobile pumps (only after a *completed* deployment)
    upstream_delay_enabled: bool = True


def band_from_depth(depth_m: float, threshold_m: float) -> str:
    """Ordinal band relative to a synthetic asset threshold (e.g. underpass closure depth)."""
    if threshold_m <= 0:
        return "low"
    r = depth_m / threshold_m
    if r < 0.25:
        return "low"
    if r < 0.6:
        return "moderate"
    if r < 1.0:
        return "high"
    return "severe"


def max_band(bands: list[str]) -> str:
    return max(bands, key=BANDS.index) if bands else "low"


def simulate(catchments: list[CatchmentSpec], rain_mm_h: dict[str, list[float]], controls: Controls, dt_min: int = 5,
             horizon_min: int = 180, asset_thresholds_m: dict[str, float] | None = None, initial_storage_m3: dict[str, float] | None = None) -> dict:
    """Run the water balance.  ``rain_mm_h[cid]`` is a per-step series (padded/truncated to the horizon)."""
    steps = horizon_min // dt_min
    dt_s = dt_min * 60
    thresholds = asset_thresholds_m or {}
    by_id = {c.id: c for c in catchments}
    order = _topological(catchments)

    storage = {c.id: float((initial_storage_m3 or {}).get(c.id, 0.0)) for c in catchments}
    transit: dict[str, deque] = {c.id: deque() for c in catchments}  # downstream inbox: (arrive_step, m3)
    totals = {"rain_in": 0.0, "drained": 0.0, "pumped": 0.0, "spilled_out": 0.0}
    series: dict[str, list[dict]] = {c.id: [] for c in catchments}
    peak_depth = {c.id: 0.0 for c in catchments}
    worst_band = {c.id: "low" for c in catchments}
    max_mass_error = 0.0

    for step in range(steps):
        t_min = (step + 1) * dt_min
        for cid in order:
            c = by_id[cid]
            series_rain = rain_mm_h.get(cid, [])
            intensity = (series_rain[step] if step < len(series_rain) else 0.0) * controls.rain_multiplier
            intensity = max(0.0, intensity)
            local_in = (intensity / 1000.0) * (dt_min / 60.0) * c.area_m2 * c.runoff_coefficient
            totals["rain_in"] += local_in

            upstream_in = 0.0
            inbox = transit[cid]
            while inbox and inbox[0][0] <= step:
                upstream_in += inbox.popleft()[1]

            available = storage[cid] + local_in + upstream_in
            drain_cap = c.drain_capacity_m3_s * (1.0 - min(max(controls.drain_blockage, 0.0), 1.0)) * dt_s
            pump_cap = (c.pump_capacity_m3_s * min(max(controls.pump_availability, 0.0), 1.0) + controls.extra_pump_m3_s) * dt_s
            drained = min(available, drain_cap)
            pumped = min(available - drained, pump_cap)
            remaining = available - drained - pumped
            assert remaining >= -1e-9, "negative water"

            spilled = 0.0
            if c.mechanism == "flash_flood":
                # Little storage: excess runoff travels downstream (or leaves the system if there is no downstream).
                spilled = remaining
                remaining = 0.0
            elif c.max_storage_m3 is not None and remaining > c.max_storage_m3:
                spilled = remaining - c.max_storage_m3
                remaining = c.max_storage_m3

            if spilled > 0:
                if c.downstream_id and c.downstream_id in transit:
                    delay_steps = int(round(c.travel_minutes / dt_min)) if controls.upstream_delay_enabled else 0
                    transit[c.downstream_id].append((step + delay_steps, spilled))
                else:
                    totals["spilled_out"] += spilled
            storage[cid] = remaining
            totals["drained"] += drained
            totals["pumped"] += pumped

            depth = remaining / c.storage_area_m2 if c.storage_area_m2 > 0 else 0.0
            peak_depth[cid] = max(peak_depth[cid], depth)
            thr = min([thresholds[a] for a in c.protects_asset_ids if a in thresholds], default=0.3)
            band = band_from_depth(depth, thr)
            worst_band[cid] = max_band([worst_band[cid], band])
            series[cid].append({"t_min": t_min, "rain_mm_h": round(intensity, 2), "inflow_m3": round(local_in, 1), "upstream_in_m3": round(upstream_in, 1),
                                "drained_m3": round(drained, 1), "pumped_m3": round(pumped, 1), "spilled_m3": round(spilled, 1),
                                "storage_m3": round(remaining, 1), "depth_m": round(depth, 3), "band": band})

        in_transit = sum(v for q in transit.values() for _, v in q)
        stored = sum(storage.values())
        balance = totals["rain_in"] - (totals["drained"] + totals["pumped"] + stored + in_transit + totals["spilled_out"])
        max_mass_error = max(max_mass_error, abs(balance))
        if abs(balance) > 1e-6 * max(1.0, totals["rain_in"]):
            raise AssertionError(f"mass balance violated at step {step}: {balance}")

    snapshots = {}
    for h in (30, 60, 180):
        idx = h // dt_min - 1
        if 0 <= idx < steps:
            snapshots[f"+{h}"] = {cid: {"depth_m": series[cid][idx]["depth_m"], "storage_m3": series[cid][idx]["storage_m3"], "band": series[cid][idx]["band"]} for cid in order}

    return {
        "tool_version": TOOL_VERSION,
        "label": "scenario model — uncalibrated",
        "dt_min": dt_min, "horizon_min": horizon_min,
        "controls": controls.__dict__,
        "assumptions": [
            "Inflow = rainfall depth × catchment area × runoff coefficient (stated per catchment).",
            "Synthetic depth = storage ÷ assumed ponding footprint; not a surveyed street depth.",
            "Drained water leaves the modelled system (stormwater network/sea) and is not re-counted.",
            "Upstream travel delay is an explicit scenario assumption; each m³ of runoff is routed once.",
            "Horizons +30/+60/+180 min are simulation horizons, not claimed warning lead times.",
        ],
        "catchments": {cid: {"name": by_id[cid].name, "mechanism": by_id[cid].mechanism, "peak_depth_m": round(peak_depth[cid], 3),
                             "worst_band": worst_band[cid], "final_storage_m3": round(storage[cid], 1), "protects": by_id[cid].protects_asset_ids}
                       for cid in order},
        "series": series,
        "snapshots": snapshots,
        "totals_m3": {k: round(v, 1) for k, v in totals.items()},
        "mass_balance_max_error_m3": max_mass_error,
        "overall_band": max_band(list(worst_band.values())),
    }


def _topological(catchments: list[CatchmentSpec]) -> list[str]:
    ids = {c.id for c in catchments}
    indeg = {c.id: 0 for c in catchments}
    for c in catchments:
        if c.downstream_id in ids:
            indeg[c.downstream_id] += 1
    order, queue = [], [c.id for c in catchments if indeg[c.id] == 0]
    by_id = {c.id: c for c in catchments}
    while queue:
        cid = queue.pop(0)
        order.append(cid)
        d = by_id[cid].downstream_id
        if d in ids:
            indeg[d] -= 1
            if indeg[d] == 0:
                queue.append(d)
    if len(order) != len(catchments):
        raise ValueError("catchment graph has a cycle")
    return order


def compare(baseline: dict, intervention: dict) -> dict:
    """Baseline vs intervention summary with stated differences in controls."""
    out = {}
    for cid, b in baseline["catchments"].items():
        i = intervention["catchments"].get(cid)
        if i:
            out[cid] = {"baseline_peak_depth_m": b["peak_depth_m"], "intervention_peak_depth_m": i["peak_depth_m"],
                        "delta_depth_m": round(i["peak_depth_m"] - b["peak_depth_m"], 3), "baseline_band": b["worst_band"], "intervention_band": i["worst_band"]}
    return {"per_catchment": out, "control_changes": {k: (baseline["controls"][k], intervention["controls"][k]) for k in baseline["controls"] if baseline["controls"][k] != intervention["controls"][k]},
            "label": "scenario comparison — uncalibrated"}
