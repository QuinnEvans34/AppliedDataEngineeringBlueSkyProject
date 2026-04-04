# 33 Hydration Correctness and Label Quality Audit Findings

Date: 2026-04-04  
Mode: local read-only audit (`0` Snowflake queries, `0` reruns)

## 1) Executive Summary
- **Hydration code path appears technically correct** for request batching, retryability handling, success/miss state transitions, and output row normalization.
- **Current hydrated engagement signal is very sparse** even before downstream joins:
  - on all hydrated rows (`19,731`), `68.27%` have total engagement `= 0`, `85.01%` are `<= 1`, `97.84%` are `<= 5`.
- **Downstream label input is weaker than raw hydrated signal** because Phase 26 selected only one hydrated shard (`9,597` rows) for `19,999` prepared posts:
  - feature-table engagement totals: `85.62%` `= 0`, `93.46%` `<= 1`, `99.17%` `<= 5`.
- **Hydration timing is very likely the main root cause of low-signal labels** in this run:
  - capture-to-hydrate lag median `0.0726h` (~`4.35m`), p90 `0.0996h` (~`5.98m`), max `0.1069h` (~`6.42m`), and `100%` within 1 hour.
- **Model impact is severe**: majority-class prediction behavior (`LOW` only for best baseline), macro F1 `0.3075`, minority recall `0.0` for `MEDIUM` and `HIGH`.
- **Blunt next move**: prioritize **future-run hydration sequencing/timing changes** (delay + possible multi-pass), not hydration client correctness rewrites.

## 2) Hydration Code-Path Audit

### Confirmed facts
Hydration implementation inspected:
- `bluesky_pipeline/main_hydrate.py`
- `bluesky_pipeline/hydrate/client.py`
- `bluesky_pipeline/hydrate/selector.py`
- `bluesky_pipeline/hydrate/normalizer.py`
- `bluesky_pipeline/state/sqlite_store.py`
- `scripts/ops/stage_drain.py`

Code-path behavior:
- Work selection expects `captured_posts` rows in `pending`/`retryable` with `captured_at <= maturity_cutoff` (`selector` + `store.claim_mature_posts`).
- Endpoint/client logic uses `https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts`, URI chunk limit <= 25, retry/backoff on transient failures (`429`, `5xx`, transport errors).
- Engagement fields extracted from returned post views:
  - `likeCount`, `replyCount`, `repostCount`, `quoteCount` -> normalized to `like_count`, `reply_count`, `repost_count`, `quote_count`.
- Success vs miss determination:
  - returned/normalized rows -> `hydrated`
  - not returned by `getPosts` -> retryable until `attempt_count >= max_unresolved_attempts` (default 3), then terminal `missing` + miss file row.
- Retry/drain behavior:
  - in-worker retryability handling (`mark_posts_retryable`), expired-claim recovery, and one-shot retryable-cycle guard.
  - optional orchestration loop in `scripts/ops/stage_drain.py drain-hydration` repeatedly runs one-shot hydration + completion checks.
- Completion decision:
  - worker one-shot exits complete when no mature claimable rows remain.
  - stage completion gate requires: capture run completed, all rows mature, no mature `pending/retryable`, no `claimed` in-flight.
- Identifiers preserved for downstream joins in hydrated rows:
  - `uri`, `capture_run_id`, `hydrate_run_id`, `author_did`, `author_handle`, `cid`, plus timestamps.

### Inference
- No obvious logic bug was found in hydration request/response handling, normalization, or state transitions.
- The code is operationally mature enough to reuse at larger scale, assuming sequencing is corrected.

## 3) Hydration Artifact/Schema Summary

### Paths used
- Large source root: `../snowflake_package - Copy`
- Hydrated files:
  - `../snowflake_package - Copy/hydrated_posts/hyd_20260402T181936Z_5cf8bb07/hydrated_posts_000001.jsonl.gz`
  - `../snowflake_package - Copy/hydrated_posts/hyd_20260402T181936Z_5cf8bb07/hydrated_posts_000002.jsonl.gz`
  - `../snowflake_package - Copy/hydrated_posts/hyd_20260402T181936Z_5cf8bb07/hydrated_posts_000003.jsonl.gz`
- Phase 26 selected hydrated input (single file):
  - `../snowflake_package - Copy/hydrated_posts/hyd_20260402T181936Z_5cf8bb07/hydrated_posts_000002.jsonl.gz`

### Counts and consistency
| Metric | Value |
|---|---:|
| Raw rows | 19,994 |
| Hydrated rows | 19,731 |
| Hydration miss rows under large root | 0 |
| Raw-only URIs (not in hydrated files) | 268 |
| Hydrated-only URIs (not in raw files) | 5 |
| URI intersection raw/hydrated | 19,726 |

### Schema and key fields (hydrated)
- Observed keys: `uri`, `capture_run_id`, `hydrate_run_id`, `cid`, `indexed_at`, `hydrated_at`, `author_did`, `author_handle`, `author_display_name`, `like_count`, `reply_count`, `repost_count`, `quote_count`, `labels`, `record`.
- Required engagement/join fields were fully present in sampled large-run hydrated rows.
- Timestamp fields present/parseable on all hydrated rows: `indexed_at`, `hydrated_at`, `record.createdAt`.

### Miss artifact note
- The large run root has no `hydration_misses_*.jsonl.gz` files, so unresolved hydration outcomes for raw-only URIs are not directly auditable there.

## 4) Engagement Distribution Summary

