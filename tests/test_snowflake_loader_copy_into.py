from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from snowflake_loader.copy_into import fetch_loaded_file_paths, filter_pending_files
from snowflake_loader.manifest import ManifestFile


class _FakeSession:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params: tuple[object, ...]):
        self.calls.append((sql, params))
        return self.rows


class SnowflakeLoaderCopyIntoTests(unittest.TestCase):
    def test_fetch_loaded_file_paths_and_filter_pending(self) -> None:
        session = _FakeSession(rows=[("/tmp/a.jsonl.gz",)])
        loaded = fetch_loaded_file_paths(
            session=session,  # type: ignore[arg-type]
            manifest_table_name="LOADER_FILE_MANIFEST",
            dataset_family="raw_posts",
            run_tag="run_1",
        )

        self.assertEqual(loaded, {"/tmp/a.jsonl.gz"})
        self.assertEqual(len(session.calls), 1)

        with tempfile.TemporaryDirectory() as tempdir:
            a = Path(tempdir) / "a.jsonl.gz"
            b = Path(tempdir) / "b.jsonl.gz"
            a.write_text("", encoding="utf-8")
            b.write_text("", encoding="utf-8")

            files = [
                ManifestFile("raw_posts", "cap", a, row_count=1, byte_size=1),
                ManifestFile("raw_posts", "cap", b, row_count=1, byte_size=1),
            ]
            pending = filter_pending_files(files, {str(a)})
            self.assertEqual([item.local_path for item in pending], [b])


if __name__ == "__main__":
    unittest.main()
