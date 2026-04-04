# 28 Local Model Refinement and Ablation Findings

Date: 2026-04-04

## Scope
- Phase spec: `docs/28_local_model_refinement_and_ablation.md`
- Mode: local-only (`0` Snowflake queries, `0` collection/enrichment reruns)
- Input feature table: `local/derived/features/bluesky_engagement_features.parquet`
- Baseline artifacts used:
  - `local/derived/modeling/baseline_model_metrics.json`
  - `local/derived/modeling/baseline_model_summary.json`
  - `local/derived/modeling/baseline_confusion_matrix.csv`
  - `local/derived/modeling/baseline_feature_importance.parquet`

## Baseline Starting Point
- Best baseline from Phase 27: `bagged_stump_ensemble`
- Baseline weakness confirmed: minority class `HIGH` recall = `0.0000` on the Phase 27 test split.
- Baseline reference metrics:
  - accuracy: `0.7500`
  - balanced accuracy: `0.5000`
  - macro precision: `0.5714`
  - macro recall: `0.5000`
  - macro F1: `0.5000`

## Refinement Experiments Run
All experiments reused the same deterministic split protocol and fixed seed.

1. `control_bagged_stump`
- family: bagged stump
- balanced resampling: no
- result: accuracy `0.7500`, balanced accuracy `0.5000`, macro F1 `0.5000`

2. `bagged_stump_balanced_resample`
- family: bagged stump
- balanced resampling: yes (class-balanced train resample)
- result: accuracy `0.6250`, balanced accuracy `0.4333`, macro F1 `0.4091`

3. `bagged_stump_balanced_resample_tuned`
- family: bagged stump
- balanced resampling: yes
- modest tuning: higher estimator count + threshold count
- result: accuracy `0.6250`, balanced accuracy `0.4333`, macro F1 `0.4091`

4. `softmax_refined_control`
- family: softmax regression
- balanced resampling: no
- modest linear-control hyperparameters
- result: accuracy `0.6250`, balanced accuracy `0.4333`, macro F1 `0.4646`

Selected refined experiment (by macro F1, then balanced accuracy, then accuracy):
- `control_bagged_stump`

## Baseline vs Refined Comparison
- Selected refined experiment reproduces baseline-best metrics exactly:
  - macro F1 delta: `0.0000`
  - balanced accuracy delta: `0.0000`
  - accuracy delta: `0.0000`
  - `HIGH` recall delta: `0.0000`
- Decision rule outcome: `prefer_refined_model = false`
- Recommended final modeling story: **baseline**

## Feature Groups and Ablation Results
Derived groups from actual baseline model columns:
- `trend_match`: `14` columns
- `post_text`: `11` columns
- `actor_account`: `11` columns
- `temporal`: `1` column

Required ablations run:
- `full_features`
- `no_trend_match_features`
- `no_post_text_features`
- `no_actor_account_features`
- `no_temporal_features`

Observed result:
- All ablation variants produced the same metrics as full features on this very small split:
  - accuracy `0.7500`
  - balanced accuracy `0.5000`
  - macro F1 `0.5000`
- Interpretation: with current sample size (`25` total rows, `8` test rows), group-level ablation sensitivity is too weak to draw strong causal claims.

## Feature Importance Follow-Up (Selected Refined Model)
Top refined (stump) signals remained consistent with Phase 27 diagnostics:
- `num__actor_followers_to_follows_ratio`
- `num__post_unique_token_count`
- `num__post_char_count`
- `num__post_token_count`
- `num__candidate_count`

## Outputs Written
- `src/modeling/model_refinement.py`
- `tests/test_model_refinement.py`
- `notebooks/28_local_model_refinement_and_ablation.ipynb`
- `local/derived/modeling/refined_model_metrics.json`
- `local/derived/modeling/model_ablation_results.parquet`
- `local/derived/modeling/refined_feature_importance.parquet`
- `local/derived/modeling/refined_predictions_sample.parquet`
- `data/samples/refined_predictions_sample_1000.csv`
- `local/derived/modeling/model_refinement_summary.json` (optional)
- `local/derived/modeling/refined_confusion_matrix.csv` (optional)

## Recommendation and Readiness
- Final model to present: **Phase 27 baseline (`bagged_stump_ensemble`)**.
- Why:
  - refinement experiments did not produce material metric improvement,
  - balanced-resample variants degraded macro and balanced performance,
  - simpler baseline story is cleaner and more defensible.
- Project readiness for final reporting/presentation artifacts: **YES, with explicit small-sample caveats**.
