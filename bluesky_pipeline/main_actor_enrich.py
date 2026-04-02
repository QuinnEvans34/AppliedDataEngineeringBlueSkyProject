"""Actor/profile enrichment worker entrypoint.

Phase 5 responsibilities:
- seed unique actor DIDs from existing captured pipeline state
- claim actor DIDs safely from SQLite
- request actor profile views from `app.bsky.actor.getProfiles`
- write normalized actor rows to rotating local `.jsonl.gz` files
- transition per-actor enrichment state and actor-run progress in SQLite
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from bluesky_pipeline.actor.client import ActorClient, ActorRequestError
from bluesky_pipeline.actor.normalizer import normalize_actor_profile
from bluesky_pipeline.actor.selector import ActorEnrichmentClaim, ActorSelector
from bluesky_pipeline.batching.writer import FinalizedBatchFile, GzipJsonlBatchWriter
from bluesky_pipeline.config import load_config
from bluesky_pipeline.logging_config import configure_logging
from bluesky_pipeline.state.sqlite_store import SQLiteStore
from bluesky_pipeline.utils.time_utils import utc_now_iso

MISSING_REASON_NOT_RETURNED = "not_returned_by_getProfiles"
RETRY_ERROR_REQUEST = "getProfiles request failed"


@dataclass(slots=True)
class ActorEnrichmentCounters:
    poll_cycles: int = 0
    idle_polls: int = 0
    seeded_from_hydrated: int = 0
    seeded_from_captured: int = 0
    seeded_total: int = 0
    pending_actor_rows: int = 0
    expired_claims_released: int = 0
    rows_claimed: int = 0
    request_batches_sent: int = 0
    requested_dids: int = 0
    enriched_rows_written: int = 0
    unresolved_dids: int = 0
    rows_marked_enriched: int = 0
    rows_marked_retryable: int = 0
    rows_marked_missing: int = 0
    rows_marked_failed: int = 0


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for actor enrichment worker."""

    parser = argparse.ArgumentParser(description="Bluesky actor enrichment job")
    parser.add_argument("--db-path", type=Path, default=Path("data/state/pipeline_state.db"))
    parser.add_argument("--log-path", type=Path, default=Path("data/logs/actor_enrich.log"))
    parser.add_argument("--worker-id", type=str, default=None)
    parser.add_argument("--actor-api-base-url", type=str, default=None)
    parser.add_argument("--get-profiles-path", type=str, default=None)
    parser.add_argument("--actor-output-dir", type=Path, default=None)
    parser.add_argument("--claim-batch-size", type=int, default=None)
    parser.add_argument("--claim-ttl-seconds", type=int, default=None)
    parser.add_argument("--request-batch-size", type=int, default=None)
    parser.add_argument("--request-timeout-seconds", type=float, default=None)
    parser.add_argument("--max-unresolved-attempts", type=int, default=None)
    parser.add_argument("--max-rows-per-file", type=int, default=None)
    parser.add_argument("--max-seconds-per-file", type=float, default=None)
    parser.add_argument("--poll-interval-seconds", type=float, default=None)
    parser.add_argument("--progress-log-interval-seconds", type=float, default=None)
    parser.add_argument("--continue-polling", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run actor enrichment worker loop until queue exhaustion or interruption."""

    args = build_parser().parse_args(argv)
    config = load_config()
    logger = configure_logging("actor_enrich", args.log_path)

    db_path = args.db_path
    actor_api_base_url = args.actor_api_base_url or config.actor.api_base_url
    get_profiles_path = args.get_profiles_path or config.actor.get_profiles_path
    claim_batch_size = (
        args.claim_batch_size if args.claim_batch_size is not None else config.actor.claim_batch_size
    )
    claim_ttl_seconds = (
        args.claim_ttl_seconds if args.claim_ttl_seconds is not None else config.actor.claim_ttl_seconds
    )
    request_batch_size = (
        args.request_batch_size if args.request_batch_size is not None else config.actor.request_batch_size
    )
    request_timeout_seconds = (
        args.request_timeout_seconds
        if args.request_timeout_seconds is not None
        else config.actor.request_timeout_seconds
    )
    max_unresolved_attempts = (
        args.max_unresolved_attempts
        if args.max_unresolved_attempts is not None
        else config.actor.max_unresolved_attempts
    )
    max_rows_per_file = args.max_rows_per_file or config.batching.flush_row_count
    max_seconds_per_file = args.max_seconds_per_file or float(config.batching.flush_interval_seconds)
    poll_interval_seconds = (
        args.poll_interval_seconds
        if args.poll_interval_seconds is not None
        else float(config.actor.poll_interval_seconds)
    )
    progress_log_interval = (
        args.progress_log_interval_seconds
        if args.progress_log_interval_seconds is not None
        else config.actor.progress_log_interval_seconds
    )
    continue_polling = bool(args.continue_polling or config.actor.continue_polling_when_idle)

    if claim_batch_size <= 0:
        raise ValueError("claim_batch_size must be > 0")
    if claim_ttl_seconds <= 0:
        raise ValueError("claim_ttl_seconds must be > 0")
    if request_batch_size <= 0:
        raise ValueError("request_batch_size must be > 0")
    if request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be > 0")
    if poll_interval_seconds < 0:
        raise ValueError("poll_interval_seconds must be >= 0")
    if progress_log_interval <= 0:
        raise ValueError("progress_log_interval_seconds must be > 0")
    if max_unresolved_attempts <= 0:
        raise ValueError("max_unresolved_attempts must be > 0")

    counters = ActorEnrichmentCounters()
    worker_id = args.worker_id or f"actor-enricher-{os.getpid()}"
    started_monotonic = time.monotonic()
    last_progress_log_at = started_monotonic

    store = SQLiteStore(db_path)
    actor_writer: GzipJsonlBatchWriter | None = None
    actor_run_id: str | None = None
    current_claimed_dids: set[str] = set()
    run_completed = False
    failure_note: str | None = None
    exit_code = 0

    logger.info("Starting actor enrichment worker")
    logger.info("Worker ID: %s", worker_id)
    logger.info("Actor endpoint: %s%s", actor_api_base_url, get_profiles_path)
    logger.info(
        "claim_batch_size=%d request_batch_size=%d continue_polling=%s",
        claim_batch_size,
        request_batch_size,
        continue_polling,
    )

    try:
        store.connect()
        store.ensure_schema()
        actor_run_id = store.create_actor_run()

        actor_output_dir = (args.actor_output_dir or config.paths.actor_profiles_dir) / actor_run_id
        actor_writer = GzipJsonlBatchWriter(
            output_dir=actor_output_dir,
            file_prefix="actor_profiles",
            max_rows_per_file=max_rows_per_file,
            max_seconds_per_file=max_seconds_per_file,
        )

        selector = ActorSelector(store=store, claim_ttl_seconds=claim_ttl_seconds)
        client = ActorClient(
            api_base_url=actor_api_base_url,
            get_profiles_path=get_profiles_path,
            max_actors_per_request=request_batch_size,
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

            seed_result = selector.seed_actor_dids()
            if seed_result.inserted_total > 0:
                counters.seeded_from_hydrated += seed_result.inserted_from_hydrated
                counters.seeded_from_captured += seed_result.inserted_from_captured
                counters.seeded_total += seed_result.inserted_total
                store.update_actor_run_progress(
                    actor_run_id,
                    seeded_delta=seed_result.inserted_total,
                )
                logger.info(
                    "Seeded actor DIDs hydrated=%d captured_fallback=%d total=%d",
                    seed_result.inserted_from_hydrated,
                    seed_result.inserted_from_captured,
                    seed_result.inserted_total,
                )

            released = selector.release_expired_claims()
            counters.expired_claims_released += released
            if released > 0:
                logger.info("Released %d expired actor claims", released)

            counters.pending_actor_rows = selector.count_pending_actor_dids()
            claims = selector.claim_actor_dids(worker_id=worker_id, limit=claim_batch_size)

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
                logger.info("No actor DIDs remain eligible; actor enrichment run is complete.")
                break

            store.update_actor_run_progress(actor_run_id, eligible_delta=len(claims))
            counters.rows_claimed += len(claims)

            claim_by_did = {claim.did: claim for claim in claims}
            claimed_dids = [claim.did for claim in claims]
            current_claimed_dids = set(claimed_dids)

            for did_chunk in client.chunk_dids(claimed_dids):
                counters.request_batches_sent += 1
                counters.requested_dids += len(did_chunk)
                checked_at = utc_now_iso()

                try:
                    batch_result = client.get_profiles(did_chunk)
                except ActorRequestError as exc:
                    message = f"{RETRY_ERROR_REQUEST}: {exc}"
                    if exc.retryable:
                        expected_retryable_count = len(did_chunk)
                        marked_retryable = store.mark_actors_retryable(
                            did_chunk,
                            error_message=message,
                            attempted_at_iso=checked_at,
                        )
                        if marked_retryable != expected_retryable_count:
                            logger.warning(
                                "Retryable actor marking count mismatch expected=%d actual=%d",
                                expected_retryable_count,
                                marked_retryable,
                            )
                        counters.rows_marked_retryable += marked_retryable
                        cycle_retryable_marked += marked_retryable
                        logger.warning(
                            "Retryable getProfiles failure for batch_size=%d: %s",
                            len(did_chunk),
                            exc,
                        )
                    else:
                        expected_failed_count = len(did_chunk)
                        marked_failed = store.mark_actors_failed(
                            did_chunk,
                            actor_run_id=actor_run_id,
                            error_message=message,
                            attempted_at_iso=checked_at,
                        )
                        if marked_failed != expected_failed_count:
                            logger.warning(
                                "Failed actor marking count mismatch expected=%d actual=%d",
                                expected_failed_count,
                                marked_failed,
                            )
                        counters.rows_marked_failed += marked_failed
                        cycle_terminal_marked += marked_failed
                        store.update_actor_run_progress(actor_run_id, failed_delta=marked_failed)
                        logger.error(
                            "Non-retryable getProfiles failure for batch_size=%d: %s",
                            len(did_chunk),
                            exc,
                        )

                    current_claimed_dids.difference_update(did_chunk)
                    continue

                actor_rows, normalization_failed_dids = _normalize_returned_rows(
                    actor_run_id=actor_run_id,
                    claim_by_did=claim_by_did,
                    returned_profiles=batch_result.profiles,
                    enriched_at=checked_at,
                    logger=logger,
                )

                if actor_rows:
                    actor_writer.write_rows(actor_rows)
                    _persist_completed_files(
                        store=store,
                        actor_run_id=actor_run_id,
                        completed_files=actor_writer.pop_completed_files(),
                    )

                    enriched_dids = [row["did"] for row in actor_rows if isinstance(row.get("did"), str)]
                    expected_enriched_count = len(enriched_dids)
                    marked_enriched = store.mark_actors_enriched(
                        enriched_dids,
                        actor_run_id=actor_run_id,
                        enriched_at_iso=checked_at,
                    )
                    if marked_enriched != expected_enriched_count:
                        logger.warning(
                            "Enriched actor marking count mismatch expected=%d actual=%d",
                            expected_enriched_count,
                            marked_enriched,
                        )
                    counters.enriched_rows_written += len(actor_rows)
                    counters.rows_marked_enriched += marked_enriched
                    cycle_terminal_marked += marked_enriched
                    store.update_actor_run_progress(actor_run_id, enriched_delta=marked_enriched)

                if normalization_failed_dids:
                    expected_failed_count = len(normalization_failed_dids)
                    marked_failed = store.mark_actors_failed(
                        normalization_failed_dids,
                        actor_run_id=actor_run_id,
                        error_message="normalize_actor_profile failed",
                        attempted_at_iso=checked_at,
                    )
                    if marked_failed != expected_failed_count:
                        logger.warning(
                            "Normalization-failed actor marking mismatch expected=%d actual=%d",
                            expected_failed_count,
                            marked_failed,
                        )
                    counters.rows_marked_failed += marked_failed
                    cycle_terminal_marked += marked_failed
                    store.update_actor_run_progress(actor_run_id, failed_delta=marked_failed)

                missing_claims = [claim_by_did[did] for did in batch_result.missing_dids if did in claim_by_did]
                counters.unresolved_dids += len(missing_claims)

                retryable_missing_dids: list[str] = []
                terminal_missing_dids: list[str] = []
                for missing_claim in missing_claims:
                    if missing_claim.attempt_count >= max_unresolved_attempts:
                        terminal_missing_dids.append(missing_claim.did)
                    else:
                        retryable_missing_dids.append(missing_claim.did)

                if retryable_missing_dids:
                    expected_retryable_count = len(retryable_missing_dids)
                    marked_retryable = store.mark_actors_retryable(
                        retryable_missing_dids,
                        error_message=MISSING_REASON_NOT_RETURNED,
                        attempted_at_iso=checked_at,
                    )
                    if marked_retryable != expected_retryable_count:
                        logger.warning(
                            "Missing-retryable actor marking mismatch expected=%d actual=%d",
                            expected_retryable_count,
                            marked_retryable,
                        )
                    counters.rows_marked_retryable += marked_retryable
                    cycle_retryable_marked += marked_retryable

                if terminal_missing_dids:
                    expected_missing_count = len(terminal_missing_dids)
                    marked_missing = store.mark_actors_missing(
                        terminal_missing_dids,
                        actor_run_id=actor_run_id,
                        attempted_at_iso=checked_at,
                        reason=MISSING_REASON_NOT_RETURNED,
                    )
                    if marked_missing != expected_missing_count:
                        logger.warning(
                            "Missing actor marking count mismatch expected=%d actual=%d",
                            expected_missing_count,
                            marked_missing,
                        )
                    counters.rows_marked_missing += marked_missing
                    cycle_terminal_marked += marked_missing
                    store.update_actor_run_progress(actor_run_id, missing_delta=marked_missing)

                current_claimed_dids.difference_update(did_chunk)

            if cycle_retryable_marked > 0 and cycle_terminal_marked == 0:
                if continue_polling:
                    logger.info(
                        "Retryable-only actor cycle detected; sleeping %.2fs before next poll.",
                        poll_interval_seconds,
                    )
                    time.sleep(max(0.0, poll_interval_seconds))
                else:
                    logger.info(
                        "Retryable-only actor cycle detected in one-shot mode; ending run to avoid hot retries."
                    )
                    run_completed = True
                    break

            actor_writer.flush()
            _persist_completed_files(
                store=store,
                actor_run_id=actor_run_id,
                completed_files=actor_writer.pop_completed_files(),
            )

            now = time.monotonic()
            if now - last_progress_log_at >= progress_log_interval:
                _log_progress(logger, counters, started_monotonic)
                last_progress_log_at = now

        exit_code = 0
        return exit_code
    except KeyboardInterrupt:
        failure_note = "Interrupted by user"
        logger.warning("Actor enrichment interrupted by user")
        exit_code = 130
        return exit_code
    except Exception as exc:
        failure_note = str(exc)
        logger.exception("Actor enrichment worker failed: %s", exc)
        exit_code = 1
        return exit_code
    finally:
        if current_claimed_dids and actor_run_id is not None:
            attempted_at = utc_now_iso()
            try:
                marked_retryable = store.mark_actors_retryable(
                    current_claimed_dids,
                    error_message="actor enrichment worker shutdown before completion",
                    attempted_at_iso=attempted_at,
                )
                counters.rows_marked_retryable += marked_retryable
            except Exception:
                logger.exception("Failed to release outstanding claimed actor rows")

        if actor_writer is not None and actor_run_id is not None:
            try:
                completed_actor_files = actor_writer.close()
                _persist_completed_files(
                    store=store,
                    actor_run_id=actor_run_id,
                    completed_files=completed_actor_files,
                )
            except Exception:
                run_completed = False
                failure_note = failure_note or "Failed to finalize actor writer"
                logger.exception("Actor writer finalization failed")

        if actor_run_id is not None:
            try:
                if run_completed and exit_code == 0:
                    store.complete_actor_run(actor_run_id, status="completed")
                else:
                    if failure_note:
                        logger.error("Actor run failing: %s", failure_note)
                    store.fail_actor_run(actor_run_id, notes=failure_note)
            except Exception:
                logger.exception("Failed to update actor run terminal status")

        _log_progress(logger, counters, started_monotonic)
        store.close()


def _normalize_returned_rows(
    *,
    actor_run_id: str,
    claim_by_did: dict[str, ActorEnrichmentClaim],
    returned_profiles: Iterable[dict[str, Any]],
    enriched_at: str,
    logger: logging.Logger,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize returned profile views and collect per-row normalization failures."""

    actor_rows: list[dict[str, Any]] = []
    normalization_failed_dids: list[str] = []

    for profile_view in returned_profiles:
        did = profile_view.get("did")
        if not isinstance(did, str):
            continue
        claim = claim_by_did.get(did)
        if claim is None:
            continue

        try:
            row = normalize_actor_profile(
                actor_run_id=actor_run_id,
                profile_view=profile_view,
                enriched_at=enriched_at,
            )
        except Exception as exc:
            normalization_failed_dids.append(did)
            logger.warning("Failed to normalize actor did=%s: %s", did, exc)
            continue

        actor_rows.append(row)

    return actor_rows, normalization_failed_dids


def _persist_completed_files(
    *,
    store: SQLiteStore,
    actor_run_id: str,
    completed_files: Iterable[FinalizedBatchFile],
) -> None:
    """Persist finalized actor output files into SQLite `batch_files`."""

    for completed in completed_files:
        file_id = store.create_batch_file(
            job_type="actor",
            run_id=actor_run_id,
            dataset_type="actor_profiles",
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
    counters: ActorEnrichmentCounters,
    started_monotonic: float,
) -> None:
    """Emit standard progress metrics for actor enrichment worker."""

    elapsed = max(0.001, time.monotonic() - started_monotonic)
    requested_rate = counters.requested_dids / elapsed

    logger.info(
        "progress polls=%d idle=%d seeded_hydrated=%d seeded_captured=%d seeded_total=%d "
        "pending=%d released_claims=%d claimed=%d request_batches=%d requested_dids=%d "
        "enriched_rows_written=%d unresolved=%d state_enriched=%d state_retryable=%d "
        "state_missing=%d state_failed=%d requested_per_sec=%.2f",
        counters.poll_cycles,
        counters.idle_polls,
        counters.seeded_from_hydrated,
        counters.seeded_from_captured,
        counters.seeded_total,
        counters.pending_actor_rows,
        counters.expired_claims_released,
        counters.rows_claimed,
        counters.request_batches_sent,
        counters.requested_dids,
        counters.enriched_rows_written,
        counters.unresolved_dids,
        counters.rows_marked_enriched,
        counters.rows_marked_retryable,
        counters.rows_marked_missing,
        counters.rows_marked_failed,
        requested_rate,
    )


if __name__ == "__main__":
    raise SystemExit(main())

