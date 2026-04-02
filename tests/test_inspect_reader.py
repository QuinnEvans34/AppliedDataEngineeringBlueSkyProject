from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from bluesky_pipeline.inspect.reader import discover_data_files, iter_row_records


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def _write_jsonl_gz(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


class InspectReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_discover_data_files_directory_sorted(self) -> None:
        _write_jsonl(self.root / "b.jsonl", [{"a": 1}])
        _write_jsonl_gz(self.root / "a.jsonl.gz", [{"a": 2}])
        _write_jsonl(self.root / "ignore.jsonl.tmp", [{"a": 3}])
        (self.root / "notes.txt").write_text("nope", encoding="utf-8")

        discovered = discover_data_files(self.root)

        self.assertEqual([path.name for path in discovered], ["a.jsonl.gz", "b.jsonl"])

    def test_iter_row_records_includes_source_metadata(self) -> None:
        _write_jsonl(self.root / "raw_posts" / "part1.jsonl", [{"x": 1}, {"x": 2}])
        _write_jsonl_gz(self.root / "raw_posts" / "part2.jsonl.gz", [{"x": 3}])

        rows = list(iter_row_records(self.root / "raw_posts"))

        self.assertEqual([row.data["x"] for row in rows], [1, 2, 3])
        self.assertEqual([row.row_index for row in rows], [1, 2, 3])
        self.assertEqual(rows[0].line_number, 1)
        self.assertEqual(rows[1].line_number, 2)

    def test_iter_row_records_invalid_json_raises(self) -> None:
        path = self.root / "broken.jsonl"
        path.write_text('{"a":1}\nnot-json\n', encoding="utf-8")

        with self.assertRaises(ValueError):
            list(iter_row_records(path))


if __name__ == "__main__":
    unittest.main()

