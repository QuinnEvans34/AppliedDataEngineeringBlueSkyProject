# Text Enrichment Stage Design (No Code Changes)

This document defines the proposed design for a new dedicated pipeline stage that performs:
- language detection
- translation to English
- profanity detection/masking

Design is grounded in current repo patterns (`main_firehose`, `main_hydrate`, `main_actor_enrich`, SQLite control-plane, rotating gzip JSONL outputs) and preserves existing raw/hydrated contracts unchanged.

## 1) Canonical Source Text Decision

### Current text locations in repo
- Raw stage stores full post record under `record` in [`bluesky_pipeline/firehose/normalizer.py`](../bluesky_pipeline/firehose/normalizer.py). Primary text is typically `record.text`.
- Hydrated stage also stores `record` from AppView in [`bluesky_pipeline/hydrate/normalizer.py`](../bluesky_pipeline/hydrate/normalizer.py), also typically with `record.text`.

### Raw vs hydrated comparison
- Raw text advantages:
  - Captured at ingest time, closest to original publish-time payload.
  - Available immediately after capture (no 24h maturity delay).
  - Not affected by hydration misses (`hydration_misses` proves some URIs are unresolved during hydrate runs).
  - Better for reproducible feature lineage tied to publish-time data.
- Hydrated text advantages:
  - Comes from AppView and may reflect later normalized view.
- Hydrated text drawbacks for canonical input:
  - Depends on hydration success and timing window.
  - Introduces selection bias if some URIs are missing/failed in hydration.
  - Couples text enrichment to hydration operational latency.

### Recommendation
Use **raw `record.text`** as canonical text input.
- `source_text_origin` default: `raw_record_text`.
- Optional fallback only if needed (policy-gated): `hydrated_record_text` when raw text is missing.
- Keep fallback explicit in output metadata and policy versioning.

## 2) Architectural Placement

### Recommendation
Add text enrichment as a **separate dedicated stage** (not embedded into firehose or hydration).

### Why separate stage is best in this repo
- Existing architecture already uses stage separation with independent entrypoints:
  - firehose capture: [`bluesky_pipeline/main_firehose.py`](../bluesky_pipeline/main_firehose.py)
  - hydration: [`bluesky_pipeline/main_hydrate.py`](../bluesky_pipeline/main_hydrate.py)
  - actor enrichment: [`bluesky_pipeline/main_actor_enrich.py`](../bluesky_pipeline/main_actor_enrich.py)
- Adding translation/profanity to firehose would increase ingest fragility and cost on the hottest path.
- Adding translation/profanity to hydration would couple text processing to engagement-timing logic and unresolved hydrate rows.
- Separate stage supports reruns/backfills/version changes without recapturing or rehydrating.

## 3) Proposed Runtime Entrypoint

### CLI location/name
- Module: `bluesky_pipeline/main_text_enrich.py`
- Command: `python3 -m bluesky_pipeline.main_text_enrich`

### Proposed arguments (patterned after existing CLIs)
- `--db-path` (default `data/state/pipeline_state.db`)
- `--log-path` (default `data/logs/text_enrich.log`)
- `--input-dir` (raw dataset root, typically `$BASE/raw_posts`)
- `--text-output-dir` (typically `$BASE/text_enriched_posts`)
- `--capture-run-id` (optional scope)
- `--worker-id` (optional)
- `--claim-batch-size`
- `--claim-ttl-seconds`
- `--poll-interval-seconds`
- `--progress-log-interval-seconds`
- `--max-unresolved-attempts`
- `--continue-polling`
- `--min-text-length` (skip threshold)
- `--max-text-chars` (cost guard)
- `--translation-provider`
- `--translation-model`
- `--language-detector`
- `--profanity-policy-version`

### Run behavior
- One-shot mode by default (same operational style as hydrate/actor defaults).
- Optional polling mode for continuous operation.
- Emits startup config summary + progress counters + terminal status.

### Logs
- Use existing logger pattern in [`bluesky_pipeline/logging_config.py`](../bluesky_pipeline/logging_config.py).
- Log policy/version signature at startup for reproducibility.

## 4) Proposed Storage/Output Contract

