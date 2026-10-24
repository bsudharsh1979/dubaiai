"""Background worker: durable job queue (resume graph, reassess), escalation timers,
approval expiry and retry budgets.  Runs as a thread inside the API process by default
(docker-compose runs it as a separate container with the same code)."""
from __future__ import annotations

import logging
import threading
import time
import traceback

from sqlalchemy import select

from . import audit, events
from .clock import iso, utcnow
from .config import get_settings
from .db import session_scope
from .models import Approval, Incident, Job, WorkOrder

log = logging.getLogger("rainready.worker")
_thread: threading.Thread | None = None
_stop = threading.Event()
_last_tick: str | None = None


def is_alive() -> bool:
    return _thread is not None and _thread.is_alive()


def last_tick() -> str | None:
    return _last_tick


def run_job(job_kind: str, payload: dict) -> None:
    from .agents import runner
    if job_kind == "resume_graph":
        runner.resume_incident(payload["incident_id"], {"decision": payload["decision"], "approval_id": payload.get("approval_id")})
    elif job_kind == "reassess":
        runner.reassess_incident(payload["incident_id"], payload.get("reason", "reassess"))
    else:
        raise ValueError(f"unknown job kind {job_kind}")


def tick_once() -> int:
    """Process due jobs and timers once; returns number of jobs handled.  Safe to call from tests."""
    global _last_tick
    s = get_settings()
    handled = 0
    now = utcnow()
    # --- claim one job at a time (BEGIN IMMEDIATE on SQLite serialises claims) ---
    while True:
        with session_scope() as db:
            job = db.execute(select(Job).where(Job.status == "queued", Job.run_at <= now).order_by(Job.run_at).limit(1)).scalar_one_or_none()
            if not job:
                break
            job.status = "running"
            job.attempts += 1
            jid, kind, payload, attempts, max_attempts = job.id, job.kind, dict(job.payload), job.attempts, job.max_attempts
        try:
            run_job(kind, payload)
            with session_scope() as db:
                j = db.get(Job, jid)
                j.status = "done"
        except Exception as e:  # noqa: BLE001
            log.error("job %s failed: %s\n%s", jid, e, traceback.format_exc())
            with session_scope() as db:
                j = db.get(Job, jid)
                j.last_error = str(e)[:500]
                if attempts >= max_attempts:
                    j.status = "failed"
                    audit.record(db, "worker", "job.failed", "job", jid, {"kind": kind, "error": j.last_error, "attempts": attempts})
                    inc = db.get(Incident, payload.get("incident_id", "")) if payload.get("incident_id") else None
                    if inc and inc.status not in {"closed", "cancelled"}:
                        inc.status = "urgent_human_review"
                        inc.next_decision = f"urgent human review — background job {kind} exhausted its retry budget"
                else:
                    j.status = "queued"
                    j.run_at = utcnow().replace(microsecond=0) + __import__("datetime").timedelta(seconds=2 * attempts)
        handled += 1
    # --- escalation timers: dispatched work orders without acknowledgement ---
    with session_scope() as db:
        for wo in db.execute(select(WorkOrder).where(WorkOrder.status == "dispatched", WorkOrder.escalation_due_at.isnot(None), WorkOrder.escalation_due_at <= now)).scalars().all():
            wo.escalation_due_at = None
            wo.retry_count += 1
            wo.payload = {**wo.payload, "escalated_at": iso(now), "escalation": "no acknowledgement within window"}
            audit.record(db, "worker", "workorder.escalated", "work_order", wo.id, {"department": wo.department, "retry_count": wo.retry_count})
            inc = db.get(Incident, wo.incident_id)
            if inc and inc.status not in {"closed", "cancelled"}:
                inc.next_decision = f"escalation: {wo.department} has not acknowledged {wo.kind} work order {wo.id}"
            events.publish("escalation", {"incident_id": wo.incident_id, "work_order_id": wo.id})
        # --- approval expiry ---
        for ap in db.execute(select(Approval).where(Approval.status == "active", Approval.expires_at <= now)).scalars().all():
            ap.status = "expired"
            audit.record(db, "worker", "approval.expired", "approval", ap.id, {"proposal_id": ap.proposal_id})
            for wo in db.execute(select(WorkOrder).where(WorkOrder.approval_id == ap.id, WorkOrder.status == "approved")).scalars().all():
                wo.status = "expired"
            events.publish("approval", {"approval_id": ap.id, "status": "expired", "incident_id": ap.incident_id})
    _last_tick = iso(now)
    return handled


def _loop() -> None:
    s = get_settings()
    while not _stop.is_set():
        try:
            tick_once()
        except Exception as e:  # noqa: BLE001
            log.error("worker tick error: %s", e)
        _stop.wait(s.worker_poll_s)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="rainready-worker", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=5)


def main() -> None:
    """Standalone worker process (Compose `worker` service): migrations are owned by the API."""
    from . import bootstrap

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bootstrap.startup()
    log.info("standalone worker started")
    try:
        _loop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
