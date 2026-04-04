#!/usr/bin/env python3
"""Thin Week 2 RAW ingestion demo runner for internal-stage Snowpipe flow."""

from __future__ import annotations

import argparse
import gzip
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from snowflake_loader.fixture_generator import FixtureGenerationSummary, generate_fixture_run
from snowflake_loader.main_load_run import main as run_loader_main
from snowflake_loader.manifest import DATASET_FAMILIES


def build_parser() -> argparse.ArgumentParser:
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(
        description="Run the Week 2 RAW ingestion demo (fixtures -> stage -> load -> summary)."
    )
    parser.add_argument("--source-root", type=Path, default=repo_root / "data")
    parser.add_argument("--run-root", type=Path, default=repo_root / "data" / "output" / "w2_fixture_25")
    parser.add_argument("--rows-per-family", type=int, default=25)
    parser.add_argument("--run-id", type=str, default="fixture_25")
    parser.add_argument("--load-mode", choices=("snowpipe", "copy"), default="snowpipe")
    parser.add_argument(
        "--enforce-completion-gate",
        action="store_true",
        help="Use strict completion gate instead of fixture/demo bypass.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-loader-json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_root = Path(args.source_root).resolve()
    run_root = Path(args.run_root).resolve()

    synthetic_seeded_families = _ensure_minimal_fixture_sources(
        source_root=source_root,
        output_run_root=run_root,
    )

    try:
        fixture_summary = generate_fixture_run(
            source_root=source_root,
            output_run_root=run_root,
            rows_per_family=int(args.rows_per_family),
            run_id=str(args.run_id),
        )
    except Exception as exc:
        print("Week 2 RAW Ingestion Demo")
        print("- status: failed_before_loader")
        print(f"- error: {exc}")
        return 1

    loader_argv = [
        "--run-root",
        str(run_root),
        "--load-mode",
        str(args.load_mode),
    ]
    if not args.enforce_completion_gate:
        loader_argv.append("--skip-completion-gate")
    if args.dry_run:
        loader_argv.append("--dry-run")

    loader_stdout = io.StringIO()
    loader_error: str | None = None
    try:
        with redirect_stdout(loader_stdout):
            loader_exit_code = run_loader_main(loader_argv)
    except Exception as exc:
        loader_exit_code = 1
        loader_error = str(exc)
        _print_loader_error_hints(exc)
    loader_output = loader_stdout.getvalue().strip()
    loader_payload = _parse_json_payload(loader_output)

    _print_human_summary(
        fixture_summary=fixture_summary,
        load_mode=str(args.load_mode),
        loader_exit_code=loader_exit_code,
        loader_payload=loader_payload,
        synthetic_seeded_families=synthetic_seeded_families,
        loader_error=loader_error,
    )

    if args.print_loader_json and loader_output:
        print("\nLoader JSON:")
        print(loader_output)

    return loader_exit_code


def _parse_json_payload(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        payload = json.loads(text)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _print_human_summary(
    *,
    fixture_summary: FixtureGenerationSummary,
    load_mode: str,
    loader_exit_code: int,
    loader_payload: dict[str, Any] | None,
    synthetic_seeded_families: tuple[str, ...],
    loader_error: str | None,
) -> None:
    print("Week 2 RAW Ingestion Demo")
    print(f"- run_root: {fixture_summary.output_run_root}")
    print(f"- rows_per_family: {fixture_summary.rows_per_family}")
    print("- families: raw_posts, hydrated_posts, hydration_misses, actor_profiles")
    if synthetic_seeded_families:
        joined = ", ".join(synthetic_seeded_families)
        print(f"- synthetic_seeded_families: {joined}")
    print("- fixture_files:")
    for family in fixture_summary.families:
        print(f"  - {family.dataset_family}: generated_rows={family.generated_rows} file={family.output_file}")

    print(f"- load_mode: {load_mode}")
    print(f"- loader_exit_code: {loader_exit_code}")
    if loader_error:
        print(f"- loader_error: {loader_error}")

    if loader_payload is None:
        print("- loader_summary: unavailable (non-JSON loader output)")
        return

    if loader_payload.get("mode") == "dry_run":
        print("- loader_mode: dry_run (no Snowflake mutation)")
        dataset_manifest = loader_payload.get("dataset_manifest", {})
        if isinstance(dataset_manifest, dict):
            print("- dataset_manifest:")
            for family in DATASET_FAMILIES:
                item = dataset_manifest.get(family, {})
                if not isinstance(item, dict):
                    item = {}
                print(
                    "  - "
                    f"{family}: files={int(item.get('file_count', 0))} "
                    f"rows={int(item.get('row_count', 0))}"
                )
        return

    parity = loader_payload.get("parity")
    if isinstance(parity, dict):
        print(f"- parity_all_pass: {bool(parity.get('all_pass', False))}")
    else:
        print("- parity_all_pass: n/a")

    summary_key = "snowpipe_summary" if load_mode == "snowpipe" else "copy_summary"
    family_summary = loader_payload.get(summary_key, {})
    if not isinstance(family_summary, dict):
        print(f"- {summary_key}: unavailable")
        return

    print(f"- {summary_key}:")
    for family in DATASET_FAMILIES:
        item = family_summary.get(family, {})
        if not isinstance(item, dict):
            item = {}
        if load_mode == "snowpipe":
            print(
                "  - "
                f"{family}: attempted={int(item.get('attempted_files', 0))} "
                f"loaded={int(item.get('loaded_files', 0))} "
                f"failed={int(item.get('failed_files', 0))} "
                f"timed_out={int(item.get('timed_out_files', 0))} "
                f"rows={int(item.get('loaded_rows', 0))} "
                f"skipped={int(item.get('skipped_as_already_loaded', 0))}"
            )
        else:
            print(
                "  - "
                f"{family}: attempted={int(item.get('attempted_files', 0))} "
                f"loaded={int(item.get('loaded_files', 0))} "
                f"rows={int(item.get('loaded_rows', 0))} "
                f"skipped={int(item.get('skipped_as_already_loaded', 0))}"
            )


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _ensure_minimal_fixture_sources(*, source_root: Path, output_run_root: Path) -> tuple[str, ...]:
    source_root.mkdir(parents=True, exist_ok=True)
    output_run_root = output_run_root.resolve()

    present_families = _discover_source_families(source_root=source_root, output_run_root=output_run_root)
    missing_families = [family for family in DATASET_FAMILIES if family not in present_families]
    if not missing_families:
        return ()

    seed_root = source_root / "w2_demo_seed"
    seed_rows = _default_seed_rows()

    for family in missing_families:
        file_path = seed_root / family / "seed_000001" / f"{family}_000001.jsonl.gz"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(file_path, "wt", encoding="utf-8") as handle:
            for row in seed_rows[family]:
                handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True))
                handle.write("\n")

    return tuple(missing_families)


