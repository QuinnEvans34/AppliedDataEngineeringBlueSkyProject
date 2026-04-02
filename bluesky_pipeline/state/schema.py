"""SQLite schema bootstrap and versioning for pipeline state.

This module owns table/index creation for the control-plane database.
It intentionally stops at schema contracts; runtime state transitions are
implemented in later phases.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

SCHEMA_VERSION = 2

CAPTURE_RUN_STATUS_VALUES: tuple[str, ...] = (
    "running",
    "completed",
    "failed",
)

HYDRATE_RUN_STATUS_VALUES: tuple[str, ...] = (
    "running",
    "completed",
    "failed",
)

ACTOR_RUN_STATUS_VALUES: tuple[str, ...] = (
    "running",
    "completed",
    "failed",
)

BATCH_FILE_STATUS_VALUES: tuple[str, ...] = (
    "open",
    "closed",
    "failed",
)

HYDRATION_STATUS_VALUES: tuple[str, ...] = (
    "pending",
    "claimed",
    "hydrated",
    "retryable",
    "missing",
    "failed",
)

ACTOR_ENRICHMENT_STATUS_VALUES: tuple[str, ...] = (
    "pending",
    "claimed",
    "enriched",
    "retryable",
    "missing",
    "failed",
)

_CAPTURE_RUNS_DDL = f"""
CREATE TABLE IF NOT EXISTS capture_runs (
    capture_run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN {CAPTURE_RUN_STATUS_VALUES}),
    target_post_count INTEGER NOT NULL,
    written_post_count INTEGER NOT NULL DEFAULT 0,
    last_seq_seen INTEGER,
    notes TEXT
);
"""

_HYDRATE_RUNS_DDL = f"""
CREATE TABLE IF NOT EXISTS hydrate_runs (
    hydrate_run_id TEXT PRIMARY KEY,
    capture_run_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN {HYDRATE_RUN_STATUS_VALUES}),
    eligible_post_count INTEGER NOT NULL DEFAULT 0,
    hydrated_post_count INTEGER NOT NULL DEFAULT 0,
    missing_post_count INTEGER NOT NULL DEFAULT 0,
    failed_post_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (capture_run_id) REFERENCES capture_runs(capture_run_id)
);
"""

_ACTOR_RUNS_DDL = f"""
CREATE TABLE IF NOT EXISTS actor_runs (
    actor_run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN {ACTOR_RUN_STATUS_VALUES}),
    seeded_actor_count INTEGER NOT NULL DEFAULT 0,
    eligible_actor_count INTEGER NOT NULL DEFAULT 0,
    enriched_actor_count INTEGER NOT NULL DEFAULT 0,
    missing_actor_count INTEGER NOT NULL DEFAULT 0,
    failed_actor_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
"""

_BATCH_FILES_DDL = f"""
CREATE TABLE IF NOT EXISTS batch_files (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    run_id TEXT NOT NULL,
    dataset_type TEXT NOT NULL,
    local_path TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    byte_size INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN {BATCH_FILE_STATUS_VALUES}),
    created_at TEXT NOT NULL,
    closed_at TEXT,
    UNIQUE(local_path)
);
"""

_CAPTURED_POSTS_DDL = f"""
CREATE TABLE IF NOT EXISTS captured_posts (
    uri TEXT PRIMARY KEY,
    capture_run_id TEXT NOT NULL,
    repo_did TEXT NOT NULL,
    rkey TEXT NOT NULL,
    cid_at_capture TEXT,
    seq INTEGER,
    record_created_at TEXT,
    captured_at TEXT NOT NULL,
    capture_file_id INTEGER,
    hydration_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (hydration_status IN {HYDRATION_STATUS_VALUES}),
    hydration_attempt_count INTEGER NOT NULL DEFAULT 0,
    last_hydration_attempt_at TEXT,
    hydrated_at TEXT,
    hydrate_run_id TEXT,
    last_error TEXT,
    claimed_by_worker TEXT,
    claim_expires_at TEXT,
    FOREIGN KEY (capture_run_id) REFERENCES capture_runs(capture_run_id),
    FOREIGN KEY (capture_file_id) REFERENCES batch_files(file_id),
    FOREIGN KEY (hydrate_run_id) REFERENCES hydrate_runs(hydrate_run_id)
);
"""

_ACTOR_PROFILES_STATE_DDL = f"""
CREATE TABLE IF NOT EXISTS actor_profiles_state (
    did TEXT PRIMARY KEY,
    seeded_at TEXT NOT NULL,
    source_first_seen TEXT NOT NULL,
    enrichment_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (enrichment_status IN {ACTOR_ENRICHMENT_STATUS_VALUES}),
    enrichment_attempt_count INTEGER NOT NULL DEFAULT 0,
    last_enrichment_attempt_at TEXT,
    enriched_at TEXT,
    actor_run_id TEXT,
    last_error TEXT,
    claimed_by_worker TEXT,
    claim_expires_at TEXT,
    FOREIGN KEY (actor_run_id) REFERENCES actor_runs(actor_run_id)
);
"""

_INDEX_DDLS: tuple[str, ...] = (
    """
    CREATE INDEX IF NOT EXISTS idx_capture_runs_status
    ON capture_runs(status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_hydrate_runs_capture
    ON hydrate_runs(capture_run_id, status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_batch_files_run_lookup
    ON batch_files(job_type, run_id, dataset_type, status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_actor_runs_status
    ON actor_runs(status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_captured_posts_status_captured_at
    ON captured_posts(hydration_status, captured_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_captured_posts_claim_expiration
    ON captured_posts(claim_expires_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_captured_posts_status_claim_expiration
    ON captured_posts(hydration_status, claim_expires_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_captured_posts_hydrate_run
    ON captured_posts(hydrate_run_id, hydration_status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_actor_profiles_state_status
    ON actor_profiles_state(enrichment_status, did);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_actor_profiles_state_claim_expiration
    ON actor_profiles_state(claim_expires_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_actor_profiles_state_run
    ON actor_profiles_state(actor_run_id, enrichment_status);
    """,
)

_TABLE_DDLS: tuple[str, ...] = (
    _CAPTURE_RUNS_DDL,
    _HYDRATE_RUNS_DDL,
    _ACTOR_RUNS_DDL,
    _BATCH_FILES_DDL,
    _CAPTURED_POSTS_DDL,
    _ACTOR_PROFILES_STATE_DDL,
)


def _execute_ddl_statements(conn: sqlite3.Connection, ddls: Sequence[str]) -> None:
    """Execute a list of DDL statements in order."""

    for ddl in ddls:
        conn.execute(ddl)


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all required tables/indexes and set schema version.

    DDL statements are idempotent (`IF NOT EXISTS`) so this can safely run on
    startup for scaffolding and early development.
    """

    conn.execute("PRAGMA foreign_keys = ON;")
    _execute_ddl_statements(conn, _TABLE_DDLS)
    _execute_ddl_statements(conn, _INDEX_DDLS)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION};")
    conn.commit()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure schema exists and is compatible with current SCHEMA_VERSION."""

    conn.execute("PRAGMA foreign_keys = ON;")
    current_version = int(conn.execute("PRAGMA user_version;").fetchone()[0])

    if current_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {current_version} is newer than supported "
            f"version {SCHEMA_VERSION}."
        )

    # For scaffolding phase, we re-run idempotent DDL and then bump user_version.
    create_schema(conn)
