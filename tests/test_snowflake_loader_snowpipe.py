from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowflake_loader.manifest import ManifestFile
from snowflake_loader.snowpipe import (
    SnowpipeFileOutcome,
    load_pending_files_for_family,
    poll_pipe_file_outcomes,
    refresh_pipe_prefix,
)


class _FakeSession:
    def __init__(
        self,
        execute_rows: list[list[object]] | None = None,
        scalar_values: list[object] | None = None,
    ) -> None:
        self.execute_rows = execute_rows or []
        self.scalar_values = scalar_values or []
        self.execute_calls: list[tuple[str, tuple[object, ...] | None]] = []
        self.scalar_calls: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> list[object]:
        self.execute_calls.append((sql, params))
        if self.execute_rows:
            return self.execute_rows.pop(0)
        return []

    def execute_scalar(self, sql: str, params: tuple[object, ...] | None = None) -> object:
        self.scalar_calls.append((sql, params))
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return 0


class SnowpipeHelperTests(unittest.TestCase):
    def test_refresh_pipe_prefix_issues_expected_sql(self) -> None:
        session = _FakeSession()
        refresh_pipe_prefix(
            session=session,  # type: ignore[arg-type]
            pipe_name="BLUESKY_RAW_POSTS_PIPE",
            stage_prefix="run_1/raw_posts",
        )

        self.assertEqual(len(session.execute_calls), 1)
        self.assertIn("ALTER PIPE BLUESKY_RAW_POSTS_PIPE REFRESH", session.execute_calls[0][0])
        self.assertIn("PREFIX = 'run_1/raw_posts'", session.execute_calls[0][0])

    def test_poll_pipe_file_outcomes_classifies_loaded_failed_and_timeout(self) -> None:
        session = _FakeSession(
            execute_rows=[
                [
                    (
                        "run_1/raw_posts/cap/raw_posts_000001.jsonl.gz",
                        "LOADED",
                        25,
                        None,
                    ),
                    (
                        "run_1/raw_posts/cap/raw_posts_000002.jsonl.gz",
                        "LOAD_FAILED",
                        0,
                        "bad json",
                    ),
                ]
            ]
        )

        outcomes = poll_pipe_file_outcomes(
            session=session,  # type: ignore[arg-type]
            landing_table_name="LANDING_RAW_POSTS",
            stage_prefix="run_1/raw_posts",
            pending_stage_file_names=[
                "run_1/raw_posts/cap/raw_posts_000001.jsonl.gz",
                "run_1/raw_posts/cap/raw_posts_000002.jsonl.gz",
                "run_1/raw_posts/cap/raw_posts_000003.jsonl.gz",
            ],
            timeout_seconds=0,
            poll_interval_seconds=0,
            history_lookback_hours=1,
        )

        self.assertEqual(outcomes["run_1/raw_posts/cap/raw_posts_000001.jsonl.gz"].status, "loaded")
        self.assertEqual(outcomes["run_1/raw_posts/cap/raw_posts_000002.jsonl.gz"].status, "failed")
        self.assertEqual(outcomes["run_1/raw_posts/cap/raw_posts_000003.jsonl.gz"].status, "timed_out")

    def test_load_pending_records_manifest_only_for_loaded_files(self) -> None:
        session = _FakeSession()

        with tempfile.TemporaryDirectory() as tempdir:
            a = Path(tempdir) / "raw_posts_000001.jsonl.gz"
            b = Path(tempdir) / "raw_posts_000002.jsonl.gz"
            a.write_text("", encoding="utf-8")
            b.write_text("", encoding="utf-8")

            files = [
                ManifestFile("raw_posts", "cap", a, row_count=7, byte_size=1),
                ManifestFile("raw_posts", "cap", b, row_count=9, byte_size=1),
            ]

            with mock.patch(
                "snowflake_loader.snowpipe.poll_pipe_file_outcomes",
                return_value={
                    "run_1/raw_posts/cap/raw_posts_000001.jsonl.gz": SnowpipeFileOutcome(
                        stage_file_name="run_1/raw_posts/cap/raw_posts_000001.jsonl.gz",
                        status="loaded",
                        rows_loaded=7,
                    ),
                    "run_1/raw_posts/cap/raw_posts_000002.jsonl.gz": SnowpipeFileOutcome(
                        stage_file_name="run_1/raw_posts/cap/raw_posts_000002.jsonl.gz",
                        status="failed",
                        rows_loaded=0,
                        error_message="boom",
                    ),
                },
            ):
                summary = load_pending_files_for_family(
                    session=session,  # type: ignore[arg-type]
                    pending_files=files,
                    dataset_family="raw_posts",
                    run_tag="run_1",
                    load_invocation_id="load_test",
                    pipe_name="BLUESKY_RAW_POSTS_PIPE",
                    landing_table_name="LANDING_RAW_POSTS",
                    manifest_table_name="LOADER_FILE_MANIFEST",
                    poll_timeout_seconds=1,
                    poll_interval_seconds=0,
                    history_lookback_hours=1,
                )

        self.assertEqual(summary.attempted_files, 2)
        self.assertEqual(summary.loaded_files, 1)
        self.assertEqual(summary.failed_files, 1)
        self.assertEqual(summary.timed_out_files, 0)
        self.assertEqual(summary.loaded_rows, 7)

        insert_calls = [sql for sql, _ in session.execute_calls if "INSERT INTO LOADER_FILE_MANIFEST" in sql]
        self.assertEqual(len(insert_calls), 1)

    def test_load_pending_uses_landing_count_when_history_row_count_missing(self) -> None:
        session = _FakeSession(scalar_values=[3])

        with tempfile.TemporaryDirectory() as tempdir:
            a = Path(tempdir) / "raw_posts_000001.jsonl.gz"
            a.write_text("", encoding="utf-8")
            files = [ManifestFile("raw_posts", "cap", a, row_count=7, byte_size=1)]

            with mock.patch(
                "snowflake_loader.snowpipe.poll_pipe_file_outcomes",
                return_value={
                    "run_1/raw_posts/cap/raw_posts_000001.jsonl.gz": SnowpipeFileOutcome(
                        stage_file_name="run_1/raw_posts/cap/raw_posts_000001.jsonl.gz",
                        status="loaded",
                        rows_loaded=None,
                    ),
                },
            ):
                summary = load_pending_files_for_family(
                    session=session,  # type: ignore[arg-type]
                    pending_files=files,
                    dataset_family="raw_posts",
                    run_tag="run_1",
                    load_invocation_id="load_test",
                    pipe_name="BLUESKY_RAW_POSTS_PIPE",
                    landing_table_name="LANDING_RAW_POSTS",
                    manifest_table_name="LOADER_FILE_MANIFEST",
                    poll_timeout_seconds=1,
                    poll_interval_seconds=0,
                    history_lookback_hours=1,
                )

        self.assertEqual(summary.loaded_rows, 3)
        self.assertEqual(len(session.scalar_calls), 1)

        insert_params = [params for sql, params in session.execute_calls if "INSERT INTO LOADER_FILE_MANIFEST" in sql]
        self.assertEqual(len(insert_params), 1)
        self.assertIsNotNone(insert_params[0])
        self.assertEqual(insert_params[0][6], 3)

    def test_load_pending_falls_back_to_local_row_count_when_no_history_or_landing_rows(self) -> None:
        session = _FakeSession(scalar_values=[0])

        with tempfile.TemporaryDirectory() as tempdir:
            a = Path(tempdir) / "raw_posts_000001.jsonl.gz"
            a.write_text("", encoding="utf-8")
            files = [ManifestFile("raw_posts", "cap", a, row_count=7, byte_size=1)]

            with mock.patch(
                "snowflake_loader.snowpipe.poll_pipe_file_outcomes",
                return_value={
                    "run_1/raw_posts/cap/raw_posts_000001.jsonl.gz": SnowpipeFileOutcome(
                        stage_file_name="run_1/raw_posts/cap/raw_posts_000001.jsonl.gz",
                        status="loaded",
                        rows_loaded=None,
                    ),
                },
            ):
                summary = load_pending_files_for_family(
                    session=session,  # type: ignore[arg-type]
                    pending_files=files,
                    dataset_family="raw_posts",
                    run_tag="run_1",
                    load_invocation_id="load_test",
                    pipe_name="BLUESKY_RAW_POSTS_PIPE",
                    landing_table_name="LANDING_RAW_POSTS",
                    manifest_table_name="LOADER_FILE_MANIFEST",
                    poll_timeout_seconds=1,
                    poll_interval_seconds=0,
                    history_lookback_hours=1,
                )

        self.assertEqual(summary.loaded_rows, 7)
        insert_params = [params for sql, params in session.execute_calls if "INSERT INTO LOADER_FILE_MANIFEST" in sql]
        self.assertEqual(len(insert_params), 1)
        self.assertIsNotNone(insert_params[0])
        self.assertEqual(insert_params[0][6], 7)


if __name__ == "__main__":
    unittest.main()
