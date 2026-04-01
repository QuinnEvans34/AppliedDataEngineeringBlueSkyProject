"""Rotating local gzip JSONL batch writer.

Phase 2 implementation goals:
- write one JSON object per line to `.jsonl.gz`
- rotate by row count or elapsed time
- write to temp files and only publish finalized file names
- expose finalized file metadata for SQLite tracking
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(slots=True, frozen=True)
class FinalizedBatchFile:
    """Metadata for one finalized batch file."""

    file_index: int
    final_path: Path
    row_count: int
    byte_size: int
    opened_at: str
    closed_at: str


class GzipJsonlBatchWriter:
    """Buffered writer that emits rotating `.jsonl.gz` files.

    The writer opens a temp gzip stream, appends compact JSON lines, and only
    publishes a finalized file via atomic rename when the file is complete.
    """

    def __init__(
        self,
        output_dir: Path | str,
        file_prefix: str,
        *,
        max_rows_per_file: int = 10_000,
        max_seconds_per_file: float = 60.0,
        buffer_row_limit: int = 500,
    ) -> None:
        if max_rows_per_file <= 0:
            raise ValueError("max_rows_per_file must be > 0")
        if max_seconds_per_file <= 0:
            raise ValueError("max_seconds_per_file must be > 0")
        if buffer_row_limit <= 0:
            raise ValueError("buffer_row_limit must be > 0")

        self.output_dir = Path(output_dir)
        self.file_prefix = file_prefix
        self.max_rows_per_file = max_rows_per_file
        self.max_seconds_per_file = max_seconds_per_file
        self.buffer_row_limit = buffer_row_limit

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._buffer: list[dict[str, Any]] = []
        self._rows_written_total = 0
        self._closed = False

        self._current_file_index = self._discover_last_file_index()
        self._current_row_count = 0
        self._current_opened_at_iso: str | None = None
        self._current_opened_monotonic: float | None = None

        self._current_final_path: Path | None = None
        self._current_temp_path: Path | None = None
        self._current_handle: gzip.GzipFile | None = None

        self._completed_files: list[FinalizedBatchFile] = []

    @property
    def rows_written(self) -> int:
        """Total rows written (across all finalized and open files)."""

        return self._rows_written_total

    @property
    def current_row_count(self) -> int:
        """Row count in the currently open file."""

        return self._current_row_count

    @property
    def current_final_path(self) -> Path | None:
        """Final path for the currently open file."""

        return self._current_final_path

    @property
    def current_temp_path(self) -> Path | None:
        """Temp path for the currently open file."""

        return self._current_temp_path

    @property
    def is_closed(self) -> bool:
        """Whether `close()` has been called."""

        return self._closed

    def write_row(self, row: dict[str, Any]) -> None:
        """Append one JSON-serializable row and rotate when thresholds are met."""

        if self._closed:
            raise RuntimeError("Cannot write to a closed GzipJsonlBatchWriter")

        self._ensure_open_file()
        self._rotate_if_time_due()

        self._buffer.append(row)
        self._current_row_count += 1
        self._rows_written_total += 1

        if len(self._buffer) >= self.buffer_row_limit:
            self._flush_buffer_to_disk()

        if self._current_row_count >= self.max_rows_per_file:
            self._flush_buffer_to_disk()
            self._finalize_current_file()

    def write_rows(self, rows: Iterable[dict[str, Any]]) -> None:
        """Append multiple rows."""

        for row in rows:
            self.write_row(row)

    def flush(self) -> None:
        """Flush buffered rows and rotate if elapsed-time threshold is reached."""

        if self._closed:
            raise RuntimeError("Cannot flush a closed GzipJsonlBatchWriter")
        if self._current_handle is None:
            return

        self._flush_buffer_to_disk()
        self._rotate_if_time_due()

    def close(self) -> list[FinalizedBatchFile]:
        """Finalize current file and return pending completed-file metadata."""

        if self._closed:
            return self.pop_completed_files()

        self._flush_buffer_to_disk()

        if self._current_handle is not None:
            if self._current_row_count > 0:
                self._finalize_current_file()
            else:
                self._discard_current_empty_temp_file()

        self._closed = True
        return self.pop_completed_files()

    def pop_completed_files(self) -> list[FinalizedBatchFile]:
        """Return and clear finalized-file metadata accumulated so far."""

        completed = list(self._completed_files)
        self._completed_files.clear()
        return completed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _discover_last_file_index(self) -> int:
        """Find the highest existing `<prefix>_<NNNNNN>.jsonl.gz` index."""

        pattern = re.compile(rf"^{re.escape(self.file_prefix)}_(\d{{6}})\.jsonl\.gz$")
        max_index = 0

        for path in self.output_dir.glob(f"{self.file_prefix}_*.jsonl.gz"):
            match = pattern.match(path.name)
            if match is None:
                continue
            max_index = max(max_index, int(match.group(1)))

        return max_index

    def _ensure_open_file(self) -> None:
        """Open a new temp gzip file if no file is currently open."""

        if self._current_handle is not None:
            return

        next_index = self._current_file_index + 1
        final_name = f"{self.file_prefix}_{next_index:06d}.jsonl.gz"
        final_path = self.output_dir / final_name
        temp_path = self.output_dir / f"{final_name}.tmp"

        # Recovery-friendly behavior: if a stale temp file exists, overwrite it.
        if temp_path.exists():
            temp_path.unlink()

        self._current_file_index = next_index
        self._current_final_path = final_path
        self._current_temp_path = temp_path
        self._current_opened_at_iso = datetime.now(timezone.utc).isoformat()
        self._current_opened_monotonic = time.monotonic()
        self._current_row_count = 0
        self._buffer.clear()

        self._current_handle = gzip.open(temp_path, mode="wt", encoding="utf-8")

    def _rotate_if_time_due(self) -> None:
        """Finalize current file when elapsed time threshold is reached."""

        if self._current_handle is None:
            return
        if self._current_row_count == 0:
            return
        if self._current_opened_monotonic is None:
            return

        elapsed = time.monotonic() - self._current_opened_monotonic
        if elapsed >= self.max_seconds_per_file:
            self._flush_buffer_to_disk()
            self._finalize_current_file()

    def _flush_buffer_to_disk(self) -> None:
        """Flush in-memory rows to the current gzip stream."""

        if not self._buffer:
            return
        if self._current_handle is None:
            raise RuntimeError("Cannot flush rows without an open file handle")

        for row in self._buffer:
            line = json.dumps(row, separators=(",", ":"), ensure_ascii=False)
            self._current_handle.write(line)
            self._current_handle.write("\n")

        self._buffer.clear()
        self._current_handle.flush()

    def _finalize_current_file(self) -> None:
        """Close temp file and atomically publish final gzip file."""

        if self._current_handle is None or self._current_temp_path is None or self._current_final_path is None:
            raise RuntimeError("Cannot finalize file: no open file state")
        if self._current_opened_at_iso is None:
            raise RuntimeError("Cannot finalize file: missing opened_at metadata")

        self._current_handle.close()
        self._current_handle = None

        os.replace(self._current_temp_path, self._current_final_path)
        byte_size = self._current_final_path.stat().st_size
        closed_at = datetime.now(timezone.utc).isoformat()

        self._completed_files.append(
            FinalizedBatchFile(
                file_index=self._current_file_index,
                final_path=self._current_final_path,
                row_count=self._current_row_count,
                byte_size=byte_size,
                opened_at=self._current_opened_at_iso,
                closed_at=closed_at,
            )
        )

        self._clear_current_file_state()

    def _discard_current_empty_temp_file(self) -> None:
        """Drop empty temp file on close so empty outputs are not published."""

        if self._current_handle is None:
            return

        self._current_handle.close()
        self._current_handle = None

        if self._current_temp_path is not None and self._current_temp_path.exists():
            self._current_temp_path.unlink()

        self._clear_current_file_state()

    def _clear_current_file_state(self) -> None:
        self._current_row_count = 0
        self._current_opened_at_iso = None
        self._current_opened_monotonic = None
        self._current_final_path = None
        self._current_temp_path = None
        self._buffer.clear()
