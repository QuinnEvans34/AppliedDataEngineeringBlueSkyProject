# 32 Bluesky Source-Root Repoint and Full Downstream Rerun Findings

Date: 2026-04-04

## Summary
- Root cause confirmed: downstream phases were defaulting to repo-local `data/`, which only had a tiny diagnostic subset.
- Implemented a shared configurable source-root resolver and repointed rerun execution to `../snowflake_package - Copy`.
- Reran downstream phases 23-27 on the larger corpus and regenerated artifacts.
- No Snowflake queries were used.

## What Was Wrong
- Downstream source discovery for Bluesky data effectively assumed `data/`.
- That path only contained diagnostic-scale files (`25` raw/hydrated posts), so phases 23-27 ran on tiny input.

## Code/Config Changes
1. Added shared source-root helper:
- `src/source_paths.py`
- `resolve_bluesky_source_root(base_dir=None)` precedence:
  1. explicit arg
  2. `BLUESKY_SOURCE_ROOT`
  3. default `data`

2. Updated real loaders to use shared resolver:
- `src/nlp/post_normalization.py`
  - `discover_local_source_candidates`
  - `select_best_local_source_candidate`
  - `prepare_from_best_local_source`
- `src/features/feature_engineering.py`
  - `select_best_hydrated_source_file`
  - `select_best_actor_profile_source_file`

3. Updated notebooks that were hardcoding repo-local `data`:
- `notebooks/23_local_bluesky_text_preparation.ipynb`
- `notebooks/26_local_feature_engineering.ipynb`

## Source Path Used For Rerun
- Effective source root: `../snowflake_package - Copy`
- Phase 23 selected run root: `../snowflake_package - Copy`
- Phase 26 selected hydrated source file:
  - `../snowflake_package - Copy/hydrated_posts/hyd_20260402T181936Z_5cf8bb07/hydrated_posts_000002.jsonl.gz`
- Phase 26 selected actor source file:
  - `../snowflake_package - Copy/actor_profiles/act_20260402T182221Z_1784be30/actor_profiles_000001.jsonl.gz`

## Rerun Status By Phase
| Phase | Status | Notes |
|---|---|---|
| 23 Bluesky text preparation | success | Full prepared artifact regenerated from larger source root |
| 24 topic candidate generation | success | Candidate artifact regenerated from full prepared posts |
| 25 post-to-trend matching | success | Regenerated using full candidate set and full normalized Twitter trends (parallel chunk execution, same stage logic/config) |
| 26 feature engineering | success | Feature table regenerated at one row per prepared `uri` |
| 27 baseline modeling | success | Baseline artifacts regenerated from new feature table |

## Old vs New Coverage (High Level)
| Metric | Before | After |
|---|---:|---:|
| Prepared posts rows | 25 | 19,999 |
| Topic candidate rows | 237 | 237,351 |
| Best-match rows | 19 | 17,958 |
| Best matched rows | 6 | 6,360 |
| Feature rows | 25 | 19,999 |

## Matching Outcome Shift
- Best-match stage counts (after rerun):
  - `unmatched`: 11,598
  - `semantic`: 4,555
  - `exact`: 1,134
  - `fuzzy`: 671
- Best matched rate:
  - before: `6/19 = 31.6%`
  - after: `6360/17958 = 35.4%`
- Temporal mode remained dominated by global fallback:
  - `global_fallback_no_date_overlap`: 217,115
  - `global_fallback_no_candidate_date`: 20,236

## Feature + Modeling Shift
- Feature label distribution (after rerun):
  - `LOW`: 17,124
  - `MEDIUM`: 1,568
  - `HIGH`: 1,307
- Baseline best model remained `bagged_stump_ensemble`.
- Metrics comparison (best model):
  - Accuracy: `0.75 -> 0.8563`
  - Macro F1: `0.50 -> 0.3075`
  - Balanced accuracy: `0.50 -> 0.3333`
- Confusion behavior on rerun data: model predicts majority class (`LOW`) and misses minority classes (`MEDIUM`/`HIGH` recall `0.0`).

## Important Limitations Observed
1. Matching still has high unresolved share (`unmatched` dominates best-stage output).
2. Feature joins are partial for downstream enrichment:
- prepared -> best match coverage: `89.79%`
- prepared -> hydrated metrics coverage: `47.99%`
- prepared -> actor profile coverage: `70.22%`
3. Baseline model quality is now dominated by class imbalance (high accuracy, weak macro/balanced performance).

## Artifacts Regenerated
- Phase 23:
  - `local/derived/bluesky/bluesky_posts_prepared.parquet`
  - `data/samples/bluesky_posts_prepared_sample_1000.parquet`
  - `data/samples/bluesky_posts_prepared_sample_1000.csv`
  - `local/derived/bluesky/bluesky_posts_preparation_summary.json`
- Phase 24:
  - `local/derived/bluesky/bluesky_topic_candidates.parquet`
  - `data/samples/bluesky_topic_candidates_sample_1000.parquet`
  - `data/samples/bluesky_topic_candidates_sample_1000.csv`
  - `local/derived/bluesky/bluesky_topic_candidate_summary.json`
- Phase 25:
  - `local/derived/matching/bluesky_post_trend_matches.parquet`
  - `local/derived/matching/bluesky_post_best_trend_matches.parquet`
  - `data/samples/bluesky_post_trend_matches_sample_1000.parquet`
  - `data/samples/bluesky_post_trend_matches_sample_1000.csv`
  - `local/derived/matching/bluesky_post_trend_matching_summary.json`
- Phase 26:
  - `local/derived/features/bluesky_engagement_features.parquet`
  - `data/samples/bluesky_engagement_features_sample_1000.parquet`
  - `data/samples/bluesky_engagement_features_sample_1000.csv`
  - `local/derived/features/bluesky_engagement_feature_summary.json`
- Phase 27:
  - `local/derived/modeling/baseline_model_metrics.json`
  - `local/derived/modeling/baseline_feature_importance.parquet`
  - `local/derived/modeling/baseline_predictions_sample.parquet`
  - `data/samples/baseline_predictions_sample_1000.csv`

## Recommended Next Move
- Keep this source-root fix as the default operational pattern (`BLUESKY_SOURCE_ROOT` override + repo-local fallback).
- Next highest-impact cleanup is not new model work:
  1. improve coverage by ingesting/unioning all hydrated and actor files under the selected root (not single-file selection),
  2. rerun Phase 26/27,
  3. then revisit matching quality and class-imbalance strategy with broader feature coverage.
