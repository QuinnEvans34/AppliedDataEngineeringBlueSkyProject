# 30 Data Location and Coverage Audit

Date: 2026-04-04
Mode: read-only local inspection (no Snowflake, no reruns)

## Executive Result
- The expected large Bluesky corpus (`~20k` raw/hydrated, `~13k` actor) is **not present** in this local footprint.
- Confirmed on disk:
  - raw posts: `25` rows
  - hydrated posts: `25` rows (plus separate `2`-row hydrated scratch file)
  - actor profiles: `21` rows
- Downstream phases 23–27 are using full available local artifacts, but those artifacts are small because upstream local source files are small.
- Twitter full snapshot is present locally and matching uses the full normalized Twitter parquet, not a sample.

## 1) Bluesky Source Inventory

### A. Family locations (confirmed)
- Raw posts directories:
  - `data/phase6_diagnostic_20260401/raw_posts/`
  - `data/raw_posts/` (empty placeholder)
  - `data/output/phase9_configcheck_20260402_095603/raw_posts/` (empty)
- Hydrated posts directories:
  - `data/phase6_diagnostic_20260401/hydrated_posts/`
  - `data/hydrated_posts/`
  - `data/output/phase9_configcheck_20260402_095603/hydrated_posts/` (empty)
- Actor profiles directories:
  - `data/phase5_actor_validation_20260401/actor_profiles/`
  - `data/output/phase9_configcheck_20260402_095603/actor_profiles/` (empty)
- Hydration misses directories:
  - `data/hydration_misses/`
  - `data/phase6_diagnostic_20260401/hydration_misses/` (empty)
  - `data/output/phase9_configcheck_20260402_095603/hydration_misses/` (empty)

### B. Run-root inventory (usable roots + coverage)
Counts below are from actual `*.jsonl.gz` files.

| Run Root | Family | Files | Rows | Notes |
|---|---|---:|---:|---|
| `data/phase6_diagnostic_20260401` | `raw_posts` | 1 | 25 | main downstream post source |
| `data/phase6_diagnostic_20260401` | `hydrated_posts` | 1 | 25 | main downstream hydrated source |
| `data/phase6_diagnostic_20260401` | `hydration_misses` | 0 | 0 | directory present, no rows |
| `data/phase5_actor_validation_20260401` | `actor_profiles` | 1 | 21 | main downstream actor source |
| `data` | `hydrated_posts` | 1 | 2 | tiny scratch/validation run |
| `data` | `hydration_misses` | 1 | 1 | tiny scratch/validation run |
| `data/output/phase9_configcheck_20260402_095603` | all families | 0 | 0 | config-check root only |

### C. Which source is best for downstream local NLP/features?
- For post text and hydration: `data/phase6_diagnostic_20260401` (largest usable post/hydrated source locally).
- For actor profiles: `data/phase5_actor_validation_20260401`.
- There is no single run root with large non-empty raw+hydrated+actor families.

## 2) Twitter Source Inventory

### A. Full local Twitter snapshot (confirmed)
- Full raw snapshot parquet:
  - `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`
  - rows: `101,731`
- Full normalized Twitter parquet:
  - `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`
  - rows: `101,731`

### B. Samples
- Raw sample:
  - `data/samples/twitter_trending_sample_1000.parquet`
  - `data/samples/twitter_trending_sample_1000.csv`
- Normalized sample:
  - `data/samples/twitter_trending_normalized_sample_1000.parquet`
  - `data/samples/twitter_trending_normalized_sample_1000.csv`

### C. Is matching using full normalized Twitter data or sample?
- Confirmed full dataset usage.
- Matching summary input path:
  - `local/derived/matching/bluesky_post_trend_matching_summary.json` -> `"trends": "local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet"`
- Matching notebook also points to full normalized parquet, not sample.
- No evidence that matching input is restricted to sample Twitter data.

## 3) Downstream Data-Path Tracing (Phases 23–27)

| Phase | Input artifact(s) used | Rows loaded | Output artifact(s) |
|---|---|---:|---|
| 23 Bluesky text prep | selected source from `data/` (chosen: `data/phase6_diagnostic_20260401/raw_posts/...` + `.../hydrated_posts/...`) | raw `25`, hydrated `25`, prepared `25` | `local/derived/bluesky/bluesky_posts_prepared.parquet` |
| 24 candidate extraction | `local/derived/bluesky/bluesky_posts_prepared.parquet` | prepared `25` | `local/derived/bluesky/bluesky_topic_candidates.parquet` (`237` rows) |
| 25 matching | candidates parquet + full normalized Twitter parquet | candidates `237`, trends `101,731` | `local/derived/matching/bluesky_post_trend_matches.parquet` (`243` rows), `...best...` (`19` rows) |
| 26 feature engineering | prepared (`25`) + best matches (`19`) + full matches (`243`) + selected hydrated (`25`) + selected actor (`21`) | base grain `25` posts | `local/derived/features/bluesky_engagement_features.parquet` (`25` rows) |
| 27 baseline modeling | `local/derived/features/bluesky_engagement_features.parquet` | `25` rows (train `17` / test `8`) | baseline modeling artifacts under `local/derived/modeling/` |

## 4) Why only ~25 posts reached downstream

### Confirmed facts
1. There are only five local `*.jsonl.gz` source files total for raw/hydrated/actor/misses.
2. The main post/hydrated run root (`data/phase6_diagnostic_20260401`) contains only `25` raw + `25` hydrated rows.
3. Phase 23 source selection picked the largest available candidate by prepared text coverage and URI count; selected root has `25` prepared rows.
4. Phases 24–27 consume the full outputs of prior phases (not sample inputs).
5. No hardcoded row cap of `25` exists in phase 23–27 processing logic.

### Root cause (evidence-based)
- The bottleneck is upstream local data availability: the local Bluesky source files feeding phase 23 are small (25 rows), so all downstream tables remain small.
- This is not caused by downstream sampling, row-limit logic, or Snowflake dependencies.

## 5) Can we safely scale now?

### Blunt answer
- Full local Twitter dataset: **yes, already usable and already used in matching**.
- Full local Bluesky dataset (`~20k`) for downstream NLP/features/modeling: **no, not yet available in current local files**.

### Specific blockers
1. Missing large local Bluesky raw/hydrated source files (current usable source is 25 rows).
2. Missing large local actor-profile source file (current actor source is 21 rows).
3. Downstream phases are structurally ready, but constrained by tiny upstream corpus.

## What is safe to use right now
- `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet` (full 101,731 rows).
- Existing local downstream pipeline on diagnostic-scale Bluesky data (25-post slice) for functional testing.

## What is causing the current bottleneck
- Upstream local Bluesky footprint is diagnostic-size only (25 raw/hydrated rows + 21 actor rows), and phase 23 correctly selected that as best available source.

## Recommended next move
1. Locate/import the intended larger local Bluesky run root(s) (raw, hydrated, actor families) into `data/` without changing downstream code.
2. Re-run phases 23–27 on the larger local source once present.
3. Keep Twitter input path unchanged (already full and correct).
