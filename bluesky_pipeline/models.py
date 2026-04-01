"""Shared data contracts for pipeline records and state.

These dataclasses and enums define shape-level contracts that higher-level
logic will use as implementations are filled in during later phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class HydrationStatus(str, Enum):
    """Allowed per-post hydration lifecycle states."""

    PENDING = "pending"
    CLAIMED = "claimed"
    HYDRATED = "hydrated"
    RETRYABLE = "retryable"
    MISSING = "missing"
    FAILED = "failed"


@dataclass(slots=True)
class CaptureRunRecord:
    """Row contract for `capture_runs`."""

    capture_run_id: str
    started_at: str
    completed_at: Optional[str]
    status: str
    target_post_count: int
    written_post_count: int
    last_seq_seen: Optional[int]
    notes: Optional[str]


@dataclass(slots=True)
class HydrateRunRecord:
    """Row contract for `hydrate_runs`."""

    hydrate_run_id: str
    capture_run_id: str
    started_at: str
    completed_at: Optional[str]
    status: str
    eligible_post_count: int
    hydrated_post_count: int
    missing_post_count: int
    failed_post_count: int


@dataclass(slots=True)
class BatchFileRecord:
    """Row contract for `batch_files`."""

    file_id: Optional[int]
    job_type: str
    run_id: str
    dataset_type: str
    local_path: str
    row_count: int
    byte_size: int
    status: str
    created_at: str
    closed_at: Optional[str]


@dataclass(slots=True)
class CapturedPostRecord:
    """Row contract for `captured_posts`."""

    uri: str
    capture_run_id: str
    repo_did: str
    rkey: str
    cid_at_capture: Optional[str]
    seq: Optional[int]
    record_created_at: Optional[str]
    captured_at: str
    capture_file_id: Optional[int]
    hydration_status: HydrationStatus = HydrationStatus.PENDING
    hydration_attempt_count: int = 0
    last_hydration_attempt_at: Optional[str] = None
    hydrated_at: Optional[str] = None
    hydrate_run_id: Optional[str] = None
    last_error: Optional[str] = None
    claimed_by_worker: Optional[str] = None
    claim_expires_at: Optional[str] = None