### A) Hydrated rows selected by Phase 26 (`9,597` rows)
| Metric | Value |
|---|---:|
| `% total engagement = 0` | 70.04% |
| `% total engagement <= 1` | 86.38% |
| `% total engagement <= 5` | 98.28% |

Per-component sparsity (selected file):
- likes: `76.17%` zero
- replies: `87.18%` zero
- reposts: `96.13%` zero
- quotes: `99.50%` zero

Quantiles (selected file):
- total engagement: p50 `0`, p75 `1`, p90 `2`, p95 `3`, p99 `8`
- likes: p50 `0`, p90 `1`, p95 `2`
- replies: p50 `0`, p95 `1`
- reposts: p50 `0`, p99 `1`
- quotes: p99 `0`

### B) All hydrated rows under large root (`19,731` rows)
| Metric | Value |
|---|---:|
| `% total engagement = 0` | 68.27% |
| `% total engagement <= 1` | 85.01% |
| `% total engagement <= 5` | 97.84% |

### C) Effective downstream label input (`local/derived/features/bluesky_engagement_features.parquet`, `19,999` rows)
| Metric | Value |
|---|---:|
| `% engagement_total = 0` | 85.62% |
| `% engagement_total <= 1` | 93.46% |
| `% engagement_total <= 5` | 99.17% |
| non-zero engagement rows | 2,875 |

Confirmed mechanism: Phase 26 hydration join coverage is `47.99%`, and missing joins are null-filled to zero for engagement components, which increases zero inflation in label inputs.

## 5) Label-Construction Audit (Phase 26)

### Confirmed facts
From `src/features/feature_engineering.py`:
- Aggregate engagement formula:
  - `engagement_total = eng_like_count + eng_reply_count + eng_repost_count + eng_quote_count`
- Primary label rule:
  - quantile bins using q33/q66 (`LOW <= q33`, `MEDIUM <= q66`, `HIGH > q66`)
- Fallback rule when quantiles collapse or produce empty class:
  - `LOW == 0`, `MEDIUM == 1`, `HIGH >= 2`.
- Current run metadata (`local/derived/features/bluesky_engagement_feature_summary.json`):
  - `q33 = 0.0`, `q66 = 0.0`
  - rule used: `fallback_count_bins`
  - label distribution: `LOW=17124`, `MEDIUM=1568`, `HIGH=1307`.

### Inference
- Label logic itself is technically correct and deterministic.
- Label usefulness is weak because input engagement is highly sparse/zero-inflated; fallback bins mostly separate `0` vs `1` vs `>=2`, which is a very low-signal target regime.

## 6) Root-Cause Assessment (Timing vs Code Correctness)

### Confirmed facts
- Capture run ID in artifacts: `cap_20260402T181311Z_f98d0c5f`.
- Hydrate run ID in artifacts: `hyd_20260402T181936Z_5cf8bb07`.
- Observed timestamps:
  - raw capture range: `2026-04-02T18:13:12Z` to `2026-04-02T18:19:20Z`
  - hydrated range: `2026-04-02T18:19:37Z` to `2026-04-02T18:21:44Z`
- Joined URI timing deltas (`n=19,726`):
  - capture->hydrate median: `0.0726h` (~`4.35m`)
  - p90: `0.0996h` (~`5.98m`)
  - min/max: `0.0400h` to `0.1069h` (~`2.40m` to `6.42m`)
  - `100%` <= 1 hour.

### Inference
- Hydration was effectively immediate after capture in this run, strongly consistent with prematurely low engagement counts.
- This timing pattern is a much stronger explanation for sparse engagement labels than hydration client correctness defects.
- Additional amplifier (separate from timing): Phase 26 currently uses a single hydrated shard, further weakening label inputs via missing->zero fill.

## 7) Downstream Impact on Modeling

### Confirmed facts
- Feature-table label distribution is heavily imbalanced (`LOW` dominant).
- Best baseline (`bagged_stump_ensemble`) metrics:
  - accuracy `0.8563`
  - balanced accuracy `0.3333`
  - macro F1 `0.3075`
  - recall `0.0` for both `MEDIUM` and `HIGH` (predicts `LOW` only on test split).

### Inference
- Hydration-quality weakness (premature/sparse engagement) materially degrades target separability.
- High apparent accuracy is mostly majority-class capture; minority-class utility is near-zero.
- Current model outputs are not reliable for practical multi-class engagement ranking decisions.

## 8) Readiness for Future 1M-Post Workflow

### Confirmed facts
- Hydration worker code supports chunking, retries, claim recovery, miss recording, and completion gating.
- Stage drain utility supports repeated one-shot cycles until completeness checks pass.

### Inference
- Hydration code is reusable for larger runs.
- Operational sequencing should change before 1M-scale runs:
  - hydrate after a delay window (not immediate)
  - likely run one delayed pass minimum; multiple passes are reasonable if business goals need longer-tail engagement capture
  - validate pre-modeling engagement sparsity and class distribution before committing downstream training.

## 9) Recommended Next Move (Blunt)
- **Primary recommendation: change hydration timing/sequencing, not hydration code correctness.**
- Hydration implementation appears technically sound; the dominant failure mode is low-signal labels caused by near-immediate hydration.
- For next run planning, treat delayed hydration as required.
- Also carry forward the already-known downstream integration gap: ensure feature engineering consumes full hydrated coverage (not one shard), so sequencing improvements are not diluted by join-driven structural zeros.

---

Optional structured audit output written:
- `local/derived/audit/hydration_label_quality_summary.json`
