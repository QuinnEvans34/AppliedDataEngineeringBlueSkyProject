# Full Architecture Handoff (Code-Grounded)

This handoff is based on direct inspection of this repo's code, tests, docs, and sample artifacts as of 2026-04-02.

## 1. Project purpose

This project is a local-first Bluesky data pipeline that captures post-create events from the ATProto firehose, then enriches those captured posts later via Bluesky public APIs.

End-to-end goal shown in code and docs:
- Ingest post-level raw events from firehose.
- Persist normalized raw rows to rotating `jsonl.gz` files.
- Track per-run/per-post state in SQLite.
- Hydrate captured posts later (engagement metrics + author fields) via `app.bsky.feed.getPosts`.
- Enrich actor/profile data via `app.bsky.actor.getProfiles`.
- Provide QA/inspection/export tooling for local validation.

Inputs:
- Live firehose websocket frames (`com.atproto.sync.subscribeRepos`) in [`bluesky_pipeline/main_firehose.py`](../bluesky_pipeline/main_firehose.py) + [`bluesky_pipeline/firehose/client.py`](../bluesky_pipeline/firehose/client.py).
- Existing captured post state in SQLite for hydration/actor jobs in [`bluesky_pipeline/state/sqlite_store.py`](../bluesky_pipeline/state/sqlite_store.py).

What hydration/enrichment does:
- Hydration adds delayed post-view fields: reply/repost/like/quote counts plus hydrated author fields and hydrated record snapshot in [`bluesky_pipeline/hydrate/normalizer.py`](../bluesky_pipeline/hydrate/normalizer.py).
- Actor enrichment adds DID-level profile metrics and full profile snapshot in [`bluesky_pipeline/actor/normalizer.py`](../bluesky_pipeline/actor/normalizer.py).

Current outputs:
- Raw post dataset (`raw_posts_*.jsonl.gz`).
- Hydrated post dataset (`hydrated_posts_*.jsonl.gz`).
- Hydration misses dataset (`hydration_misses_*.jsonl.gz`).
- Actor profiles dataset (`actor_profiles_*.jsonl.gz`).
- SQLite control-plane state DB.
- Logs.
- Optional inspection exports/profiles via inspect CLI.

Likely downstream purpose (explicit in docs, not implemented in code here):
- Build ML-ready analytics/features using raw publish-time features + delayed engagement labels + author enrichment, then load/join downstream outside this repo (see [`docs/07_feature_contract_and_weekend_runbook.md`](./07_feature_contract_and_weekend_runbook.md)).

## 2. End-to-end pipeline flow

1. Firehose ingestion starts:
- Entrypoint: [`bluesky_pipeline/main_firehose.py`](../bluesky_pipeline/main_firehose.py).
- Opens SQLite store, ensures schema, creates `capture_runs` row.
- Creates `GzipJsonlBatchWriter` for run-specific raw output folder.

2. Frame receive/decode/extract:
- `FirehoseClient.iter_frames()` in [`bluesky_pipeline/firehose/client.py`](../bluesky_pipeline/firehose/client.py).
- `decode_frame()` in [`bluesky_pipeline/firehose/decoder.py`](../bluesky_pipeline/firehose/decoder.py).
- `extract_post_creates()` in [`bluesky_pipeline/firehose/extractor.py`](../bluesky_pipeline/firehose/extractor.py) keeps only `create` ops in `app.bsky.feed.post`.

3. Raw normalization + persistence:
- `normalize_raw_post()` in [`bluesky_pipeline/firehose/normalizer.py`](../bluesky_pipeline/firehose/normalizer.py).
- Idempotent insert by `uri` via `insert_captured_post()` in [`bluesky_pipeline/state/sqlite_store.py`](../bluesky_pipeline/state/sqlite_store.py).
- New rows are written to writer; duplicates are skipped.
- Finalized files are registered in `batch_files` via `_persist_completed_files()` in main.

4. Capture run progress/state:
- Periodic progress updates via `update_capture_run_progress()`.
- On success/failure: `complete_capture_run()` / `fail_capture_run()`.