def _discover_source_families(*, source_root: Path, output_run_root: Path) -> set[str]:
    found: set[str] = set()
    for path in sorted(source_root.rglob("*.jsonl.gz")):
        resolved = path.resolve()
        if _is_relative_to(resolved, output_run_root):
            continue
        family = _infer_family_from_path(resolved)
        if family is None:
            continue
        if _file_has_any_json_line(resolved):
            found.add(family)
            if len(found) == len(DATASET_FAMILIES):
                break
    return found


def _infer_family_from_path(path: Path) -> str | None:
    for part in path.parts:
        if part in DATASET_FAMILIES:
            return part
    return None


def _file_has_any_json_line(path: Path) -> bool:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    return True
    except Exception:
        return False
    return False


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _default_seed_rows() -> dict[str, list[dict[str, object]]]:
    return {
        "raw_posts": [
            {
                "uri": "at://did:plc:w2seed/app.bsky.feed.post/000001",
                "capture_run_id": "seed_capture",
                "record": {"text": "week2 seed raw post"},
            }
        ],
        "hydrated_posts": [
            {
                "uri": "at://did:plc:w2seed/app.bsky.feed.post/000001",
                "capture_run_id": "seed_capture",
                "hydrate_run_id": "seed_hydrate",
                "record": {"text": "week2 seed hydrated post"},
            }
        ],
        "hydration_misses": [
            {
                "uri": "at://did:plc:w2seed/app.bsky.feed.post/000002",
                "capture_run_id": "seed_capture",
                "hydrate_run_id": "seed_hydrate",
                "status": "missing",
                "reason": "seed_not_returned",
            }
        ],
        "actor_profiles": [
            {
                "did": "did:plc:w2seed",
                "actor_run_id": "seed_actor",
                "handle": "week2.seed",
            }
        ],
    }


def _print_loader_error_hints(exc: Exception) -> None:
    message = str(exc)
    if message.startswith("Missing required Snowflake environment variables:"):
        print("Hint: load Snowflake env vars before non-dry runs.")
        print("Hint: `set -a; source local/snowflake.env; set +a`")
        return
    if "snowflake-connector-python is not installed" in message:
        print("Hint: install dependencies before non-dry runs.")
        print("Hint: `python3 -m pip install -r requirements.txt`")


if __name__ == "__main__":
    raise SystemExit(main())
