"""SQLite data-access layer for pipeline state.

This module implements the Phase 2 control-plane behavior:
- run lifecycle tracking
- batch file lifecycle tracking
- captured post dedupe + lifecycle updates
- mature hydration claiming and claim recovery
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Sequence

from bluesky_pipeline.models import CapturedPostRecord
from bluesky_pipeline.state.schema import ensure_schema
from bluesky_pipeline.utils.ids import (
    new_actor_run_id,
    new_capture_run_id,
    new_hydrate_run_id,
)
from bluesky_pipeline.utils.time_utils import utc_now, utc_now_iso


class SQLiteStore:
    """Connection-oriented SQLite store with explicit transaction boundaries."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Open and configure a SQLite connection if needed."""

        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA synchronous = NORMAL;")
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

        ensure_schema(self.connect())

    # ---------------------------------------------------------------------
    # Capture run lifecycle
    # ---------------------------------------------------------------------
    def create_capture_run(
        self,
        target_post_count: int,
        notes: str | None = None,
        capture_run_id: str | None = None,
        started_at_iso: str | None = None,
    ) -> str:
        """Create a capture run in `running` state and return its ID."""

        run_id = capture_run_id or new_capture_run_id()
        started_at = started_at_iso or utc_now_iso()

        conn = self.connect()
        conn.execute(
            """
            INSERT INTO capture_runs (
                capture_run_id,
                started_at,
                completed_at,
                status,
                target_post_count,
                written_post_count,
                last_seq_seen,
                notes
            ) VALUES (?, ?, NULL, 'running', ?, 0, NULL, ?)
            """,
            (run_id, started_at, target_post_count, notes),
        )
        conn.commit()
        return run_id

    def update_capture_run_progress(
        self,
        capture_run_id: str,
        *,
        written_post_count: int | None = None,
        increment_written_by: int | None = None,
        last_seq_seen: int | None = None,
    ) -> None:
        """Update capture run progress fields while run is active."""

        if written_post_count is not None and increment_written_by is not None:
            raise ValueError("Pass either written_post_count or increment_written_by, not both")
        if written_post_count is None and increment_written_by is None and last_seq_seen is None:
            return

        set_clauses: list[str] = []
        params: list[object] = []

        if written_post_count is not None:
            set_clauses.append("written_post_count = ?")
            params.append(written_post_count)
        elif increment_written_by is not None:
            set_clauses.append("written_post_count = written_post_count + ?")
            params.append(increment_written_by)

        if last_seq_seen is not None:
            set_clauses.append("last_seq_seen = ?")
            params.append(last_seq_seen)

        params.extend([capture_run_id, "running"])

        conn = self.connect()
        cursor = conn.execute(
            f"""
            UPDATE capture_runs
            SET {', '.join(set_clauses)}
            WHERE capture_run_id = ? AND status = ?
            """,
            params,
        )
        conn.commit()

        if cursor.rowcount == 0:
            raise LookupError(f"No running capture run found for capture_run_id={capture_run_id}")

    def complete_capture_run(
        self,
        capture_run_id: str,
        status: str = "completed",
        notes: str | None = None,
    ) -> None:
        """Mark a capture run as terminal (`completed` or `failed`)."""

        if status not in {"completed", "failed"}:
            raise ValueError("Capture run terminal status must be 'completed' or 'failed'")

        self._set_capture_run_terminal_status(capture_run_id, status=status, notes=notes)

    def fail_capture_run(self, capture_run_id: str, notes: str | None = None) -> None:
        """Mark a capture run as failed."""

        self._set_capture_run_terminal_status(capture_run_id, status="failed", notes=notes)

    def _set_capture_run_terminal_status(
        self,
        capture_run_id: str,
        *,
        status: str,
        notes: str | None,
    ) -> None:
        closed_at = utc_now_iso()
        conn = self.connect()
        cursor = conn.execute(
            """
            UPDATE capture_runs
            SET
                status = ?,
                completed_at = ?,
                notes = COALESCE(?, notes)
            WHERE capture_run_id = ? AND status = 'running'
            """,
            (status, closed_at, notes, capture_run_id),
        )

        if cursor.rowcount == 0:
            existing = self.get_capture_run(capture_run_id)
            conn.commit()
            if existing is None:
                raise LookupError(f"Capture run not found: {capture_run_id}")
            if existing["status"] == status:
                return
            raise ValueError(
                "Capture run is not in 'running' state and cannot be transitioned "
                f"to '{status}' (current status={existing['status']})"
            )

        conn.commit()

    def get_capture_run(self, capture_run_id: str) -> sqlite3.Row | None:
        """Fetch one capture run by ID."""

        return self.connect().execute(
            "SELECT * FROM capture_runs WHERE capture_run_id = ?",
            (capture_run_id,),
        ).fetchone()

    # ---------------------------------------------------------------------
    # Hydrate run lifecycle
    # ---------------------------------------------------------------------
    def create_hydrate_run(
        self,
        capture_run_id: str,
        hydrate_run_id: str | None = None,
        started_at_iso: str | None = None,
    ) -> str:
        """Create a hydrate run linked to a capture run in `running` state."""

        run_id = hydrate_run_id or new_hydrate_run_id()
        started_at = started_at_iso or utc_now_iso()

        conn = self.connect()
        conn.execute(
            """
            INSERT INTO hydrate_runs (
                hydrate_run_id,
                capture_run_id,
                started_at,
                completed_at,
                status,
                eligible_post_count,
                hydrated_post_count,
                missing_post_count,
                failed_post_count
            ) VALUES (?, ?, ?, NULL, 'running', 0, 0, 0, 0)
            """,
            (run_id, capture_run_id, started_at),
        )
        conn.commit()
        return run_id

    def update_hydrate_run_progress(
        self,
        hydrate_run_id: str,
        *,
        eligible_delta: int = 0,
        hydrated_delta: int = 0,
        missing_delta: int = 0,
        failed_delta: int = 0,
    ) -> None:
        """Increment hydrate run counters while run is active."""

        if not any([eligible_delta, hydrated_delta, missing_delta, failed_delta]):
            return

        conn = self.connect()
        cursor = conn.execute(
            """
            UPDATE hydrate_runs
            SET
                eligible_post_count = eligible_post_count + ?,
                hydrated_post_count = hydrated_post_count + ?,
                missing_post_count = missing_post_count + ?,
                failed_post_count = failed_post_count + ?
            WHERE hydrate_run_id = ? AND status = 'running'
            """,
            (
                eligible_delta,
                hydrated_delta,
                missing_delta,
                failed_delta,
                hydrate_run_id,
            ),
        )
        conn.commit()

        if cursor.rowcount == 0:
            raise LookupError(f"No running hydrate run found for hydrate_run_id={hydrate_run_id}")

    def complete_hydrate_run(self, hydrate_run_id: str, status: str = "completed") -> None:
        """Mark a hydrate run as terminal (`completed` or `failed`)."""

        if status not in {"completed", "failed"}:
            raise ValueError("Hydrate run terminal status must be 'completed' or 'failed'")

        self._set_hydrate_run_terminal_status(hydrate_run_id, status=status)

    def fail_hydrate_run(self, hydrate_run_id: str) -> None:
        """Mark a hydrate run as failed."""

        self._set_hydrate_run_terminal_status(hydrate_run_id, status="failed")

    def _set_hydrate_run_terminal_status(self, hydrate_run_id: str, *, status: str) -> None:
        closed_at = utc_now_iso()
        conn = self.connect()
        cursor = conn.execute(
            """
            UPDATE hydrate_runs
            SET status = ?, completed_at = ?
            WHERE hydrate_run_id = ? AND status = 'running'
            """,
            (status, closed_at, hydrate_run_id),
        )

        if cursor.rowcount == 0:
            existing = self.get_hydrate_run(hydrate_run_id)
            conn.commit()
            if existing is None:
                raise LookupError(f"Hydrate run not found: {hydrate_run_id}")
            if existing["status"] == status:
                return
            raise ValueError(
                "Hydrate run is not in 'running' state and cannot be transitioned "
                f"to '{status}' (current status={existing['status']})"
            )

        conn.commit()

    def get_hydrate_run(self, hydrate_run_id: str) -> sqlite3.Row | None:
        """Fetch one hydrate run by ID."""

        return self.connect().execute(
            "SELECT * FROM hydrate_runs WHERE hydrate_run_id = ?",
            (hydrate_run_id,),
        ).fetchone()

    # ---------------------------------------------------------------------
    # Actor enrichment run lifecycle
    # ---------------------------------------------------------------------
    def create_actor_run(
        self,
        actor_run_id: str | None = None,
        started_at_iso: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Create an actor enrichment run in `running` state."""

        run_id = actor_run_id or new_actor_run_id()
        started_at = started_at_iso or utc_now_iso()

        conn = self.connect()
        conn.execute(
            """
            INSERT INTO actor_runs (
                actor_run_id,
                started_at,
                completed_at,
                status,
                seeded_actor_count,
                eligible_actor_count,
                enriched_actor_count,
                missing_actor_count,
                failed_actor_count,
                notes
            ) VALUES (?, ?, NULL, 'running', 0, 0, 0, 0, 0, ?)
            """,
            (run_id, started_at, notes),
        )
        conn.commit()
        return run_id

    def update_actor_run_progress(
        self,
        actor_run_id: str,
        *,
        seeded_delta: int = 0,
        eligible_delta: int = 0,
        enriched_delta: int = 0,
        missing_delta: int = 0,
        failed_delta: int = 0,
    ) -> None:
        """Increment actor-run counters while run is active."""

        if not any([seeded_delta, eligible_delta, enriched_delta, missing_delta, failed_delta]):
            return

        conn = self.connect()
        cursor = conn.execute(
            """
            UPDATE actor_runs
            SET
                seeded_actor_count = seeded_actor_count + ?,
                eligible_actor_count = eligible_actor_count + ?,
                enriched_actor_count = enriched_actor_count + ?,
                missing_actor_count = missing_actor_count + ?,
                failed_actor_count = failed_actor_count + ?
            WHERE actor_run_id = ? AND status = 'running'
            """,
            (
                seeded_delta,
                eligible_delta,
                enriched_delta,
                missing_delta,
                failed_delta,
                actor_run_id,
            ),
        )
        conn.commit()

        if cursor.rowcount == 0:
            raise LookupError(f"No running actor run found for actor_run_id={actor_run_id}")

    def complete_actor_run(
        self,
        actor_run_id: str,
        status: str = "completed",
        notes: str | None = None,
    ) -> None:
        """Mark an actor run as terminal (`completed` or `failed`)."""

        if status not in {"completed", "failed"}:
            raise ValueError("Actor run terminal status must be 'completed' or 'failed'")
        self._set_actor_run_terminal_status(actor_run_id, status=status, notes=notes)

    def fail_actor_run(self, actor_run_id: str, notes: str | None = None) -> None:
        """Mark an actor run as failed."""

        self._set_actor_run_terminal_status(actor_run_id, status="failed", notes=notes)

    def _set_actor_run_terminal_status(
        self,
        actor_run_id: str,
        *,
        status: str,
        notes: str | None,
    ) -> None:
        closed_at = utc_now_iso()
        conn = self.connect()
        cursor = conn.execute(
            """
            UPDATE actor_runs
            SET
                status = ?,
                completed_at = ?,
                notes = COALESCE(?, notes)
            WHERE actor_run_id = ? AND status = 'running'
            """,
            (status, closed_at, notes, actor_run_id),
        )

        if cursor.rowcount == 0:
            existing = self.get_actor_run(actor_run_id)
            conn.commit()
            if existing is None:
                raise LookupError(f"Actor run not found: {actor_run_id}")
            if existing["status"] == status:
                return
            raise ValueError(
                "Actor run is not in 'running' state and cannot be transitioned "
                f"to '{status}' (current status={existing['status']})"
            )

        conn.commit()

    def get_actor_run(self, actor_run_id: str) -> sqlite3.Row | None:
        """Fetch one actor run by ID."""

        return self.connect().execute(
            "SELECT * FROM actor_runs WHERE actor_run_id = ?",
            (actor_run_id,),
        ).fetchone()

    # ---------------------------------------------------------------------
    # Batch file lifecycle
    # ---------------------------------------------------------------------
    def create_batch_file(
        self,
        job_type: str,
        run_id: str,
        dataset_type: str,
        local_path: str,
        created_at_iso: str | None = None,
    ) -> int:
        """Create a batch file row in `open` state and return `file_id`."""

        created_at = created_at_iso or utc_now_iso()
        conn = self.connect()
        cursor = conn.execute(
            """
            INSERT INTO batch_files (
                job_type,
                run_id,
                dataset_type,
                local_path,
                row_count,
                byte_size,
                status,
                created_at,
                closed_at
            ) VALUES (?, ?, ?, ?, 0, 0, 'open', ?, NULL)
            """,
            (job_type, run_id, dataset_type, local_path, created_at),
        )
        file_id = cursor.lastrowid
        conn.commit()
        if file_id is None:
            raise RuntimeError("Failed to create batch file row: SQLite did not return a row id")
        return file_id

    def open_batch_file(self, job_type: str, run_id: str, dataset_type: str, local_path: str) -> int:
        """Backward-compatible alias for `create_batch_file(...)`."""

        return self.create_batch_file(job_type, run_id, dataset_type, local_path)

    def update_batch_file_progress(self, file_id: int, row_count: int, byte_size: int) -> None:
        """Update row/byte counters for an open batch file."""

        conn = self.connect()
        cursor = conn.execute(
            """
            UPDATE batch_files
            SET row_count = ?, byte_size = ?
            WHERE file_id = ? AND status = 'open'
            """,
            (row_count, byte_size, file_id),
        )
        conn.commit()

        if cursor.rowcount == 0:
            raise LookupError(f"No open batch file found for file_id={file_id}")

    def close_batch_file(
        self,
        file_id: int,
        row_count: int,
        byte_size: int,
        status: str = "closed",
        closed_at_iso: str | None = None,
    ) -> None:
        """Close an open batch file as `closed` or `failed`."""

        if status not in {"closed", "failed"}:
            raise ValueError("Batch file terminal status must be 'closed' or 'failed'")

        closed_at = closed_at_iso or utc_now_iso()
        conn = self.connect()
        cursor = conn.execute(
            """
            UPDATE batch_files
            SET
                row_count = ?,
                byte_size = ?,
                status = ?,
                closed_at = ?
            WHERE file_id = ? AND status = 'open'
            """,
            (row_count, byte_size, status, closed_at, file_id),
        )

        if cursor.rowcount == 0:
            existing = self.get_batch_file(file_id)
            conn.commit()
            if existing is None:
                raise LookupError(f"Batch file not found: {file_id}")
            if existing["status"] == status:
                return
            raise ValueError(
                "Batch file is not in 'open' state and cannot be transitioned "
                f"to '{status}' (current status={existing['status']})"
            )

        conn.commit()

    def fail_batch_file(self, file_id: int, row_count: int = 0, byte_size: int = 0) -> None:
        """Mark an open batch file as failed."""

        self.close_batch_file(file_id=file_id, row_count=row_count, byte_size=byte_size, status="failed")

    def get_batch_file(self, file_id: int) -> sqlite3.Row | None:
        """Fetch one batch file by ID."""

        return self.connect().execute(
            "SELECT * FROM batch_files WHERE file_id = ?",
            (file_id,),
        ).fetchone()

    # ---------------------------------------------------------------------
    # Captured posts
    # ---------------------------------------------------------------------
    def insert_captured_post(
        self,
        *,
        uri: str,
        capture_run_id: str,
        repo_did: str,
        rkey: str,
        cid_at_capture: str | None,
        seq: int | None,
        record_created_at: str | None,
        captured_at: str,
        capture_file_id: int | None,
    ) -> bool:
        """Insert a captured post if URI is new.

        Returns True when inserted, False when the URI already exists.
        """

        conn = self.connect()
        cursor = conn.execute(
            """
            INSERT INTO captured_posts (
                uri,
                capture_run_id,
                repo_did,
                rkey,
                cid_at_capture,
                seq,
                record_created_at,
                captured_at,
                capture_file_id,
                hydration_status,
                hydration_attempt_count,
                last_hydration_attempt_at,
                hydrated_at,
                hydrate_run_id,
                last_error,
                claimed_by_worker,
                claim_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, NULL, NULL, NULL, NULL)
            ON CONFLICT(uri) DO NOTHING
            """,
            (
                uri,
                capture_run_id,
                repo_did,
                rkey,
                cid_at_capture,
                seq,
                record_created_at,
                captured_at,
                capture_file_id,
            ),
        )
        conn.commit()
        return cursor.rowcount == 1

    def upsert_captured_post(self, post: CapturedPostRecord) -> bool:
        """Backward-compatible alias using `CapturedPostRecord` input."""

        return self.insert_captured_post(
            uri=post.uri,
            capture_run_id=post.capture_run_id,
            repo_did=post.repo_did,
            rkey=post.rkey,
            cid_at_capture=post.cid_at_capture,
            seq=post.seq,
            record_created_at=post.record_created_at,
            captured_at=post.captured_at,
            capture_file_id=post.capture_file_id,
        )

    def get_captured_post(self, uri: str) -> sqlite3.Row | None:
        """Fetch one captured post by URI."""

        return self.connect().execute(
            "SELECT * FROM captured_posts WHERE uri = ?",
            (uri,),
        ).fetchone()

    def count_captured_posts_for_run(self, capture_run_id: str) -> int:
        """Count unique captured posts for a run."""

        row = self.connect().execute(
            "SELECT COUNT(*) AS count FROM captured_posts WHERE capture_run_id = ?",
            (capture_run_id,),
        ).fetchone()
        return int(row["count"])

    def count_pending_mature_posts(self, maturity_cutoff_iso: str) -> int:
        """Count mature posts eligible for claim (`pending` or `retryable`)."""

        row = self.connect().execute(
            """
            SELECT COUNT(*) AS count
            FROM captured_posts
            WHERE hydration_status IN ('pending', 'retryable')
              AND captured_at <= ?
            """,
            (maturity_cutoff_iso,),
        ).fetchone()
        return int(row["count"])

    # ---------------------------------------------------------------------
    # Actor enrichment state
    # ---------------------------------------------------------------------
    def seed_actor_dids_from_hydrated_then_captured(self, seeded_at_iso: str | None = None) -> tuple[int, int]:
        """Seed unique actor DIDs into actor state from pipeline-captured data.

        Returns `(inserted_from_hydrated, inserted_from_captured_fallback)`.
        """

        seeded_at = seeded_at_iso or utc_now_iso()
        conn = self.connect()

        hydrated_before = conn.total_changes
        conn.execute(
            """
            INSERT INTO actor_profiles_state (
                did,
                seeded_at,
                source_first_seen,
                enrichment_status,
                enrichment_attempt_count,
                last_enrichment_attempt_at,
                enriched_at,
                actor_run_id,
                last_error,
                claimed_by_worker,
                claim_expires_at
            )
            SELECT DISTINCT
                repo_did,
                ?,
                'hydrated',
                'pending',
                0,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL
            FROM captured_posts
            WHERE hydration_status = 'hydrated'
              AND repo_did IS NOT NULL
              AND repo_did != ''
            ON CONFLICT(did) DO NOTHING
            """,
            (seeded_at,),
        )
        inserted_hydrated = conn.total_changes - hydrated_before

        captured_before = conn.total_changes
        conn.execute(
            """
            INSERT INTO actor_profiles_state (
                did,
                seeded_at,
                source_first_seen,
                enrichment_status,
                enrichment_attempt_count,
                last_enrichment_attempt_at,
                enriched_at,
                actor_run_id,
                last_error,
                claimed_by_worker,
                claim_expires_at
            )
            SELECT DISTINCT
                repo_did,
                ?,
                'captured',
                'pending',
                0,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL
            FROM captured_posts
            WHERE repo_did IS NOT NULL
              AND repo_did != ''
            ON CONFLICT(did) DO NOTHING
            """,
            (seeded_at,),
        )
        inserted_captured = conn.total_changes - captured_before
        conn.commit()

        return int(inserted_hydrated), int(inserted_captured)

    def get_actor_state(self, did: str) -> sqlite3.Row | None:
        """Fetch actor enrichment state by DID."""

        return self.connect().execute(
            "SELECT * FROM actor_profiles_state WHERE did = ?",
            (did,),
        ).fetchone()

    def count_pending_actor_dids(self) -> int:
        """Count actor rows eligible for enrichment claim."""

        row = self.connect().execute(
            """
            SELECT COUNT(*) AS count
            FROM actor_profiles_state
            WHERE enrichment_status IN ('pending', 'retryable')
            """
        ).fetchone()
        return int(row["count"])

    def claim_actor_dids(
        self,
        worker_id: str,
        limit: int,
        claim_ttl_seconds: int,
    ) -> Sequence[sqlite3.Row]:
        """Claim actor rows in `pending`/`retryable` states for enrichment."""

        if limit <= 0:
            return []
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be > 0")

        now = utc_now()
        claim_expires_at = (now + timedelta(seconds=claim_ttl_seconds)).isoformat()
        attempted_at = now.isoformat()

        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            candidates = conn.execute(
                """
                SELECT did
                FROM actor_profiles_state
                WHERE enrichment_status IN ('pending', 'retryable')
                ORDER BY did ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            if not candidates:
                conn.commit()
                return []

            candidate_dids = [row["did"] for row in candidates]
            placeholders = ",".join("?" for _ in candidate_dids)

            conn.execute(
                f"""
                UPDATE actor_profiles_state
                SET
                    enrichment_status = 'claimed',
                    claimed_by_worker = ?,
                    claim_expires_at = ?,
                    last_enrichment_attempt_at = ?,
                    enrichment_attempt_count = enrichment_attempt_count + 1
                WHERE did IN ({placeholders})
                  AND enrichment_status IN ('pending', 'retryable')
                """,
                (worker_id, claim_expires_at, attempted_at, *candidate_dids),
            )

            claimed_rows = conn.execute(
                f"""
                SELECT *
                FROM actor_profiles_state
                WHERE did IN ({placeholders})
                  AND enrichment_status = 'claimed'
                  AND claimed_by_worker = ?
                ORDER BY did ASC
                """,
                (*candidate_dids, worker_id),
            ).fetchall()

            conn.commit()
            return claimed_rows
        except Exception:
            conn.rollback()
            raise

    def release_expired_actor_claims(self, now_iso: str) -> int:
        """Reset expired claimed actors back to `pending` for recovery."""

        conn = self.connect()
        cursor = conn.execute(
            """
            UPDATE actor_profiles_state
            SET
                enrichment_status = 'pending',
                claimed_by_worker = NULL,
                claim_expires_at = NULL
            WHERE enrichment_status = 'claimed'
              AND claim_expires_at IS NOT NULL
              AND claim_expires_at <= ?
            """,
            (now_iso,),
        )
        conn.commit()
        return int(cursor.rowcount)

    def mark_actors_enriched(
        self,
        dids: Iterable[str],
        actor_run_id: str,
        enriched_at_iso: str,
    ) -> int:
        """Transition claimed actor rows to terminal `enriched`."""

        did_list = self._normalize_did_list(dids)
        if not did_list:
            return 0

        conn = self.connect()
        placeholders = ",".join("?" for _ in did_list)
        cursor = conn.execute(
            f"""
            UPDATE actor_profiles_state
            SET
                enrichment_status = 'enriched',
                enriched_at = ?,
                actor_run_id = ?,
                last_error = NULL,
                claimed_by_worker = NULL,
                claim_expires_at = NULL
            WHERE did IN ({placeholders})
              AND enrichment_status = 'claimed'
            """,
            (enriched_at_iso, actor_run_id, *did_list),
        )
        conn.commit()
        return int(cursor.rowcount)

    def mark_actors_retryable(
        self,
        dids: Iterable[str],
        error_message: str,
        attempted_at_iso: str,
    ) -> int:
        """Transition claimed actor rows to `retryable`."""

        did_list = self._normalize_did_list(dids)
        if not did_list:
            return 0

        conn = self.connect()
        placeholders = ",".join("?" for _ in did_list)
        cursor = conn.execute(
            f"""
            UPDATE actor_profiles_state
            SET
                enrichment_status = 'retryable',
                last_error = ?,
                last_enrichment_attempt_at = ?,
                claimed_by_worker = NULL,
                claim_expires_at = NULL
            WHERE did IN ({placeholders})
              AND enrichment_status = 'claimed'
            """,
            (error_message, attempted_at_iso, *did_list),
        )
        conn.commit()
        return int(cursor.rowcount)

    def mark_actors_missing(
        self,
        dids: Iterable[str],
        actor_run_id: str,
        attempted_at_iso: str,
        reason: str | None = None,
    ) -> int:
        """Transition claimed/retryable actor rows to terminal `missing`."""

        did_list = self._normalize_did_list(dids)
        if not did_list:
            return 0

        conn = self.connect()
        placeholders = ",".join("?" for _ in did_list)
        cursor = conn.execute(
            f"""
            UPDATE actor_profiles_state
            SET
                enrichment_status = 'missing',
                actor_run_id = ?,
                last_enrichment_attempt_at = ?,
                last_error = COALESCE(?, last_error),
                claimed_by_worker = NULL,
                claim_expires_at = NULL
            WHERE did IN ({placeholders})
              AND enrichment_status IN ('claimed', 'retryable')
            """,
            (actor_run_id, attempted_at_iso, reason, *did_list),
        )
        conn.commit()
        return int(cursor.rowcount)

    def mark_actors_failed(
        self,
        dids: Iterable[str],
        actor_run_id: str,
        error_message: str,
        attempted_at_iso: str,
    ) -> int:
        """Transition claimed/retryable actor rows to terminal `failed`."""

        did_list = self._normalize_did_list(dids)
        if not did_list:
            return 0

        conn = self.connect()
        placeholders = ",".join("?" for _ in did_list)
        cursor = conn.execute(
            f"""
            UPDATE actor_profiles_state
            SET
                enrichment_status = 'failed',
                actor_run_id = ?,
                last_enrichment_attempt_at = ?,
                last_error = ?,
                claimed_by_worker = NULL,
                claim_expires_at = NULL
            WHERE did IN ({placeholders})
              AND enrichment_status IN ('claimed', 'retryable')
            """,
            (actor_run_id, attempted_at_iso, error_message, *did_list),
        )
        conn.commit()
        return int(cursor.rowcount)

    # ---------------------------------------------------------------------
    # Claiming + hydration outcomes
    # ---------------------------------------------------------------------
    def claim_mature_posts(
        self,
        worker_id: str,
        limit: int,
        maturity_cutoff_iso: str,
        claim_ttl_seconds: int,
    ) -> Sequence[sqlite3.Row]:
        """Claim mature rows in `pending`/`retryable` states.

        This method performs selection + state transition in one write transaction
        using `BEGIN IMMEDIATE` to avoid competing claim writes.
        """

        if limit <= 0:
            return []
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be > 0")

        now = utc_now()
        claim_expires_at = (now + timedelta(seconds=claim_ttl_seconds)).isoformat()
        attempted_at = now.isoformat()

        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            candidates = conn.execute(
                """
                SELECT uri
                FROM captured_posts
                WHERE hydration_status IN ('pending', 'retryable')
                  AND captured_at <= ?
                ORDER BY captured_at ASC, uri ASC
                LIMIT ?
                """,
                (maturity_cutoff_iso, limit),
            ).fetchall()

            if not candidates:
                conn.commit()
                return []

            candidate_uris = [row["uri"] for row in candidates]
            placeholders = ",".join("?" for _ in candidate_uris)

            conn.execute(
                f"""
                UPDATE captured_posts
                SET
                    hydration_status = 'claimed',
                    claimed_by_worker = ?,
                    claim_expires_at = ?,
                    last_hydration_attempt_at = ?,
                    hydration_attempt_count = hydration_attempt_count + 1
                WHERE uri IN ({placeholders})
                  AND hydration_status IN ('pending', 'retryable')
                """,
                (worker_id, claim_expires_at, attempted_at, *candidate_uris),
            )

            claimed_rows = conn.execute(
                f"""
                SELECT *
                FROM captured_posts
                WHERE uri IN ({placeholders})
                  AND hydration_status = 'claimed'
                  AND claimed_by_worker = ?
                ORDER BY captured_at ASC, uri ASC
                """,
                (*candidate_uris, worker_id),
            ).fetchall()

            conn.commit()
            return claimed_rows
        except Exception:
            conn.rollback()
            raise

    def release_expired_claims(self, now_iso: str) -> int:
        """Reset expired `claimed` rows back to `pending` for recovery."""

        conn = self.connect()
        cursor = conn.execute(
            """
            UPDATE captured_posts
            SET
                hydration_status = 'pending',
                claimed_by_worker = NULL,
                claim_expires_at = NULL
            WHERE hydration_status = 'claimed'
              AND claim_expires_at IS NOT NULL
              AND claim_expires_at <= ?
            """,
            (now_iso,),
        )
        conn.commit()
        return int(cursor.rowcount)

    def mark_posts_hydrated(self, uris: Iterable[str], hydrate_run_id: str, hydrated_at_iso: str) -> int:
        """Transition claimed rows to terminal `hydrated`."""

        uri_list = self._normalize_uri_list(uris)
        if not uri_list:
            return 0

        conn = self.connect()
        placeholders = ",".join("?" for _ in uri_list)
        cursor = conn.execute(
            f"""
            UPDATE captured_posts
            SET
                hydration_status = 'hydrated',
                hydrated_at = ?,
                hydrate_run_id = ?,
                last_error = NULL,
                claimed_by_worker = NULL,
                claim_expires_at = NULL
            WHERE uri IN ({placeholders})
              AND hydration_status = 'claimed'
            """,
            (hydrated_at_iso, hydrate_run_id, *uri_list),
        )
        conn.commit()
        return int(cursor.rowcount)

    def mark_posts_retryable(self, uris: Iterable[str], error_message: str, attempted_at_iso: str) -> int:
        """Transition claimed rows to `retryable` after transient failures."""

        uri_list = self._normalize_uri_list(uris)
        if not uri_list:
            return 0

        conn = self.connect()
        placeholders = ",".join("?" for _ in uri_list)
        cursor = conn.execute(
            f"""
            UPDATE captured_posts
            SET
                hydration_status = 'retryable',
                last_error = ?,
                last_hydration_attempt_at = ?,
                claimed_by_worker = NULL,
                claim_expires_at = NULL
            WHERE uri IN ({placeholders})
              AND hydration_status = 'claimed'
            """,
            (error_message, attempted_at_iso, *uri_list),
        )
        conn.commit()
        return int(cursor.rowcount)

    def mark_posts_missing(
        self,
        uris: Iterable[str],
        hydrate_run_id: str,
        attempted_at_iso: str,
        reason: str | None = None,
    ) -> int:
        """Transition claimed/retryable rows to terminal `missing`."""

        uri_list = self._normalize_uri_list(uris)
        if not uri_list:
            return 0

        conn = self.connect()
        placeholders = ",".join("?" for _ in uri_list)
        cursor = conn.execute(
            f"""
            UPDATE captured_posts
            SET
                hydration_status = 'missing',
                hydrate_run_id = ?,
                last_hydration_attempt_at = ?,
                last_error = COALESCE(?, last_error),
                claimed_by_worker = NULL,
                claim_expires_at = NULL
            WHERE uri IN ({placeholders})
              AND hydration_status IN ('claimed', 'retryable')
            """,
            (hydrate_run_id, attempted_at_iso, reason, *uri_list),
        )
        conn.commit()
        return int(cursor.rowcount)

    def mark_posts_failed(
        self,
        uris: Iterable[str],
        hydrate_run_id: str,
        error_message: str,
        attempted_at_iso: str,
    ) -> int:
        """Transition claimed/retryable rows to terminal `failed`."""

        uri_list = self._normalize_uri_list(uris)
        if not uri_list:
            return 0

        conn = self.connect()
        placeholders = ",".join("?" for _ in uri_list)
        cursor = conn.execute(
            f"""
            UPDATE captured_posts
            SET
                hydration_status = 'failed',
                hydrate_run_id = ?,
                last_hydration_attempt_at = ?,
                last_error = ?,
                claimed_by_worker = NULL,
                claim_expires_at = NULL
            WHERE uri IN ({placeholders})
              AND hydration_status IN ('claimed', 'retryable')
            """,
            (hydrate_run_id, attempted_at_iso, error_message, *uri_list),
        )
        conn.commit()
        return int(cursor.rowcount)

    # Backward-compatible single-row wrappers
    def mark_post_retryable(self, uri: str, error_message: str, attempted_at_iso: str) -> None:
        """Mark one claimed row retryable."""

        self.mark_posts_retryable([uri], error_message, attempted_at_iso)

    def mark_post_missing(self, uri: str, hydrate_run_id: str, attempted_at_iso: str) -> None:
        """Mark one row as terminal missing."""

        self.mark_posts_missing([uri], hydrate_run_id, attempted_at_iso)

    def mark_post_failed(self, uri: str, hydrate_run_id: str, error_message: str, attempted_at_iso: str) -> None:
        """Mark one row as terminal failed."""

        self.mark_posts_failed([uri], hydrate_run_id, error_message, attempted_at_iso)

    @staticmethod
    def _normalize_uri_list(uris: Iterable[str]) -> list[str]:
        """Deduplicate URI iterable while preserving order."""

        ordered_unique: list[str] = []
        seen: set[str] = set()
        for uri in uris:
            if uri in seen:
                continue
            ordered_unique.append(uri)
            seen.add(uri)
        return ordered_unique

    @staticmethod
    def _normalize_did_list(dids: Iterable[str]) -> list[str]:
        """Deduplicate DID iterable while preserving order."""

        ordered_unique: list[str] = []
        seen: set[str] = set()
        for did in dids:
            if did in seen:
                continue
            ordered_unique.append(did)
            seen.add(did)
        return ordered_unique
