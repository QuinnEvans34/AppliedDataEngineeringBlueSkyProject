"""Snowpipe helpers for internal-stage loader mode."""

from __future__ import annotations

import time
from dataclasses import dataclass

from snowflake_loader.connection import SnowflakeSession
from snowflake_loader.copy_into import _insert_manifest_row
from snowflake_loader.manifest import ManifestFile
from snowflake_loader.stage_upload import stage_file_name_for_entry

_LOADED_STATUSES = {"LOADED"}
_FAILED_STATUSES = {"FAILED", "LOAD_FAILED", "PARTIALLY_LOADED"}


@dataclass(frozen=True, slots=True)
class SnowpipeFileOutcome:
    stage_file_name: str
    status: str  # loaded | failed | timed_out
    rows_loaded: int | None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class SnowpipeSummary:
    dataset_family: str
    attempted_files: int
    loaded_files: int
    failed_files: int
    timed_out_files: int
    loaded_rows: int


@dataclass(frozen=True, slots=True)
class _CopyHistoryRecord:
    file_name: str
    status: str
    row_count: int | None
    error_message: str | None


def load_pending_files_for_family(
    *,
    session: SnowflakeSession,
    pending_files: list[ManifestFile],
    dataset_family: str,
    run_tag: str,
    load_invocation_id: str,
    pipe_name: str,
    landing_table_name: str,
    manifest_table_name: str,
    poll_timeout_seconds: int = 120,
    poll_interval_seconds: int = 2,
    history_lookback_hours: int = 6,
) -> SnowpipeSummary:
    """Trigger Snowpipe load for one family and record manifest rows for loaded files only."""

    if not pending_files:
        return SnowpipeSummary(
            dataset_family=dataset_family,
            attempted_files=0,
            loaded_files=0,
            failed_files=0,
            timed_out_files=0,
            loaded_rows=0,
        )

    stage_file_name_by_local_path: dict[str, str] = {}
    pending_stage_file_names: list[str] = []
    for entry in pending_files:
        stage_file_name = stage_file_name_for_entry(
            run_tag=run_tag,
            dataset_family=dataset_family,
            run_id=entry.run_id,
            filename=entry.local_path.name,
        )
        stage_file_name_by_local_path[str(entry.local_path)] = stage_file_name
        pending_stage_file_names.append(stage_file_name)

    refresh_pipe_prefix(
        session=session,
        pipe_name=pipe_name,
        stage_prefix=f"{run_tag}/{dataset_family}",
    )

    outcomes = poll_pipe_file_outcomes(
        session=session,
        landing_table_name=landing_table_name,
        stage_prefix=f"{run_tag}/{dataset_family}",
        pending_stage_file_names=pending_stage_file_names,
        timeout_seconds=poll_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        history_lookback_hours=history_lookback_hours,
    )

    loaded_files = 0
    failed_files = 0
    timed_out_files = 0
    loaded_rows_total = 0

    for entry in pending_files:
        stage_file_name = stage_file_name_by_local_path[str(entry.local_path)]
        outcome = outcomes.get(stage_file_name)
        if outcome is None or outcome.status == "timed_out":
            timed_out_files += 1
            continue
        if outcome.status == "failed":
            failed_files += 1
            continue

        rows_loaded = outcome.rows_loaded or 0
        if rows_loaded <= 0:
            rows_loaded = _query_landing_rows_for_stage_file(
                session=session,
                landing_table_name=landing_table_name,
                run_tag=run_tag,
                dataset_family=dataset_family,
                stage_file_name=stage_file_name,
            )
        if rows_loaded <= 0:
            rows_loaded = entry.row_count

        _insert_manifest_row(
            session=session,
            manifest_table_name=manifest_table_name,
            dataset_family=dataset_family,
            run_tag=run_tag,
            load_invocation_id=load_invocation_id,
            entry=entry,
            stage_file_name=stage_file_name,
            landing_rows_loaded=rows_loaded,
        )
        loaded_files += 1
        loaded_rows_total += rows_loaded

    return SnowpipeSummary(
        dataset_family=dataset_family,
        attempted_files=len(pending_files),
        loaded_files=loaded_files,
        failed_files=failed_files,
        timed_out_files=timed_out_files,
        loaded_rows=loaded_rows_total,
    )


def refresh_pipe_prefix(*, session: SnowflakeSession, pipe_name: str, stage_prefix: str) -> None:
    """Trigger Snowpipe refresh for one dataset-family stage prefix."""

    sql = (
        f"ALTER PIPE {pipe_name} REFRESH "
        f"PREFIX = {_sql_literal(stage_prefix)}"
    )
    session.execute(sql)


