# 27 — Local Baseline ML Modeling

## Objective
Train and evaluate a local baseline classifier that predicts Bluesky engagement class (`LOW`, `MEDIUM`, `HIGH`) from the engineered local feature dataset.

This phase is local-only.

## Why this phase exists
Phase 26 produced an ML-ready local feature table.
The next step is to establish a credible baseline model, measure performance, identify the strongest signals, and determine whether the current feature set is good enough to support the class project goal.

This phase is baseline modeling only.
It should not introduce production orchestration or return to Snowflake.

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the Bluesky firehose
- Do NOT rerun hydration
- Do NOT rerun actor/profile enrichment
- Do NOT create new collection runs
- Do NOT modify raw source files in place
- Keep all work local and reproducible
- Keep modeling choices simple, explicit, and auditable
- Prefer lightweight baseline models before any complex tuning
- Do NOT build final Tableau outputs yet

## Required context to read first
Before implementing anything, read:

- `docs/26_local_feature_engineering.md`
- `docs/26_local_feature_engineering_findings.md`

If they exist, also read:
- `docs/26_local_feature_dictionary.md`
- `local/derived/features/bluesky_engagement_feature_summary.json`

Also inspect the actual local feature dataset schema before writing model logic.

## Inputs
Primary local input:
- `local/derived/features/bluesky_engagement_features.parquet`

Reference/debug inputs if useful:
- `data/samples/bluesky_engagement_features_sample_1000.parquet`
- `data/samples/bluesky_engagement_features_sample_1000.csv`

Use only the already-built local feature dataset.
Do not rebuild upstream phases in this phase.

## Deliverables
Create:

- `src/modeling/baseline_model.py`
- `notebooks/27_local_baseline_ml_modeling.ipynb`
- `docs/27_local_baseline_ml_modeling_findings.md`
- `tests/test_baseline_model.py`

Create local outputs:

- `local/derived/modeling/baseline_model_metrics.json`
- `local/derived/modeling/baseline_feature_importance.parquet`
- `local/derived/modeling/baseline_predictions_sample.parquet`
- `data/samples/baseline_predictions_sample_1000.csv`

Optional but preferred if useful:
- `local/derived/modeling/baseline_model_summary.json`
- `local/derived/modeling/baseline_confusion_matrix.csv`

## Required implementation behavior

### 1. Inspect and document the actual feature dataset
Inspect and document:
- target label column used
- raw engagement aggregate column used
- feature columns available
- debug/reference columns present
- categorical vs numeric vs boolean feature groups
- columns excluded from modeling and why

Do not assume field names blindly.
Use the actual Phase 26 output schema.

### 2. Define the modeling dataset explicitly
Create a reproducible modeling dataset from the feature table.

Requirements:
- one row per post unless Phase 26 explicitly produced a different grain
- explicit separation of:
  - target column
  - modeling features
  - debug/reference columns
- clear handling of non-model columns
- clear handling of missing values
- clear encoding strategy for categorical features

Do not allow accidental leakage columns into the model input.

### 3. Train baseline models only
Train a small set of clear baseline models.

Required starting models:
- multinomial logistic regression or equivalent linear baseline
- random forest or gradient boosting baseline

Optional:
- one additional lightweight baseline if it adds value cleanly

Do not overcomplicate the stack.
Do not jump straight to heavy tuning.

### 4. Train/test evaluation strategy
Implement a reproducible evaluation strategy.

Requirements:
- use a documented train/test split or cross-validation approach
- preserve class balance if appropriate and supported
- set random seeds for reproducibility
- document the exact split/evaluation approach used

Preferred:
- stratified train/test split for first baseline
- optional cross-validation summary if it is easy and clean

### 5. Metrics
Report practical multi-class classification metrics.

At minimum include:
- accuracy
- balanced accuracy
- macro precision
- macro recall
- macro F1
- per-class precision/recall/F1
- confusion matrix

If class imbalance is significant, make that explicit.
Do not rely on accuracy alone.

### 6. Baseline comparison
Compare the baseline models clearly.

Requirements:
- report metric summaries for each model
- identify the best baseline under a documented criterion
- keep model-comparison logic explicit and readable

### 7. Feature importance / interpretability
Provide lightweight interpretability for the baseline results.

At minimum:
- coefficient-based importance for logistic regression where meaningful
- feature importance for tree-based model where available

Requirements:
- write a local feature-importance artifact
- identify top positive/negative or most influential signals
- be explicit about the limits of the interpretation

### 8. Prediction outputs
Write a sample prediction output that includes enough auditability to inspect model behavior.

At minimum retain fields equivalent to:
- stable post identifier if available
- true label
- predicted label
- optional class probabilities if convenient
- raw engagement aggregate if useful
- a small set of debug/reference columns if available

### 9. Error analysis
Include lightweight error analysis.

At minimum inspect:
- common confusion pairs
- examples of wrong predictions
- whether errors cluster in particular label bands
- whether some features appear noisy, sparse, or unhelpful

Do not overdo it.
Keep it practical.

### 10. Notebook requirements
The notebook should:
- inspect the actual feature schema used
- explain model-input selection
- explain label distribution
- explain split/evaluation method
- train the baseline models
- compare results
- show confusion matrix
- show feature-importance summaries
- include lightweight error analysis
- end with a clear statement on whether the feature set is good enough for the project baseline

Keep it readable and concise.

### 11. Findings markdown
Write:
- `docs/27_local_baseline_ml_modeling_findings.md`

It should summarize:
- actual target/features used
- model-input exclusions and why
- evaluation strategy
- baseline models trained
- metrics by model
- best baseline selected and why
- top feature-importance observations
- major error-analysis observations
- known limitations
- whether the project is ready for Phase 28 refinement/final reporting

## Suggested module structure
`src/modeling/baseline_model.py` should expose small readable functions.

Suggested structure:
- dataset preparation helper
- split/evaluation helper
- baseline model builders
- metrics computation helper
- feature-importance extraction helper
- prediction artifact writer
- orchestration function

Keep it simple.
Do not build a framework.

## Modeling guardrails
- Do not include raw target-construction components as explanatory features if they leak the target label directly
- Do not include obviously unusable identifiers as model features
- Document excluded columns clearly
- Prefer reproducibility over marginal performance gains
- Keep hyperparameter tuning minimal or absent in this phase

## Testing requirements
Create tests for:
- model-input column selection / exclusion behavior
- deterministic split behavior with fixed seeds
- metric computation correctness
- baseline training pipeline runs on small synthetic data
- prediction output schema
- feature-importance artifact generation where applicable
- leakage guardrails where practical

Tests should validate correctness and reproducibility, not benchmark performance.

## Non-goals
This phase should NOT:
- touch Snowflake
- rerun any Bluesky collection/enrichment job
- rebuild the feature table
- perform extensive hyperparameter tuning
- build Tableau dashboards yet
- productionize the pipeline

## Definition of done
This phase is done when:
1. reusable baseline modeling logic exists in `src/modeling/baseline_model.py`
2. local model metrics, prediction samples, and feature-importance artifacts are written
3. tests cover core dataset-prep, evaluation, and artifact-writing logic
4. notebook and markdown findings document exactly how the baseline was trained and evaluated
5. the project is ready either for modest model refinement or final reporting/presentation work