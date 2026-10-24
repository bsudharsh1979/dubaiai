"""Flow/pressure residual method for leak suspicion (transparent, uncalibrated).

residual_t = observed_t − expected_t, where expected is a seeded diurnal baseline per
sensor.  A sustained positive flow residual together with a negative pressure
residual on the same network segment raises the anomaly band.  Competing
explanations (planned operations, maintenance, demand change, rainfall-driven
inflow, sensor health) are consulted and reported.  Absent telemetry ⇒
``insufficient evidence``.  The output is a *suspected* anomaly with an uncertain
segment; confirmation requires utility/field evidence.
"""
from __future__ import annotations

from statistics import mean, pstdev

TOOL_VERSION = "pressure_flow_residual/0.2.0"


def residuals(observed: list[float], expected: list[float]) -> list[float]:
    n = min(len(observed), len(expected))
    return [observed[i] - expected[i] for i in range(n)]


def zscore(values: list[float], noise_sd: float) -> float:
    if not values:
        return 0.0
    sd = max(noise_sd, 1e-6)
    return mean(values) / sd


def assess(flow_obs: list[float], flow_exp: list[float], pressure_obs: list[float], pressure_exp: list[float], flow_noise_sd: float, pressure_noise_sd: float,
           competing_events: list[dict], sensor_health: dict[str, str], rain_recent_mm: float, segment_ids: list[str], min_samples: int = 6) -> dict:
    fr = residuals(flow_obs, flow_exp)
    pr = residuals(pressure_obs, pressure_exp)
    if len(fr) < min_samples or len(pr) < min_samples:
        return {"tool_version": TOOL_VERSION, "label": "anomaly screen — uncalibrated", "evidence_sufficiency": "insufficient",
                "anomaly_band": "unknown", "reason": f"need ≥{min_samples} paired samples; got flow={len(fr)}, pressure={len(pr)}",
                "candidate_segments": [], "competing_explanations": [], "recommendation": "request telemetry / meter health check"}
    unhealthy = {k: v for k, v in sensor_health.items() if v != "ok"}
    fz = zscore(fr, flow_noise_sd)
    pz = zscore(pr, pressure_noise_sd)
    explanations = []
    for ev in competing_events:
        explanations.append({"kind": ev.get("kind"), "description": ev.get("description"), "segment_id": ev.get("segment_id"),
                             "could_explain": ev.get("kind") in {"planned_operation", "maintenance", "demand_change"}})
    if rain_recent_mm > 2.0:
        explanations.append({"kind": "rainfall", "description": f"{rain_recent_mm:.1f} mm recent rainfall — surface water or infiltration could explain wet ground / flow changes", "could_explain": True})
    if unhealthy:
        explanations.append({"kind": "sensor_health", "description": f"sensor(s) not healthy: {unhealthy}", "could_explain": True})

    # Ordinal band from the joint signature (flow up, pressure down).
    if fz > 4 and pz < -4:
        band = "high"
    elif fz > 2.5 and pz < -2.5:
        band = "moderate"
    elif fz > 2.5 or pz < -2.5:
        band = "low"
    else:
        band = "none"
    plausible_alt = [e for e in explanations if e["could_explain"]]
    sufficiency = "weak" if unhealthy else ("adequate" if band in {"moderate", "high"} else "weak")
    if unhealthy and band != "none":
        band_note = "band downgraded one step because telemetry health is degraded"
        band = {"high": "moderate", "moderate": "low", "low": "low"}[band]
    else:
        band_note = None
    return {"tool_version": TOOL_VERSION, "label": "anomaly screen — uncalibrated",
            "flow_residual_mean": round(mean(fr), 3), "flow_residual_sd": round(pstdev(fr), 3), "flow_z": round(fz, 2),
            "pressure_residual_mean": round(mean(pr), 3), "pressure_z": round(pz, 2),
            "anomaly_band": band, "band_note": band_note, "evidence_sufficiency": sufficiency,
            "competing_explanations": explanations, "plausible_alternatives": len(plausible_alt),
            "candidate_segments": segment_ids if band in {"moderate", "high"} else [],
            "location_uncertainty": "network segment level; exact point unknown",
            "recommendation": ("request utility confirmation and field inspection" if band in {"moderate", "high"} and not plausible_alt
                               else "resolve competing explanations before escalating" if plausible_alt and band != "none"
                               else "continue monitoring"),
            "caveats": ["A wet satellite patch or photo alone cannot confirm a burst pipe.", "Confirmation requires utility/field evidence."]}