5. Hydration candidate selection:
- Entrypoint: [`bluesky_pipeline/main_hydrate.py`](../bluesky_pipeline/main_hydrate.py).
- Selector: [`bluesky_pipeline/hydrate/selector.py`](../bluesky_pipeline/hydrate/selector.py).
- Eligible rows are `hydration_status IN ('pending','retryable')` and `captured_at <= now - maturity_hours`.
- Claims are acquired in DB transaction (`BEGIN IMMEDIATE`) with TTL expiration.

6. Hydration requests:
- Client: [`bluesky_pipeline/hydrate/client.py`](../bluesky_pipeline/hydrate/client.py).
- Chunks max 25 URIs/request.
- Retries retryable transport/429/5xx errors with backoff.

7. Hydration normalization + state transitions:
- Success rows normalized via `normalize_hydrated_post()` and written to hydrated dataset.
- Missing/unresolved rows become retryable or terminal missing (with miss rows via `normalize_hydration_miss()`).
- Non-retryable failures become terminal failed.
- State transitions are done via `mark_posts_hydrated/retryable/missing/failed` in SQLite store.

8. Actor/profile enrichment:
- Entrypoint: [`bluesky_pipeline/main_actor_enrich.py`](../bluesky_pipeline/main_actor_enrich.py).
- Seeding/claiming via [`bluesky_pipeline/actor/selector.py`](../bluesky_pipeline/actor/selector.py).
- Seed strategy: hydrated-first DIDs, then captured fallback (`seed_actor_dids_from_hydrated_then_captured`).
- Profile fetch via [`bluesky_pipeline/actor/client.py`](../bluesky_pipeline/actor/client.py), max 25 actors/request.
- Normalize/write actor rows via [`bluesky_pipeline/actor/normalizer.py`](../bluesky_pipeline/actor/normalizer.py).
- Mark actor state as enriched/retryable/missing/failed.

9. Exports/final outputs for operators:
- No separate “final feature table builder” exists in code.
- Inspection/QA/export CLI in [`bluesky_pipeline/main_inspect.py`](../bluesky_pipeline/main_inspect.py) reads datasets and exports samples/profiles.

10. Logging/recovery/reruns:
- Logging configured by [`bluesky_pipeline/logging_config.py`](../bluesky_pipeline/logging_config.py).
- Expired claims are released each poll in hydration/actor loops.
- Outstanding claimed rows are returned to retryable on shutdown in both hydration and actor workers.
- One-shot retryable-only cycle guard prevents hot retry loops in hydration and actor workers.

## 3. Repo map

Important files/folders only:

| Path | What it does | Operational importance | Type |
|---|---|---|---|
| `bluesky_pipeline/main_firehose.py` | Firehose capture orchestrator | Critical | Orchestration |
| `bluesky_pipeline/main_hydrate.py` | Hydration worker orchestrator + maturity logic | Critical | Orchestration |
| `bluesky_pipeline/main_actor_enrich.py` | Actor enrichment worker orchestrator | Critical | Orchestration |
| `bluesky_pipeline/main_inspect.py` | QA/inspect/export CLI | High | Operator tooling |
| `bluesky_pipeline/config.py` | Typed defaults (paths, batching, retry, firehose/hydrate/actor settings) | Critical | Config |
| `bluesky_pipeline/state/schema.py` | SQLite DDL + indexes + schema version | Critical | Persistence contract |
| `bluesky_pipeline/state/sqlite_store.py` | All DB lifecycle/state/claim transitions | Critical | Persistence/coordination |
| `bluesky_pipeline/batching/writer.py` | Rotating temp-to-final gzip JSONL writer | Critical | Persistence/output |
| `bluesky_pipeline/firehose/client.py` | Websocket/mock frame transport | Critical | Ingestion transport |
| `bluesky_pipeline/firehose/decoder.py` | Frame decoding to event contract | Critical | Transform |
| `bluesky_pipeline/firehose/extractor.py` | Commit op filtering and post extraction | Critical | Transform |
| `bluesky_pipeline/firehose/normalizer.py` | Raw row schema normalization | Critical | Transform |
| `bluesky_pipeline/hydrate/client.py` | `getPosts` API client + retry/backoff | Critical | Enrichment transport |
| `bluesky_pipeline/hydrate/selector.py` | Mature-row count/claim/release | Critical | Coordination |
| `bluesky_pipeline/hydrate/normalizer.py` | Hydrated row + miss row schema | Critical | Transform |
| `bluesky_pipeline/actor/client.py` | `getProfiles` API client + retry/backoff | Critical | Enrichment transport |
| `bluesky_pipeline/actor/selector.py` | Actor DID seeding/claim/release | Critical | Coordination |
| `bluesky_pipeline/actor/normalizer.py` | Actor profile row schema | Critical | Transform |
| `bluesky_pipeline/inspect/*` | Data readers, validation, profiling, sample export | High | QA tooling |
| `tests/test_main_hydrate.py` | Hydration orchestration integration tests | High | Tests |
| `tests/test_main_actor_enrich.py` | Actor orchestration integration tests | High | Tests |
| `tests/test_hydrate_*.py` / `tests/test_actor_*.py` | Client/selector/normalizer behavior tests | High | Tests |
| `tests/test_main_inspect.py` + inspect tests | Inspect CLI behavior tests | Medium | Tests |
| `docs/07_*`, `docs/08_*`, `docs/09_*` | Frozen runbook/contract + Phase 9 hardening | High | Operations docs |
| `data/output/<run_tag>/...` | Standardized run-root layout (operator convention) | High | Runtime artifacts |

## 4. Runtime entrypoints

### A) Firehose capture
Command:
- `python3 -m bluesky_pipeline.main_firehose`

Required args:
- None strictly required by parser.

Important optional args:
- `--db-path`, `--log-path`.
- `--raw-output-dir`.
- `--target-count`.
- `--mock-frames-path` (deterministic local replay).
- `--max-rows-per-file`, `--max-seconds-per-file`.

Writes:
- Raw dataset files under `<raw-output-dir>/<capture_run_id>/`.
- State tables: `capture_runs`, `captured_posts`, `batch_files`.

Preconditions:
- For live firehose: `websockets` package.
- For decoding actual binary subscribeRepos frames: `atproto_firehose` + `atproto_core` dependencies must be present.

When operator runs it:
- First step of a run; captures target number of unique post URIs.

### B) Hydration worker
Command:
- `python3 -m bluesky_pipeline.main_hydrate`

Required args:
- None strictly required by parser.

Important optional args:
- `--db-path`, `--log-path`.
- `--capture-run-id` (FK linkage for hydrate run, not currently used to filter claim query).
- `--hydrated-output-dir`, `--miss-output-dir`.
- `--maturity-hours` (default 24).
- `--claim-batch-size`, `--request-batch-size`, `--max-unresolved-attempts`.
- `--continue-polling`.

Writes:
- Hydrated files under `<hydrated-output-dir>/<hydrate_run_id>/`.
- Miss files under `<miss-output-dir>/<hydrate_run_id>/`.
- State tables: `hydrate_runs`, `captured_posts`, `batch_files`.

Preconditions:
- Existing capture data in DB (`capture_runs` + `captured_posts`).
- Network access to public API endpoint.

When operator runs it:
- After capture; production mode expects mature posts (default 24h).

### C) Actor enrichment worker
Command:
- `python3 -m bluesky_pipeline.main_actor_enrich`

Required args:
- None strictly required by parser.

Important optional args:
- `--db-path`, `--log-path`.
- `--actor-output-dir`.
- `--claim-batch-size`, `--request-batch-size`, `--max-unresolved-attempts`.
- `--continue-polling`.

Writes:
- Actor files under `<actor-output-dir>/<actor_run_id>/`.
- State tables: `actor_runs`, `actor_profiles_state`, `batch_files`.

Preconditions:
- `captured_posts` with `repo_did` values (hydrated-first seeding, captured fallback).