def poll_pipe_file_outcomes(
    *,
    session: SnowflakeSession,
    landing_table_name: str,
    stage_prefix: str,
    pending_stage_file_names: list[str],
    timeout_seconds: int,
    poll_interval_seconds: int,
    history_lookback_hours: int,
) -> dict[str, SnowpipeFileOutcome]:
    """Poll COPY history until files are loaded/failed or timeout is reached."""

    pending = set(pending_stage_file_names)
    unresolved = set(pending)
    outcomes: dict[str, SnowpipeFileOutcome] = {}

    deadline = time.monotonic() + max(timeout_seconds, 0)

    while unresolved:
        history_rows = _query_copy_history(
            session=session,
            landing_table_name=landing_table_name,
            stage_prefix=stage_prefix,
            history_lookback_hours=history_lookback_hours,
        )
        for record in history_rows:
            stage_file_name = _match_stage_file_name(
                file_name=record.file_name,
                candidate_stage_file_names=unresolved,
            )
            if stage_file_name is None:
                continue

            status = record.status.upper().strip()
            if status in _LOADED_STATUSES:
                outcomes[stage_file_name] = SnowpipeFileOutcome(
                    stage_file_name=stage_file_name,
                    status="loaded",
                    rows_loaded=record.row_count,
                    error_message=None,
                )
                unresolved.discard(stage_file_name)
            elif status in _FAILED_STATUSES:
                outcomes[stage_file_name] = SnowpipeFileOutcome(
                    stage_file_name=stage_file_name,
                    status="failed",
                    rows_loaded=record.row_count,
                    error_message=record.error_message,
                )
                unresolved.discard(stage_file_name)

        if not unresolved:
            break
        if time.monotonic() >= deadline:
            break

        remaining = max(deadline - time.monotonic(), 0)
        if remaining <= 0:
            break
        sleep_seconds = poll_interval_seconds if poll_interval_seconds > 0 else 0.1
        time.sleep(min(sleep_seconds, remaining))

    for stage_file_name in unresolved:
        outcomes[stage_file_name] = SnowpipeFileOutcome(
            stage_file_name=stage_file_name,
            status="timed_out",
            rows_loaded=None,
            error_message="Timed out waiting for Snowpipe load history status.",
        )

    for stage_file_name in pending:
        outcomes.setdefault(
            stage_file_name,
            SnowpipeFileOutcome(
                stage_file_name=stage_file_name,
                status="timed_out",
                rows_loaded=None,
                error_message="Snowpipe outcome unavailable.",
            ),
        )

    return outcomes


def _query_copy_history(
    *,
    session: SnowflakeSession,
    landing_table_name: str,
    stage_prefix: str,
    history_lookback_hours: int,
) -> list[_CopyHistoryRecord]:
    sql = f"""
SELECT
  FILE_NAME,
  STATUS,
  ROW_COUNT,
  FIRST_ERROR_MESSAGE
FROM TABLE(
  INFORMATION_SCHEMA.COPY_HISTORY(
    TABLE_NAME=>{_sql_literal(landing_table_name)},
    START_TIME=>DATEADD('HOUR', -{int(history_lookback_hours)}, CURRENT_TIMESTAMP())
  )
)
WHERE FILE_NAME ILIKE {_sql_literal('%' + stage_prefix + '/%')}
ORDER BY LAST_LOAD_TIME DESC
"""
    rows = session.execute(sql)
    records: list[_CopyHistoryRecord] = []
    for row in rows:
        record = _coerce_copy_history_record(row)
        if record is not None:
            records.append(record)
    return records


def _query_landing_rows_for_stage_file(
    *,
    session: SnowflakeSession,
    landing_table_name: str,
    run_tag: str,
    dataset_family: str,
    stage_file_name: str,
) -> int:
    sql = f"""
SELECT COUNT(*)
FROM {landing_table_name}
WHERE source_run_tag = %s
  AND dataset_family = %s
  AND source_filename ILIKE %s
"""
    value = session.execute_scalar(
        sql,
        (run_tag, dataset_family, f"%{stage_file_name}"),
    )
    try:
        return int(value or 0)
    except Exception:
        return 0


def _coerce_copy_history_record(row: object) -> _CopyHistoryRecord | None:
    if isinstance(row, dict):
        file_name = _dict_get(row, "file_name", "FILE_NAME")
        status = _dict_get(row, "status", "STATUS")
        row_count = _to_int_or_none(_dict_get(row, "row_count", "ROW_COUNT"))
        error_message = _to_str_or_none(_dict_get(row, "first_error_message", "FIRST_ERROR_MESSAGE"))
        if file_name and status:
            return _CopyHistoryRecord(
                file_name=file_name,
                status=status,
                row_count=row_count,
                error_message=error_message,
            )
        return None

    if isinstance(row, tuple) and len(row) >= 2:
        file_name = _to_str_or_none(row[0])
        status = _to_str_or_none(row[1])
        row_count = _to_int_or_none(row[2]) if len(row) > 2 else None
        error_message = _to_str_or_none(row[3]) if len(row) > 3 else None
        if file_name and status:
            return _CopyHistoryRecord(
                file_name=file_name,
                status=status,
                row_count=row_count,
                error_message=error_message,
            )
    return None


def _match_stage_file_name(
    *,
    file_name: str,
    candidate_stage_file_names: set[str],
) -> str | None:
    if file_name in candidate_stage_file_names:
        return file_name

    for candidate in candidate_stage_file_names:
        if file_name.endswith(candidate) or file_name.endswith("/" + candidate):
            return candidate
    return None


def _dict_get(row: dict[object, object], *keys: str) -> object | None:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _to_str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _to_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except Exception:
        return None


def _sql_literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"
