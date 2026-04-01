"""Small gzip JSONL utility helpers.

This module offers simple primitives for writing line-delimited JSON in gzip
format; advanced atomic file semantics are left for later writer upgrades.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def write_jsonl_gz(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    """Write rows to a gzip-compressed JSONL file and return row count."""

    path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with gzip.open(path, mode="wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False))
            handle.write("\n")
            row_count += 1
    return row_count
