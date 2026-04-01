# SQLite Schema and State-Transition Spec (Phase 1)

## Purpose

This document defines the initial SQLite control-plane schema for the Bluesky
pipeline and the expected hydration state transitions. It is intentionally
limited to scaffolding contracts and does not define full SQL workflows yet.

## Tables

### `capture_runs`
Tracks firehose capture job runs.

Columns:
- `capture_run_id` (`TEXT`, PK): unique run identifier.
- `started_at` (`TEXT`, not null): UTC ISO timestamp run started.
- `completed_at` (`TEXT`, nullable): UTC ISO timestamp run finished.
- `status` (`TEXT`, not null): run lifecycle status (e.g., `running`, `completed`, `failed`).
- `target_post_count` (`INTEGER`, not null): configured unique URI target.
- `written_post_count` (`INTEGER`, not null, default 0): unique rows written.
- `last_seq_seen` (`INTEGER`, nullable): latest sequence observed.
- `notes` (`TEXT`, nullable): diagnostic notes.

### `hydrate_runs`
Tracks hydration worker runs.

Columns:
- `hydrate_run_id` (`TEXT`, PK): unique hydration run identifier.
- `capture_run_id` (`TEXT`, not null, FK -> `capture_runs.capture_run_id`): associated capture lineage.
- `started_at` (`TEXT`, not null): UTC ISO timestamp run started.
- `completed_at` (`TEXT`, nullable): UTC ISO timestamp run finished.
- `status` (`TEXT`, not null): run lifecycle status.
- `eligible_post_count` (`INTEGER`, not null, default 0): total rows eligible this run.
- `hydrated_post_count` (`INTEGER`, not null, default 0): successful hydrations.
- `missing_post_count` (`INTEGER`, not null, default 0): terminal misses.
- `failed_post_count` (`INTEGER`, not null, default 0): terminal failures.

### `batch_files`
Tracks each local output file produced by either job.

Columns:
- `file_id` (`INTEGER`, PK AUTOINCREMENT): file identity.
- `job_type` (`TEXT`, not null): `firehose` or `hydrate`.
- `run_id` (`TEXT`, not null): owning run identifier.
- `dataset_type` (`TEXT`, not null): `raw_posts`, `hydrated_posts`, or `hydration_misses`.
- `local_path` (`TEXT`, not null, unique): absolute or repo-relative file path.
- `row_count` (`INTEGER`, not null, default 0): rows written.
- `byte_size` (`INTEGER`, not null, default 0): file size at close.
- `status` (`TEXT`, not null): lifecycle state such as `open`, `closed`, `failed`.
- `created_at` (`TEXT`, not null): UTC ISO timestamp created.
- `closed_at` (`TEXT`, nullable): UTC ISO timestamp finalized.

### `captured_posts`
Tracks per-URI capture and hydration lifecycle.

Columns:
- `uri` (`TEXT`, PK): dedupe and primary join key.
- `capture_run_id` (`TEXT`, not null, FK -> `capture_runs.capture_run_id`): originating run.
- `repo_did` (`TEXT`, not null): actor DID.
- `rkey` (`TEXT`, not null): record key.
- `cid_at_capture` (`TEXT`, nullable): CID observed during capture.
- `seq` (`INTEGER`, nullable): firehose sequence for observability.
- `record_created_at` (`TEXT`, nullable): post record creation timestamp.
- `captured_at` (`TEXT`, not null): UTC ISO timestamp when captured.
- `capture_file_id` (`INTEGER`, nullable, FK -> `batch_files.file_id`): source raw file.
- `hydration_status` (`TEXT`, not null, default `pending`): lifecycle state.
- `hydration_attempt_count` (`INTEGER`, not null, default 0): hydration attempts.
- `last_hydration_attempt_at` (`TEXT`, nullable): latest hydration attempt timestamp.
- `hydrated_at` (`TEXT`, nullable): timestamp hydrated successfully.
- `hydrate_run_id` (`TEXT`, nullable, FK -> `hydrate_runs.hydrate_run_id`): last hydrate run touching row.
- `last_error` (`TEXT`, nullable): latest failure message.
- `claimed_by_worker` (`TEXT`, nullable): worker identifier holding claim.
- `claim_expires_at` (`TEXT`, nullable): claim expiry for recovery.

Constraint:
- `hydration_status` CHECK in set:
  - `pending`
  - `claimed`
  - `hydrated`
  - `retryable`
  - `missing`
  - `failed`

## Indexing Strategy (Phase 1)

Implemented indexes prioritize hydration polling and claim recovery:
- `captured_posts(hydration_status, captured_at)` for maturity + state scanning.
- `captured_posts(claim_expires_at)` for expired claim cleanup.
- `captured_posts(hydrate_run_id, hydration_status)` for run-level audit/reporting.
- supporting run/file lookup indexes on `capture_runs`, `hydrate_runs`, and `batch_files`.

## Hydration State Transition Model

Allowed transitions for implementation:
- `pending -> claimed -> hydrated`
- `pending -> retryable`
- `claimed -> retryable`
- `retryable -> claimed`
- `claimed -> missing`
- `retryable -> missing`
- `claimed -> failed`
- `retryable -> failed`

Terminal states:
- `hydrated`
- `missing`
- `failed`

Rows in terminal states should not be selected again unless explicitly reset by
future maintenance tooling.

## Claim Timeout and Retry Expectations

Expected behavior contract for future hydrator implementation:
- Claim operation sets `claimed_by_worker` and `claim_expires_at`.
- If a claim expires before completion, the row becomes eligible for recovery.
- Recovery should clear stale claim ownership and return row to a non-terminal
  retryable path (`retryable` preferred, or `pending` based on policy).
- Every failed hydration attempt should increment `hydration_attempt_count` and
  set `last_hydration_attempt_at`.

## Non-Goals for Phase 1

Phase 1 does not include:
- Full SQL claiming/releasing implementation.
- Retry execution engine.
- Trigger-based transition enforcement.
- API integration or firehose decoding.
- Snowflake or downstream warehouse logic.
