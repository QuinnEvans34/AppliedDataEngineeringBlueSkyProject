"""Identifier generation helpers for run and worker IDs."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def new_capture_run_id() -> str:
    """Create a time-sortable capture run identifier."""

    return f"cap_{_timestamp()}_{uuid4().hex[:8]}"


def new_hydrate_run_id() -> str:
    """Create a time-sortable hydrate run identifier."""

    return f"hyd_{_timestamp()}_{uuid4().hex[:8]}"


def new_actor_run_id() -> str:
    """Create a time-sortable actor enrichment run identifier."""

    return f"act_{_timestamp()}_{uuid4().hex[:8]}"


def new_worker_id(prefix: str = "worker") -> str:
    """Create a short worker identifier for claim ownership."""

    return f"{prefix}_{uuid4().hex[:8]}"
