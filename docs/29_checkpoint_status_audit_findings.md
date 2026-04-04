# 29 Checkpoint Status Audit Findings

Date: 2026-04-04

## Executive Summary
- Phases `20b` through `28` are broadly implemented locally with docs, code, notebooks, and output artifacts present.
- Verification evidence is strong for phases with tests: `75` targeted tests passed across validation, NLP, matching, features, baseline modeling, and refinement.
- Main pipeline weakness is not missing implementation; it is **weak match signal + tiny modeling dataset**:
  - only `25` prepared posts total,
  - no exact post-to-trend matches in current outputs,
  - best-match stage is mostly `unmatched`.
- Refinement/ablation ran, but did not beat baseline (recommended final model remains baseline).

## Phase-by-Phase Status (20b–28)
Status scheme used: `spec_only`, `partial`, `implemented_unverified`, `implemented_with_artifacts`, `complete`, `missing`.

| Phase | Spec Doc | Code | Tests | Notebook | Artifacts | Run Evidence | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| 20b local snapshot validation | yes | yes (`scripts/validate_twitter_snapshot_local.py`, `scripts/preflight_local_data_env.py`) | yes (`test_validate_twitter_snapshot_local.py`) | n/a | yes | validation JSON exists and reports pass | `complete` | `overall_pass=true`, `blocking_issues=0` |
| 21 local profiling | yes | n/a (not required) | none | yes | yes | profile summary/report JSON present | `implemented_with_artifacts` | no dedicated automated tests |
| 22 trend normalization | yes | yes (`src/nlp/trend_normalization.py`) | yes | yes | yes | normalized parquet + sample outputs present | `complete` | test file present and passed |
| 23 Bluesky text prep | yes | yes (`src/nlp/post_normalization.py`) | yes | yes | yes | prepared parquet + summary present | `complete` | test file present and passed |
| 24 candidate extraction | yes | yes (`src/nlp/topic_candidate_generation.py`) | yes | yes | yes | candidate parquet + summary present | `complete` | test file present and passed |
| 25 post-to-trend matching | yes | yes (`src/nlp/post_trend_matching.py`) | yes | yes | yes | full/best match parquet + summary present | `complete` | test file present and passed |
| 26 feature engineering | yes | yes (`src/features/feature_engineering.py`) | yes | yes | yes | features parquet + summary present | `complete` | test file present and passed |
| 27 baseline modeling | yes | yes (`src/modeling/baseline_model.py`) | yes | yes | yes | baseline metrics/importance/predictions present | `complete` | test file present and passed |
| 28 refinement/ablation | yes | yes (`src/modeling/model_refinement.py`) | yes | yes | yes | refined metrics/ablation/predictions present | `complete` | test file present and passed |

## Artifact Summary (Key Existing Outputs)
- Validation:
  - `local/reference_snapshots/twitter_trending/twitter_trending_validation_report.json`
- Twitter trend normalization:
  - `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`
  - `data/samples/twitter_trending_normalized_sample_1000.{parquet,csv}`
- Bluesky NLP/matching:
  - `local/derived/bluesky/bluesky_posts_prepared.parquet`
  - `local/derived/bluesky/bluesky_topic_candidates.parquet`
  - `local/derived/matching/bluesky_post_trend_matches.parquet`
  - `local/derived/matching/bluesky_post_best_trend_matches.parquet`
- Features:
  - `local/derived/features/bluesky_engagement_features.parquet`
- Modeling:
  - baseline: metrics, importance, predictions, confusion matrix
  - refinement: refined metrics, ablation parquet, refined importance/predictions, confusion matrix

## Test / Verification Evidence
- Executed command:
  - `python3 -m unittest -v tests.test_validate_twitter_snapshot_local tests.test_trend_normalization tests.test_post_normalization tests.test_topic_candidate_generation tests.test_post_trend_matching tests.test_feature_engineering tests.test_baseline_model tests.test_model_refinement`
- Result:
  - `Ran 75 tests ... OK`
- Coverage evidence by phase:
  - 20b, 22, 23, 24, 25, 26, 27, 28 each have dedicated test modules and passing evidence.
  - Phase 21 profiling has no dedicated unit tests (artifact/notebook-driven phase).

## NLP Pipeline Status
- Trend normalization (Phase 22):
  - normalized rows: `101,731`
  - columns: `20`
  - unique normalized date values: `749`
  - unique `normalized_key_no_hash`: `32,208`
- Bluesky text preparation (Phase 23):
  - prepared rows: `25` (`25` unique `uri`)
  - non-empty clean text: `24`; blank clean text: `1`
  - text source split: `hydrated_record_text=24`, `none=1`
- Candidate extraction (Phase 24):
  - candidate rows: `237`
  - posts with candidates: `19` (posts without candidates: `6`)
  - source mix: mostly `ngram_4`, `ngram_3`, `ngram_2`
- Matching (Phase 25):
  - full match rows: `243`
  - best-match rows: `19` (`19` unique posts)
  - best matched rate: `0.3158`
  - best stage distribution: `unmatched=13`, `semantic=4`, `fuzzy=2`, `exact=0`
  - temporal pool mode from summary: `global_fallback_no_date_overlap` dominates

## Feature Dataset Status (Phase 26)
- Feature table exists and is usable for modeling:
  - rows: `25`
  - columns: `92`
  - target `engagement_label` present
- Label distribution:
  - `LOW=16`, `MEDIUM=5`, `HIGH=4`
- Join coverage from feature summary:
  - prepared -> best match: `76%`
  - hydrated metrics: `100%`
  - actor profiles: `100%`
- Practical warning:
  - dataset is very small and class-imbalanced.

## Baseline + Refinement Modeling Status (Phases 27–28)
- Baseline best model: `bagged_stump_ensemble`
  - accuracy `0.75`
  - balanced accuracy `0.50`
  - macro F1 `0.50`
  - known issue: `HIGH` class recall is `0.0` on the test split
- Refinement/ablation:
  - refinement experiments executed: `4`
  - ablation artifact exists and is populated
  - selected refined experiment: `control_bagged_stump`
  - baseline vs refined deltas: all `0.0` for top-line metrics
  - recommendation in artifacts: keep `baseline`

## Biggest Current Risks (Evidence-Based)
1. **Data volume is too small for stable conclusions** (`25` posts total; test set tiny).
2. **Matching signal is weak** (`exact=0`, best stage mostly `unmatched`).
3. **Temporal alignment appears weak** (matching summary indicates global fallback mode dominates).
4. **Metric-definition ambiguity in matching summaries**:
   - summary `candidate_stage_counts` totals (`237`) do not equal full match row count (`243`), suggesting aggregation definitions differ and should be clarified before final reporting.
5. **Phase 21 lacks automated test verification** (artifact-driven only).

## Recommended Next Move (Blunt)
**Direction: debug a weak phase (matching) before any further model work.**

Specifically:
1. Reconcile and document matching summary metric definitions (`candidate_stage_counts` vs full rows).
2. Improve date/key alignment and exact/fuzzy candidate quality so match coverage improves.
3. Only after matching quality improves, rerun feature/model phases for a more credible final model narrative.

Current implementation coverage is high; the blocker is **signal quality**, not missing code.
