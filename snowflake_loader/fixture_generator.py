"""Deterministic Week 2 fixture generation for Snowflake RAW loader demos."""

from __future__ import annotations

import argparse
import gzip
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from snowflake_loader.manifest import DATASET_FAMILIES


@dataclass(frozen=True, slots=True)
class FamilyFixtureSummary:
    dataset_family: str
    source_rows_available: int
    generated_rows: int
    duplicated_rows: int
    output_file: str


@dataclass(frozen=True, slots=True)
class FixtureGenerationSummary:
    source_root: str
    output_run_root: str
    rows_per_family: int
    run_id: str
    families: tuple[FamilyFixtureSummary, ...]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate deterministic 25-row fixture files for Week 2 loader demos")
    parser.add_argument("--source-root", type=Path, default=Path("data"))
    parser.add_argument("--output-run-root", type=Path, default=Path("data/output/w2_fixture_25"))
    parser.add_argument("--rows-per-family", type=int, default=25)
    parser.add_argument("--run-id", type=str, default="fixture_25")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = generate_fixture_run(
        source_root=args.source_root,
        output_run_root=args.output_run_root,
        rows_per_family=int(args.rows_per_family),
        run_id=str(args.run_id),
    )
    print(json.dumps(asdict(summary), indent=2))
    return 0


def generate_fixture_run(
    *,
    source_root: Path,
    output_run_root: Path,
    rows_per_family: int,
    run_id: str,
) -> FixtureGenerationSummary:
    """Build one deterministic fixture run root with exact rows per family."""

    if rows_per_family <= 0:
        raise ValueError("rows_per_family must be > 0")

    source_root = source_root.resolve()
    output_run_root = output_run_root.resolve()
    output_run_root.mkdir(parents=True, exist_ok=True)

    source_rows_by_family = _load_source_rows_by_family(
        source_root=source_root,
        excluded_root=output_run_root,
    )

    summaries: list[FamilyFixtureSummary] = []
    for dataset_family in DATASET_FAMILIES:
        source_rows = source_rows_by_family[dataset_family]
        if not source_rows:
            raise ValueError(
                "Unable to generate fixtures because no source rows were found for "
                f"dataset family '{dataset_family}' under {source_root}"
            )

        selected_rows = [source_rows[i % len(source_rows)] for i in range(rows_per_family)]
        out_file = output_run_root / dataset_family / run_id / f"{dataset_family}_000001.jsonl.gz"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        _write_jsonl_gz(out_file, selected_rows)

        summaries.append(
            FamilyFixtureSummary(
                dataset_family=dataset_family,
                source_rows_available=len(source_rows),
                generated_rows=rows_per_family,
                duplicated_rows=max(rows_per_family - len(source_rows), 0),
                output_file=str(out_file),
            )
        )

    return FixtureGenerationSummary(
        source_root=str(source_root),
        output_run_root=str(output_run_root),
        rows_per_family=rows_per_family,
        run_id=run_id,
        families=tuple(summaries),
    )


def _load_source_rows_by_family(*, source_root: Path, excluded_root: Path) -> dict[str, list[Any]]:
    rows_by_family: dict[str, list[Any]] = {family: [] for family in DATASET_FAMILIES}

    for path in sorted(source_root.rglob("*.jsonl.gz")):
        resolved = path.resolve()
        if _is_relative_to(resolved, excluded_root):
            continue

        dataset_family = _infer_dataset_family_from_path(resolved)
        if dataset_family is None:
            continue

        with gzip.open(resolved, "rt", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                rows_by_family[dataset_family].append(json.loads(text))

    return rows_by_family


def _infer_dataset_family_from_path(path: Path) -> str | None:
    for part in path.parts:
        if part in DATASET_FAMILIES:
            return part
    return None


def _write_jsonl_gz(path: Path, rows: list[Any]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True))
            handle.write("\n")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
