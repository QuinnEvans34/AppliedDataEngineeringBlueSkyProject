from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from bluesky_pipeline.inspect.exporter import export_sample_rows
from bluesky_pipeline.inspect.profiler import profile_dataset


def _write_jsonl_gz(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def _raw_row(has_reply: bool) -> dict[str, object]:
    return {
        "capture_run_id": "cap_test",
        "seq": 1,
        "repo_did": "did:plc:test",
        "event_time": "2026-04-01T00:00:00Z",
        "operation": "create",
        "collection": "app.bsky.feed.post",
        "rkey": "abc",
        "uri": "at://did:plc:test/app.bsky.feed.post/abc",
        "cid": "bafy...",
        "record_created_at": "2026-04-01T00:00:00Z",
        "has_reply": has_reply,
        "has_embed": False,
        "captured_at": "2026-04-01T00:00:01+00:00",
        "record": {"$type": "app.bsky.feed.post", "text": "hello"},
    }


class InspectExporterProfilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.input_path = self.root / "raw_posts" / "part1.jsonl.gz"
        _write_jsonl_gz(self.input_path, [_raw_row(False), _raw_row(True)])

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_export_sample_jsonl(self) -> None:
        out_path = self.root / "exports" / "sample.jsonl"

        result = export_sample_rows(self.input_path, out_path, limit=1, tail=False)

        self.assertEqual(result.output_format, "jsonl")
        self.assertEqual(result.row_count, 1)
        lines = out_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_export_sample_json(self) -> None:
        out_path = self.root / "exports" / "sample.json"

        result = export_sample_rows(self.input_path, out_path, limit=2, tail=False)

        self.assertEqual(result.output_format, "json")
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload), 2)

    def test_profile_dataset(self) -> None:
        result = profile_dataset(str(self.root / "raw_posts"), dataset="auto", top_k=5)

        self.assertEqual(result.dataset, "raw")
        self.assertEqual(result.files_count, 1)
        self.assertEqual(result.rows_count, 2)
        self.assertEqual(result.missing_required_rows, 0)
        self.assertIn("has_reply", result.field_distributions)
        self.assertEqual(result.field_distributions["has_reply"]["False"], 1)
        self.assertEqual(result.field_distributions["has_reply"]["True"], 1)


if __name__ == "__main__":
    unittest.main()

