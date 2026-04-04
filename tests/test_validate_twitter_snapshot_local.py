from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import ModuleType

import pandas as pd


def _load_validation_module() -> ModuleType:
    module_path = Path("scripts/validate_twitter_snapshot_local.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "validate_twitter_snapshot_local", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load validate_twitter_snapshot_local module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class ValidateTwitterSnapshotLocalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_validation_module()

    def _create_fixture(
        self,
        *,
        full_rows: int = 5,
        sample_rows: int | None = None,
        metadata_override: dict[str, object] | None = None,
        invalid_metadata_json: bool = False,
        remove_sample_csv: bool = False,
    ) -> tuple[Path, Path, Path, Path]:
        root = Path(tempfile.mkdtemp())
        full = root / "twitter_trending_full.parquet"
        meta = root / "twitter_trending_snapshot_metadata.json"
        sample_parquet = root / "twitter_trending_sample_1000.parquet"
        sample_csv = root / "twitter_trending_sample_1000.csv"

        df = pd.DataFrame(
            {
                "num_hours": [1 + i for i in range(full_rows)],
                "date": [date(2024, 1, min(28, i + 1)) for i in range(full_rows)],
                "name": [f"topic_{i}" for i in range(full_rows)],
                "counts": [float(1000 + i) for i in range(full_rows)],
            }
        )
        df.to_parquet(full, index=False)

        srows = sample_rows if sample_rows is not None else min(1000, len(df))
        sample_df = df.head(srows).copy()
        sample_df.to_parquet(sample_parquet, index=False)
        sample_df.to_csv(sample_csv, index=False)

        metadata: dict[str, object] = {
            "source_table": "DAILY_TWITTER_TOP_TRENDS.DIESEL.TWITTER_TRENDING",
            "extraction_started_at_utc": "2026-04-04T00:00:00+00:00",
            "extraction_completed_at_utc": "2026-04-04T00:01:00+00:00",
            "row_count": len(df),
            "column_names": list(df.columns),
            "column_dtypes": {column: str(dtype) for column, dtype in df.dtypes.items()},
            "local_file_path": str(full.resolve()),
            "sample_file_paths": {
                "parquet": str(sample_parquet.resolve()),
                "csv": str(sample_csv.resolve()),
            },
        }
        if metadata_override:
            metadata.update(metadata_override)

        if invalid_metadata_json:
            meta.write_text("{invalid_json", encoding="utf-8")
        else:
            meta.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        if remove_sample_csv:
            sample_csv.unlink()

        return full, meta, sample_parquet, sample_csv

    def test_missing_artifact_is_blocking(self) -> None:
        full, meta, sample_parquet, sample_csv = self._create_fixture(remove_sample_csv=True)
        report = self.module.validate_local_snapshot(
            full_parquet_path=full,
            metadata_json_path=meta,
            sample_parquet_path=sample_parquet,
            sample_csv_path=sample_csv,
            run_env_preflight=False,
        )
        self.assertFalse(report["overall_pass"])
        self.assertIn("missing_file:sample_csv", report["blocking_issues"])

    def test_invalid_metadata_json_is_blocking(self) -> None:
        full, meta, sample_parquet, sample_csv = self._create_fixture(invalid_metadata_json=True)
        report = self.module.validate_local_snapshot(
            full_parquet_path=full,
            metadata_json_path=meta,
            sample_parquet_path=sample_parquet,
            sample_csv_path=sample_csv,
            run_env_preflight=False,
        )
        self.assertFalse(report["overall_pass"])
        self.assertIn("metadata_json_parse_failed", report["blocking_issues"])

    def test_metadata_parquet_row_count_mismatch_is_blocking(self) -> None:
        full, meta, sample_parquet, sample_csv = self._create_fixture(
            metadata_override={"row_count": 999}
        )
        report = self.module.validate_local_snapshot(
            full_parquet_path=full,
            metadata_json_path=meta,
            sample_parquet_path=sample_parquet,
            sample_csv_path=sample_csv,
            run_env_preflight=False,
        )
        self.assertFalse(report["overall_pass"])
        self.assertIn("metadata_row_count_mismatch", report["blocking_issues"])

    def test_sample_row_count_mismatch_is_blocking(self) -> None:
        full, meta, sample_parquet, sample_csv = self._create_fixture(full_rows=5, sample_rows=3)
        report = self.module.validate_local_snapshot(
            full_parquet_path=full,
            metadata_json_path=meta,
            sample_parquet_path=sample_parquet,
            sample_csv_path=sample_csv,
            run_env_preflight=False,
        )
        self.assertFalse(report["overall_pass"])
        self.assertIn("sample_parquet_row_count_mismatch", report["blocking_issues"])
        self.assertIn("sample_csv_row_count_mismatch", report["blocking_issues"])

    def test_row_level_comparison_handles_date_representation_difference(self) -> None:
        full, meta, sample_parquet, sample_csv = self._create_fixture(full_rows=5, sample_rows=5)
        report = self.module.validate_local_snapshot(
            full_parquet_path=full,
            metadata_json_path=meta,
            sample_parquet_path=sample_parquet,
            sample_csv_path=sample_csv,
            run_env_preflight=False,
        )
        self.assertTrue(
            report["consistency"]["sample_vs_snapshot"][
                "sample_csv_rows_match_snapshot_prefix"
            ]
        )
        self.assertTrue(report["overall_pass"])

    def test_metadata_path_mismatch_is_warning_not_blocking(self) -> None:
        full, meta, sample_parquet, sample_csv = self._create_fixture(
            metadata_override={
                "local_file_path": "/tmp/somewhere_else/twitter_trending_full.parquet",
                "sample_file_paths": {
                    "parquet": "/tmp/somewhere_else/sample.parquet",
                    "csv": "/tmp/somewhere_else/sample.csv",
                },
            }
        )
        report = self.module.validate_local_snapshot(
            full_parquet_path=full,
            metadata_json_path=meta,
            sample_parquet_path=sample_parquet,
            sample_csv_path=sample_csv,
            run_env_preflight=False,
        )
        self.assertTrue(report["overall_pass"])
        self.assertIn("metadata_local_file_path_mismatch", report["warnings"])
        self.assertIn("metadata_sample_parquet_path_mismatch", report["warnings"])
        self.assertIn("metadata_sample_csv_path_mismatch", report["warnings"])


if __name__ == "__main__":
    unittest.main()