### Proposed output layout
Under run root:

```text
data/output/<run_tag>/
  text_enriched_posts/
    <text_run_id>/
      text_enriched_posts_000001.jsonl.gz
      text_enriched_posts_000002.jsonl.gz
```

### Filename pattern
- `text_enriched_posts_<NNNNNN>.jsonl.gz`

### Dataset role
- **Derived canonical text dataset** for downstream analytics/ML text features.
- Not a replacement for raw/hydrated datasets.
- Raw/hydrated contracts remain unchanged.

### Optional audit dataset (later hardening)
- If needed later: `text_enrichment_audit/<text_run_id>/...` for detailed provider errors/skips.
- Initial design can keep detailed errors in SQLite + logs.

## 5) Proposed SQLite Control-Plane Additions

### New table 1: `text_enrich_runs`
Purpose:
- Run lifecycle and counters, parallel to `hydrate_runs` / `actor_runs`.

Design-level fields:
- `text_run_id` (PK)
- `started_at`, `completed_at`, `status` (`running/completed/failed`)
- `source_dataset_type` (initially `raw`)
- `capture_run_id` (nullable scope)
- `eligible_row_count`
- `enriched_row_count`
- `skipped_row_count`
- `failed_row_count`
- `notes`

### New table 2: `text_enrichment_state`
Purpose:
- Per-URI enrichment lifecycle tracking + idempotency/retry.

Design-level fields:
- `uri` (PK)
- `capture_run_id`
- `source_text_hash`
- `source_text_origin`
- `enrichment_status` (`pending/claimed/enriched/retryable/skipped/failed`)
- `enrichment_attempt_count`
- `last_enrichment_attempt_at`
- `enriched_at`
- `text_run_id`
- `last_error`
- `claimed_by_worker`
- `claim_expires_at`
- `last_transform_signature`

### Claim/retry/idempotency expectations
- Mirror hydrate/actor pattern from [`bluesky_pipeline/state/sqlite_store.py`](../bluesky_pipeline/state/sqlite_store.py):
  - claim `pending/retryable`
  - expire stale claims back to `pending`
  - mark `enriched/retryable/skipped/failed`
- Idempotency gate:
  - If `source_text_hash` unchanged and `last_transform_signature` unchanged, do not re-enrich.
  - If text hash or transform signature changes, re-queue row.

### Uncertainty to resolve before implementation
- Whether to store source text itself in SQLite state (not recommended initially; keep DB as control-plane metadata, not large text payloads).

## 6) Proposed Row Schema (Derived Text Dataset)

One output row per URI enrichment attempt that reaches terminal `enriched` or `skipped`.

Proposed fields:
- `text_run_id`
- `uri`
- `capture_run_id`
- `source_text`
- `source_text_hash`
- `source_text_origin` (`raw_record_text` or explicit fallback)
- `source_text_length`
- `detected_language`
- `language_confidence`
- `language_detector_provider`
- `language_detector_version`
- `translated_text_en`
- `translation_status` (`translated`, `skipped_already_english`, `skipped_empty`, `skipped_short`, `failed`)
- `translation_provider`
- `translation_model`
- `translation_model_version`
- `profanity_source_flag`
- `profanity_source_score`
- `profanity_source_categories`
- `profanity_translated_flag`
- `profanity_translated_score`
- `profanity_translated_categories`
- `cleaned_source_text`
- `cleaned_translated_text_en`
- `profanity_policy_version`
- `transform_signature`
- `transformed_at`

Notes:
- Keep both original and cleaned variants; never overwrite source text.
- If translation is skipped/fails, `translated_text_en` may be `null` or equal to source based on frozen policy.

## 7) Transformation Policies To Freeze Before Build

Minimum decisions to freeze:

1. Profanity target scope
- Recommended: run profanity detection/masking on both:
  - source text
  - translated English text (when translation exists)

2. English post behavior
- Recommended: detect language first.
- If English: skip translation API call, set `translation_status=skipped_already_english`.

3. Empty/null/very short behavior
- Recommended skip rules:
  - null/empty after trim -> `skipped_empty`
  - below configurable length threshold -> `skipped_short`

