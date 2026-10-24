"""Append-only, hash-linked application audit log.

Protection actually implemented: every event stores ``sha256(prev_hash || canonical
json(event))`` and the export endpoint recomputes the chain so any edited, removed or
re-ordered row is detected.  This is tamper-*evident* within the application
database, not tamper-*proof*: an operator with direct database access could rewrite
the whole chain.  Anchoring the chain head to an external WORM store is listed as
an integration requirement.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import utcnow
from .models import AuditEvent

GENESIS = "0" * 64

REDACT_KEYS = {"api_key", "authorization", "password", "secret", "token", "cookie", "photo_path"}


def redact(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: ("[redacted]" if k.lower() in REDACT_KEYS else redact(v)) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact(v) for v in payload]
    return payload


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def payload_hash(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def _event_hash(prev: str, ts: datetime, actor: str, action: str, subject_type: str, subject_id: str, payload: dict) -> str:
    body = canonical({"ts": ts.isoformat(), "actor": actor, "action": action, "subject_type": subject_type, "subject_id": subject_id, "payload": payload})
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


def record(db: Session, actor: str, action: str, subject_type: str, subject_id: str, payload: dict | None = None) -> AuditEvent:
    last = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
    prev = last.hash if last else GENESIS
    ts = utcnow()
    clean = redact(payload or {})
    ev = AuditEvent(ts=ts, actor=actor, action=action, subject_type=subject_type, subject_id=subject_id, payload=clean, prev_hash=prev,
                    hash=_event_hash(prev, ts, actor, action, subject_type, subject_id, clean))
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session) -> dict:
    rows = db.execute(select(AuditEvent).order_by(AuditEvent.seq.asc())).scalars().all()
    prev = GENESIS
    for row in rows:
        if row.prev_hash != prev:
            return {"ok": False, "events": len(rows), "broken_at_seq": row.seq, "reason": "prev_hash mismatch"}
        expected = _event_hash(prev, row.ts, row.actor, row.action, row.subject_type, row.subject_id, row.payload)
        if expected != row.hash:
            return {"ok": False, "events": len(rows), "broken_at_seq": row.seq, "reason": "content hash mismatch"}
        prev = row.hash
    return {"ok": True, "events": len(rows), "head": prev, "protection": "hash-linked, tamper-evident within the application database (not tamper-proof)"}