When operator runs it:
- Typically after hydration to enrich unique authors.

### D) Inspect/QA/export CLI
Command:
- `python3 -m bluesky_pipeline.main_inspect <files|show|export|validate|profile> ...`

Required args:
- Subcommand-specific (`--input` always required; `--output` for export).

Important optional args:
- `--dataset` (`auto`, `raw`, `hydrated`, `actor`, `misses`).
- `--limit`, `--tail`, `--pretty`, `--show-source`, `--top-k`, `--max-issues`.

Writes:
- Only for `export`: user-specified `.json` or `.jsonl` sample output.

Preconditions:
- Existing dataset files (`.jsonl` or `.jsonl.gz`).

When operator runs it:
- Smoke checks, post-run QA, and sample export.

## 5. Data model / storage model

Primary DB:
- SQLite at configured `db-path` (default `data/state/pipeline_state.db` in config).
- Schema version: `SCHEMA_VERSION = 2` in [`bluesky_pipeline/state/schema.py`](../bluesky_pipeline/state/schema.py).

Tables:
- `capture_runs`: firehose run lifecycle and progress.
- `hydrate_runs`: hydration run lifecycle and counters.
- `actor_runs`: actor run lifecycle and counters.
- `batch_files`: file-level output registry.
- `captured_posts`: per-post lifecycle and hydration state.
- `actor_profiles_state`: per-DID lifecycle and enrichment state.

Post identity:
- `captured_posts.uri` is the primary key and dedupe key.
- Secondary lineage fields include `cid_at_capture`, `repo_did`, `capture_run_id`.

Hydration claim/retry/skip behavior:
- Claim query: rows in `pending`/`retryable`, mature by `captured_at` cutoff.
- Claims set state to `claimed`, set `claimed_by_worker`, `claim_expires_at`, increment `hydration_attempt_count`.
- Expired claims are reset to `pending`.
- Outcomes:
  - `hydrated`: returned and normalized.
  - `retryable`: transient request failures or unresolved below retry cap.
  - `missing`: unresolved and attempt cap reached.
  - `failed`: non-retryable request failures or normalization failures.

Actor/profile state behavior:
- Seed unique DIDs into `actor_profiles_state` from hydrated-first, then captured fallback.
- Claim rows in `pending`/`retryable`.
- Expired claims reset to `pending`.
- Outcomes mirror hydration model (`enriched`, `retryable`, `missing`, `failed`).

Where actor/profile data is stored:
- Output files: actor dataset under `actor_profiles/<actor_run_id>/`.
- State: `actor_profiles_state` table.

Raw vs hydrated vs exported artifacts:
- Raw/hydrated/miss/actor are canonical pipeline outputs.
- Inspect exports are operator samples, not canonical production datasets.

Grounded reconstruction caveats:
- `captured_posts.capture_file_id` exists but current firehose path always inserts `capture_file_id=None` (no post-to-batch_file FK currently populated).
- `hydrate_runs.capture_run_id` is recorded, but hydration claim SQL currently does not filter by capture run.

## 6. Output contract

Target operational layout (Phase 7/8/9 runbook):

```text
data/output/<run_tag>/
  raw_posts/
    <capture_run_id>/raw_posts_*.jsonl.gz
  hydrated_posts/
    <hydrate_run_id>/hydrated_posts_*.jsonl.gz
  hydration_misses/
    <hydrate_run_id>/hydration_misses_*.jsonl.gz
  actor_profiles/
    <actor_run_id>/actor_profiles_*.jsonl.gz
  exports/
  logs/
  state/
```

Which process writes each folder:
- `raw_posts/`: `main_firehose`.
- `hydrated_posts/`: `main_hydrate`.
- `hydration_misses/`: `main_hydrate` unresolved terminal misses.
- `actor_profiles/`: `main_actor_enrich`.
- `exports/`: `main_inspect export/profile` outputs.
- `logs/`: each CLI via `--log-path`.
- `state/`: SQLite DB via `--db-path`.

