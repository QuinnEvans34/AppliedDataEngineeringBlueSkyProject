# 27 Local Baseline ML Modeling Findings

Date: 2026-04-04

## Scope
- Phase spec: `docs/27_local_baseline_ml_modeling.md`
- Mode: local-only (`0` Snowflake queries, `0` collection/enrichment reruns)
- Input feature table: `local/derived/features/bluesky_engagement_features.parquet`

## Modeling Setup
Actual target used:
- `engagement_label` (`LOW`, `MEDIUM`, `HIGH`)

Label-support columns retained for audit only:
- `engagement_total`
- `eng_like_count`, `eng_reply_count`, `eng_repost_count`, `eng_quote_count`

Model/debug separation:
- target column: `engagement_label`
- selected model feature columns: `36`
- debug/reference columns: `19`

Because `scikit-learn` is unavailable in this local environment, deterministic NumPy baselines were used:
1. `softmax_regression` (multinomial linear baseline)
2. `bagged_stump_ensemble` (random-forest-style tree baseline via bagged decision stumps)

## Excluded Columns and Why
Leakage exclusions:
- `engagement_label`, `engagement_total`
- `eng_like_count`, `eng_reply_count`, `eng_repost_count`, `eng_quote_count`
- `like_count`, `reply_count`, `repost_count`, `quote_count`

Debug/reference exclusions:
- identifiers and trace fields such as `uri`, author DIDs/handles, raw text fields, trend display fields, and lineage JSONs

Additional exclusions:
- unsupported high-cardinality/string timestamp-id fields (for simple reproducible baseline encoding)
- constant columns (no learning signal in this slice)

## Evaluation Strategy
- Deterministic stratified split with fixed seed (`random_seed=42`)
- Test size: `0.30` (actual split: train `17`, test `8`)
- Class distribution:
  - train: `HIGH=3`, `LOW=11`, `MEDIUM=3`
  - test: `HIGH=1`, `LOW=5`, `MEDIUM=2`
- Model selection criterion:
  - `macro_f1` (primary), then `balanced_accuracy`, then `accuracy`

## Metrics by Model
### Softmax Regression
- Accuracy: `0.6250`
- Balanced accuracy: `0.4333`
- Macro precision: `0.5556`
- Macro recall: `0.4333`
- Macro F1: `0.4646`
- Per-class:
  - HIGH: precision `0.0000`, recall `0.0000`, F1 `0.0000`
  - LOW: precision `0.6667`, recall `0.8000`, F1 `0.7273`
  - MEDIUM: precision `1.0000`, recall `0.5000`, F1 `0.6667`
- Confusion matrix (`[HIGH, LOW, MEDIUM]` rows/cols):
  - `[[0,1,0],[1,4,0],[0,1,1]]`

### Bagged Stump Ensemble
- Accuracy: `0.7500`
- Balanced accuracy: `0.5000`
- Macro precision: `0.5714`
- Macro recall: `0.5000`
- Macro F1: `0.5000`
- Per-class:
  - HIGH: precision `0.0000`, recall `0.0000`, F1 `0.0000`
  - LOW: precision `0.7143`, recall `1.0000`, F1 `0.8333`
  - MEDIUM: precision `1.0000`, recall `0.5000`, F1 `0.6667`
- Confusion matrix (`[HIGH, LOW, MEDIUM]` rows/cols):
  - `[[0,1,0],[0,5,0],[0,1,1]]`

## Best Baseline
Selected best baseline: **`bagged_stump_ensemble`**

Why:
- higher macro F1 (`0.5000` vs `0.4646`)
- higher balanced accuracy (`0.5000` vs `0.4333`)
- higher accuracy (`0.7500` vs `0.6250`)

## Feature-Importance Observations
Top softmax aggregate signals (`__all__` importance):
- `num__raw_question_count`
- `num__actor_followers_to_follows_ratio`
- `num__is_ambiguous_match`
- `num__trend_counts`
- `num__raw_exclamation_count`

Top stump importance signals:
- `num__actor_followers_to_follows_ratio`
- `num__post_unique_token_count`
- `num__post_char_count`
- `num__post_token_count`
- `num__candidate_count`

Interpretation caveat:
- dataset is very small; these importances are directional baseline diagnostics, not stable causal evidence.

## Error Analysis (Lightweight)
Prediction sample size: `8` test rows

Common confusion pairs:
- `MEDIUM -> LOW` (`1` row)
- `HIGH -> LOW` (`1` row)

Pattern:
- models are biased toward `LOW` on sparse data; both baselines miss the single `HIGH` test example.

## Outputs Written
- `src/modeling/baseline_model.py`
- `tests/test_baseline_model.py`
- `notebooks/27_local_baseline_ml_modeling.ipynb`
- `local/derived/modeling/baseline_model_metrics.json`
- `local/derived/modeling/baseline_feature_importance.parquet`
- `local/derived/modeling/baseline_predictions_sample.parquet`
- `data/samples/baseline_predictions_sample_1000.csv`
- `local/derived/modeling/baseline_model_summary.json` (optional)
- `local/derived/modeling/baseline_confusion_matrix.csv` (optional)

## Limitations
- Very small dataset (`25` rows total, `8` test rows).
- Class imbalance and sparse match-signal coverage reduce reliability for minority/high-engagement class performance.
- No cross-validation in this phase to avoid overengineering on tiny data.

## Readiness for Next Phase
Ready for next phase (refinement/final reporting): **YES, with caveats**.

Reason:
- deterministic baseline modeling pipeline is implemented, tested, and auditable.
- required model metrics, comparison, confusion, importance, and prediction artifacts are available.

Caveat:
- next phase should focus on stability/robustness (e.g., richer data slice, tighter feature pruning, and optional CV) before drawing strong performance conclusions.
