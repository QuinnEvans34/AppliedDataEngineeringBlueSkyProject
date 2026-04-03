"""Stage upload helpers for finalized local dataset files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from snowflake_loader.connection import SnowflakeSession
from snowflake_loader.manifest import ManifestFile


@dataclass(frozen=True, slots=True)
class StageUploadResult:
    dataset_family: str
    local_path: Path
    stage_path: str
    uploaded: bool


def upload_dataset_files(
    *,
    session: SnowflakeSession,
    stage_name: str,
    run_tag: str,
    dataset_family: str,
    files: list[ManifestFile],
    dry_run: bool,
) -> list[StageUploadResult]:
    """Upload pending files to a family-specific internal stage path."""

    results: list[StageUploadResult] = []
    for entry in files:
        stage_subdir = _stage_subdir(
            run_tag=run_tag,
            dataset_family=dataset_family,
            run_id=entry.run_id,
        )
        stage_path = f"@{stage_name}/{stage_subdir}"

        if dry_run:
            results.append(
                StageUploadResult(
                    dataset_family=dataset_family,
                    local_path=entry.local_path,
                    stage_path=stage_path,
                    uploaded=False,
                )
            )
            continue

        put_sql = (
            f"PUT {_sql_literal('file://' + str(entry.local_path))} "
            f"{stage_path} AUTO_COMPRESS=FALSE OVERWRITE=FALSE"
        )
        session.execute(put_sql)
        results.append(
            StageUploadResult(
                dataset_family=dataset_family,
                local_path=entry.local_path,
                stage_path=stage_path,
                uploaded=True,
            )
        )

    return results


def stage_file_name_for_entry(*, run_tag: str, dataset_family: str, run_id: str, filename: str) -> str:
    """Return deterministic stage-relative file path used by loader."""

    return f"{_stage_subdir(run_tag=run_tag, dataset_family=dataset_family, run_id=run_id)}/{filename}"


def _stage_subdir(*, run_tag: str, dataset_family: str, run_id: str) -> str:
    return f"{run_tag}/{dataset_family}/{run_id}"


def _sql_literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"
