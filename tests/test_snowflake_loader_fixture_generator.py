from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from snowflake_loader.fixture_generator import generate_fixture_run


class FixtureGeneratorTests(unittest.TestCase):
    def test_generate_fixture_run_writes_exact_rows_for_all_families(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            source_root = Path(tempdir) / "source"
            output_root = Path(tempdir) / "output" / "w2_fixture_25"

            self._write_rows(source_root / "phase6" / "raw_posts" / "cap" / "raw_posts_000001.jsonl.gz", 25, "uri")
            self._write_rows(source_root / "phase6" / "hydrated_posts" / "hyd" / "hydrated_posts_000001.jsonl.gz", 25, "uri")
            self._write_rows(source_root / "phase5" / "actor_profiles" / "act" / "actor_profiles_000001.jsonl.gz", 21, "did")
            self._write_rows(source_root / "phase5" / "hydration_misses" / "hyd" / "hydration_misses_000001.jsonl.gz", 1, "uri")

            summary = generate_fixture_run(
                source_root=source_root,
                output_run_root=output_root,
                rows_per_family=25,
                run_id="fixture_25",
            )

            self.assertEqual(summary.rows_per_family, 25)
            self.assertEqual(len(summary.families), 4)

            for item in summary.families:
                rows = self._read_rows(Path(item.output_file))
                self.assertEqual(len(rows), 25)
                self.assertEqual(item.generated_rows, 25)

            actor_file = output_root / "actor_profiles" / "fixture_25" / "actor_profiles_000001.jsonl.gz"
            actor_rows = self._read_rows(actor_file)
            self.assertEqual(actor_rows[0]["did"], "did_000001")
            self.assertEqual(actor_rows[20]["did"], "did_000021")
            self.assertEqual(actor_rows[21]["did"], "did_000001")

            miss_file = output_root / "hydration_misses" / "fixture_25" / "hydration_misses_000001.jsonl.gz"
            miss_rows = self._read_rows(miss_file)
            self.assertTrue(all(row["uri"] == "uri_000001" for row in miss_rows))

    def test_generate_fixture_run_raises_when_family_has_no_source_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            source_root = Path(tempdir) / "source"
            output_root = Path(tempdir) / "output" / "w2_fixture_25"
            self._write_rows(source_root / "raw_posts" / "cap" / "raw_posts_000001.jsonl.gz", 1, "uri")

            with self.assertRaises(ValueError):
                generate_fixture_run(
                    source_root=source_root,
                    output_run_root=output_root,
                    rows_per_family=25,
                    run_id="fixture_25",
                )

    def _write_rows(self, path: Path, count: int, key: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for i in range(1, count + 1):
                handle.write(json.dumps({key: f"{key}_{i:06d}", "n": i}) + "\n")

    def _read_rows(self, path: Path) -> list[dict[str, object]]:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


if __name__ == "__main__":
    unittest.main()
