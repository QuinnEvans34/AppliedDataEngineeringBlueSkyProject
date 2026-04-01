"""UTC time helpers for consistent timestamp generation and comparisons."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""

    return utc_now().isoformat()


def is_mature(captured_at: datetime, maturity_hours: int, *, now: datetime | None = None) -> bool:
    """Check whether a captured post meets maturity threshold."""

    compare_time = now or utc_now()
    return compare_time >= captured_at + timedelta(hours=maturity_hours)
