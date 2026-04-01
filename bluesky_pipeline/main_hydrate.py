"""Hydration worker entrypoint.

Phase 4 responsibilities:
- poll and claim mature captured posts from SQLite
- request hydrated post views from `app.bsky.feed.getPosts`
- write hydrated rows and terminal misses to rotating local `.jsonl.gz`
- transition per-post hydration state and hydrate-run progress in SQLite
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from bluesky_pipeline.batching.writer import FinalizedBatchFile, GzipJsonlBatchWriter
from bluesky_pipeline.config import load_config
from bluesky_pipeline.hydrate.client import HydrateClient, HydrateRequestError
from bluesky_pipeline.hydrate.normalizer import normalize_hydrated_post, normalize_hydration_miss
from bluesky_pipeline.hydrate.selector import HydrationClaim, HydrationSelector
from bluesky_pipeline.logging_config import configure_logging
from bluesky_pipeline.state.sqlite_store import SQLiteStore
from bluesky_pipeline.utils.time_utils import utc_now_iso

MISSING_REASON_NOT_RETURNED = "not_returned_by_getPosts"
RETRY_ERROR_REQUEST = "getPosts request failed"


@dataclass(slots=True)
class HydrationCounters:
    poll_cycles: int = 0
    idle_polls: int = 0
    mature_pending_rows: int = 0
    expired_claims_released: int = 0
    rows_claimed: int = 0
    request_batches_sent: int = 0
    requested_uris: int = 0
    hydrated_rows_written: int = 0
    unresolved_uris: int = 0
    rows_marked_hydrated: int = 0
    rows_marked_retryable: int = 0
    rows_marked_missing: int = 0
    rows_marked_failed: int = 0


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for hydration worker."""

    parser = argparse.ArgumentParser(description="Bluesky hydration job")
    parser.add_argument("--db-path", type=Path, default=Path("data/state/pipeline_state.db"))
    parser.add_argument("--log-path", type=Path, default=Path("data/logs/hydrate.log"))
    parser.add_argument("--capture-run-id", type=str, default=None)
    parser.add_argument("--worker-id", type=str, default=None)
    parser.add_argument("--hydrate-api-base-url", type=str, default=None)
    parser.add_argument("--get-posts-path", type=str, default=None)
    parser.add_argument("--hydrated-output-dir", type=Path, default=None)
    parser.add_argument("--miss-output-dir", type=Path, default=None)
    parser.add_argument("--claim-batch-size", type=int, default=None)
    parser.add_argument("--claim-ttl-seconds", type=int, default=None)
    parser.add_argument("--request-batch-size", type=int, default=None)
    parser.add_argument("--request-timeout-seconds", type=float, default=None)
    parser.add_argument("--maturity-hours", type=int, default=None)
    parser.add_argument("--poll-interval-seconds", type=float, default=None)
    parser.add_argument("--max-unresolved-attempts", type=int, default=None)
    parser.add_argument("--max-rows-per-file", type=int, default=None)
    parser.add_argument("--max-seconds-per-file", type=float, default=None)
    parser.add_argument("--progress-log-interval-seconds", type=float, default=None)
    parser.add_argument("--continue-polling", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run hydration worker loop until queue exhaustion or interruption."""

    args = build_parser().parse_args(argv)
    config = load_config()
    logger = configure_logging("hydrate", args.log_path)

    db_path = args.db_path
    hydrate_api_base_url = args.hydrate_api_base_url or config.hydrate.api_base_url
    get_posts_path = args.get_posts_path or config.hydrate.get_posts_path
    maturity_hours = args.maturity_hours if args.maturity_hours is not None else config.hydrate.maturity_hours
    claim_batch_size = (
        args.claim_batch_size
        if args.claim_batch_size is not None
        else config.hydrate.claim_batch_size
    )
    claim_ttl_seconds = (
        args.claim_ttl_seconds
        if args.claim_ttl_seconds is not None
        else config.hydrate.claim_ttl_seconds
    )
    request_batch_size = (
        args.request_batch_size
        if args.request_batch_size is not None
        else config.hydrate.request_batch_size
    )
    request_timeout_seconds = (
        args.request_timeout_seconds
        if args.request_timeout_seconds is not None
        else config.hydrate.request_timeout_seconds
    )
    poll_interval_seconds = (
        args.poll_interval_seconds
        if args.poll_interval_seconds is not None
        else float(config.hydrate.poll_interval_seconds)
    )
    max_unresolved_attempts = (
        args.max_unresolved_attempts
        if args.max_unresolved_attempts is not None
        else config.hydrate.max_unresolved_attempts
    )
    max_rows_per_file = args.max_rows_per_file or config.batching.flush_row_count
    max_seconds_per_file = args.max_seconds_per_file or float(config.batching.flush_interval_seconds)
    progress_log_interval = (
        args.progress_log_interval_seconds
        if args.progress_log_interval_seconds is not None
        else config.hydrate.progress_log_interval_seconds
    )
    continue_polling = bool(args.continue_polling or config.hydrate.continue_polling_when_idle)
    if claim_batch_size <= 0:
        raise ValueError("claim_batch_size must be > 0")
    if request_batch_size <= 0:
        raise ValueError("request_batch_size must be > 0")
    if poll_interval_seconds < 0:
        raise ValueError("poll_interval_seconds must be >= 0")
    if progress_log_interval <= 0:
        raise ValueError("progress_log_interval_seconds must be > 0")
    if max_unresolved_attempts <= 0:
        raise ValueError("max_unresolved_attempts must be > 0")

    counters = HydrationCounters()
    worker_id = args.worker_id or f"hydrator-{os.getpid()}"
    started_monotonic = time.monotonic()
    last_progress_log_at = started_monotonic

    store = SQLiteStore(db_path)
    hydrated_writer: GzipJsonlBatchWriter | None = None
    miss_writer: GzipJsonlBatchWriter | None = None
    hydrate_run_id: str | None = None
    current_claimed_uris: set[str] = set()
    run_completed = False
    failure_note: str | None = None
    exit_code = 0

    logger.info("Starting hydration worker")
    logger.info("Worker ID: %s", worker_id)
    logger.info("Hydration endpoint: %s%s", hydrate_api_base_url, get_posts_path)
    logger.info(
        "maturity_hours=%d claim_batch_size=%d request_batch_size=%d continue_polling=%s",
        maturity_hours,
        claim_batch_size,
        request_batch_size,
        continue_polling,
    )

    try:
        store.connect()
        store.ensure_schema()
        capture_run_id = _resolve_capture_run_id(store, requested_capture_run_id=args.capture_run_id)
        hydrate_run_id = store.create_hydrate_run(capture_run_id=capture_run_id)

        hydrated_output_dir = (args.hydrated_output_dir or config.paths.hydrated_posts_dir) / hydrate_run_id
        miss_output_dir = (args.miss_output_dir or config.paths.hydration_misses_dir) / hydrate_run_id

        hydrated_writer = GzipJsonlBatchWriter(
            output_dir=hydrated_output_dir,
            file_prefix="hydrated_posts",
            max_rows_per_file=max_rows_per_file,
            max_seconds_per_file=max_seconds_per_file,
        )
        miss_writer = GzipJsonlBatchWriter(
            output_dir=miss_output_dir,
            file_prefix="hydration_misses",
            max_rows_per_file=max_rows_per_file,
            max_seconds_per_file=max_seconds_per_file,
        )

        selector = HydrationSelector(
            store=store,
            maturity_hours=maturity_hours,
            claim_ttl_seconds=claim_ttl_seconds,
        )
        client = HydrateClient(
            api_base_url=hydrate_api_base_url,
            get_posts_path=get_posts_path,
            max_uris_per_request=request_batch_size,
            request_timeout_seconds=request_timeout_seconds,
            max_attempts=config.retry.max_attempts,
            backoff_base_delay_seconds=config.retry.base_delay_seconds,
            backoff_max_delay_seconds=config.retry.max_delay_seconds,
            jitter_ratio=config.retry.jitter_ratio,
        )

        while True:
            counters.poll_cycles += 1
            cycle_retryable_marked = 0
            cycle_terminal_marked = 0

            released = selector.release_expired_claims()
            counters.expired_claims_released += released
            if released > 0:
                logger.info("Released %d expired claims", released)

            counters.mature_pending_rows = selector.count_pending_mature_posts()
            claims = selector.claim_mature_posts(worker_id=worker_id, limit=claim_batch_size)

            if not claims:
                counters.idle_polls += 1
                now = time.monotonic()
                if now - last_progress_log_at >= progress_log_interval:
                    _log_progress(logger, counters, started_monotonic)
                    last_progress_log_at = now

                if continue_polling:
                    time.sleep(max(0.0, poll_interval_seconds))
                    continue

                run_completed = True
                logger.info("No mature eligible posts remain; hydration run is complete.")
                break

            store.update_hydrate_run_progress(hydrate_run_id, eligible_delta=len(claims))
            counters.rows_claimed += len(claims)

            claim_by_uri = {claim.uri: claim for claim in claims}
            claimed_uris = [claim.uri for claim in claims]
            current_claimed_uris = set(claimed_uris)

            for uri_chunk in client.chunk_uris(claimed_uris):
                counters.request_batches_sent += 1
                counters.requested_uris += len(uri_chunk)
                checked_at = utc_now_iso()

                try:
                    batch_result = client.get_posts(uri_chunk)
                except HydrateRequestError as exc:
                    message = f"{RETRY_ERROR_REQUEST}: {exc}"
                    if exc.retryable:
                        expected_retryable_count = len(uri_chunk)
                        marked_retryable = store.mark_posts_retryable(
                            uri_chunk,
                            error_message=message,
                            attempted_at_iso=checked_at,
                        )
                        if marked_retryable != expected_retryable_count:
                            logger.warning(
                                "Retryable marking count mismatch expected=%d actual=%d",
                                expected_retryable_count,
                                marked_retryable,
                            )
                        counters.rows_marked_retryable += marked_retryable
                        cycle_retryable_marked += marked_retryable
                        logger.warning(
                            "Retryable getPosts failure for batch_size=%d: %s",
                            len(uri_chunk),
                            exc,
                        )
                    else:
                        expected_failed_count = len(uri_chunk)
                        marked_failed = store.mark_posts_failed(
                            uri_chunk,
                            hydrate_run_id=hydrate_run_id,
                            error_message=message,
                            attempted_at_iso=checked_at,
                        )
                        if marked_failed != expected_failed_count:
                            logger.warning(
                                "Failed marking count mismatch expected=%d actual=%d",
                                expected_failed_count,
                                marked_failed,
                            )
                        counters.rows_marked_failed += marked_failed
                        cycle_terminal_marked += marked_failed
                        store.update_hydrate_run_progress(hydrate_run_id, failed_delta=marked_failed)
                        logger.error(
                            "Non-retryable getPosts failure for batch_size=%d: %s",
                            len(uri_chunk),
                            exc,
                        )

                    current_claimed_uris.difference_update(uri_chunk)
                    continue

                hydrated_rows, normalization_failed_uris = _normalize_returned_rows(
                    hydrate_run_id=hydrate_run_id,
                    claim_by_uri=claim_by_uri,
                    returned_posts=batch_result.posts,
                    hydrated_at=checked_at,
                    logger=logger,
                )

                if hydrated_rows:
                    hydrated_writer.write_rows(hydrated_rows)
                    _persist_completed_files(
                        store=store,
                        hydrate_run_id=hydrate_run_id,
                        dataset_type="hydrated_posts",
                        completed_files=hydrated_writer.pop_completed_files(),
                    )

                    hydrated_uris = [row["uri"] for row in hydrated_rows if isinstance(row.get("uri"), str)]
                    expected_hydrated_count = len(hydrated_uris)
                    marked_hydrated = store.mark_posts_hydrated(
                        hydrated_uris,
                        hydrate_run_id=hydrate_run_id,
                        hydrated_at_iso=checked_at,
                    )
                    if marked_hydrated != expected_hydrated_count:
                        logger.warning(
                            "Hydrated marking count mismatch expected=%d actual=%d",
                            expected_hydrated_count,
                            marked_hydrated,
                        )
                    counters.hydrated_rows_written += len(hydrated_rows)
                    counters.rows_marked_hydrated += marked_hydrated
                    cycle_terminal_marked += marked_hydrated
                    store.update_hydrate_run_progress(hydrate_run_id, hydrated_delta=marked_hydrated)

                if normalization_failed_uris:
                    expected_failed_count = len(normalization_failed_uris)
                    marked_failed = store.mark_posts_failed(
                        normalization_failed_uris,
                        hydrate_run_id=hydrate_run_id,
                        error_message="normalize_hydrated_post failed",
                        attempted_at_iso=checked_at,
                    )
                    if marked_failed != expected_failed_count:
                        logger.warning(
                            "Normalization-failed marking mismatch expected=%d actual=%d",
                            expected_failed_count,
                            marked_failed,
                        )
                    counters.rows_marked_failed += marked_failed
                    cycle_terminal_marked += marked_failed
                    store.update_hydrate_run_progress(hydrate_run_id, failed_delta=marked_failed)

                missing_claims = [
                    claim_by_uri[uri]
                    for uri in batch_result.missing_uris
                    if uri in claim_by_uri
                ]
                counters.unresolved_uris += len(missing_claims)

                retryable_missing_uris: list[str] = []
                terminal_missing_claims: list[HydrationClaim] = []

                for missing_claim in missing_claims:
                    if missing_claim.attempt_count >= max_unresolved_attempts:
                        terminal_missing_claims.append(missing_claim)
                    else:
                        retryable_missing_uris.append(missing_claim.uri)

                if retryable_missing_uris:
                    expected_retryable_count = len(retryable_missing_uris)
                    marked_retryable = store.mark_posts_retryable(
                        retryable_missing_uris,
                        error_message=MISSING_REASON_NOT_RETURNED,
                        attempted_at_iso=checked_at,
                    )
                    if marked_retryable != expected_retryable_count:
                        logger.warning(
                            "Missing-retryable marking mismatch expected=%d actual=%d",
                            expected_retryable_count,
                            marked_retryable,
                        )
                    counters.rows_marked_retryable += marked_retryable
                    cycle_retryable_marked += marked_retryable

                if terminal_missing_claims:
                    miss_rows: list[dict[str, Any]] = []
                    miss_normalization_failed_uris: list[str] = []

                    for claim in terminal_missing_claims:
                        try:
                            miss_row = normalize_hydration_miss(
                                hydrate_run_id=hydrate_run_id,
                                capture_run_id=claim.capture_run_id,
                                uri=claim.uri,
                                cid_at_capture=claim.cid_at_capture,
                                captured_at=claim.captured_at,
                                attempt_count=claim.attempt_count,
                                reason=MISSING_REASON_NOT_RETURNED,
                                checked_at=checked_at,
                            )
                        except Exception as exc:
                            logger.warning("Failed to normalize miss row uri=%s: %s", claim.uri, exc)
                            miss_normalization_failed_uris.append(claim.uri)
                            continue

                        miss_rows.append(miss_row)

                    if miss_normalization_failed_uris:
                        expected_failed_count = len(miss_normalization_failed_uris)
                        marked_failed = store.mark_posts_failed(
                            miss_normalization_failed_uris,
                            hydrate_run_id=hydrate_run_id,
                            error_message="normalize_hydration_miss failed",
                            attempted_at_iso=checked_at,
                        )
                        if marked_failed != expected_failed_count:
                            logger.warning(
                                "Miss-normalization failed marking mismatch expected=%d actual=%d",
                                expected_failed_count,
                                marked_failed,
                            )
                        counters.rows_marked_failed += marked_failed
                        cycle_terminal_marked += marked_failed
                        store.update_hydrate_run_progress(hydrate_run_id, failed_delta=marked_failed)

                    if miss_rows:
                        miss_writer.write_rows(miss_rows)
                        _persist_completed_files(
                            store=store,
                            hydrate_run_id=hydrate_run_id,
                            dataset_type="hydration_misses",
                            completed_files=miss_writer.pop_completed_files(),
                        )

                        terminal_missing_uris = [row["uri"] for row in miss_rows if isinstance(row.get("uri"), str)]
                        expected_missing_count = len(terminal_missing_uris)
                        marked_missing = store.mark_posts_missing(
                            terminal_missing_uris,
                            hydrate_run_id=hydrate_run_id,
                            attempted_at_iso=checked_at,
                            reason=MISSING_REASON_NOT_RETURNED,
                        )
                        if marked_missing != expected_missing_count:
                            logger.warning(
                                "Missing marking count mismatch expected=%d actual=%d",
                                expected_missing_count,
                                marked_missing,
                            )
                        counters.rows_marked_missing += marked_missing
                        cycle_terminal_marked += marked_missing
                        store.update_hydrate_run_progress(hydrate_run_id, missing_delta=marked_missing)

                current_claimed_uris.difference_update(uri_chunk)

            if cycle_retryable_marked > 0 and cycle_terminal_marked == 0:
                if continue_polling:
                    logger.info(
                        "Retryable-only cycle detected; sleeping %.2fs before next poll.",
                        poll_interval_seconds,
                    )
                    time.sleep(max(0.0, poll_interval_seconds))
                else:
                    logger.info(
                        "Retryable-only cycle detected in one-shot mode; ending run to avoid hot retries."
                    )
                    run_completed = True
                    break

            hydrated_writer.flush()
            miss_writer.flush()
            _persist_completed_files(
                store=store,
                hydrate_run_id=hydrate_run_id,
                dataset_type="hydrated_posts",
                completed_files=hydrated_writer.pop_completed_files(),
            )
            _persist_completed_files(
                store=store,
                hydrate_run_id=hydrate_run_id,
                dataset_type="hydration_misses",
                completed_files=miss_writer.pop_completed_files(),
            )

            now = time.monotonic()
            if now - last_progress_log_at >= progress_log_interval:
                _log_progress(logger, counters, started_monotonic)
                last_progress_log_at = now

        exit_code = 0
        return exit_code

    except KeyboardInterrupt:
        failure_note = "Interrupted by user"
        logger.warning("Hydration interrupted by user")
        exit_code = 130
        return exit_code
    except Exception as exc:
        failure_note = str(exc)
        logger.exception("Hydration worker failed: %s", exc)
        exit_code = 1
        return exit_code
    finally:
        if current_claimed_uris and hydrate_run_id is not None:
            attempted_at = utc_now_iso()
            try:
                marked_retryable = store.mark_posts_retryable(
                    current_claimed_uris,
                    error_message="hydration worker shutdown before completion",
                    attempted_at_iso=attempted_at,
                )
                counters.rows_marked_retryable += marked_retryable
            except Exception:
                logger.exception("Failed to release outstanding claimed rows")

        if hydrated_writer is not None and hydrate_run_id is not None:
            try:
                completed_hydrated_files = hydrated_writer.close()
                _persist_completed_files(
                    store=store,
                    hydrate_run_id=hydrate_run_id,
                    dataset_type="hydrated_posts",
                    completed_files=completed_hydrated_files,
                )
            except Exception:
                run_completed = False
                failure_note = failure_note or "Failed to finalize hydrated writer"
                logger.exception("Hydrated writer finalization failed")

        if miss_writer is not None and hydrate_run_id is not None:
            try:
                completed_miss_files = miss_writer.close()
                _persist_completed_files(
                    store=store,
                    hydrate_run_id=hydrate_run_id,
                    dataset_type="hydration_misses",
                    completed_files=completed_miss_files,
                )
            except Exception:
                run_completed = False
                failure_note = failure_note or "Failed to finalize miss writer"
                logger.exception("Miss writer finalization failed")

        if hydrate_run_id is not None:
            try:
                if run_completed and exit_code == 0:
                    store.complete_hydrate_run(hydrate_run_id, status="completed")
                else:
                    if failure_note:
                        logger.error("Hydrate run failing: %s", failure_note)
                    store.fail_hydrate_run(hydrate_run_id)
            except Exception:
                logger.exception("Failed to update hydrate run terminal status")

        _log_progress(logger, counters, started_monotonic)
        store.close()


def _resolve_capture_run_id(store: SQLiteStore, requested_capture_run_id: str | None) -> str:
    """Resolve capture run ID for hydrate-run FK linkage."""

    if requested_capture_run_id is not None:
        if store.get_capture_run(requested_capture_run_id) is None:
            raise LookupError(f"Capture run not found: {requested_capture_run_id}")
        return requested_capture_run_id

    row = store.connect().execute(
        """
        SELECT capture_run_id
        FROM capture_runs
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError(
            "No capture runs found. Run firehose capture first or pass --capture-run-id."
        )
    return str(row["capture_run_id"])


def _normalize_returned_rows(
    *,
    hydrate_run_id: str,
    claim_by_uri: dict[str, HydrationClaim],
    returned_posts: Iterable[dict[str, Any]],
    hydrated_at: str,
    logger: logging.Logger,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize returned post views and collect per-row normalization failures."""

    hydrated_rows: list[dict[str, Any]] = []
    normalization_failed_uris: list[str] = []

    for post_view in returned_posts:
        uri = post_view.get("uri")
        if not isinstance(uri, str):
            continue
        claim = claim_by_uri.get(uri)
        if claim is None:
            continue

        try:
            row = normalize_hydrated_post(
                hydrate_run_id=hydrate_run_id,
                capture_run_id=claim.capture_run_id,
                post_view=post_view,
                hydrated_at=hydrated_at,
            )
        except Exception as exc:
            normalization_failed_uris.append(uri)
            logger.warning("Failed to normalize post uri=%s: %s", uri, exc)
            continue

        hydrated_rows.append(row)

    return hydrated_rows, normalization_failed_uris


def _persist_completed_files(
    *,
    store: SQLiteStore,
    hydrate_run_id: str,
    dataset_type: str,
    completed_files: Iterable[FinalizedBatchFile],
) -> None:
    """Persist finalized hydrate output files into SQLite `batch_files`."""

    for completed in completed_files:
        file_id = store.create_batch_file(
            job_type="hydrate",
            run_id=hydrate_run_id,
            dataset_type=dataset_type,
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


def _log_progress(logger: logging.Logger, counters: HydrationCounters, started_monotonic: float) -> None:
    """Emit standard progress metrics for the hydration worker."""

    elapsed = max(0.001, time.monotonic() - started_monotonic)
    requested_rate = counters.requested_uris / elapsed

    logger.info(
        "progress polls=%d idle=%d mature_pending=%d released_claims=%d claimed=%d "
        "request_batches=%d requested_uris=%d hydrated_rows_written=%d unresolved=%d "
        "state_hydrated=%d state_retryable=%d state_missing=%d state_failed=%d "
        "requested_per_sec=%.2f",
        counters.poll_cycles,
        counters.idle_polls,
        counters.mature_pending_rows,
        counters.expired_claims_released,
        counters.rows_claimed,
        counters.request_batches_sent,
        counters.requested_uris,
        counters.hydrated_rows_written,
        counters.unresolved_uris,
        counters.rows_marked_hydrated,
        counters.rows_marked_retryable,
        counters.rows_marked_missing,
        counters.rows_marked_failed,
        requested_rate,
    )


if __name__ == "__main__":
    raise SystemExit(main())
