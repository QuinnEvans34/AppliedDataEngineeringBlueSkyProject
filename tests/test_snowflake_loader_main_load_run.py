from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowflake_loader.config import LoaderConfig, SnowflakeAuthConfig, SnowflakeObjectConfig
from snowflake_loader.copy_into import CopyIntoSummary
from snowflake_loader.main_load_run import build_parser, main
from snowflake_loader.manifest import DATASET_FAMILIES, ManifestFile, RunManifest
from snowflake_loader.snowpipe import SnowpipeSummary
from snowflake_loader.validate_load import (
    ActorCheckResult,
    CompletionGateSummary,
    DatasetParityResult,
    HydrationCheckResult,
    ParitySummary,
)


class _SessionContext:
    def __init__(self) -> None:
        self.session = object()

    def __enter__(self) -> object:
        return self.session

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None


class MainLoadRunModeTests(unittest.TestCase):
    def test_parser_defaults_to_snowpipe_mode(self) -> None:
        args = build_parser().parse_args(["--run-root", "/tmp/run"])
        self.assertEqual(args.load_mode, "snowpipe")

    def test_parser_accepts_copy_mode(self) -> None:
        args = build_parser().parse_args(["--run-root", "/tmp/run", "--load-mode", "copy"])
        self.assertEqual(args.load_mode, "copy")

    def test_parser_accepts_skip_completion_gate_flag(self) -> None:
        args = build_parser().parse_args(["--run-root", "/tmp/run", "--skip-completion-gate"])
        self.assertTrue(args.skip_completion_gate)

    def test_main_skip_completion_gate_bypasses_gate_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            run_root = Path(tempdir) / "run_skip_gate"
            run_root.mkdir(parents=True, exist_ok=True)
            manifest = _build_manifest(run_root)
            config = _build_config(run_root, dry_run=True)

            with mock.patch("snowflake_loader.main_load_run.build_loader_config", return_value=config), mock.patch(
                "snowflake_loader.main_load_run.discover_run_manifest", return_value=manifest
            ), mock.patch(
                "snowflake_loader.main_load_run.resolve_state_db_path"
            ) as mock_resolve_state_db_path, mock.patch(
                "snowflake_loader.main_load_run.enforce_completion_gate"
            ) as mock_enforce_completion_gate, mock.patch("sys.stdout", new_callable=io.StringIO):
                code = main(["--run-root", str(run_root), "--skip-completion-gate", "--dry-run"])

        self.assertEqual(code, 0)
        mock_resolve_state_db_path.assert_not_called()
        mock_enforce_completion_gate.assert_not_called()

    def test_main_copy_mode_uses_copy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            run_root = Path(tempdir) / "run_copy"
            run_root.mkdir(parents=True, exist_ok=True)
            manifest = _build_manifest(run_root)
            config = _build_config(run_root, dry_run=False)
            gate_summary = _gate_summary()
            parity = _parity_summary()

            with mock.patch("snowflake_loader.main_load_run.build_loader_config", return_value=config), mock.patch(
                "snowflake_loader.main_load_run.discover_run_manifest", return_value=manifest
            ), mock.patch("snowflake_loader.main_load_run.resolve_state_db_path", return_value=run_root / "state" / "run.db"), mock.patch(
                "snowflake_loader.main_load_run.enforce_completion_gate", return_value=gate_summary
            ), mock.patch("snowflake_loader.main_load_run.ensure_required_snowflake_env"), mock.patch(
                "snowflake_loader.main_load_run.SnowflakeSession.connect_from_config", return_value=_SessionContext()
            ), mock.patch("snowflake_loader.main_load_run.fetch_loaded_file_paths", return_value=set()), mock.patch(
                "snowflake_loader.main_load_run.filter_pending_files", side_effect=lambda all_files, loaded_file_paths: list(all_files)
            ), mock.patch("snowflake_loader.main_load_run.upload_dataset_files"), mock.patch(
                "snowflake_loader.main_load_run.copy_pending_files_for_family",
                side_effect=lambda **kwargs: CopyIntoSummary(
                    dataset_family=kwargs["dataset_family"],
                    attempted_files=len(kwargs["pending_files"]),
                    skipped_files=0,
                    loaded_files=len(kwargs["pending_files"]),
                    loaded_rows=sum(item.row_count for item in kwargs["pending_files"]),
                ),
            ) as mock_copy, mock.patch(
                "snowflake_loader.main_load_run.snowpipe_load_pending_files_for_family"
            ) as mock_snowpipe, mock.patch(
                "snowflake_loader.main_load_run.run_parity_checks", return_value=parity
            ), mock.patch("sys.stdout", new_callable=io.StringIO):
                code = main(["--run-root", str(run_root), "--load-mode", "copy"])

        self.assertEqual(code, 0)
        self.assertEqual(mock_copy.call_count, len(DATASET_FAMILIES))
        mock_snowpipe.assert_not_called()

    def test_main_snowpipe_mode_uses_snowpipe_path(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            run_root = Path(tempdir) / "run_snowpipe"
            run_root.mkdir(parents=True, exist_ok=True)
            manifest = _build_manifest(run_root)
            config = _build_config(run_root, dry_run=False)
            gate_summary = _gate_summary()
            parity = _parity_summary()

            with mock.patch("snowflake_loader.main_load_run.build_loader_config", return_value=config), mock.patch(
                "snowflake_loader.main_load_run.discover_run_manifest", return_value=manifest
            ), mock.patch("snowflake_loader.main_load_run.resolve_state_db_path", return_value=run_root / "state" / "run.db"), mock.patch(
                "snowflake_loader.main_load_run.enforce_completion_gate", return_value=gate_summary
            ), mock.patch("snowflake_loader.main_load_run.ensure_required_snowflake_env"), mock.patch(
                "snowflake_loader.main_load_run.SnowflakeSession.connect_from_config", return_value=_SessionContext()
            ), mock.patch("snowflake_loader.main_load_run.fetch_loaded_file_paths", return_value=set()), mock.patch(
                "snowflake_loader.main_load_run.filter_pending_files", side_effect=lambda all_files, loaded_file_paths: list(all_files)
            ), mock.patch("snowflake_loader.main_load_run.upload_dataset_files"), mock.patch(
                "snowflake_loader.main_load_run.copy_pending_files_for_family"
            ) as mock_copy, mock.patch(
                "snowflake_loader.main_load_run.snowpipe_load_pending_files_for_family",
                side_effect=lambda **kwargs: SnowpipeSummary(
                    dataset_family=kwargs["dataset_family"],
                    attempted_files=len(kwargs["pending_files"]),
                    loaded_files=len(kwargs["pending_files"]),
                    failed_files=0,
                    timed_out_files=0,
                    loaded_rows=sum(item.row_count for item in kwargs["pending_files"]),
                ),
            ) as mock_snowpipe, mock.patch(
                "snowflake_loader.main_load_run.run_parity_checks", return_value=parity
            ), mock.patch("sys.stdout", new_callable=io.StringIO):
                code = main(["--run-root", str(run_root), "--load-mode", "snowpipe"])

        self.assertEqual(code, 0)
        self.assertEqual(mock_snowpipe.call_count, len(DATASET_FAMILIES))
        mock_copy.assert_not_called()
        called_pipe_names = [call.kwargs["pipe_name"] for call in mock_snowpipe.call_args_list]
        expected_pipe_names = [config.objects.pipe_names[family] for family in DATASET_FAMILIES]
        self.assertEqual(called_pipe_names, expected_pipe_names)


def _build_config(run_root: Path, *, dry_run: bool) -> LoaderConfig:
    return LoaderConfig(
        run_root=run_root,
        run_tag=run_root.name,
        state_db_path=None,
        dry_run=dry_run,
        maturity_hours=24,
        strict_completion_gate=True,
        load_invocation_id="load_test",
        auth=SnowflakeAuthConfig(
            account="acct",
            user="user",
            password="pwd",
            role="role",
            warehouse="wh",
            database="db",
            schema="schema",
        ),
        objects=SnowflakeObjectConfig(),
    )


def _build_manifest(run_root: Path) -> RunManifest:
    files_by_family: dict[str, tuple[ManifestFile, ...]] = {}
    for family in DATASET_FAMILIES:
        path = run_root / family / "rid" / f"{family}_000001.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        files_by_family[family] = (ManifestFile(family, "rid", path, row_count=1, byte_size=1),)
    return RunManifest(run_root=run_root, run_tag=run_root.name, files_by_family=files_by_family)


def _gate_summary() -> CompletionGateSummary:
    return CompletionGateSummary(
        capture_run_id="rid",
        hydration=HydrationCheckResult(
            capture_run_id="rid",
            capture_run_status="completed",
            capture_completed=True,
            total_rows=1,
            all_rows_mature=True,
            mature_pending_retryable=0,
            claimed_in_flight=0,
            maturity_hours=24,
            cutoff_utc_iso="2026-04-01T00:00:00+00:00",
            is_complete=True,
        ),
        actor=ActorCheckResult(
            actor_rows_total=1,
            pending_retryable=0,
            claimed_in_flight=0,
            is_complete=True,
            skipped=False,
            skip_reason=None,
        ),
    )


def _parity_summary() -> ParitySummary:
    return ParitySummary(
        dataset_results=tuple(
            DatasetParityResult(
                dataset_family=family,
                local_file_count=1,
                local_row_count=1,
                stage_file_count=1,
                stage_row_count=1,
                landing_row_count=1,
                landing_distinct_business_keys=1,
                parity_pass=True,
            )
            for family in DATASET_FAMILIES
        )
    )


if __name__ == "__main__":
    unittest.main()
