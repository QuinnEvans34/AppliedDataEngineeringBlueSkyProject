# Phase 5 Hydration Hardening Audit

Date: 2026-04-01

## Current Phase 4 status
Phase 4 hydration implementation was present and functional before this work:
- Real `getPosts` client
- Mature selection and claim handling
- Hydrated/miss normalization
- Main orchestration loop and output writing
- SQLite state transitions and batch file persistence
- Basic mocked validation

## What was verified
Code audit covered:
- `bluesky_pipeline/hydrate/client.py`
- `bluesky_pipeline/hydrate/selector.py`
- `bluesky_pipeline/hydrate/normalizer.py`
- `bluesky_pipeline/main_hydrate.py`
- `bluesky_pipeline/config.py`

Behavior verified during this phase:
- 25-URI request cap and chunking behavior
- Retry/backoff paths and retryable classification
- Selector maturity cutoff and claim expiration release
- Normalized hydrated and miss row shapes
- Orchestration handling of hydrated/retryable/missing/failed transitions
- Interrupt shutdown path releasing outstanding claimed rows
- Batch file creation/close tracking and output writing

## Reliability risks found
1. Retryable-only loops could hot-spin in one-shot mode.
- If a cycle produced only retryable outcomes (for example repeated transient request failures), rows could be reclaimed again immediately in the same run and repeatedly increment attempts.

2. Miss-row normalization failures were not isolated.
- A miss row normalization error could fail the whole run instead of isolating the bad row.

3. Progress/state update mismatches were not visible.
- Marking functions return row counts, but mismatches vs expected counts were not logged.

4. Logger handler lifecycle leaked file handles in repeated same-process runs.
- Existing logger reconfiguration cleared handlers without closing them first.

## Changes made in Phase 5
### Hydration orchestration hardening
Updated `bluesky_pipeline/main_hydrate.py`:
- Added startup validation for key numeric settings:
  - `claim_batch_size > 0`
  - `request_batch_size > 0`
  - `progress_log_interval_seconds > 0`
  - `max_unresolved_attempts > 0`
  - `poll_interval_seconds >= 0`
- Added per-cycle retryable/terminal counters.
- Added one-shot retryable-only guard:
  - if cycle has retryable outcomes and no terminal outcomes, end run cleanly in one-shot mode to avoid hot retries.
  - in continuous mode, sleep `poll_interval_seconds` before next poll.
- Added count-mismatch warnings for:
  - `mark_posts_hydrated`
  - `mark_posts_retryable`
  - `mark_posts_missing`
  - `mark_posts_failed`
- Isolated miss normalization failures:
  - bad miss rows are logged and their URIs are marked `failed` instead of crashing the worker.

### Logging robustness
Updated `bluesky_pipeline/logging_config.py`:
- Existing handlers are now explicitly closed before removal when reconfiguring a logger.

## Files changed
Code:
- `bluesky_pipeline/main_hydrate.py`
- `bluesky_pipeline/logging_config.py`

Tests added:
- `tests/test_hydrate_client.py`
- `tests/test_hydrate_selector.py`
- `tests/test_hydrate_normalizer.py`
- `tests/test_main_hydrate.py`

Documentation:
- `docs/phase5_hydration_hardening.md`

## Tests added
### Client tests
`tests/test_hydrate_client.py`
- URI chunking at 25/request
- Response filtering + missing set-difference behavior
- Retryable errors retried
- Non-retryable errors not retried
- HTTP classification:
  - `429` retryable
  - `5xx` retryable
  - `400` non-retryable
- Transport timeout (`URLError`) retryable
- Invalid JSON response retryable

### Selector tests
`tests/test_hydrate_selector.py`
- Maturity cutoff selection from `captured_at`
- Claim behavior and attempt increment
- Expired claim release back to `pending`

### Normalizer tests
`tests/test_hydrate_normalizer.py`
- Hydrated row normalization fields and int coercion
- Miss row normalization fields

### Orchestration integration tests
`tests/test_main_hydrate.py`
- Partial success + missing escalation (`attempt_count >= 3 -> missing`)
- Partial batch success + retryable request failure behavior
- Non-retryable request error -> per-post `failed` transition
- Clean shutdown/interrupt releases outstanding claims to `retryable`
- Run-level counter and status checks
- Output row-count checks in gzip JSONL files

## Validation performed
1. Compilation checks
- `python3 -m compileall tests bluesky_pipeline/main_hydrate.py`
- `python3 -m compileall bluesky_pipeline/logging_config.py tests/test_main_hydrate.py`

2. Automated test suite
- Command: `python3 -m unittest discover -s tests -v`
- Result: `17` tests, all passed.

3. Larger mocked soak-style run
- Seeded `80` mature captured posts.
- Mocked client hydrated even-indexed URIs; odd-indexed unresolved.
- `10` rows started at attempt `2` to exercise missing escalation.
- Run output:
  - exit code: `0`
  - status counts: `hydrated=40`, `missing=5`, `retryable=35`
  - hydrate run: `completed`, `eligible_post_count=115`, `hydrated_post_count=40`, `missing_post_count=5`, `failed_post_count=0`
  - batch files persisted: `3`

## Results
- Hydration pipeline now has stronger recovery behavior for retryable-only cycles.
- Miss-row normalization is isolated and no longer an all-or-nothing failure.
- State update mismatches are surfaced via logs.
- Logger handler lifecycle no longer leaks file descriptors in repeated in-process runs.
- Automated test coverage now exists for core hydration reliability paths and orchestration scenarios.

## Remaining risks / open issues
1. Retry scheduling has no time-based backoff in DB state.
- Retryable rows are deferred to future runs by policy, but there is no `next_attempt_at` field.
- True scheduler-grade retry pacing would require broader control-plane design changes.

2. Run-level `eligible_post_count` tracks claims, not unique URIs.
- Multiple claims of the same URI across retries increase this count.
- This is consistent with current implementation but should be documented as claim-volume, not unique-post count.

3. Single-process orchestration assumptions remain.
- The design is still optimized for simple worker operation, not high-contention multi-worker deployment.

## Recommendation: ready or not ready for Phase 6
Recommendation: **Ready for Phase 6** with the above known constraints documented.

Reasoning:
- Core hydration correctness, safety, and recovery behavior are materially improved.
- Automated tests now cover critical client/selector/normalizer/orchestration paths.
- Larger mocked run demonstrated stable behavior under mixed outcomes and chunked processing.

## Exact next steps
1. Use the new test suite as a merge gate for hydration changes.
2. If Phase 6 includes reliability expansion, evaluate whether DB-level retry scheduling (`next_attempt_at`) is required.
3. Clarify semantics of hydrate run counters (`eligible_post_count` as claim count) in operational docs.
4. Add one real public-endpoint smoke validation against a small mature sample before production-scale runs.
