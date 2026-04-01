"""Buffered gzip JSONL writer scaffolding.

Intended responsibility:
- buffer normalized rows
- flush to `.jsonl.gz` safely
- support future file rotation by row/time thresholds
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any


class GzipJsonlBatchWriter:
    """Simple buffered writer used as a placeholder for full rotation logic."""

    def __init__(self, output_path: Path, flush_every_rows: int = 10_000) -> None:
        self.output_path = output_path
        self.flush_every_rows = flush_every_rows
        self._buffer: list[dict[str, Any]] = []
        self._rows_written = 0
        self._closed = False

    @property
    def rows_written(self) -> int:
        """Total rows written to disk by this writer."""

        return self._rows_written

    def write_row(self, row: dict[str, Any]) -> None:
        """Buffer one row and flush when threshold is reached."""

        if self._closed:
            raise RuntimeError("Cannot write to a closed GzipJsonlBatchWriter")

        self._buffer.append(row)
        if len(self._buffer) >= self.flush_every_rows:
            self.flush()

    def flush(self) -> None:
        """Flush buffered rows to gzip JSONL output.

        Phase-1 note: this is a single-file writer. Rolling/atomic temp-rename
        behavior will be added in later phases.
        """

        if not self._buffer:
            return

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(self.output_path, mode="at", encoding="utf-8") as handle:
            for row in self._buffer:
                handle.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False))
                handle.write("\n")

        self._rows_written += len(self._buffer)
        self._buffer.clear()

    def close(self) -> None:
        """Flush remaining rows and prevent further writes."""

        if self._closed:
            return

        self.flush()
        self._closed = True
