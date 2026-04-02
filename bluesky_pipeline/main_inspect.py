"""Inspection and QA CLI for local pipeline datasets."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from bluesky_pipeline.inspect.exporter import export_sample_rows
from bluesky_pipeline.inspect.profiler import profile_dataset
from bluesky_pipeline.inspect.validator import DATASET_CHOICES, resolve_dataset_type, validate_required_fields
from bluesky_pipeline.inspect.viewer import list_dataset_files, sample_rows


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser for inspection subcommands."""

    parser = argparse.ArgumentParser(description="Bluesky pipeline inspection and QA tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)

    files_parser = subparsers.add_parser("files", help="List discovered data files")
    files_parser.add_argument("--input", type=Path, required=True)

    show_parser = subparsers.add_parser("show", help="Print first/last rows")
    show_parser.add_argument("--input", type=Path, required=True)
    show_parser.add_argument("--dataset", type=str, default="auto", choices=DATASET_CHOICES)
    show_parser.add_argument("--limit", type=int, default=5)
    show_parser.add_argument("--tail", action="store_true")
    show_parser.add_argument("--pretty", action="store_true")
    show_parser.add_argument("--show-source", action="store_true")

    export_parser = subparsers.add_parser("export", help="Export sample rows to .jsonl or .json")
    export_parser.add_argument("--input", type=Path, required=True)
    export_parser.add_argument("--dataset", type=str, default="auto", choices=DATASET_CHOICES)
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--limit", type=int, default=100)
    export_parser.add_argument("--tail", action="store_true")

    validate_parser = subparsers.add_parser("validate", help="Validate required fields")
    validate_parser.add_argument("--input", type=Path, required=True)
    validate_parser.add_argument("--dataset", type=str, default="auto", choices=DATASET_CHOICES)
    validate_parser.add_argument("--max-issues", type=int, default=20)

    profile_parser = subparsers.add_parser("profile", help="Show quick QA profile summary")
    profile_parser.add_argument("--input", type=Path, required=True)
    profile_parser.add_argument("--dataset", type=str, default="auto", choices=DATASET_CHOICES)
    profile_parser.add_argument("--top-k", type=int, default=10)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run inspection subcommand."""

    args = build_parser().parse_args(argv)

    try:
        if args.command == "files":
            return _run_files(args.input)
        if args.command == "show":
            return _run_show(args.input, args.dataset, args.limit, args.tail, args.pretty, args.show_source)
        if args.command == "export":
            return _run_export(args.input, args.dataset, args.output, args.limit, args.tail)
        if args.command == "validate":
            return _run_validate(args.input, args.dataset, args.max_issues)
        if args.command == "profile":
            return _run_profile(args.input, args.dataset, args.top_k)
        raise ValueError(f"Unsupported command: {args.command}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _run_files(input_path: Path) -> int:
    summaries = list_dataset_files(input_path)
    if not summaries:
        print("No data files found.")
        return 0

    total_rows = 0
    total_bytes = 0
    for summary in summaries:
        total_rows += summary.row_count
        total_bytes += summary.byte_size
        print(f"{summary.path}\trows={summary.row_count}\tbytes={summary.byte_size}")
    print(
        f"TOTAL files={len(summaries)} rows={total_rows} bytes={total_bytes}"
    )
    return 0


def _run_show(
    input_path: Path,
    dataset: str,
    limit: int,
    tail: bool,
    pretty: bool,
    show_source: bool,
) -> int:
    resolved = resolve_dataset_type(input_path, dataset=dataset)
    rows = sample_rows(input_path, limit=limit, tail=tail)
    print(
        f"dataset={resolved} rows_shown={len(rows)} mode={'tail' if tail else 'head'}"
    )

    for record in rows:
        if show_source:
            print(
                f"# source={record.source_file} line={record.line_number} row_index={record.row_index}"
            )
        if pretty:
            print(json.dumps(record.data, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print(json.dumps(record.data, ensure_ascii=False, separators=(",", ":")))
    return 0


def _run_export(
    input_path: Path,
    dataset: str,
    output_path: Path,
    limit: int,
    tail: bool,
) -> int:
    resolved = resolve_dataset_type(input_path, dataset=dataset)
    result = export_sample_rows(
        input_path=input_path,
        output_path=output_path,
        limit=limit,
        tail=tail,
    )
    print(
        f"dataset={resolved} exported_rows={result.row_count} format={result.output_format} output={result.output_path}"
    )
    return 0


def _run_validate(input_path: Path, dataset: str, max_issues: int) -> int:
    result = validate_required_fields(
        input_path=input_path,
        dataset=dataset,
        max_issues=max_issues,
    )

    print(
        f"dataset={result.dataset} rows_checked={result.rows_checked} "
        f"missing_field_rows={result.missing_field_rows}"
    )

    for issue in result.issues:
        print(
            f"issue row_index={issue.row_index} source={issue.source_file}:{issue.line_number} "
            f"missing_fields={','.join(issue.missing_fields)}"
        )

    if result.no_rows:
        print("Validation failed: no rows found.")
        return 1
    if result.missing_field_rows > 0:
        return 1
    return 0


def _run_profile(input_path: Path, dataset: str, top_k: int) -> int:
    result = profile_dataset(
        str(input_path),
        dataset=dataset,
        top_k=top_k,
    )
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

