"""Graph runner: starts incidents, resumes interrupts, re-enters for reassessment.
A single compiled graph with a durable checkpointer is shared per process; dropping
the handle (``reset_graph``) simulates a restart — state survives in the database."""
from __future__ import annotations

import logging
import threading

from langgraph.types import Command

from .. import audit, events
from ..clock import iso, utcnow
from ..db import session_scope
from ..geo import apply_bbox
from ..models import Asset, Incident, Scenario, new_id
from .graph import build_context, build_graph, make_checkpointer

log = logging.getLogger("rainready.runner")
_graph = None
_lock = threading.Lock()


def get_graph():
    global _graph
    with _lock:
        if _graph is None:
            _graph = build_graph(make_checkpointer())
    return _graph


def reset_graph() -> None:
    """Simulates a worker restart: drops the in-memory graph/checkpointer handle."""
    global _graph
    with _lock:
        _graph = None


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}


def _thread_id(incident_id: str) -> str:
    with session_scope() as db:
        inc = db.get(Incident, incident_id)
        return (inc.graph_thread_id if inc and inc.graph_thread_id else incident_id)


def pending_interrupt(incident_id: str, thread_id: str | None = None) -> dict | None:
    snap = get_graph().get_state(_config(thread_id or _thread_id(incident_id)))
    for task in getattr(snap, "tasks", ()) or ():
        for intr in getattr(task, "interrupts", ()) or ():
            return intr.value if hasattr(intr, "value") else dict(intr)
    return None


def start_incident(scenario_id: str, kind: str, actor: str, trigger: dict | None = None, title: str | None = None) -> str:
    with session_scope() as db:
        sc = db.get(Scenario, scenario_id)
        if not sc:
            raise ValueError("unknown scenario")
        p = sc.params or {}
        focus = p.get("focus_asset_ids", [])
        geom = p.get("area_geometry")
        if geom is None and focus:
            a = db.get(Asset, focus[0])
            geom = a.geometry if a else None
        dedupe = f"{kind}:{scenario_id}:{focus[0] if focus else 'area'}"
        inc = Incident(id=new_id("inc"), scenario_id=scenario_id, kind=kind, title=title or p.get("title", sc.name), title_ar=p.get("title_ar"), label=p.get("initial_label", "susceptibility"),
                       status="open", severity_band="low", risk_band="low", consequence="minor", evidence_quality="insufficient", asset_ids=focus, jurisdiction="dubai-demo",
                       summary={"scenario": sc.name, "data_mode": sc.data_mode}, created_at=utcnow(), updated_at=utcnow(), dedupe_key=dedupe, graph_thread_id=None)
        apply_bbox(inc, geom)
        inc.graph_thread_id = inc.id
        db.add(inc)
        db.flush()
        audit.record(db, actor, "incident.created", "incident", inc.id, {"scenario_id": scenario_id, "kind": kind, "dedupe_key": dedupe})
        incident_id = inc.id
        decision_time = iso(sc.decision_time)
        ctx = build_context(db, sc, kind)
    events.publish("incident", {"incident_id": incident_id, "status": "open", "step": "created"})
    state = {"incident_id": incident_id, "thread_id": incident_id, "scenario_id": scenario_id, "decision_time": decision_time, "kind": kind,
             "trigger": trigger or {"reason": "scenario_start", "actor": actor}, "context": ctx, "evidence_loop": 0, "log": []}
    get_graph().invoke(state, _config(incident_id))
    return incident_id


def resume_incident(incident_id: str, decision: dict) -> bool:
    tid = _thread_id(incident_id)
    if pending_interrupt(incident_id) is None:
        log.info("resume ignored for %s: no pending interrupt", incident_id)
        return False
    get_graph().invoke(Command(resume=decision), _config(tid))
    return True


def reassess_incident(incident_id: str, reason: str, actor: str = "worker") -> bool:
    """Re-enter the graph (new evidence / completed work / timer) on a fresh thread lineage.
    The incident version bump invalidates any approval bound to the previous version."""
    with session_scope() as db:
        inc = db.get(Incident, incident_id)
        if not inc or inc.status in {"closed", "cancelled"}:
            return False
        sc = db.get(Scenario, inc.scenario_id)
        if not sc:
            return False
        loop = len(inc.summary.get("evidence_requests", [])) if inc.status == "awaiting_evidence" else 0
        inc.summary = {**inc.summary, "reassess_count": int(inc.summary.get("reassess_count", 0)) + 1}
        inc.version += 1
        inc.updated_at = utcnow()
        thread_id = f"{incident_id}#v{inc.version}"
        inc.graph_thread_id = thread_id
        audit.record(db, actor, "incident.reassess", "incident", inc.id, {"reason": reason, "version": inc.version})
        decision_time = iso(sc.decision_time)
        ctx = build_context(db, sc, inc.kind)
        kind, scenario_id = inc.kind, inc.scenario_id
    state = {"incident_id": incident_id, "thread_id": thread_id, "scenario_id": scenario_id, "decision_time": decision_time, "kind": kind,
             "trigger": {"reason": "reassess", "detail": reason, "actor": actor}, "context": ctx, "evidence_loop": loop, "log": []}
    get_graph().invoke(state, _config(thread_id))
    return True
