"""Evaluation harness.

Four separate tracks with honest defaults:
* observed-water segmentation (IoU / precision / recall) — runs on labelled rasters; the
  only labels available here are *synthetic* fixtures, so results are reported as
  "synthetic fixture only — predictive skill not evaluated";
* forecast skill (event recall, false alerts per area-time, lead time, calibration) — no
  real labels → "not evaluated";
* leak detection (event precision/recall, time to detection) — no confirmed labels →
  "not evaluated";
* agent operation (tool selection, evidence grounding, task completion, approval
  compliance, latency) — measured from persisted runs in this database.

Partitioning: fixtures carry an ``event_id``/time/geography; the harness refuses to score
a tile whose footprint overlaps a training tile and only admits inputs with
``available_at <= decision_time``.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import rasterio
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AgentRun, Approval, Incident, PolicyDecision, ToolResult, WorkOrder


def segmentation_metrics(pred_path: str, truth_path: str, positive_class: int = 1) -> dict:
    with rasterio.open(pred_path) as p, rasterio.open(truth_path) as t:
        pred = p.read(1) == positive_class
        truth = t.read(1) > 0
        unknown = p.read(1) == 3
    valid = ~unknown
    tp = int((pred & truth & valid).sum())
    fp = int((pred & ~truth & valid).sum())
    fn = int((~pred & truth & valid).sum())
    iou = tp / (tp + fp + fn) if (tp + fp + fn) else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    return {"iou": round(iou, 4), "precision": round(prec, 4), "recall": round(rec, 4), "tp": tp, "fp": fp, "fn": fn, "unknown_excluded_px": int(unknown.sum()),
            "note": "computed on the explicitly SYNTHETIC fixture — validates the pipeline, not predictive skill"}


def no_leakage(inputs: list[dict], decision_time: datetime) -> dict:
    late = [i for i in inputs if i.get("available_at") and i["available_at"] > decision_time]
    return {"ok": not late, "excluded_future_inputs": [i.get("id") for i in late]}


def tiles_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def partition_check(train_tiles: list[tuple], test_tiles: list[tuple]) -> dict:
    overlaps = [(i, j) for i, a in enumerate(train_tiles) for j, b in enumerate(test_tiles) if tiles_overlap(a, b)]
    return {"ok": not overlaps, "overlapping_pairs": overlaps}


def agent_metrics(db: Session) -> dict:
    runs = db.execute(select(AgentRun)).scalars().all()
    tools = db.execute(select(ToolResult)).scalars().all()
    incs = db.execute(select(Incident)).scalars().all()
    aps = db.execute(select(Approval)).scalars().all()
    wos = db.execute(select(WorkOrder)).scalars().all()
    pds = db.execute(select(PolicyDecision)).scalars().all()
    lat = [(r.finished_at - r.started_at).total_seconds() for r in runs if r.finished_at]
    completed = [r for r in runs if r.status == "completed"]
    exercised = [r for r in runs if r.model_exercised]
    return {"persona_runs": len(runs), "completed": len(completed), "failed_or_limited": len([r for r in runs if r.status in {"failed", "limited"}]),
            "model_exercised_runs": len(exercised), "tool_calls": len(tools), "tool_errors": len([t for t in tools if not t.ok]),
            "mean_persona_latency_s": round(float(np.mean(lat)), 3) if lat else None, "p95_persona_latency_s": round(float(np.percentile(lat, 95)), 3) if lat else None,
            "incidents": len(incs), "incidents_with_proposals": len({a.incident_id for a in aps}), "approvals": len(aps), "approvals_expired_or_invalidated": len([a for a in aps if a.status in {"expired", "invalidated"}]),
            "work_orders": len(wos), "work_orders_completed": len([w for w in wos if w.status == "completed"]),
            "policy_denials": len([p for p in pds if p.decision == "deny"]), "policy_reviews": len([p for p in pds if p.decision == "review"]),
            "dispatch_without_approval": len([w for w in wos if w.status in {"dispatched", "acknowledged", "completed"} and not w.approval_id]),
            "note": "workflow validation on synthetic scenarios; not a measure of real-world accuracy"}


def summary(db: Session) -> dict:
    return {"observed_water_segmentation": {"status": "synthetic fixture only", "metric_names": ["IoU", "precision", "recall"], "real_labelled_imagery": "not available — not evaluated"},
            "forecast_skill": {"status": "not evaluated", "metric_names": ["event recall", "false alerts per area-time", "lead time", "calibration (if probabilities exist)"], "reason": "no real event labels; twin outputs are uncalibrated bands"},
            "leak_detection": {"status": "not evaluated", "metric_names": ["event precision", "event recall", "time to detection"], "reason": "no confirmed leak labels"},
            "agent_operation": agent_metrics(db),
            "partitioning": "by event / time / geography; overlapping tiles rejected; inputs with available_at > decision_time excluded"}
