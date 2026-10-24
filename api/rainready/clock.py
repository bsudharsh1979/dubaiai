"""Time handling.

Everything is stored in UTC. Operational display uses Asia/Dubai.  The replay
clock lets the demo and the historical-replay mode fix a "decision time"; tools
that read evidence must filter on ``available_at <= decision time`` so that
information unavailable at the time can never leak into a decision.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DUBAI = ZoneInfo("Asia/Dubai")
UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_dubai(dt: datetime) -> datetime:
    return as_utc(dt).astimezone(DUBAI)


def parse_iso(value: str) -> datetime:
    return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def iso(dt: datetime | None) -> str | None:
    return as_utc(dt).isoformat() if dt else None


class ReplayClock:
    """Mutable decision clock.  ``None`` offset means wall-clock time."""

    def __init__(self, default_iso: str | None = None):
        self._fixed: datetime | None = parse_iso(default_iso) if default_iso else None

    def now(self) -> datetime:
        return self._fixed or utcnow()

    def set(self, dt: datetime | None) -> None:
        self._fixed = as_utc(dt) if dt else None

    def is_fixed(self) -> bool:
        return self._fixed is not None
