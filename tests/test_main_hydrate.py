from __future__ import annotations

import gzip
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bluesky_pipeline.hydrate.client import HydrateBatchResult, HydrateRequestError
from bluesky_pipeline.main_hydrate import main
from bluesky_pipeline.state.sqlite_store import SQLiteStore


class MainHydrateIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "state.db"
        self.log_path = self.root / "hydrate.log"
        self.hydrated_dir = self.root / "hydrated"
        self.miss_dir = self.root / "misses"

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
        captured_at: str,
        status: str = "pending",
        attempts: int = 0,
    ) -> None:
        with SQLiteStore(self.db_path) as store:
            store.insert_captured_post(
                uri=uri,
                capture_run_id=capture_run_id,
                repo_did="did:plc:test",
                rkey=uri.rsplit("/", 1)[-1],
                cid_at_capture=f"cid_{uri.rsplit('/', 1)[-1]}",
                seq=1,
                record_created_at=captured_at,
                captured_at=captured_at,
                capture_file_id=None,
            )
            if status != "pending" or attempts != 0:
                conn = store.connect()
                conn.execute(
                    """
                    UPDATE captured_posts
                    SET hydration_status = ?, hydration_attempt_count = ?
                    WHERE uri = ?
                    """,
                    (status, attempts, uri),
                )
                conn.commit()

    def _read_statuses(self) -> dict[str, str]:
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("SELECT uri, hydration_status FROM captured_posts").fetchall()
            return {uri: status for uri, status in rows}
        finally:
            conn.close()

    def _fetch_hydrate_run_row(self) -> dict[str, object]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT hydrate_run_id, status, eligible_post_count, hydrated_post_count,
                       missing_post_count, failed_post_count
                FROM hydrate_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                raise AssertionError("No hydrate_run row found")
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
        mature_ts = "2026-03-01T00:00:00+00:00"

        uri_ok_1 = "at://did:plc:test/app.bsky.feed.post/a"
        uri_ok_2 = "at://did:plc:test/app.bsky.feed.post/b"
        uri_missing_terminal = "at://did:plc:test/app.bsky.feed.post/c"

        self._insert_post(capture_run_id=capture_run_id, uri=uri_ok_1, captured_at=mature_ts)
        self._insert_post(capture_run_id=capture_run_id, uri=uri_ok_2, captured_at=mature_ts)
        self._insert_post(
            capture_run_id=capture_run_id,
            uri=uri_missing_terminal,
            captured_at=mature_ts,
            status="retryable",
            attempts=2,
        )

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def chunk_uris(self, uris):
                yield list(uris)

            def get_posts(self, uris):
                posts = [
                    {
                        "uri": uri_ok_1,
                        "cid": "cid_a",
                        "indexedAt": "2026-03-02T00:00:00Z",
                        "author": {"did": "did:plc:test", "handle": "a.bsky.social"},
                        "replyCount": 1,
                        "repostCount": 2,
                        "likeCount": 3,
                        "quoteCount": 4,
                        "labels": [],
                        "record": {"$type": "app.bsky.feed.post", "text": "a"},
                    },
                    {
                        "uri": uri_ok_2,
                        "cid": "cid_b",
                        "indexedAt": "2026-03-02T00:00:00Z",
                        "author": {"did": "did:plc:test", "handle": "b.bsky.social"},
                        "replyCount": 5,
                        "repostCount": 6,
                        "likeCount": 7,
                        "quoteCount": 8,
                        "labels": [],
                        "record": {"$type": "app.bsky.feed.post", "text": "b"},
                    },
                ]
                missing = tuple(uri for uri in uris if uri == uri_missing_terminal)
                return HydrateBatchResult(
                    requested_uris=tuple(uris),
                    posts=tuple(posts),
                    missing_uris=missing,
                )

        with mock.patch("bluesky_pipeline.main_hydrate.HydrateClient", FakeClient):
            exit_code = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--log-path",
                    str(self.log_path),
                    "--capture-run-id",
                    capture_run_id,
                    "--hydrated-output-dir",
                    str(self.hydrated_dir),
                    "--miss-output-dir",
                    str(self.miss_dir),
                    "--claim-batch-size",
                    "10",
                    "--request-batch-size",
                    "25",
                    "--max-unresolved-attempts",
                    "3",
                ]
            )

        self.assertEqual(exit_code, 0)

        statuses = self._read_statuses()
        self.assertEqual(statuses[uri_ok_1], "hydrated")
        self.assertEqual(statuses[uri_ok_2], "hydrated")
        self.assertEqual(statuses[uri_missing_terminal], "missing")

        run_row = self._fetch_hydrate_run_row()
        self.assertEqual(run_row["status"], "completed")
        self.assertEqual(run_row["eligible_post_count"], 3)
        self.assertEqual(run_row["hydrated_post_count"], 2)
        self.assertEqual(run_row["missing_post_count"], 1)
        self.assertEqual(run_row["failed_post_count"], 0)

        self.assertEqual(self._count_jsonl_rows(self.hydrated_dir), 2)
        self.assertEqual(self._count_jsonl_rows(self.miss_dir), 1)

    def test_partial_batch_success_and_retryable_response(self) -> None:
        capture_run_id = self._seed_capture_run("cap_partial_retry")
        mature_ts = "2026-03-01T00:00:00+00:00"

        uri_ok = "at://did:plc:test/app.bsky.feed.post/d"
        uri_retryable = "at://did:plc:test/app.bsky.feed.post/e"

        self._insert_post(capture_run_id=capture_run_id, uri=uri_ok, captured_at=mature_ts)
        self._insert_post(capture_run_id=capture_run_id, uri=uri_retryable, captured_at=mature_ts)

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self._calls = 0

            def chunk_uris(self, uris):
                # Force two request batches to simulate partial batch outcome.
                for uri in uris:
                    yield [uri]

            def get_posts(self, uris):
                self._calls += 1
                uri = uris[0]
                if uri == uri_ok:
                    return HydrateBatchResult(
                        requested_uris=(uri,),
                        posts=(
                            {
                                "uri": uri,
                                "cid": "cid_d",
                                "indexedAt": "2026-03-02T00:00:00Z",
                                "author": {"did": "did:plc:test", "handle": "d.bsky.social"},
                                "replyCount": 1,
                                "repostCount": 1,
                                "likeCount": 1,
                                "quoteCount": 0,
                                "labels": [],
                                "record": {"$type": "app.bsky.feed.post", "text": "d"},
                            },
                        ),
                        missing_uris=(),
                    )
                raise HydrateRequestError("temporary", retryable=True)

        with mock.patch("bluesky_pipeline.main_hydrate.HydrateClient", FakeClient):
            exit_code = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--log-path",
                    str(self.log_path),
                    "--capture-run-id",
                    capture_run_id,
                    "--hydrated-output-dir",
                    str(self.hydrated_dir),
                    "--miss-output-dir",
                    str(self.miss_dir),
                    "--claim-batch-size",
                    "10",
                    "--request-batch-size",
                    "1",
                ]
            )

        self.assertEqual(exit_code, 0)

        statuses = self._read_statuses()
        self.assertEqual(statuses[uri_ok], "hydrated")
        self.assertEqual(statuses[uri_retryable], "retryable")

    def test_clean_shutdown_releases_outstanding_claims(self) -> None:
        capture_run_id = self._seed_capture_run("cap_interrupt")
        mature_ts = "2026-03-01T00:00:00+00:00"
        uri = "at://did:plc:test/app.bsky.feed.post/f"
        self._insert_post(capture_run_id=capture_run_id, uri=uri, captured_at=mature_ts)

        class InterruptClient:
            def __init__(self, *args, **kwargs):
                pass

            def chunk_uris(self, uris):
                yield list(uris)

            def get_posts(self, uris):
                raise KeyboardInterrupt()

        with mock.patch("bluesky_pipeline.main_hydrate.HydrateClient", InterruptClient):
            exit_code = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--log-path",
                    str(self.log_path),
                    "--capture-run-id",
                    capture_run_id,
                    "--hydrated-output-dir",
                    str(self.hydrated_dir),
                    "--miss-output-dir",
                    str(self.miss_dir),
                ]
            )

        self.assertEqual(exit_code, 130)

        statuses = self._read_statuses()
        self.assertEqual(statuses[uri], "retryable")

        run_row = self._fetch_hydrate_run_row()
        self.assertEqual(run_row["status"], "failed")

    def test_non_retryable_request_error_marks_failed(self) -> None:
        capture_run_id = self._seed_capture_run("cap_non_retryable")
        mature_ts = "2026-03-01T00:00:00+00:00"
        uri = "at://did:plc:test/app.bsky.feed.post/g"
        self._insert_post(capture_run_id=capture_run_id, uri=uri, captured_at=mature_ts)

        class NonRetryableClient:
            def __init__(self, *args, **kwargs):
                pass

            def chunk_uris(self, uris):
                yield list(uris)

            def get_posts(self, uris):
                raise HydrateRequestError("bad-request", retryable=False)

        with mock.patch("bluesky_pipeline.main_hydrate.HydrateClient", NonRetryableClient):
            exit_code = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--log-path",
                    str(self.log_path),
                    "--capture-run-id",
                    capture_run_id,
                    "--hydrated-output-dir",
                    str(self.hydrated_dir),
                    "--miss-output-dir",
                    str(self.miss_dir),
                ]
            )

        self.assertEqual(exit_code, 0)

        statuses = self._read_statuses()
        self.assertEqual(statuses[uri], "failed")

        run_row = self._fetch_hydrate_run_row()
        self.assertEqual(run_row["status"], "completed")
        self.assertEqual(run_row["failed_post_count"], 1)

    def test_startup_logs_immediate_mode_warning_for_zero_maturity(self) -> None:
        exit_code = main(
            [
                "--db-path",
                str(self.db_path),
                "--log-path",
                str(self.log_path),
                "--maturity-hours",
                "0",
            ]
        )

        self.assertEqual(exit_code, 1)

        log_text = self.log_path.read_text(encoding="utf-8")
        self.assertIn("Hydration maturity window: 0 hour(s)", log_text)
        self.assertIn("Hydration eligibility cutoff (UTC): captured_at <=", log_text)
        self.assertIn("Hydration mode: immediate/test-style", log_text)

    def test_startup_logs_production_mode_for_default_maturity(self) -> None:
        exit_code = main(
            [
                "--db-path",
                str(self.db_path),
                "--log-path",
                str(self.log_path),
            ]
        )

        self.assertEqual(exit_code, 1)

        log_text = self.log_path.read_text(encoding="utf-8")
        self.assertIn("Hydration maturity window: 24 hour(s)", log_text)
        self.assertIn("Hydration eligibility cutoff (UTC): captured_at <=", log_text)
        self.assertIn("Hydration mode: production-style (24 hours)", log_text)

    def test_startup_logs_low_maturity_override_warning(self) -> None:
        exit_code = main(
            [
                "--db-path",
                str(self.db_path),
                "--log-path",
                str(self.log_path),
                "--maturity-hours",
                "6",
            ]
        )

        self.assertEqual(exit_code, 1)

        log_text = self.log_path.read_text(encoding="utf-8")
        self.assertIn("Hydration maturity window: 6 hour(s)", log_text)
        self.assertIn("Hydration mode: low-maturity override (6 hours)", log_text)


if __name__ == "__main__":
    unittest.main()