Canonical vs intermediate:
- Canonical datasets: raw/hydrated/actor.
- Audit dataset: hydration_misses.
- Operational artifacts: logs + state DB + batch_files entries.
- Intermediate/operator-only artifacts: `exports/` sample files.

Important implementation detail:
- Code does not auto-generate `<run_tag>`.
- `<run_tag>` layout is achieved operationally by passing CLI output/db/log paths (documented in `docs/07/08/09`).

## 7. Current operational assumptions

Why hydration happens later:
- Hydration uses delayed engagement outcomes; system intentionally waits for maturity based on `captured_at` before selecting rows.

What `maturity-hours` does:
- Eligibility cutoff is `captured_at <= now_utc - maturity_hours` in `HydrationSelector`.

Why default is 24h:
- `HydrateConfig.maturity_hours = 24` in config.
- Startup logs classify this as production-style in `main_hydrate`.
- Docs freeze 24h as production-safe default.

Smoke vs production mode:
- Smoke/immediate mode: `--maturity-hours 0`, explicit warning.
- Low-maturity override: `<24`, explicit warning.
- Production mode: `>=24`, logged as production-style.

Reruns/idempotency/safety patterns:
- Per-post idempotency via `uri` primary key.
- Claim TTL + expired-claim release for recovery.
- Shutdown releases current claims to retryable.
- Writer uses temp files + atomic rename; avoids publishing empty files.
- Actor rerun idempotency is explicitly tested (no duplicate actor state/output row).

## 8. Existing quality controls

Tests present:
- Hydration orchestration/client/selector/normalizer:
  - `tests/test_main_hydrate.py`
  - `tests/test_hydrate_client.py`
  - `tests/test_hydrate_selector.py`
  - `tests/test_hydrate_normalizer.py`
- Actor orchestration/client/selector/normalizer:
  - `tests/test_main_actor_enrich.py`
  - `tests/test_actor_client.py`
  - `tests/test_actor_selector.py`
  - `tests/test_actor_normalizer.py`
- Inspect tooling:
  - `tests/test_main_inspect.py`
  - `tests/test_inspect_reader.py`
  - `tests/test_inspect_validator.py`
  - `tests/test_inspect_exporter_profiler.py`

What behavior is validated:
- Request chunk limits (25), retry classification, retry behavior.
- Mature claim selection and expired claim release.
- Normalizer field contracts for hydrated/miss/actor rows.
- Main hydration/actor loops for partial success, retryable/non-retryable handling, missing escalation, interrupt claim release.
- Hydration maturity startup log/warning modes (0 / low / 24).
- Inspect CLI commands + strict validation exit codes.

Logging/safeguards protecting operators:
- Startup mode logs and warnings for hydration maturity.
- Progress logs with counters in each worker.
- Marking count mismatch warnings for state transition expectations.
- Retryable-only cycle guard in one-shot mode to avoid hot retries.
- Logger handler cleanup to avoid file descriptor leaks on same-process reruns.

Known hardening completed in prior phases (docs + code):
- Phase 5 hydration hardening in `docs/phase5_hydration_hardening.md` + `main_hydrate` improvements.
- Phase 6 live diagnostic and contract validation docs/artifacts.
- Phase 9 output layout + hydration timing hardening docs and tests/log evidence.

Gaps in test coverage:
- No dedicated unit/integration tests for `main_firehose.py` path in current test suite.
- No direct tests for `batching/writer.py` and many `SQLiteStore` methods as standalone units.

## 9. Clear extension points for next phase (translation + profanity)

### Option A: Ingestion-time transforms (during raw normalization)
Likely insertion file/module:
- [`bluesky_pipeline/firehose/normalizer.py`](../bluesky_pipeline/firehose/normalizer.py) (or called just before writer in `main_firehose.py`).

Pros:
- One pass close to source event.
- Captures earliest text snapshot.

Cons:
- High cost at firehose throughput scale.
- Couples expensive text processing to ingestion reliability.
- Harder to rerun just text logic without recapturing or re-reading raw files.

