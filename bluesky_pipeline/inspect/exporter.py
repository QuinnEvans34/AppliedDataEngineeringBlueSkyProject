"""Sample export helpers for inspection workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bluesky_pipeline.inspect.viewer import sample_rows


@dataclass(slots=True, frozen=True)
class ExportResult:
    """Summary of one export operation."""

    output_path: Path
    output_format: str
    row_count: int


def export_sample_rows(
    input_path: Path | str,
    output_path: Path | str,
    *,
    limit: int,
    tail: bool = False,
) -> ExportResult:
    """Export sample rows as plain `.jsonl` or pretty `.json`."""

    out_path = Path(output_path)
    suffix_lower = out_path.name.lower()

    if suffix_lower.endswith(".json"):
        output_format = "json"
    elif suffix_lower.endswith(".jsonl"):
        output_format = "jsonl"
    else:
        raise ValueError("Output file must end with .json or .jsonl")

    rows = sample_rows(input_path, limit=limit, tail=tail)
    payload = [record.data for record in rows]

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "json":
        with out_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    else:
        with out_path.open("w", encoding="utf-8") as handle:
            for row in payload:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")

    return ExportResult(output_path=out_path, output_format=output_format, row_count=len(payload))

