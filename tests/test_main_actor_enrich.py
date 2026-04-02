from __future__ import annotations

import gzip
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bluesky_pipeline.actor.client import ActorBatchResult, ActorRequestError
from bluesky_pipeline.main_actor_enrich import main
from bluesky_pipeline.state.sqlite_store import SQLiteStore
from bluesky_pipeline.utils.time_utils import utc_now_iso


class MainActorEnrichIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "state.db"
        self.log_path = self.root / "actor_enrich.log"
        self.actor_dir = self.root / "actor_profiles"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _seed_capture_run(self, capture_run_id: str = "cap_test") -> str:
        with SQLiteStore(self.db_path) as store:
            store.ensure_schema()
            store.create_capture_run(target_post_count=100, capture_run_id=capture_run_id)
        return capture_run_id

    def _insert_post(
        self,
        *,
        capture_run_id: str,
        uri: str,
        did: str,
        hydration_status: str = "hydrated",
    ) -> None:
        now = utc_now_iso()
        with SQLiteStore(self.db_path) as store:
            store.insert_captured_post(
                uri=uri,
                capture_run_id=capture_run_id,
                repo_did=did,
                rkey=uri.rsplit("/", 1)[-1],
                cid_at_capture=f"cid_{uri.rsplit('/', 1)[-1]}",
                seq=1,
                record_created_at=now,
                captured_at=now,
                capture_file_id=None,
            )
            conn = store.connect()
            conn.execute(
                "UPDATE captured_posts SET hydration_status = ? WHERE uri = ?",
                (hydration_status, uri),
            )
            conn.commit()

    def _read_actor_statuses(self) -> dict[str, str]:
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("SELECT did, enrichment_status FROM actor_profiles_state").fetchall()
            return {did: status for did, status in rows}
        finally:
            conn.close()

    def _fetch_latest_actor_run_row(self) -> dict[str, object]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT actor_run_id, status, seeded_actor_count, eligible_actor_count,
                       enriched_actor_count, missing_actor_count, failed_actor_count
                FROM actor_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                raise AssertionError("No actor_run row found")
            return dict(row)
        finally:
            conn.close()

    def _count_jsonl_rows(self, directory: Path) -> int:
        total = 0
        for path in directory.glob("**/*.jsonl.gz"):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                total += sum(1 for _ in handle)
        return total

    def test_orchestration_partial_success_and_missing_escalation(self) -> None:
        capture_run_id = self._seed_capture_run("cap_partial")
        did_ok_1 = "did:plc:ok1"
        did_ok_2 = "did:plc:ok2"
        did_missing_terminal = "did:plc:missing"

        self._insert_post(
            capture_run_id=capture_run_id,
            uri="at://did:plc:ok1/app.bsky.feed.post/a",
            did=did_ok_1,
            hydration_status="hydrated",
        )
        self._insert_post(
            capture_run_id=capture_run_id,
            uri="at://did:plc:ok2/app.bsky.feed.post/b",
            did=did_ok_2,
            hydration_status="hydrated",
        )
        self._insert_post(
            capture_run_id=capture_run_id,
            uri="at://did:plc:missing/app.bsky.feed.post/c",
            did=did_missing_terminal,
            hydration_status="hydrated",
        )

        with SQLiteStore(self.db_path) as store:
            store.ensure_schema()
            store.seed_actor_dids_from_hydrated_then_captured()
            conn = store.connect()
            conn.execute(
                """
                UPDATE actor_profiles_state
                SET enrichment_status = 'retryable', enrichment_attempt_count = 2
                WHERE did = ?
                """,
                (did_missing_terminal,),
            )
            conn.commit()

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def chunk_dids(self, dids):
                yield list(dids)

            def get_profiles(self, dids):
                profiles = [
                    {
                        "did": did_ok_1,
                        "handle": "ok1.bsky.social",
                        "displayName": "OK 1",
                        "followersCount": 1,
                        "followsCount": 2,
                        "postsCount": 3,
                        "labels": [],
                    },
                    {
                        "did": did_ok_2,
                        "handle": "ok2.bsky.social",
                        "displayName": "OK 2",
                        "followersCount": 4,
                        "followsCount": 5,
                        "postsCount": 6,
                        "labels": [],
                    },
                ]
                missing = tuple(did for did in dids if did == did_missing_terminal)
                return ActorBatchResult(
                    requested_dids=tuple(dids),
                    profiles=tuple(profiles),
                    missing_dids=missing,
                )

        with mock.patch("bluesky_pipeline.main_actor_enrich.ActorClient", FakeClient):
            exit_code = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--log-path",
                    str(self.log_path),
                    "--actor-output-dir",
                    str(self.actor_dir),
                    "--claim-batch-size",
                    "10",
                    "--request-batch-size",
                    "25",
                    "--max-unresolved-attempts",
                    "3",
                ]
            )

        self.assertEqual(exit_code, 0)

        statuses = self._read_actor_statuses()
        self.assertEqual(statuses[did_ok_1], "enriched")
        self.assertEqual(statuses[did_ok_2], "enriched")
        self.assertEqual(statuses[did_missing_terminal], "missing")

        run_row = self._fetch_latest_actor_run_row()
        self.assertEqual(run_row["status"], "completed")
        self.assertEqual(run_row["eligible_actor_count"], 3)
        self.assertEqual(run_row["enriched_actor_count"], 2)
        self.assertEqual(run_row["missing_actor_count"], 1)
        self.assertEqual(run_row["failed_actor_count"], 0)

        self.assertEqual(self._count_jsonl_rows(self.actor_dir), 2)

    def test_partial_batch_success_and_retryable_response(self) -> None:
        capture_run_id = self._seed_capture_run("cap_partial_retry")
        did_ok = "did:plc:ok"
        did_retryable = "did:plc:retry"
        self._insert_post(
            capture_run_id=capture_run_id,
            uri="at://did:plc:ok/app.bsky.feed.post/a",
            did=did_ok,
            hydration_status="hydrated",
        )
        self._insert_post(
            capture_run_id=capture_run_id,
            uri="at://did:plc:retry/app.bsky.feed.post/b",
            did=did_retryable,
            hydration_status="hydrated",
        )

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def chunk_dids(self, dids):
                for did in dids:
                    yield [did]

            def get_profiles(self, dids):
                did = dids[0]
                if did == did_ok:
                    return ActorBatchResult(
                        requested_dids=(did,),
                        profiles=(
                            {
                                "did": did,
                                "handle": "ok.bsky.social",
                                "followersCount": 1,
                                "followsCount": 1,
                                "postsCount": 1,
                                "labels": [],
                            },
                        ),
                        missing_dids=(),
                    )
                raise ActorRequestError("temporary", retryable=True)

        with mock.patch("bluesky_pipeline.main_actor_enrich.ActorClient", FakeClient):
            exit_code = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--log-path",
                    str(self.log_path),
                    "--actor-output-dir",
                    str(self.actor_dir),
                    "--claim-batch-size",
                    "10",
                    "--request-batch-size",
                    "1",
                ]
            )

        self.assertEqual(exit_code, 0)
        statuses = self._read_actor_statuses()
        self.assertEqual(statuses[did_ok], "enriched")
        self.assertEqual(statuses[did_retryable], "retryable")

    def test_clean_shutdown_releases_outstanding_claims(self) -> None:
        capture_run_id = self._seed_capture_run("cap_interrupt")
        did = "did:plc:interrupt"
        self._insert_post(
            capture_run_id=capture_run_id,
            uri="at://did:plc:interrupt/app.bsky.feed.post/a",
            did=did,
            hydration_status="hydrated",
        )

        class InterruptClient:
            def __init__(self, *args, **kwargs):
                pass

            def chunk_dids(self, dids):
                yield list(dids)

            def get_profiles(self, dids):
                raise KeyboardInterrupt()

        with mock.patch("bluesky_pipeline.main_actor_enrich.ActorClient", InterruptClient):
            exit_code = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--log-path",
                    str(self.log_path),
                    "--actor-output-dir",
                    str(self.actor_dir),
                ]
            )

        self.assertEqual(exit_code, 130)
        statuses = self._read_actor_statuses()
        self.assertEqual(statuses[did], "retryable")

        run_row = self._fetch_latest_actor_run_row()
        self.assertEqual(run_row["status"], "failed")

    def test_non_retryable_request_error_marks_failed(self) -> None:
        capture_run_id = self._seed_capture_run("cap_non_retryable")
        did = "did:plc:bad"
        self._insert_post(
            capture_run_id=capture_run_id,
            uri="at://did:plc:bad/app.bsky.feed.post/a",
            did=did,
            hydration_status="hydrated",
        )

        class NonRetryableClient:
            def __init__(self, *args, **kwargs):
                pass

            def chunk_dids(self, dids):
                yield list(dids)

            def get_profiles(self, dids):
                raise ActorRequestError("bad-request", retryable=False)

        with mock.patch("bluesky_pipeline.main_actor_enrich.ActorClient", NonRetryableClient):
            exit_code = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--log-path",
                    str(self.log_path),
                    "--actor-output-dir",
                    str(self.actor_dir),
                ]
            )

        self.assertEqual(exit_code, 0)
        statuses = self._read_actor_statuses()
        self.assertEqual(statuses[did], "failed")

        run_row = self._fetch_latest_actor_run_row()
        self.assertEqual(run_row["status"], "completed")
        self.assertEqual(run_row["failed_actor_count"], 1)

    def test_rerun_idempotency_does_not_duplicate_enriched_rows(self) -> None:
        capture_run_id = self._seed_capture_run("cap_rerun")
        did = "did:plc:rerun"
        self._insert_post(
            capture_run_id=capture_run_id,
            uri="at://did:plc:rerun/app.bsky.feed.post/a",
            did=did,
            hydration_status="hydrated",
        )

        class SuccessClient:
            def __init__(self, *args, **kwargs):
                pass

            def chunk_dids(self, dids):
                yield list(dids)

            def get_profiles(self, dids):
                return ActorBatchResult(
                    requested_dids=tuple(dids),
                    profiles=(
                        {
                            "did": did,
                            "handle": "rerun.bsky.social",
                            "followersCount": 1,
                            "followsCount": 1,
                            "postsCount": 1,
                            "labels": [],
                        },
                    ),
                    missing_dids=(),
                )

        with mock.patch("bluesky_pipeline.main_actor_enrich.ActorClient", SuccessClient):
            exit_code_1 = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--log-path",
                    str(self.log_path),
                    "--actor-output-dir",
                    str(self.actor_dir),
                ]
            )
        self.assertEqual(exit_code_1, 0)

        with mock.patch("bluesky_pipeline.main_actor_enrich.ActorClient", SuccessClient):
            exit_code_2 = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--log-path",
                    str(self.log_path),
                    "--actor-output-dir",
                    str(self.actor_dir),
                ]
            )
        self.assertEqual(exit_code_2, 0)

        conn = sqlite3.connect(self.db_path)
        try:
            actor_state_count = conn.execute("SELECT COUNT(*) FROM actor_profiles_state").fetchone()[0]
        finally:
            conn.close()

        statuses = self._read_actor_statuses()
        self.assertEqual(statuses[did], "enriched")
        self.assertEqual(actor_state_count, 1)
        self.assertEqual(self._count_jsonl_rows(self.actor_dir), 1)


if __name__ == "__main__":
    unittest.main()

