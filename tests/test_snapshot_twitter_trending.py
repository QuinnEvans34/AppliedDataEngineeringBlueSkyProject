from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

from scripts import snapshot_twitter_trending as snapshot


class _FakeCursor:
    def __init__(self) -> None:
        self.execute_calls: list[str] = []
        self.sfqid = "fake_query_id_123"

    def execute(self, query: str) -> None:
        self.execute_calls.append(query)

    def fetch_arrow_batches(self):
        table1 = pa.table(
            {
                "id": pa.array([1, 2], type=pa.int64()),
                "topic": pa.array(["a", "b"], type=pa.string()),
            }
        )
        table2 = pa.table(
            {
                "id": pa.array([3], type=pa.int64()),
                "topic": pa.array(["c"], type=pa.string()),
            }
        )
        yield table1
        yield table2

    def close(self) -> None:
        return None


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


class SnapshotTwitterTrendingTests(unittest.TestCase):
    def test_snapshot_uses_single_query_and_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            full = root / "local/reference_snapshots/twitter_trending/twitter_trending_full.parquet"
            meta = root / "local/reference_snapshots/twitter_trending/twitter_trending_snapshot_metadata.json"
            sample_parquet = root / "data/samples/twitter_trending_sample_1000.parquet"
            sample_csv = root / "data/samples/twitter_trending_sample_1000.csv"

            fake_cursor = _FakeCursor()
            fake_conn = _FakeConnection(fake_cursor)

            env = {
                "SNOWFLAKE_ACCOUNT": "acct",
                "SNOWFLAKE_USER": "user",
                "SNOWFLAKE_PASSWORD": "pwd",
                "SNOWFLAKE_ROLE": "role",
                "SNOWFLAKE_WAREHOUSE": "wh",
                "SNOWFLAKE_DATABASE": "db",
                "SNOWFLAKE_SCHEMA": "schema",
            }

            with mock.patch.object(snapshot, "FULL_SNAPSHOT_PATH", full), mock.patch.object(
                snapshot, "METADATA_PATH", meta
            ), mock.patch.object(snapshot, "SAMPLE_PARQUET_PATH", sample_parquet), mock.patch.object(
                snapshot, "SAMPLE_CSV_PATH", sample_csv
            ), mock.patch(
                "scripts.snapshot_twitter_trending.snowflake.connector.connect",
                return_value=fake_conn,
            ), mock.patch.dict("os.environ", env, clear=False):
                rc = snapshot.main([])

            self.assertEqual(rc, 0)
            self.assertEqual(
                fake_cursor.execute_calls,
                [f"SELECT * FROM {snapshot.DEFAULT_SOURCE_TABLE}"],
            )
            self.assertTrue(fake_conn.closed)
            self.assertTrue(full.exists())
            self.assertTrue(meta.exists())
            self.assertTrue(sample_parquet.exists())
            self.assertTrue(sample_csv.exists())

            full_tbl = pq.read_table(full)
            sample_tbl = pq.read_table(sample_parquet)
            self.assertEqual(full_tbl.num_rows, 3)
            self.assertEqual(sample_tbl.num_rows, 3)

            metadata = json.loads(meta.read_text(encoding="utf-8"))
            self.assertEqual(metadata["query_count"], 1)
            self.assertEqual(metadata["row_count"], 3)
            self.assertEqual(metadata["column_names"], ["id", "topic"])


if __name__ == "__main__":
    unittest.main()
