"""COPY INTO + manifest idempotency helpers for Snowflake loader."""

from __future__ import annotations

import re
from dataclasses import dataclass

from snowflake_loader.connection import SnowflakeSession
from snowflake_loader.manifest import ManifestFile
from snowflake_loader.stage_upload import stage_file_name_for_entry


@dataclass(frozen=True, slots=True)
class CopyIntoSummary:
    dataset_family: str
    attempted_files: int
    skipped_files: int
    loaded_files: int
    loaded_rows: int


def fetch_loaded_file_paths(
    *,
    session: SnowflakeSession,
    manifest_table_name: str,
    dataset_family: str,
    run_tag: str,
) -> set[str]:
    """Read already-loaded local file paths for one family/run tag."""

    sql = (
        f"SELECT local_file_path FROM {manifest_table_name} "
        "WHERE dataset_family = %s AND source_run_tag = %s"
    )
    rows = session.execute(sql, (dataset_family, run_tag))
    return {str(row[0]) for row in rows}


def filter_pending_files(all_files: list[ManifestFile], loaded_file_paths: set[str]) -> list[ManifestFile]:
    """Filter discovered files down to not-yet-loaded files."""

    return [entry for entry in all_files if str(entry.local_path) not in loaded_file_paths]


def copy_pending_files_for_family(
    *,
    session: SnowflakeSession,
    pending_files: list[ManifestFile],
    dataset_family: str,
    run_tag: str,
    load_invocation_id: str,
    stage_name: str,
    file_format_name: str,
    landing_table_name: str,
    manifest_table_name: str,
    dry_run: bool,
) -> CopyIntoSummary:
    """COPY pending files into landing and record load manifest entries."""

    loaded_rows = 0
    loaded_files = 0

    for entry in pending_files:
        stage_file_name = stage_file_name_for_entry(
            run_tag=run_tag,
            dataset_family=dataset_family,
            run_id=entry.run_id,
            filename=entry.local_path.name,
        )

        if dry_run:
            loaded_files += 0
            loaded_rows += 0
            continue

        rows_loaded = _copy_one_file(
            session=session,
            dataset_family=dataset_family,
            run_tag=run_tag,
            load_invocation_id=load_invocation_id,
            stage_name=stage_name,
            file_format_name=file_format_name,
            landing_table_name=landing_table_name,
            stage_file_name=stage_file_name,
        )
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
        loaded_rows += rows_loaded

    return CopyIntoSummary(
        dataset_family=dataset_family,
        attempted_files=len(pending_files),
        skipped_files=0,
        loaded_files=loaded_files,
        loaded_rows=loaded_rows,
    )


def _copy_one_file(
    *,
    session: SnowflakeSession,
    dataset_family: str,
    run_tag: str,
    load_invocation_id: str,
    stage_name: str,
    file_format_name: str,
    landing_table_name: str,
    stage_file_name: str,
) -> int:
    filename_pattern = re.escape(stage_file_name.split("/")[-1])
    stage_prefix = "/".join(stage_file_name.split("/")[:-1])

    sql = f"""
COPY INTO {landing_table_name}
(
    raw_payload,
    source_filename,
    source_file_row_number,
    source_run_tag,
    dataset_family,
    load_invocation_id,
    loaded_at
)
FROM (
    SELECT
        $1,
        METADATA$FILENAME,
        METADATA$FILE_ROW_NUMBER,
        %s,
        %s,
        %s,
        CURRENT_TIMESTAMP()
    FROM @{stage_name}/{stage_prefix}
    (
        FILE_FORMAT => (FORMAT_NAME => {file_format_name}),
        PATTERN => %s
    )
)
ON_ERROR = 'CONTINUE'
"""
    rows = session.execute(
        sql,
        (run_tag, dataset_family, load_invocation_id, f".*{filename_pattern}$"),
    )
    return _extract_rows_loaded(rows)


def _insert_manifest_row(
    *,
    session: SnowflakeSession,
    manifest_table_name: str,
    dataset_family: str,
    run_tag: str,
    load_invocation_id: str,
    entry: ManifestFile,
    stage_file_name: str,
    landing_rows_loaded: int,
) -> None:
    sql = f"""
INSERT INTO {manifest_table_name}
(
    dataset_family,
    source_run_tag,
    local_file_path,
    stage_file_name,
    local_row_count,
    local_byte_size,
    landing_rows_loaded,
    load_invocation_id,
    loaded_at
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP())
"""
    session.execute(
        sql,
        (
            dataset_family,
            run_tag,
            str(entry.local_path),
            stage_file_name,
            entry.row_count,
            entry.byte_size,
            landing_rows_loaded,
            load_invocation_id,
        ),
    )


def _extract_rows_loaded(rows: list[object]) -> int:
    total = 0
    for row in rows:
        if isinstance(row, dict):
            for key in ("rows_loaded", "ROWS_LOADED"):
                value = row.get(key)
                if isinstance(value, int):
                    total += value
                    break
            continue

        if isinstance(row, tuple) and len(row) >= 4 and isinstance(row[3], int):
            total += row[3]
    return total
