from __future__ import annotations

import gzip
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from bluesky_pipeline.main_inspect import main


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


class MainInspectCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.good_dir = self.root / "raw_posts" / "cap_test"
        _write_jsonl_gz(self.good_dir / "raw_posts_000001.jsonl.gz", [_raw_row()])

        bad_row = _raw_row()
        bad_row.pop("cid")
        self.bad_dir = self.root / "bad_raw"
        _write_jsonl_gz(self.bad_dir / "bad.jsonl.gz", [bad_row])

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(argv)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_files_command(self) -> None:
        exit_code, stdout, _ = self._run_cli(
            ["files", "--input", str(self.root / "raw_posts")]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("TOTAL files=1 rows=1", stdout)

    def test_show_command(self) -> None:
        exit_code, stdout, _ = self._run_cli(
            ["show", "--input", str(self.root / "raw_posts"), "--limit", "1", "--pretty"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("dataset=raw rows_shown=1", stdout)
        self.assertIn('"capture_run_id": "cap_test"', stdout)

    def test_export_command(self) -> None:
        output_path = self.root / "exports" / "sample.json"
        exit_code, stdout, _ = self._run_cli(
            [
                "export",
                "--input",
                str(self.root / "raw_posts"),
                "--output",
                str(output_path),
                "--limit",
                "1",
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("exported_rows=1", stdout)
        self.assertTrue(output_path.exists())

    def test_validate_command_strict_exit_codes(self) -> None:
        good_code, good_stdout, _ = self._run_cli(
            ["validate", "--input", str(self.root / "raw_posts")]
        )
        bad_code, bad_stdout, _ = self._run_cli(
            ["validate", "--input", str(self.bad_dir), "--dataset", "raw"]
        )

        self.assertEqual(good_code, 0)
        self.assertIn("missing_field_rows=0", good_stdout)
        self.assertEqual(bad_code, 1)
        self.assertIn("missing_field_rows=1", bad_stdout)

    def test_profile_command(self) -> None:
        exit_code, stdout, _ = self._run_cli(
            ["profile", "--input", str(self.root / "raw_posts"), "--top-k", "3"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn('"dataset": "raw"', stdout)
        self.assertIn('"rows_count": 1', stdout)


if __name__ == "__main__":
    unittest.main()

