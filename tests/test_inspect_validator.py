from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from bluesky_pipeline.inspect.validator import resolve_dataset_type, validate_required_fields


def _write_jsonl_gz(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def _raw_row() -> dict[str, object]:
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
        "has_reply": False,
        "has_embed": False,
        "captured_at": "2026-04-01T00:00:01+00:00",
        "record": {"$type": "app.bsky.feed.post", "text": "hello"},
    }


class InspectValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_resolve_dataset_from_path_marker(self) -> None:
        path = self.root / "raw_posts" / "part1.jsonl.gz"
        _write_jsonl_gz(path, [_raw_row()])

        resolved = resolve_dataset_type(self.root / "raw_posts", dataset="auto")

        self.assertEqual(resolved, "raw")

    def test_resolve_dataset_from_row_shape_fallback(self) -> None:
        path = self.root / "unknown_location" / "part1.jsonl.gz"
        _write_jsonl_gz(path, [_raw_row()])

        resolved = resolve_dataset_type(path, dataset="auto")

        self.assertEqual(resolved, "raw")

    def test_validate_required_fields_success(self) -> None:
        path = self.root / "raw_posts" / "part1.jsonl.gz"
        _write_jsonl_gz(path, [_raw_row()])

        result = validate_required_fields(path, dataset="auto")

        self.assertTrue(result.success)
        self.assertEqual(result.rows_checked, 1)
        self.assertEqual(result.missing_field_rows, 0)

    def test_validate_required_fields_failure(self) -> None:
        path = self.root / "raw_posts" / "part1.jsonl.gz"
        bad_row = _raw_row()
        bad_row.pop("cid")
        _write_jsonl_gz(path, [bad_row])

        result = validate_required_fields(path, dataset="auto")

        self.assertFalse(result.success)
        self.assertEqual(result.rows_checked, 1)
        self.assertEqual(result.missing_field_rows, 1)
        self.assertEqual(result.issues[0].missing_fields, ("cid",))


if __name__ == "__main__":
    unittest.main()

