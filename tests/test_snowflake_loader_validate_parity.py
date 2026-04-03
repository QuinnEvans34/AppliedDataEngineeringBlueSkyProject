from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowflake_loader.manifest import discover_run_manifest
from snowflake_loader.validate_load import run_parity_checks


class _NoopSession:
    pass


class SnowflakeLoaderParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.run_root = Path(self.tempdir.name) / "run_parity"
        self.run_root.mkdir(parents=True, exist_ok=True)

        self._write(self.run_root / "raw_posts" / "cap1" / "raw_posts_000001.jsonl.gz", {"uri": "u1"})
        self._write(self.run_root / "hydrated_posts" / "hyd1" / "hydrated_posts_000001.jsonl.gz", {"uri": "u1"})
        self._write(self.run_root / "hydration_misses" / "hyd1" / "hydration_misses_000001.jsonl.gz", {"uri": "u2"})
        self._write(self.run_root / "actor_profiles" / "act1" / "actor_profiles_000001.jsonl.gz", {"did": "d1"})

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write(self, path: Path, row: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def test_parity_summary_flags_mismatched_family(self) -> None:
        manifest = discover_run_manifest(self.run_root)

        def stage_file_count(*, stage_name: str, **_: object) -> int:
            if "RAW" in stage_name:
                return 2  # force mismatch on raw
            return 1

        with mock.patch(
            "snowflake_loader.validate_load._query_stage_file_count",
            side_effect=stage_file_count,
        ), mock.patch(
            "snowflake_loader.validate_load._query_stage_row_count",
            side_effect=lambda **_: 1,
        ), mock.patch(
            "snowflake_loader.validate_load._query_landing_row_count",
            side_effect=lambda **_: 1,
        ), mock.patch(
            "snowflake_loader.validate_load._query_landing_distinct_business_keys",
            side_effect=lambda **_: 1,
        ):
            summary = run_parity_checks(
                session=_NoopSession(),  # type: ignore[arg-type]
                manifest=manifest,
                stage_names={
                    "raw_posts": "BLUESKY_RAW_POSTS_STAGE",
                    "hydrated_posts": "BLUESKY_HYDRATED_POSTS_STAGE",
                    "hydration_misses": "BLUESKY_HYDRATION_MISSES_STAGE",
                    "actor_profiles": "BLUESKY_ACTOR_PROFILES_STAGE",
                },
                landing_table_names={
                    "raw_posts": "LANDING_RAW_POSTS",
                    "hydrated_posts": "LANDING_HYDRATED_POSTS",
                    "hydration_misses": "LANDING_HYDRATION_MISSES",
                    "actor_profiles": "LANDING_ACTOR_PROFILES",
                },
                file_format_name="BLUESKY_JSONL_GZ",
            )

        by_family = {item.dataset_family: item for item in summary.dataset_results}
        self.assertFalse(by_family["raw_posts"].parity_pass)
        self.assertTrue(by_family["hydrated_posts"].parity_pass)
        self.assertFalse(summary.all_pass)


if __name__ == "__main__":
    unittest.main()
