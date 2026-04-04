# 34 Large-Scale Run Readiness and Delayed-Hydration Plan Findings

Date: 2026-04-04  
Mode: local readiness audit only (`0` Snowflake queries, `0` firehose reruns, `0` hydration reruns)

## 1) Executive Summary
- The capture/hydration/actor pipeline is **operationally ready** for a large run if executed with a fresh run root + run-specific SQLite DB.
- Delayed hydration is **already supported operationally** (capture first, then hydrate later against the same DB and `capture_run_id`).
- The major prior failure mode (premature hydration) is sequencing/operations, not hydration code correctness.
- For the next real run, the recommended sequence is: **capture -> wait >=24h -> hydrate -> actor enrichment -> downstream phases**.
- Remaining risks are real but manageable:
  - capture is not first-class resumable to the same `capture_run_id` after interruption,
  - repeated re-hydration of already-hydrated posts is not first-class,
  - Phase 26 currently loads one hydrated shard (known downstream quality limiter).

## 2) Capture-Path Readiness

### Confirmed capabilities
- Capture entrypoint: `bluesky_pipeline/main_firehose.py`.
- Run-state tracking exists in SQLite (`capture_runs`, `captured_posts`, `batch_files`).
- Raw output run-root layout is run-isolated:
  - `--raw-output-dir <base>/raw_posts` + auto subdir `<capture_run_id>/raw_posts_*.jsonl.gz`.
- File rollover is implemented and tested in writer logic:
  - rotate by row/time (`max_rows_per_file`, `max_seconds_per_file`) via `GzipJsonlBatchWriter`.
- Deduplication is enforced by `captured_posts.uri` PK (`insert_captured_post ... ON CONFLICT DO NOTHING`).
- Firehose transport has reconnect/backoff behavior (`bluesky_pipeline/firehose/client.py`).
- Dependency fail-fast exists for live firehose mode (`_validate_live_firehose_dependencies`).

### Confirmed limitations
- Capture resumes are not first-class on the same run ID:
  - `main_firehose` always creates a new `capture_run_id` (no resume flag).
  - interrupted runs become `failed`; reopening same run is not supported by existing lifecycle methods.

### Readiness assessment
- **Usable for 1M capture** with stable runtime conditions and run-specific DB isolation.
- **Operational caution**: interruption/restart requires operator-managed recovery strategy (documented in checklist/runbook).

## 3) Identifier/State Preservation

### Confirmed capabilities
Identifiers needed for delayed hydration and joins are preserved:
- Raw capture row fields include:
  - `uri`, `repo_did`, `rkey`, `cid`, `record_created_at`, `captured_at`, `capture_run_id`.
- Control-plane state (`captured_posts`) preserves:
  - hydration lifecycle fields (`hydration_status`, `hydration_attempt_count`, `hydrate_run_id`, `hydrated_at`, claim metadata).
- Hydrated row fields include:
  - `uri`, `capture_run_id`, `hydrate_run_id`, `author_did`, `author_handle`, engagement counts, timestamps.
- Actor row fields include:
  - `did`, `handle`, counts, `actor_run_id`, timestamps.

Observed DB evidence (local existing runs):
- Completed diagnostic capture/hydrate run:
  - `cap_20260401T184939Z_85c99020` (`written_post_count=25`, status `completed`)
  - `hyd_20260401T185109Z_97b40e6f` linked to that capture run (`hydrated_post_count=25`, status `completed`).

### Assessment
- Identifier/state preservation is sufficient for delayed hydration and downstream joins.

## 4) Hydration Sequencing Readiness

### Confirmed capabilities
- Hydration can target earlier captured corpus via `--capture-run-id` on `main_hydrate`.
- Maturity gating exists (`captured_at <= cutoff`) with production default `maturity_hours=24`.
- Hydration completion checks exist (`scripts/ops/stage_drain.py check-hydration`) requiring:
  - capture run completed,
  - all rows mature,
  - no mature `pending/retryable`,
  - no claimed rows in-flight.
- Repeated one-shot drain orchestration exists (`drain-hydration`) for reliable completion.
- Retry/miss handling is implemented (retryable/failed/missing transitions + miss files).

