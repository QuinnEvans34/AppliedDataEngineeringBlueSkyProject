"""File listing and row sampling helpers for inspection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from bluesky_pipeline.inspect.reader import RowRecord, count_rows_in_file, discover_data_files, iter_row_records


@dataclass(slots=True, frozen=True)
class FileSummary:
    """One discovered file summary."""

    path: Path
    row_count: int
    byte_size: int


def list_dataset_files(input_path: Path | str) -> list[FileSummary]:
    """List discovered data files with row and byte counts."""

    summaries: list[FileSummary] = []
    for path in discover_data_files(input_path):
        summaries.append(
            FileSummary(
                path=path,
                row_count=count_rows_in_file(path),
                byte_size=path.stat().st_size,
            )
        )
    return summaries


def sample_rows(input_path: Path | str, *, limit: int, tail: bool = False) -> list[RowRecord]:
    """Return first/last `limit` rows from input."""

    if limit <= 0:
        raise ValueError("limit must be > 0")

    if tail:
        ring = deque(maxlen=limit)
        for record in iter_row_records(input_path):
            ring.append(record)
        return list(ring)

    rows: list[RowRecord] = []
    for record in iter_row_records(input_path):
        rows.append(record)
        if len(rows) >= limit:
            break
    return rows

