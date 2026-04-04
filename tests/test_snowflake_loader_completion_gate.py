from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from snowflake_loader.manifest import discover_run_manifest
from snowflake_loader.validate_load import enforce_completion_gate


class SnowflakeLoaderCompletionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.run_root = Path(self.tempdir.name) / "run_gate"
        self.state_dir = self.run_root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "run.db"

        self._write_raw_file()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_raw_file(self) -> None:
        path = self.run_root / "raw_posts" / "cap_gate" / "raw_posts_000001.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps({"uri": "at://did:plc:test/app.bsky.feed.post/1"}) + "\n")

    def _write_actor_file(self) -> None:
        path = self.run_root / "actor_profiles" / "act_gate" / "actor_profiles_000001.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps({"did": "did:plc:test"}) + "\n")

    def _seed_db(self, *, actor_pending: bool, include_actor_table: bool = True) -> None:
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        try:
            schema_sql = """
            CREATE TABLE capture_runs (
                capture_run_id TEXT PRIMARY KEY,
                status TEXT,
                started_at TEXT,
                completed_at TEXT
            );
            CREATE TABLE captured_posts (
                uri TEXT PRIMARY KEY,
                capture_run_id TEXT,
                captured_at TEXT,
                hydration_status TEXT
            );
            """
            if include_actor_table:
                schema_sql += """
                CREATE TABLE actor_profiles_state (
                    did TEXT PRIMARY KEY,
                    enrichment_status TEXT
                );
                """
            conn.executescript(schema_sql)
            conn.execute(
                "INSERT INTO capture_runs (capture_run_id, status, started_at, completed_at) VALUES (?, 'completed', '2026-04-01T00:00:00+00:00', '2026-04-01T01:00:00+00:00')",
                ("cap_gate",),
            )
            conn.execute(
                "INSERT INTO captured_posts (uri, capture_run_id, captured_at, hydration_status) VALUES (?, ?, ?, 'hydrated')",
                (
                    "at://did:plc:test/app.bsky.feed.post/1",
                    "cap_gate",
                    "2026-04-01T00:00:00+00:00",
                ),
            )
            if include_actor_table:
                conn.execute(
                    "INSERT INTO actor_profiles_state (did, enrichment_status) VALUES (?, ?)",
                    ("did:plc:test", "pending" if actor_pending else "enriched"),
                )
            conn.commit()
        finally:
            conn.close()

    def test_completion_gate_passes_when_hydration_and_actor_are_complete(self) -> None:
        self._seed_db(actor_pending=False)
        manifest = discover_run_manifest(self.run_root)

        summary = enforce_completion_gate(
            manifest=manifest,
            state_db_path=self.db_path,
            maturity_hours=24,
        )

        self.assertEqual(summary.capture_run_id, "cap_gate")
        self.assertTrue(summary.hydration.is_complete)
        self.assertTrue(summary.actor.is_complete)

    def test_completion_gate_fails_when_actor_rows_are_pending(self) -> None:
        self._write_actor_file()
        self._seed_db(actor_pending=True)
        manifest = discover_run_manifest(self.run_root)

        with self.assertRaises(RuntimeError):
            enforce_completion_gate(
                manifest=manifest,
                state_db_path=self.db_path,
                maturity_hours=24,
            )

    def test_completion_gate_skips_actor_when_actor_files_are_absent(self) -> None:
        self._seed_db(actor_pending=False, include_actor_table=False)
        manifest = discover_run_manifest(self.run_root)

        summary = enforce_completion_gate(
            manifest=manifest,
            state_db_path=self.db_path,
            maturity_hours=24,
        )

        self.assertTrue(summary.actor.is_complete)
        self.assertTrue(summary.actor.skipped)
        self.assertIsNotNone(summary.actor.skip_reason)


if __name__ == "__main__":
    unittest.main()
