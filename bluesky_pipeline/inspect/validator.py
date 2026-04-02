"""Dataset detection and required-field validation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from bluesky_pipeline.inspect.reader import RowRecord, discover_data_files, first_row_record, iter_row_records

DATASET_CHOICES: tuple[str, ...] = ("auto", "raw", "hydrated", "actor", "misses")

_DATASET_ALIASES: dict[str, str] = {
    "raw": "raw",
    "raw_posts": "raw",
    "hydrated": "hydrated",
    "hydrated_posts": "hydrated",
    "actor": "actor",
    "actor_profiles": "actor",
    "misses": "misses",
    "hydration_misses": "misses",
    "miss": "misses",
}

REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "raw": (
        "capture_run_id",
        "seq",
        "repo_did",
        "event_time",
        "operation",
        "collection",
        "rkey",
        "uri",
        "cid",
        "record_created_at",
        "has_reply",
        "has_embed",
        "captured_at",
        "record",
    ),
    "hydrated": (
        "hydrate_run_id",
        "capture_run_id",
        "uri",
        "cid",
        "indexed_at",
        "author_did",
        "author_handle",
        "author_display_name",
        "reply_count",
        "repost_count",
        "like_count",
        "quote_count",
        "labels",
        "hydrated_at",
        "record",
    ),
    "actor": (
        "actor_run_id",
        "did",
        "handle",
        "display_name",
        "description",
        "followers_count",
        "follows_count",
        "posts_count",
        "indexed_at",
        "created_at",
        "labels",
        "associated",
        "enriched_at",
        "profile",
    ),
    "misses": (
        "hydrate_run_id",
        "capture_run_id",
        "uri",
        "cid_at_capture",
        "captured_at",
        "status",
        "reason",
        "checked_at",
        "attempt_count",
    ),
}

_PATH_MARKERS: dict[str, str] = {
    "raw": "raw_posts",
    "hydrated": "hydrated_posts",
    "actor": "actor_profiles",
    "misses": "hydration_misses",
}

_ROW_SHAPE_SIGNATURES: dict[str, tuple[str, ...]] = {
    "raw": ("repo_did", "has_reply", "has_embed"),
    "hydrated": ("author_did", "like_count", "quote_count"),
    "actor": ("actor_run_id", "followers_count", "follows_count"),
    "misses": ("cid_at_capture", "reason", "attempt_count"),
}


@dataclass(slots=True, frozen=True)
class ValidationIssue:
    """A row-level required-field validation issue."""

    row_index: int
    source_file: Path
    line_number: int
    missing_fields: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ValidationResult:
    """Validation summary for one dataset input."""

    dataset: str
    rows_checked: int
    missing_field_rows: int
    issues: tuple[ValidationIssue, ...]
    no_rows: bool

    @property
    def success(self) -> bool:
        return (not self.no_rows) and self.missing_field_rows == 0


def normalize_dataset_choice(dataset: str) -> str:
    """Normalize dataset argument and aliases."""

    normalized = dataset.strip().lower()
    if normalized == "auto":
        return "auto"
    resolved = _DATASET_ALIASES.get(normalized)
    if resolved is None:
        raise ValueError(
            f"Unknown dataset type '{dataset}'. Expected one of: "
            f"{', '.join(DATASET_CHOICES)}"
        )
    return resolved


def resolve_dataset_type(input_path: Path | str, dataset: str = "auto") -> str:
    """Resolve dataset family using explicit choice or auto-detection."""

    normalized = normalize_dataset_choice(dataset)
    if normalized != "auto":
        return normalized

    files = discover_data_files(input_path)
    if not files:
        raise ValueError(f"No data files found under input: {input_path}")

    path_detected = _detect_dataset_from_path(Path(input_path), files)
    if path_detected is not None:
        return path_detected

    sample = first_row_record(input_path)
    if sample is None:
        raise ValueError(f"No rows found in input: {input_path}")

    row_detected = _detect_dataset_from_row_shape(sample.data)
    if row_detected is not None:
        return row_detected

    raise ValueError(
        "Unable to auto-detect dataset type from path or row shape. "
        "Pass --dataset explicitly."
    )


def validate_required_fields(
    input_path: Path | str,
    *,
    dataset: str = "auto",
    max_issues: int = 20,
) -> ValidationResult:
    """Validate required top-level fields for each row."""

    if max_issues <= 0:
        raise ValueError("max_issues must be > 0")

    resolved_dataset = resolve_dataset_type(input_path, dataset=dataset)
    required_fields = REQUIRED_FIELDS[resolved_dataset]

    rows_checked = 0
    missing_field_rows = 0
    issues: list[ValidationIssue] = []

    for record in iter_row_records(input_path):
        rows_checked += 1
        missing = tuple(field for field in required_fields if field not in record.data)
        if not missing:
            continue

        missing_field_rows += 1
        if len(issues) < max_issues:
            issues.append(
                ValidationIssue(
                    row_index=record.row_index,
                    source_file=record.source_file,
                    line_number=record.line_number,
                    missing_fields=missing,
                )
            )

    return ValidationResult(
        dataset=resolved_dataset,
        rows_checked=rows_checked,
        missing_field_rows=missing_field_rows,
        issues=tuple(issues),
        no_rows=(rows_checked == 0),
    )


def _detect_dataset_from_path(input_path: Path, files: Sequence[Path]) -> str | None:
    candidates: set[str] = set()
    paths = [input_path, *files]
    for path in paths:
        lower_parts = [part.lower() for part in path.parts]
        for dataset, marker in _PATH_MARKERS.items():
            if marker in lower_parts:
                candidates.add(dataset)

    if not candidates:
        return None
    if len(candidates) == 1:
        return next(iter(candidates))

    raise ValueError(
        "Ambiguous dataset type from path markers. Found multiple dataset markers: "
        f"{', '.join(sorted(candidates))}. Pass --dataset explicitly."
    )


def _detect_dataset_from_row_shape(row: Mapping[str, object]) -> str | None:
    keys = set(row.keys())
    matches: list[str] = []
    for dataset, signature in _ROW_SHAPE_SIGNATURES.items():
        if set(signature).issubset(keys):
            matches.append(dataset)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            "Ambiguous dataset type from row shape. Pass --dataset explicitly."
        )
    return None

