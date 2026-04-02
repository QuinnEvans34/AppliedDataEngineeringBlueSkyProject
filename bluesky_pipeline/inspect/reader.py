"""Shared readers for pipeline dataset files."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, TextIO


@dataclass(slots=True, frozen=True)
class RowRecord:
    """One parsed JSON row with source metadata."""

    data: dict[str, Any]
    source_file: Path
    line_number: int
    row_index: int


def discover_data_files(input_path: Path | str) -> list[Path]:
    """Discover readable JSONL input files from a file or directory path."""

    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")

    if path.is_file():
        if not _is_supported_data_file(path):
            raise ValueError(f"Unsupported input file type: {path}")
        return [path]

    discovered: list[Path] = []
    for candidate in path.rglob("*"):
        if not candidate.is_file():
            continue
        if not _is_supported_data_file(candidate):
            continue
        discovered.append(candidate)

    discovered.sort(key=lambda p: str(p))
    return discovered


def iter_row_records(input_path: Path | str) -> Iterator[RowRecord]:
    """Yield parsed rows from all discovered files in stable sorted order."""

    files = discover_data_files(input_path)
    row_index = 0

    for source_file in files:
        with _open_text(source_file) as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON at {source_file}:{line_number}: {exc.msg}"
                    ) from exc

                if not isinstance(payload, dict):
                    raise ValueError(
                        f"Expected JSON object at {source_file}:{line_number}, "
                        f"found {type(payload).__name__}"
                    )

                row_index += 1
                yield RowRecord(
                    data=payload,
                    source_file=source_file,
                    line_number=line_number,
                    row_index=row_index,
                )


def count_rows_in_file(path: Path) -> int:
    """Count non-empty lines in one JSONL/JSONL.GZ file."""

    count = 0
    with _open_text(path) as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def first_row_record(input_path: Path | str) -> RowRecord | None:
    """Return the first row record from input, if any."""

    for row in iter_row_records(input_path):
        return row
    return None


def _is_supported_data_file(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".tmp"):
        return False
    return name.endswith(".jsonl") or name.endswith(".jsonl.gz")


def _open_text(path: Path) -> TextIO:
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, mode="rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")

