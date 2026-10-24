"""In-process event bus feeding Server-Sent Events.

Workers and request handlers publish small JSON events; SSE clients subscribe
through a per-connection queue.  Events are also persisted as audit entries by
the caller where they matter, so SSE is a convenience, not a system of record.
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections import deque
from typing import Any

_lock = threading.Lock()
_subscribers: list[queue.Queue] = []
_recent: deque = deque(maxlen=200)
_seq = 0


def publish(kind: str, data: dict[str, Any]) -> None:
    global _seq
    with _lock:
        _seq += 1
        ev = {"seq": _seq, "kind": kind, "data": data}
        _recent.append(ev)
        for q in list(_subscribers):
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass


def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=500)
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)


def recent(since_seq: int = 0) -> list[dict]:
    with _lock:
        return [e for e in _recent if e["seq"] > since_seq]


async def sse_generator(request_is_disconnected, since_seq: int = 0):
    q = subscribe()
    try:
        for ev in recent(since_seq):
            yield {"event": ev["kind"], "id": str(ev["seq"]), "data": json.dumps(ev["data"], default=str)}
        while True:
            if await request_is_disconnected():
                break
            try:
                ev = await asyncio.get_event_loop().run_in_executor(None, lambda: q.get(timeout=1.0))
            except queue.Empty:
                yield {"event": "heartbeat", "data": "{}"}
                continue
            yield {"event": ev["kind"], "id": str(ev["seq"]), "data": json.dumps(ev["data"], default=str)}
    finally:
        unsubscribe(q)