Risks:
- Reproducibility risk if external translation/profanity services change over time.
- Operational risk (ingestion lag/failure amplification).
- Lineage complexity if transformed fields are mixed into canonical raw rows.

### Option B: Hydration-time transforms
Likely insertion file/module:
- [`bluesky_pipeline/hydrate/normalizer.py`](../bluesky_pipeline/hydrate/normalizer.py) and/or `main_hydrate.py`.

Pros:
- Naturally delayed/batched stage.
- Could use hydrated `record` snapshot and known author/language hints.

Cons:
- Hydration’s main purpose is engagement lookup; adding heavy NLP can increase runtime and failure surface.
- Text may differ between raw and hydrated record snapshots; source-of-truth choice must be explicit.

Risks:
- Cost concentration during hydration windows.
- Coupled retries could repeat expensive transformations unless separately cached/tracked.

### Option C: Dedicated post-processing text job (recommended)
Likely insertion point:
- New module(s), e.g. `bluesky_pipeline/main_text_enrich.py` + `bluesky_pipeline/text/*`, reading canonical datasets via `inspect.reader` patterns and writing a separate dataset.

Pros:
- Preserves raw/hydrated canonical contracts unchanged.
- Best rerunnability/versioning (re-run text transforms without re-capturing/hydrating).
- Clear lineage separation (`source_text` vs `translated_text` vs `cleaned_text`).
- Easier cost control and backfill.

Cons:
- Adds another job and potentially another state table.

Risks:
- Needs explicit keys/versioning to avoid duplicate transform rows.
- Needs clear choice of source text (raw record text, hydrated record text, or both).

### Option D: Export-time transforms only
Likely insertion point:
- [`bluesky_pipeline/inspect/exporter.py`](../bluesky_pipeline/inspect/exporter.py) / `main_inspect export`.

Pros:
- Fastest to prototype.

Cons:
- Not a robust pipeline stage.
- Weak state tracking/idempotency.
- Harder lineage and reproducibility.

Risks:
- Transform logic becomes ad hoc and operator-dependent.
- Not suitable for production repeatability.

### Option E: Actor description transforms (if desired)
Likely insertion file/module:
- [`bluesky_pipeline/actor/normalizer.py`](../bluesky_pipeline/actor/normalizer.py) for `description` text.

Pros:
- Covers profile-level text features.

Cons:
- Different semantic domain than post text; should likely be separate transform scope.

Risks:
- Mixing actor and post text policies can confuse downstream feature lineage.

## 10. Recommended architecture direction for text normalization

Recommended direction: add a separate, versioned text-transformation layer; do not mutate existing canonical raw/hydrated files.

Guidance:
- Preserve original text exactly as captured in existing canonical datasets (`record.text` in raw/hydrated rows).
- Create a new derived text dataset keyed by `uri` (and optionally source dataset indicator).
- Store at least:
  - `uri`
  - `capture_run_id` (and `hydrate_run_id` if source is hydrated)
  - `source_text`
  - `source_text_origin` (raw or hydrated)
  - `source_text_hash`
  - `detected_language`
  - `translated_text` (nullable)
  - `translation_provider`
  - `translation_model_or_version`
  - `profanity_cleaned_text` (nullable)
  - `profanity_policy_version`
  - `transformed_at`
  - `text_transform_run_id`
- Keep transformed outputs append-only/versioned so reruns are reproducible.
- Avoid destructive overwrite of `record` or canonical row contracts.
- Join transformed text downstream by `uri` so analytics/ML can choose raw vs translated vs cleaned features explicitly.

Why this fits current architecture:
- Current pipeline already separates concerns by stage and dataset.
- SQLite + run IDs + batch files already establish a pattern for reproducible stage outputs.
- Operator runbook already assumes multi-stage jobs under one run root.

## 11. Known uncertainties / open questions

These are not fully clear from current code/docs and need explicit decisions:

1. Capture-run scoping in hydration:
- `main_hydrate.py` records a `capture_run_id` in `hydrate_runs`, but claim SQL in `SQLiteStore.claim_mature_posts` currently does not filter by capture run.
- Follow-up files: [`bluesky_pipeline/main_hydrate.py`](../bluesky_pipeline/main_hydrate.py), [`bluesky_pipeline/state/sqlite_store.py`](../bluesky_pipeline/state/sqlite_store.py).

