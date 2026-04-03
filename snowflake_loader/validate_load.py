"""Completion gate and load parity checks for Snowflake loader."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from snowflake_loader.connection import SnowflakeSession
from snowflake_loader.manifest import BUSINESS_KEY_BY_FAMILY, DATASET_FAMILIES, RunManifest


@dataclass(frozen=True, slots=True)
class HydrationCheckResult:
    capture_run_id: str
    capture_run_status: str | None
    capture_completed: bool
    total_rows: int
    all_rows_mature: bool
    mature_pending_retryable: int
    claimed_in_flight: int
    maturity_hours: int
    cutoff_utc_iso: str
    is_complete: bool


@dataclass(frozen=True, slots=True)
class ActorCheckResult:
    actor_rows_total: int
    pending_retryable: int
    claimed_in_flight: int
    is_complete: bool


@dataclass(frozen=True, slots=True)
class CompletionGateSummary:
    capture_run_id: str
    hydration: HydrationCheckResult
    actor: ActorCheckResult


@dataclass(frozen=True, slots=True)
class DatasetParityResult:
    dataset_family: str
    local_file_count: int
    local_row_count: int
    stage_file_count: int
    stage_row_count: int
    landing_row_count: int
    landing_distinct_business_keys: int
    parity_pass: bool


@dataclass(frozen=True, slots=True)
class ParitySummary:
    dataset_results: tuple[DatasetParityResult, ...]

    @property
    def all_pass(self) -> bool:
        return all(result.parity_pass for result in self.dataset_results)


def resolve_state_db_path(run_root: Path, explicit_state_db_path: Path | None) -> Path:
    """Resolve run-scoped state DB path, requiring a usable DB file."""

    if explicit_state_db_path is not None:
        if not explicit_state_db_path.exists() or not explicit_state_db_path.is_file():
            raise FileNotFoundError(f"State DB path does not exist: {explicit_state_db_path}")
        return explicit_state_db_path.resolve()

    state_dir = run_root / "state"
    db_candidates = sorted(state_dir.glob("*.db"))

    if not db_candidates:
        raise FileNotFoundError(
            f"No state DB found under run root state directory: {state_dir}"
        )
    if len(db_candidates) > 1:
        choices = ", ".join(str(path) for path in db_candidates)
        raise ValueError(
            "Multiple state DB files found under run root; pass --state-db-path explicitly. "
            f"Candidates: {choices}"
        )

    return db_candidates[0].resolve()


def enforce_completion_gate(
    *,
    manifest: RunManifest,
    state_db_path: Path,
    maturity_hours: int,
) -> CompletionGateSummary:
    """Require hydration + actor completion checks before safe load."""

    capture_run_id = infer_capture_run_id(manifest=manifest, state_db_path=state_db_path)
    hydration = check_hydration_completion(
        db_path=state_db_path,
        capture_run_id=capture_run_id,
        maturity_hours=maturity_hours,
    )
    actor = check_actor_completion(db_path=state_db_path)

    if not hydration.is_complete:
        raise RuntimeError(
            "Hydration completion gate failed: "
            f"capture_completed={hydration.capture_completed} "
            f"all_rows_mature={hydration.all_rows_mature} "
            f"mature_pending_retryable={hydration.mature_pending_retryable} "
            f"claimed_in_flight={hydration.claimed_in_flight}"
        )
    if not actor.is_complete:
        raise RuntimeError(
            "Actor completion gate failed: "
            f"pending_retryable={actor.pending_retryable} "
            f"claimed_in_flight={actor.claimed_in_flight}"
        )

    return CompletionGateSummary(
        capture_run_id=capture_run_id,
        hydration=hydration,
        actor=actor,
    )


def infer_capture_run_id(*, manifest: RunManifest, state_db_path: Path) -> str:
    """Resolve capture run id using raw dataset path shape, then DB fallback."""

    raw_run_ids = manifest.run_ids_for_family("raw_posts")
    if len(raw_run_ids) == 1:
        return next(iter(raw_run_ids))
    if len(raw_run_ids) > 1:
        raise ValueError(
            "Multiple raw capture run IDs discovered under run root; "
            "loader requires a single capture run for strict completion check."
        )

    conn = sqlite3.connect(state_db_path)
    try:
        row = conn.execute(
            "SELECT capture_run_id FROM capture_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise LookupError("Unable to infer capture_run_id from run root or state DB")
    return str(row[0])


def check_hydration_completion(
    *,
    db_path: Path,
    capture_run_id: str,
    maturity_hours: int,
) -> HydrationCheckResult:
    """Mirror hydration completion semantics from stage drain utility."""

    if maturity_hours < 0:
        raise ValueError("maturity_hours must be >= 0")

    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc - timedelta(hours=maturity_hours)
    cutoff_utc_iso = cutoff_utc.isoformat()

    conn = sqlite3.connect(db_path)
    try:
        try:
            run_row = conn.execute(
                "SELECT status FROM capture_runs WHERE capture_run_id = ?",
                (capture_run_id,),
            ).fetchone()
            capture_run_status = str(run_row[0]) if run_row is not None else None
            capture_completed = capture_run_status == "completed"

            total_rows = int(
                conn.execute(
                    "SELECT COUNT(*) FROM captured_posts WHERE capture_run_id = ?",
                    (capture_run_id,),
                ).fetchone()[0]
            )

            max_captured_at = conn.execute(
                "SELECT MAX(captured_at) FROM captured_posts WHERE capture_run_id = ?",
                (capture_run_id,),
            ).fetchone()[0]

            if max_captured_at is None:
                all_rows_mature = True
            else:
                all_rows_mature = _parse_iso8601(str(max_captured_at)) <= cutoff_utc

            mature_pending_retryable = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM captured_posts
                    WHERE capture_run_id = ?
                      AND hydration_status IN ('pending', 'retryable')
                      AND captured_at <= ?
                    """,
                    (capture_run_id, cutoff_utc_iso),
                ).fetchone()[0]
            )

            claimed_in_flight = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM captured_posts
                    WHERE capture_run_id = ?
                      AND hydration_status = 'claimed'
                    """,
                    (capture_run_id,),
                ).fetchone()[0]
            )
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "State DB is missing required hydration gate tables/columns "
                "(expected capture_runs and captured_posts with hydration fields)."
            ) from exc
    finally:
        conn.close()

    is_complete = (
        capture_completed
        and all_rows_mature
        and mature_pending_retryable == 0
        and claimed_in_flight == 0
    )

    return HydrationCheckResult(
        capture_run_id=capture_run_id,
        capture_run_status=capture_run_status,
        capture_completed=capture_completed,
        total_rows=total_rows,
        all_rows_mature=all_rows_mature,
        mature_pending_retryable=mature_pending_retryable,
        claimed_in_flight=claimed_in_flight,
        maturity_hours=maturity_hours,
        cutoff_utc_iso=cutoff_utc_iso,
        is_complete=is_complete,
    )


def check_actor_completion(*, db_path: Path) -> ActorCheckResult:
    """Mirror actor completion semantics from stage drain utility."""

    conn = sqlite3.connect(db_path)
    try:
        try:
            actor_rows_total = int(
                conn.execute("SELECT COUNT(*) FROM actor_profiles_state").fetchone()[0]
            )
            pending_retryable = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM actor_profiles_state
                    WHERE enrichment_status IN ('pending', 'retryable')
                    """
                ).fetchone()[0]
            )
            claimed_in_flight = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM actor_profiles_state
                    WHERE enrichment_status = 'claimed'
                    """
                ).fetchone()[0]
            )
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "State DB is missing required actor completion tables/columns "
                "(expected actor_profiles_state with enrichment_status)."
            ) from exc
    finally:
        conn.close()

    return ActorCheckResult(
        actor_rows_total=actor_rows_total,
        pending_retryable=pending_retryable,
        claimed_in_flight=claimed_in_flight,
        is_complete=(pending_retryable == 0 and claimed_in_flight == 0),
    )


def run_parity_checks(
    *,
    session: SnowflakeSession,
    manifest: RunManifest,
    stage_names: dict[str, str],
    landing_table_names: dict[str, str],
    file_format_name: str,
) -> ParitySummary:
    """Compute per-family parity between local files, stage, and landing."""

    results: list[DatasetParityResult] = []

    for dataset_family in DATASET_FAMILIES:
        local_file_count = manifest.total_file_count(dataset_family)
        local_row_count = manifest.total_row_count(dataset_family)

        stage_name = stage_names[dataset_family]
        stage_prefix = f"{manifest.run_tag}/{dataset_family}"
        stage_file_count = _query_stage_file_count(
            session=session,
            stage_name=stage_name,
            stage_prefix=stage_prefix,
        )
        stage_row_count = _query_stage_row_count(
            session=session,
            stage_name=stage_name,
            stage_prefix=stage_prefix,
            file_format_name=file_format_name,
        )

        landing_table_name = landing_table_names[dataset_family]
        landing_row_count = _query_landing_row_count(
            session=session,
            landing_table_name=landing_table_name,
            run_tag=manifest.run_tag,
        )
        landing_distinct_business_keys = _query_landing_distinct_business_keys(
            session=session,
            landing_table_name=landing_table_name,
            run_tag=manifest.run_tag,
            business_key=BUSINESS_KEY_BY_FAMILY[dataset_family],
        )

        parity_pass = (
            local_file_count == stage_file_count
            and local_row_count == stage_row_count
            and stage_row_count == landing_row_count
        )

        results.append(
            DatasetParityResult(
                dataset_family=dataset_family,
                local_file_count=local_file_count,
                local_row_count=local_row_count,
                stage_file_count=stage_file_count,
                stage_row_count=stage_row_count,
                landing_row_count=landing_row_count,
                landing_distinct_business_keys=landing_distinct_business_keys,
                parity_pass=parity_pass,
            )
        )

    return ParitySummary(dataset_results=tuple(results))


def _query_stage_file_count(*, session: SnowflakeSession, stage_name: str, stage_prefix: str) -> int:
    rows = session.execute(f"LIST @{stage_name}/{stage_prefix}")
    return len(rows)


def _query_stage_row_count(
    *,
    session: SnowflakeSession,
    stage_name: str,
    stage_prefix: str,
    file_format_name: str,
) -> int:
    sql = (
        "SELECT COUNT(*) "
        f"FROM @{stage_name}/{stage_prefix} "
        f"(FILE_FORMAT => (FORMAT_NAME => {file_format_name}))"
    )
    value = session.execute_scalar(sql)
    return int(value or 0)


def _query_landing_row_count(
    *,
    session: SnowflakeSession,
    landing_table_name: str,
    run_tag: str,
) -> int:
    sql = f"SELECT COUNT(*) FROM {landing_table_name} WHERE source_run_tag = %s"
    value = session.execute_scalar(sql, (run_tag,))
    return int(value or 0)


def _query_landing_distinct_business_keys(
    *,
    session: SnowflakeSession,
    landing_table_name: str,
    run_tag: str,
    business_key: str,
) -> int:
    sql = (
        f"SELECT COUNT(DISTINCT raw_payload:{business_key}::STRING) "
        f"FROM {landing_table_name} "
        "WHERE source_run_tag = %s "
        f"AND raw_payload:{business_key} IS NOT NULL"
    )
    value = session.execute_scalar(sql, (run_tag,))
    return int(value or 0)


def _parse_iso8601(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
