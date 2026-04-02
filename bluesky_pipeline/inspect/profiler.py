"""Quick profiling helpers for dataset QA visibility."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from bluesky_pipeline.inspect.reader import iter_row_records
from bluesky_pipeline.inspect.validator import REQUIRED_FIELDS, resolve_dataset_type

_DISTRIBUTION_FIELDS: dict[str, tuple[str, ...]] = {
    "raw": ("operation", "collection", "has_reply", "has_embed"),
    "hydrated": ("author_did", "author_handle"),
    "actor": ("did", "handle"),
    "misses": ("status", "reason"),
}


@dataclass(slots=True, frozen=True)
class ProfileResult:
    """Quick profiling summary for one dataset input."""

    dataset: str
    files_count: int
    rows_count: int
    missing_required_rows: int
    missing_required_by_field: dict[str, int]
    null_counts_required_fields: dict[str, int]
    top_key_presence: dict[str, int]
    field_distributions: dict[str, dict[str, int]]


def profile_dataset(
    input_path: str,
    *,
    dataset: str = "auto",
    top_k: int = 10,
) -> ProfileResult:
    """Profile one dataset with row/key/null/distribution summaries."""

    if top_k <= 0:
        raise ValueError("top_k must be > 0")

    resolved_dataset = resolve_dataset_type(input_path, dataset=dataset)
    required_fields = REQUIRED_FIELDS[resolved_dataset]
    dist_fields = _DISTRIBUTION_FIELDS[resolved_dataset]

    files_seen: set[str] = set()
    rows_count = 0
    missing_required_rows = 0

    missing_required_by_field: Counter[str] = Counter()
    null_counts: Counter[str] = Counter()
    key_presence: Counter[str] = Counter()
    distributions: dict[str, Counter[str]] = {field: Counter() for field in dist_fields}

    for record in iter_row_records(input_path):
        rows_count += 1
        files_seen.add(str(record.source_file))
        row = record.data

        for key in row.keys():
            key_presence[key] += 1

        row_missing = False
        for field in required_fields:
            if field not in row:
                missing_required_by_field[field] += 1
                row_missing = True
            elif row[field] is None:
                null_counts[field] += 1
        if row_missing:
            missing_required_rows += 1

        for field in dist_fields:
            distributions[field][_distribution_value(row.get(field))] += 1

    top_key_presence = dict(key_presence.most_common(top_k))
    field_distributions = {
        field: dict(counter.most_common(top_k)) for field, counter in distributions.items()
    }

    return ProfileResult(
        dataset=resolved_dataset,
        files_count=len(files_seen),
        rows_count=rows_count,
        missing_required_rows=missing_required_rows,
        missing_required_by_field=dict(missing_required_by_field),
        null_counts_required_fields=dict(null_counts),
        top_key_presence=top_key_presence,
        field_distributions=field_distributions,
    )


def _distribution_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return repr(value)