2. Capture-run scoping in actor enrichment:
- Actor seeding currently scans all `captured_posts` rows in DB (hydrated-first then captured fallback), not a specified run.
- Follow-up files: [`bluesky_pipeline/actor/selector.py`](../bluesky_pipeline/actor/selector.py), [`bluesky_pipeline/state/sqlite_store.py`](../bluesky_pipeline/state/sqlite_store.py).

3. `capture_file_id` linkage completeness:
- `captured_posts.capture_file_id` exists but insert path sets `None`; no later backfill found.
- Follow-up files: [`bluesky_pipeline/main_firehose.py`](../bluesky_pipeline/main_firehose.py), [`bluesky_pipeline/state/sqlite_store.py`](../bluesky_pipeline/state/sqlite_store.py).

4. Canonical source text for future NLP:
- Both raw and hydrated datasets carry nested `record.text`; policy for authoritative source is not yet frozen.
- Follow-up files: [`bluesky_pipeline/firehose/normalizer.py`](../bluesky_pipeline/firehose/normalizer.py), [`bluesky_pipeline/hydrate/normalizer.py`](../bluesky_pipeline/hydrate/normalizer.py), [`docs/07_feature_contract_and_weekend_runbook.md`](./07_feature_contract_and_weekend_runbook.md).

5. Downstream export consumer contract:
- No code in this repo builds final joined feature tables; inspect exports are sample QA artifacts only.
- Follow-up files: [`bluesky_pipeline/main_inspect.py`](../bluesky_pipeline/main_inspect.py), docs `07/08`.

6. Dependency contract for live decode:
- Live firehose decode/extract effectively depends on `websockets`, `atproto_firehose`, and `atproto_core`; dependency installation contract file (e.g., requirements/pyproject) is not present in this repo root.
- Follow-up files: [`bluesky_pipeline/firehose/client.py`](../bluesky_pipeline/firehose/client.py), [`bluesky_pipeline/firehose/decoder.py`](../bluesky_pipeline/firehose/decoder.py), [`bluesky_pipeline/firehose/extractor.py`](../bluesky_pipeline/firehose/extractor.py).

## Pasteable AI Handoff Summary

This repo is a Python local data pipeline with 4 runtime CLIs: `main_firehose` (capture raw post-create events), `main_hydrate` (delayed hydration via `getPosts`), `main_actor_enrich` (actor/profile enrichment via `getProfiles`), and `main_inspect` (QA/export tooling). Canonical outputs are rotating gzip JSONL datasets for raw posts, hydrated posts, hydration misses, and actor profiles; SQLite is the control plane (`capture_runs`, `hydrate_runs`, `actor_runs`, `batch_files`, `captured_posts`, `actor_profiles_state`). Unique post identity is `uri` (PK in `captured_posts`), hydration/enrichment use claim TTL + retryable/missing/failed terminal states, and both workers release outstanding claims on shutdown. Hydration maturity is explicit and hardened: default `24h`, startup cutoff logging, and warnings for `0` or low maturity overrides. Operationally, Phase 7/8/9 docs standardize run folders under `data/output/<run_tag>/...`, but code only uses that layout when operators pass explicit CLI paths; defaults still point to `data/raw_posts`, `data/hydrated_posts`, etc. Important architecture caveat: hydration and actor selection SQL currently scan eligible rows across the whole DB (not strict per-capture-run filtering), even though hydrate runs record one `capture_run_id`. Text currently lives only inside nested `record.text` fields in raw/hydrated rows; no translation/profanity stage exists yet. Best next-step architecture is a separate versioned text-processing job/dataset keyed by `uri`, preserving canonical raw/hydrated artifacts unchanged and storing derived fields (`source_text`, `translated_text`, `cleaned_text`, provider/model/policy versions, transform run id, timestamps) for reproducibility and rerunnable lineage.