4. Mutability rule
- Raw/hydrated originals are never mutated.
- Text enrichment writes new derived rows only.

5. Versioning rule
- Freeze and emit explicit versions for:
  - language detector
  - translation provider/model
  - profanity policy
- Define `transform_signature` as a stable composite of those versions + key thresholds.

6. Fallback source rule
- Recommended initial freeze: canonical source is raw only.
- If fallback is allowed, make it explicit and auditable via `source_text_origin`.

## 8) Operational Concerns

### Cost
- Translation dominates cost.
- Use skip rules (`already English`, empty/short text).
- Use hash-based idempotency to avoid reprocessing unchanged text.

### Reruns
- Safe reruns require hash + transform-signature checks.
- Provider/policy changes should intentionally trigger re-enrichment.

### Provider/model drift
- Store provider and version metadata in every output row.
- Drift without metadata breaks reproducibility.

### Partial failures
- Row-level retryable/failure statuses (not run-wide abort by default).
- Terminal run can complete with failed subset, as in existing hydrate/actor patterns.

### Append-only vs overwrite
- Recommended:
  - output files append-only per run
  - state table tracks latest status/signature
  - do not edit old output files in place

### Batch sizing
- Make claim batch and provider request batch configurable.
- Include max char limits to avoid oversized payload failures/cost spikes.

### Reproducibility
- Persist transform signature + provider/model/policy versions + timestamps.
- Keep source text hash for stable lineage.

## 9) Existing Files/Modules To Reuse

Most reusable existing components:
- Writer/output rotation:
  - [`bluesky_pipeline/batching/writer.py`](../bluesky_pipeline/batching/writer.py)
- Logging setup:
  - [`bluesky_pipeline/logging_config.py`](../bluesky_pipeline/logging_config.py)
- Config pattern:
  - [`bluesky_pipeline/config.py`](../bluesky_pipeline/config.py)
- SQLite schema/store patterns:
  - [`bluesky_pipeline/state/schema.py`](../bluesky_pipeline/state/schema.py)
  - [`bluesky_pipeline/state/sqlite_store.py`](../bluesky_pipeline/state/sqlite_store.py)
- ID/time utilities:
  - [`bluesky_pipeline/utils/ids.py`](../bluesky_pipeline/utils/ids.py)
  - [`bluesky_pipeline/utils/time_utils.py`](../bluesky_pipeline/utils/time_utils.py)
- Input dataset reading:
  - [`bluesky_pipeline/inspect/reader.py`](../bluesky_pipeline/inspect/reader.py)
- Validation/profile extensions for new dataset type:
  - [`bluesky_pipeline/inspect/validator.py`](../bluesky_pipeline/inspect/validator.py)
  - [`bluesky_pipeline/inspect/profiler.py`](../bluesky_pipeline/inspect/profiler.py)
- Test style/templates:
  - [`tests/test_main_hydrate.py`](../tests/test_main_hydrate.py)
  - [`tests/test_main_actor_enrich.py`](../tests/test_main_actor_enrich.py)
  - inspect tests under `tests/test_inspect_*`

## 10) Explicit Uncertainties

1. Translation/profanity provider choice is not yet defined in repo.
2. Dependency management file for new NLP providers is not currently present.
3. Fallback policy for missing raw text needs explicit freeze.
4. Exact confidence/score scales from chosen providers are unknown until provider is selected.
5. Whether to introduce a separate audit output dataset in v1 remains open.

## Recommended Next Build Order

1. Freeze policy decisions and row schema in docs (no code).
2. Add config + run-id + schema scaffolding for text stage (no provider integration yet).
3. Implement deterministic source-text extraction + hashing from raw dataset with tests.
4. Implement text-stage orchestration loop with SQLite lifecycle/state and rotating writer.
5. Add language detection integration + unit/integration tests.
6. Add translation integration with retry/backoff + provider/version metadata capture.
7. Add profanity detection/masking integration + policy-version enforcement.
8. Extend inspect validator/profiler for `text_enriched_posts` dataset contract.
9. Add operational hardening pass (retryable-only guard, mismatch warnings, shutdown claim release).
10. Run bounded smoke workflow under `data/output/<run_tag>/...`, then document runbook updates.
