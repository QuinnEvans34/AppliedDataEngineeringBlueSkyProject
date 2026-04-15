"""Gzip JSONL writer for trend match results.

Writes post-to-trend match records as rotating `.jsonl.gz` files
under `data/trend_matches/{run_id}/`. Follows the same rotating
temp-file pattern as `bluesky_pipeline.batching.writer.GzipJsonlBatchWriter`.
"""

from __future__ import annotations

import gzip
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class FinalizedMatchFile:
    """Metadata for one finalized trend match file."""

    file_index: int
    final_path: Path
    row_count: int
    byte_size: int
    opened_at: str
    closed_at: str


class TrendMatchWriter:
    """Buffered writer that emits rotating `.jsonl.gz` trend match files.

    The writer opens a temp gzip stream, appends compact JSON lines, and only
    publishes a finalized file via atomic rename when the file is complete.
    """

    FILE_PREFIX = "trend_matches"

    def __init__(
        self,
        output_dir: Path,
        run_id: str,
        flush_row_count: int = 10_000,
    ) -> None:
        """
        Writes trend match results to gzip JSONL files.
        output_dir: base directory (e.g. data/trend_matches/)
        run_id: unique run identifier for subdirectory
        flush_row_count: rows before rotating to next file
        """
        if flush_row_count <= 0:
            raise ValueError("flush_row_count must be > 0")

        self.output_dir = output_dir / run_id
        self.run_id = run_id
        self.flush_row_count = flush_row_count

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._buffer: list[dict[str, Any]] = []
        self._rows_written_total = 0
        self._closed = False

        self._current_file_index = self._discover_last_file_index()
        self._current_row_count = 0
        self._current_opened_at_iso: str | None = None

        self._current_final_path: Path | None = None
        self._current_temp_path: Path | None = None
        self._current_handle: gzip.GzipFile | None = None

        self._completed_files: list[FinalizedMatchFile] = []

    @property
    def rows_written(self) -> int:
        """Total rows written (across all finalized and open files)."""
        return self._rows_written_total

    @property
    def is_closed(self) -> bool:
        """Whether `close()` has been called."""
        return self._closed

    def write_matches(self, matches: list[dict]) -> None:
        """
        Accepts a list of match dicts, each with:
        post_uri, trend_name, trend_date, match_method,
        match_score, matched_at
        Buffers and flushes to gzip JSONL automatically.
        """
        if self._closed:
            raise RuntimeError("Cannot write to a closed TrendMatchWriter")

        for row in matches:
            self._ensure_open_file()
            self._buffer.append(row)
            self._current_row_count += 1
            self._rows_written_total += 1

            if self._current_row_count >= self.flush_row_count:
                self._flush_buffer_to_disk()
                self._finalize_current_file()

    def close(self) -> list[Path]:
        """
        Flushes remaining buffer, closes file handles.
        Returns list of Path objects for all files written.
        """
        if self._closed:
            return [item.final_path for item in self._completed_files]

        self._flush_buffer_to_disk()

        if self._current_handle is not None:
            if self._current_row_count > 0:
                self._finalize_current_file()
            else:
                self._discard_current_empty_temp_file()

        self._closed = True
        return [item.final_path for item in self._completed_files]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _discover_last_file_index(self) -> int:
        """Find the highest existing `trend_matches_<NNNNNN>.jsonl.gz` index."""

        pattern = re.compile(
            rf"^{re.escape(self.FILE_PREFIX)}_(\d{{6}})\.jsonl\.gz$"
        )
        max_index = 0

        for path in self.output_dir.glob(f"{self.FILE_PREFIX}_*.jsonl.gz"):
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
        final_name = f"{self.FILE_PREFIX}_{next_index:06d}.jsonl.gz"
        final_path = self.output_dir / final_name
        temp_path = self.output_dir / f"{final_name}.tmp"

        if temp_path.exists():
            temp_path.unlink()

        self._current_file_index = next_index
        self._current_final_path = final_path
        self._current_temp_path = temp_path
        self._current_opened_at_iso = datetime.now(timezone.utc).isoformat()
        self._current_row_count = 0
        self._buffer.clear()

        self._current_handle = gzip.open(temp_path, mode="wt", encoding="utf-8")

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

        if (
            self._current_handle is None
            or self._current_temp_path is None
            or self._current_final_path is None
        ):
            raise RuntimeError("Cannot finalize file: no open file state")
        if self._current_opened_at_iso is None:
            raise RuntimeError("Cannot finalize file: missing opened_at metadata")

        self._current_handle.close()
        self._current_handle = None

        os.replace(self._current_temp_path, self._current_final_path)
        byte_size = self._current_final_path.stat().st_size
        closed_at = datetime.now(timezone.utc).isoformat()

        self._completed_files.append(
            FinalizedMatchFile(
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
        self._current_final_path = None
        self._current_temp_path = None
        self._buffer.clear()
