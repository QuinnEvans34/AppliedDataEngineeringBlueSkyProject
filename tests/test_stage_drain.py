from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bluesky_pipeline.state.sqlite_store import SQLiteStore


class StageDrainScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "state.db"
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script_path = self.repo_root / "scripts" / "ops" / "stage_drain.py"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script_path), *args],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
        )

    def _seed_capture_post(
        self,
        *,
        capture_run_id: str,
        uri: str,
        captured_at: str,
        repo_did: str = "did:plc:test",
        hydration_status: str = "pending",
        complete_capture_run: bool = False,
    ) -> None:
        with SQLiteStore(self.db_path) as store:
            store.ensure_schema()
            if store.get_capture_run(capture_run_id) is None:
                store.create_capture_run(target_post_count=10, capture_run_id=capture_run_id)

            store.insert_captured_post(
                uri=uri,
                capture_run_id=capture_run_id,
                repo_did=repo_did,
                rkey=uri.rsplit("/", 1)[-1],
                cid_at_capture=f"cid_{uri.rsplit('/', 1)[-1]}",
                seq=1,
                record_created_at=captured_at,
                captured_at=captured_at,
                capture_file_id=None,
            )

            conn = store.connect()
            conn.execute(
                "UPDATE captured_posts SET hydration_status = ? WHERE uri = ?",
                (hydration_status, uri),
            )
            conn.commit()

            if complete_capture_run:
                store.complete_capture_run(capture_run_id)

    def test_check_hydration_incomplete_when_mature_pending_rows_exist(self) -> None:
        capture_run_id = "cap_pending"
        self._seed_capture_post(
            capture_run_id=capture_run_id,
            uri="at://did:plc:test/app.bsky.feed.post/a",
            captured_at="2026-01-01T00:00:00+00:00",
            hydration_status="pending",
            complete_capture_run=True,
        )

        result = self._run_script(
            "check-hydration",
            "--db-path",
            str(self.db_path),
            "--capture-run-id",
            capture_run_id,
            "--maturity-hours",
            "24",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("HYDRATION_COMPLETE=0", result.stdout)
        self.assertIn("mature_pending_retryable=1", result.stdout)

    def test_check_hydration_complete_when_all_conditions_pass(self) -> None:
        capture_run_id = "cap_complete"
        self._seed_capture_post(
            capture_run_id=capture_run_id,
            uri="at://did:plc:test/app.bsky.feed.post/b",
            captured_at="2026-01-01T00:00:00+00:00",
            hydration_status="hydrated",
            complete_capture_run=True,
        )

        result = self._run_script(
            "check-hydration",
            "--db-path",
            str(self.db_path),
            "--capture-run-id",
            capture_run_id,
            "--maturity-hours",
            "24",
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("HYDRATION_COMPLETE=1", result.stdout)
        self.assertIn("claimed_in_flight=0", result.stdout)

    def test_check_actor_incomplete_and_complete_paths(self) -> None:
        capture_run_id = "cap_actor"
        did = "did:plc:actor"
        uri = "at://did:plc:actor/app.bsky.feed.post/a"
        self._seed_capture_post(
            capture_run_id=capture_run_id,
            uri=uri,
            captured_at="2026-01-01T00:00:00+00:00",
            repo_did=did,
            hydration_status="hydrated",
            complete_capture_run=True,
        )

        with SQLiteStore(self.db_path) as store:
            store.seed_actor_dids_from_hydrated_then_captured()

        incomplete = self._run_script(
            "check-actor",
            "--db-path",
            str(self.db_path),
        )
        self.assertEqual(incomplete.returncode, 1)
        self.assertIn("ACTOR_COMPLETE=0", incomplete.stdout)
        self.assertIn("pending_retryable=1", incomplete.stdout)

        with SQLiteStore(self.db_path) as store:
            conn = store.connect()
            conn.execute(
                """
                UPDATE actor_profiles_state
                SET enrichment_status = 'enriched',
                    claimed_by_worker = NULL,
                    claim_expires_at = NULL
                WHERE did = ?
                """,
                (did,),
            )
            conn.commit()

        complete = self._run_script(
            "check-actor",
            "--db-path",
            str(self.db_path),
        )
        self.assertEqual(complete.returncode, 0)
        self.assertIn("ACTOR_COMPLETE=1", complete.stdout)
        self.assertIn("pending_retryable=0", complete.stdout)


if __name__ == "__main__":
    unittest.main()
