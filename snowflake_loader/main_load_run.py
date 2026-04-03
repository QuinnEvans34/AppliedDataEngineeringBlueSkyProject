"""CLI entrypoint for loading one local run root into Snowflake."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from snowflake_loader.config import build_loader_config, ensure_required_snowflake_env
from snowflake_loader.connection import SnowflakeSession
from snowflake_loader.copy_into import (
    copy_pending_files_for_family,
    fetch_loaded_file_paths,
    filter_pending_files,
)
from snowflake_loader.manifest import DATASET_FAMILIES, discover_run_manifest
from snowflake_loader.stage_upload import upload_dataset_files
from snowflake_loader.validate_load import (
    enforce_completion_gate,
    resolve_state_db_path,
    run_parity_checks,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load one Bluesky run root into Snowflake")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--state-db-path", type=Path, default=None)
    parser.add_argument("--maturity-hours", type=int, default=24)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = build_loader_config(
        run_root=args.run_root,
        state_db_path=args.state_db_path,
        dry_run=bool(args.dry_run),
        maturity_hours=int(args.maturity_hours),
    )

    manifest = discover_run_manifest(config.run_root)
    state_db_path = resolve_state_db_path(config.run_root, config.state_db_path)

    gate_summary = enforce_completion_gate(
        manifest=manifest,
        state_db_path=state_db_path,
        maturity_hours=config.maturity_hours,
    )

    if config.dry_run:
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "run_root": str(config.run_root),
                    "run_tag": config.run_tag,
                    "state_db_path": str(state_db_path),
                    "completion_gate": asdict(gate_summary),
                    "dataset_manifest": {
                        family: {
                            "file_count": manifest.total_file_count(family),
                            "row_count": manifest.total_row_count(family),
                            "run_ids": sorted(manifest.run_ids_for_family(family)),
                        }
                        for family in DATASET_FAMILIES
                    },
                },
                indent=2,
            )
        )
        return 0

    ensure_required_snowflake_env(config)

    per_family_copy: dict[str, dict[str, int]] = {}

    with SnowflakeSession.connect_from_config(config) as session:
        for dataset_family in DATASET_FAMILIES:
            all_files = list(manifest.files_for_family(dataset_family))
            loaded_paths = fetch_loaded_file_paths(
                session=session,
                manifest_table_name=config.objects.manifest_table_name,
                dataset_family=dataset_family,
                run_tag=config.run_tag,
            )
            pending_files = filter_pending_files(all_files, loaded_paths)

            stage_name = config.objects.stage_names[dataset_family]
            upload_dataset_files(
                session=session,
                stage_name=stage_name,
                run_tag=config.run_tag,
                dataset_family=dataset_family,
                files=pending_files,
                dry_run=False,
            )

            copy_summary = copy_pending_files_for_family(
                session=session,
                pending_files=pending_files,
                dataset_family=dataset_family,
                run_tag=config.run_tag,
                load_invocation_id=config.load_invocation_id,
                stage_name=stage_name,
                file_format_name=config.objects.file_format_name,
                landing_table_name=config.objects.landing_table_names[dataset_family],
                manifest_table_name=config.objects.manifest_table_name,
                dry_run=False,
            )
            per_family_copy[dataset_family] = {
                "attempted_files": copy_summary.attempted_files,
                "loaded_files": copy_summary.loaded_files,
                "loaded_rows": copy_summary.loaded_rows,
                "skipped_as_already_loaded": len(all_files) - len(pending_files),
            }

        parity = run_parity_checks(
            session=session,
            manifest=manifest,
            stage_names=config.objects.stage_names,
            landing_table_names=config.objects.landing_table_names,
            file_format_name=config.objects.file_format_name,
        )

    print(
        json.dumps(
            {
                "mode": "load",
                "run_root": str(config.run_root),
                "run_tag": config.run_tag,
                "state_db_path": str(state_db_path),
                "load_invocation_id": config.load_invocation_id,
                "completion_gate": asdict(gate_summary),
                "copy_summary": per_family_copy,
                "parity": {
                    "all_pass": parity.all_pass,
                    "dataset_results": [asdict(item) for item in parity.dataset_results],
                },
            },
            indent=2,
        )
    )

    return 0 if parity.all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
