"""Firehose raw-capture entrypoint.

Phase 3 responsibilities:
- stream subscribeRepos firehose events
- keep only `app.bsky.feed.post` create records
- dedupe by URI through SQLite idempotent insert
- write normalized raw rows to rotating local gzip JSONL files
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from bluesky_pipeline.batching.writer import FinalizedBatchFile, GzipJsonlBatchWriter
from bluesky_pipeline.config import load_config
from bluesky_pipeline.firehose.client import FirehoseClient
from bluesky_pipeline.firehose.decoder import FirehoseDecodeError, decode_frame
from bluesky_pipeline.firehose.extractor import FirehoseExtractError, extract_post_creates
from bluesky_pipeline.firehose.normalizer import normalize_raw_post
from bluesky_pipeline.logging_config import configure_logging
from bluesky_pipeline.state.sqlite_store import SQLiteStore


@dataclass(slots=True)
class FirehoseCounters:
    """Operational counters logged during capture."""

    raw_frames_received: int = 0
    decoded_events: int = 0
    commit_events: int = 0
    commit_ops_scanned: int = 0
    post_create_matches: int = 0
    decode_errors: int = 0
    extract_errors: int = 0
    duplicates_skipped: int = 0
    unique_posts_written: int = 0


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for firehose ingestion."""

    parser = argparse.ArgumentParser(description="Bluesky firehose capture job")
    parser.add_argument("--db-path", type=Path, default=Path("data/state/pipeline_state.db"))
    parser.add_argument("--log-path", type=Path, default=Path("data/logs/firehose.log"))
    parser.add_argument("--firehose-url", type=str, default=None)
    parser.add_argument("--raw-output-dir", type=Path, default=None)
    parser.add_argument("--target-count", type=int, default=None)
    parser.add_argument("--max-rows-per-file", type=int, default=None)
    parser.add_argument("--max-seconds-per-file", type=float, default=None)
    parser.add_argument("--recv-timeout-seconds", type=float, default=None)
    parser.add_argument("--progress-log-interval-seconds", type=float, default=None)
    parser.add_argument("--progress-db-sync-interval-seconds", type=float, default=None)
    parser.add_argument("--mock-frames-path", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run firehose raw capture until target unique URI count is reached."""

    args = build_parser().parse_args(argv)
    config = load_config()

    logger = configure_logging("firehose", args.log_path)

    target_count = args.target_count or config.firehose.target_capture_count
    firehose_url = args.firehose_url or config.firehose.subscribe_repos_url
    raw_root_dir = args.raw_output_dir or config.paths.raw_posts_dir
    recv_timeout_seconds = args.recv_timeout_seconds or config.firehose.recv_timeout_seconds
    max_rows_per_file = args.max_rows_per_file or config.batching.flush_row_count
    max_seconds_per_file = args.max_seconds_per_file or float(config.batching.flush_interval_seconds)
    progress_log_interval = (
        args.progress_log_interval_seconds or config.firehose.progress_log_interval_seconds
    )
    progress_db_sync_interval = (
        args.progress_db_sync_interval_seconds
        or config.firehose.progress_db_sync_interval_seconds
    )

    logger.info("Starting firehose capture job")
    logger.info("Firehose URL: %s", firehose_url)
    logger.info("Target unique posts: %d", target_count)
    if args.mock_frames_path is not None:
        logger.info("Mock frame source enabled: %s", args.mock_frames_path)

    store = SQLiteStore(args.db_path)
    writer: GzipJsonlBatchWriter | None = None
    client: FirehoseClient | None = None

    capture_run_id: str | None = None
    run_completed = False
    failure_note: str | None = None

    counters = FirehoseCounters()
    start_monotonic = time.monotonic()
    last_log_monotonic = start_monotonic
    last_db_sync_monotonic = start_monotonic
    last_seq_seen: int | None = None

    try:
        store.connect()
        store.ensure_schema()

        capture_run_id = store.create_capture_run(target_post_count=target_count)
        output_dir = raw_root_dir / capture_run_id

        writer = GzipJsonlBatchWriter(
            output_dir=output_dir,
            file_prefix="raw_posts",
            max_rows_per_file=max_rows_per_file,
            max_seconds_per_file=max_seconds_per_file,
        )

        client = FirehoseClient(
            subscribe_url=firehose_url,
            reconnect_base_delay_seconds=config.firehose.reconnect_base_delay_seconds,
            reconnect_max_delay_seconds=config.firehose.reconnect_max_delay_seconds,
            recv_timeout_seconds=recv_timeout_seconds,
            mock_frames_path=args.mock_frames_path,
        )

        for raw_frame in client.iter_frames():
            counters.raw_frames_received += 1

            try:
                decoded = decode_frame(raw_frame)
            except FirehoseDecodeError as exc:
                counters.decode_errors += 1
                logger.debug("Decode error (frame #%d): %s", counters.raw_frames_received, exc)
                continue

            if decoded is None:
                continue

            counters.decoded_events += 1

            if decoded.event_type != "commit":
                now = time.monotonic()
                if now - last_log_monotonic >= progress_log_interval:
                    _log_progress(
                        logger=logger,
                        counters=counters,
                        target_count=target_count,
                        start_monotonic=start_monotonic,
                    )
                    last_log_monotonic = now
                continue

            counters.commit_events += 1

            try:
                extraction = extract_post_creates(decoded)
            except FirehoseExtractError as exc:
                counters.extract_errors += 1
                logger.debug("Extraction error (commit seq=%s): %s", decoded.seq, exc)
                continue

            counters.commit_ops_scanned += extraction.commit_ops_scanned
            counters.post_create_matches += len(extraction.posts)

            for extracted in extraction.posts:
                normalized_row = normalize_raw_post(
                    extracted=extracted,
                    capture_run_id=capture_run_id,
                )

                is_new = store.insert_captured_post(
                    uri=extracted.uri,
                    capture_run_id=capture_run_id,
                    repo_did=extracted.repo_did,
                    rkey=extracted.rkey,
                    cid_at_capture=extracted.cid,
                    seq=extracted.seq,
                    record_created_at=normalized_row.get("record_created_at"),
                    captured_at=str(normalized_row["captured_at"]),
                    capture_file_id=None,
                )

                if is_new:
                    writer.write_row(dict(normalized_row))
                    counters.unique_posts_written += 1
                    if extracted.seq is not None:
                        last_seq_seen = extracted.seq
                else:
                    counters.duplicates_skipped += 1

                _persist_completed_files(
                    store=store,
                    capture_run_id=capture_run_id,
                    completed_files=writer.pop_completed_files(),
                )

                if counters.unique_posts_written >= target_count:
                    break

            now = time.monotonic()

            if (
                now - last_db_sync_monotonic >= progress_db_sync_interval
                or counters.unique_posts_written >= target_count
            ):
                store.update_capture_run_progress(
                    capture_run_id,
                    written_post_count=counters.unique_posts_written,
                    last_seq_seen=last_seq_seen,
                )
                last_db_sync_monotonic = now

            if now - last_log_monotonic >= progress_log_interval:
                _log_progress(
                    logger=logger,
                    counters=counters,
                    target_count=target_count,
                    start_monotonic=start_monotonic,
                )
                last_log_monotonic = now

            if counters.unique_posts_written >= target_count:
                run_completed = True
                logger.info("Target reached: %d unique posts", counters.unique_posts_written)
                break

        if not run_completed:
            failure_note = (
                f"Capture loop ended before reaching target. "
                f"captured={counters.unique_posts_written}, target={target_count}"
            )
            raise RuntimeError(failure_note)

        return 0

    except KeyboardInterrupt:
        failure_note = (
            f"Interrupted by user. captured={counters.unique_posts_written}, target={target_count}"
        )
        logger.warning(failure_note)
        return 130

    except Exception as exc:
        if failure_note is None:
            failure_note = str(exc)
        logger.exception("Firehose capture failed: %s", exc)
        return 1

    finally:
        if client is not None:
            client.stop()

        if writer is not None and capture_run_id is not None:
            try:
                completed_files = writer.close()
                _persist_completed_files(
                    store=store,
                    capture_run_id=capture_run_id,
                    completed_files=completed_files,
                )
            except Exception as exc:
                run_completed = False
                failure_note = failure_note or f"Writer finalization failed: {exc}"
                logger.exception("Writer finalization failed")

        if capture_run_id is not None:
            try:
                store.update_capture_run_progress(
                    capture_run_id,
                    written_post_count=counters.unique_posts_written,
                    last_seq_seen=last_seq_seen,
                )
            except Exception:
                logger.exception("Final capture run progress sync failed")

            try:
                if run_completed:
                    store.complete_capture_run(capture_run_id, status="completed")
                else:
                    store.fail_capture_run(capture_run_id, notes=failure_note)
            except Exception:
                logger.exception("Capture run terminal status update failed")

        _log_progress(
            logger=logger,
            counters=counters,
            target_count=target_count,
            start_monotonic=start_monotonic,
        )

        store.close()


def _persist_completed_files(
    store: SQLiteStore,
    capture_run_id: str,
    completed_files: Iterable[FinalizedBatchFile],
) -> None:
    """Persist finalized writer files into SQLite `batch_files` table."""

    for completed in completed_files:
        file_id = store.create_batch_file(
            job_type="firehose",
            run_id=capture_run_id,
            dataset_type="raw_posts",
            local_path=str(completed.final_path),
            created_at_iso=completed.opened_at,
        )
        store.close_batch_file(
            file_id=file_id,
            row_count=completed.row_count,
            byte_size=completed.byte_size,
            status="closed",
            closed_at_iso=completed.closed_at,
        )


def _log_progress(
    logger: logging.Logger,
    counters: FirehoseCounters,
    target_count: int,
    start_monotonic: float,
) -> None:
    """Emit standard progress metrics for firehose capture."""

    elapsed = max(0.001, time.monotonic() - start_monotonic)
    rows_per_second = counters.unique_posts_written / elapsed
    remaining = max(0, target_count - counters.unique_posts_written)
    completion_pct = (counters.unique_posts_written / target_count * 100.0) if target_count else 0.0

    logger.info(
        "progress frames=%d decoded=%d commit_events=%d ops=%d matches=%d "
        "decode_errors=%d extract_errors=%d duplicates=%d unique=%d rows_per_sec=%.2f "
        "remaining=%d complete_pct=%.3f",
        counters.raw_frames_received,
        counters.decoded_events,
        counters.commit_events,
        counters.commit_ops_scanned,
        counters.post_create_matches,
        counters.decode_errors,
        counters.extract_errors,
        counters.duplicates_skipped,
        counters.unique_posts_written,
        rows_per_second,
        remaining,
        completion_pct,
    )


if __name__ == "__main__":
    raise SystemExit(main())
