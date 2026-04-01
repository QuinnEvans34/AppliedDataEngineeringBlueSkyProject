"""SQLite data-access scaffolding for pipeline state.

This class will become the single state I/O layer for both jobs. For phase 1,
we provide connection lifecycle and method contracts only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Sequence

from bluesky_pipeline.models import CapturedPostRecord
from bluesky_pipeline.state.schema import ensure_schema


class SQLiteStore:
    """Connection-oriented state store with explicit lifecycle control."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Open and configure a SQLite connection if needed."""

        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON;")
        return self._conn

    def close(self) -> None:
        """Close the current SQLite connection, if one exists."""

        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "SQLiteStore":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self.close()

    def ensure_schema(self) -> None:
        """Create/validate the database schema for this store."""

        conn = self.connect()
        ensure_schema(conn)

    def create_capture_run(self, target_post_count: int, notes: str | None = None) -> str:
        """Create a capture run row and return `capture_run_id` (TODO).

        Expected behavior:
        - insert new row with status like `running`
        - initialize counters to zero
        - be safe to call once per job startup path
        """

        _ = (target_post_count, notes)
        raise NotImplementedError

    def complete_capture_run(self, capture_run_id: str, status: str, notes: str | None = None) -> None:
        """Mark capture run terminal with completion timestamp (TODO)."""

        _ = (capture_run_id, status, notes)
        raise NotImplementedError

    def create_hydrate_run(self, capture_run_id: str) -> str:
        """Create a hydration run linked to a capture run (TODO)."""

        _ = capture_run_id
        raise NotImplementedError

    def complete_hydrate_run(self, hydrate_run_id: str, status: str) -> None:
        """Mark hydration run terminal with completion timestamp (TODO)."""

        _ = (hydrate_run_id, status)
        raise NotImplementedError

    def open_batch_file(self, job_type: str, run_id: str, dataset_type: str, local_path: str) -> int:
        """Insert batch file metadata row and return `file_id` (TODO)."""

        _ = (job_type, run_id, dataset_type, local_path)
        raise NotImplementedError

    def close_batch_file(
        self,
        file_id: int,
        row_count: int,
        byte_size: int,
        status: str = "closed",
    ) -> None:
        """Finalize batch file metadata after writer closes (TODO)."""

        _ = (file_id, row_count, byte_size, status)
        raise NotImplementedError

    def upsert_captured_post(self, post: CapturedPostRecord) -> bool:
        """Insert captured post if new URI; return True when inserted (TODO).

        Idempotency contract:
        - URI is the dedupe key
        - duplicate URI writes must be safe and should not increment unique count
        """

        _ = post
        raise NotImplementedError

    def claim_mature_posts(
        self,
        worker_id: str,
        limit: int,
        maturity_cutoff_iso: str,
        claim_ttl_seconds: int,
    ) -> Sequence[str]:
        """Claim mature rows by moving states to `claimed` atomically (TODO).

        Transition contract:
        - eligible source states: `pending`, `retryable`
        - transition: eligible -> `claimed`
        - set `claimed_by_worker` and `claim_expires_at`
        """

        _ = (worker_id, limit, maturity_cutoff_iso, claim_ttl_seconds)
        raise NotImplementedError

    def mark_posts_hydrated(self, uris: Iterable[str], hydrate_run_id: str, hydrated_at_iso: str) -> None:
        """Mark claimed rows as hydrated terminal state (TODO).

        Transition contract:
        - source state should be `claimed`
        - terminal state is `hydrated`
        """

        _ = (uris, hydrate_run_id, hydrated_at_iso)
        raise NotImplementedError

    def mark_post_retryable(self, uri: str, error_message: str, attempted_at_iso: str) -> None:
        """Record transient error and transition to `retryable` (TODO)."""

        _ = (uri, error_message, attempted_at_iso)
        raise NotImplementedError

    def mark_post_missing(self, uri: str, hydrate_run_id: str, attempted_at_iso: str) -> None:
        """Mark post unresolved after retries as terminal `missing` (TODO)."""

        _ = (uri, hydrate_run_id, attempted_at_iso)
        raise NotImplementedError

    def mark_post_failed(self, uri: str, hydrate_run_id: str, error_message: str, attempted_at_iso: str) -> None:
        """Mark unrecoverable hydration error as terminal `failed` (TODO)."""

        _ = (uri, hydrate_run_id, error_message, attempted_at_iso)
        raise NotImplementedError

    def release_expired_claims(self, now_iso: str) -> int:
        """Return expired claims to `retryable` or `pending` state (TODO)."""

        _ = now_iso
        raise NotImplementedError
