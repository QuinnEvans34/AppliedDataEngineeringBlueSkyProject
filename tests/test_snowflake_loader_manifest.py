from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from snowflake_loader.manifest import discover_run_manifest


class SnowflakeLoaderManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.run_root = Path(self.tempdir.name) / "run_20260403"
        self.run_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_jsonl_gz(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")))
                handle.write("\n")

    def test_discovers_finalized_files_and_counts_rows(self) -> None:
        self._write_jsonl_gz(
            self.run_root / "raw_posts" / "cap_test" / "raw_posts_000001.jsonl.gz",
            [{"uri": "a"}, {"uri": "b"}],
        )
        self._write_jsonl_gz(
            self.run_root / "hydrated_posts" / "hyd_test" / "hydrated_posts_000001.jsonl.gz",
            [{"uri": "a"}],
        )
        self._write_jsonl_gz(
            self.run_root / "actor_profiles" / "act_test" / "actor_profiles_000001.jsonl.gz",
            [{"did": "did:plc:test"}],
        )

        # Should be ignored because it is not finalized.
        ignored = self.run_root / "raw_posts" / "cap_test" / "raw_posts_000002.jsonl.gz.tmp"
        ignored.parent.mkdir(parents=True, exist_ok=True)
        ignored.write_text("temp", encoding="utf-8")

        manifest = discover_run_manifest(self.run_root)

        self.assertEqual(manifest.run_tag, "run_20260403")
        self.assertEqual(manifest.total_file_count("raw_posts"), 1)
        self.assertEqual(manifest.total_row_count("raw_posts"), 2)
        self.assertEqual(manifest.total_file_count("hydrated_posts"), 1)
        self.assertEqual(manifest.total_row_count("hydrated_posts"), 1)
        self.assertEqual(manifest.total_file_count("hydration_misses"), 0)
        self.assertEqual(manifest.total_file_count("actor_profiles"), 1)
        self.assertEqual(manifest.run_ids_for_family("raw_posts"), {"cap_test"})


if __name__ == "__main__":
    unittest.main()