Observed command evidence:
- Completed run check passes: `HYDRATION_COMPLETE=1` for diagnostic run.
- Incomplete run check blocks as expected when capture not complete/pending remain: `HYDRATION_COMPLETE=0` on validation DB.

### Confirmed limitations
- Delayed hydration: **yes, supported now**.
- Re-hydrating already `hydrated` posts later for refreshed engagement: **not first-class supported**.
  - Claim selection only includes `pending`/`retryable`; `hydrated` rows are terminal in current flow.

### Assessment
- Pipeline is ready for single delayed hydration pass on a prior capture run.
- Optional multi-pass refresh requires a small additional operational mechanism (not required for immediate launch).

## 5) Recommended Next-Run Sequencing

### Confirmed-safe sequence
1. Capture to target (~1M) on fresh run root + fresh DB.
2. After capture completes, wait before hydration (minimum 24h from capture completion).
3. Run hydration drain with explicit `capture_run_id` and production maturity window.
4. Run actor drain after hydration completion.
5. Validate raw/hydrated/actor artifacts.
6. Only then run downstream phases 23-27 against that run root.

### Recommendation (evidence-based)
- Minimum delay: **24h** (matches built-in production safety defaults and directly addresses the observed premature-hydration failure mode).
- Conservative option for stronger signal: hydrate after **24-36h** if schedule allows.
- Optional later hydrate pass(es): defer for now unless a small requeue mechanism is added.

## 6) Remaining Gaps / Readiness Adjustments

### Confirmed gaps
1. Capture resumability is operational, not first-class.
2. Multi-pass hydration refresh is not first-class for already hydrated rows.
3. Downstream Phase 26 still selects one hydrated shard (known from Phase 32/33), reducing engagement join coverage.

### Impact classification
- Gap 1: medium operational risk for long runs.
- Gap 2: low immediate risk (optional feature), medium future quality risk.
- Gap 3: not a launch blocker for collection/hydration, but a quality risk before final modeling.

### Fixes made in this phase
- Added a practical runbook for delayed-hydration launch execution and gates:
  - `docs/34_large_scale_run_runbook.md`

(No code refactor was required for immediate launch readiness.)

## 7) Pre-Run Checklist (Blunt)

### Required config/env
- Python env active; dependencies installed from `requirements.txt`.
- Use fresh run root and fresh DB:
  - `data/output/<run_tag>/{raw_posts,hydrated_posts,hydration_misses,actor_profiles,logs,state,exports}`.
- Use explicit `capture_run_id` for hydration checks/drains.

### Commands/tools you will use
- `python3 -m bluesky_pipeline.main_firehose`
- `python3 scripts/ops/stage_drain.py check-hydration|drain-hydration|check-actor|drain-actor`
- `python3 -m bluesky_pipeline.main_inspect files|validate`

### Do not run too early
- Do **not** run hydration immediately after capture.
- Do **not** use `--maturity-hours 0` for production run.
- Do **not** run phases 23-27 before hydration + actor completion checks pass.

### Validate after capture, before hydration
- Capture run status is `completed` and row count is sane.
- Raw artifacts exist/validate.
- Record `capture_run_id` from DB.
- Confirm delay window has elapsed.

### Validate before hydration
- Run `check-hydration` with explicit `capture_run_id` and production maturity.
- Confirm no path misconfiguration (output under chosen run root).

### Validate before downstream phases
- `check-hydration` returns complete.
- `check-actor` returns complete.
- `main_inspect validate` passes for raw/hydrated/actor.
- Set `BLUESKY_SOURCE_ROOT` to the run root for phases 23/26 notebook workflows.

## 8) Final Readiness Verdict
- **Verdict: ready to run as-is for the next large run, with strict sequencing discipline.**
- Delayed hydration is operationally supported now.
- Safe launch tomorrow/next day is reasonable if the runbook checklist is followed and hydration is not triggered early.
- Optional multi-pass hydration refresh is not first-class yet; treat as a post-launch improvement, not a pre-launch blocker.
