# 28 — Local Model Refinement and Ablation

## Objective
Refine the baseline engagement classifier with a small, controlled set of improvements and run ablation analysis to determine which feature groups materially help prediction quality.

This phase is local-only.

## Why this phase exists
Phase 27 established a baseline model and produced initial metrics, feature-importance outputs, and error-analysis findings.

The next step is not to jump into a complex modeling stack.
The next step is to make a small number of targeted improvements grounded in observed baseline weaknesses, then measure whether those changes actually help.

This phase should answer:
- which simple refinements improve performance
- which feature groups matter most
- whether the current pipeline is good enough for the class project
- what should be presented as the final modeling story

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the Bluesky firehose
- Do NOT rerun hydration
- Do NOT rerun actor/profile enrichment
- Do NOT create new collection runs
- Do NOT modify raw source files in place
- Keep all work local and reproducible
- Keep model refinement limited, explicit, and auditable
- Prefer a small number of meaningful experiments over wide hyperparameter sprawl
- Do NOT build final Tableau outputs yet

## Required context to read first
Before implementing anything, read:

- `docs/27_local_baseline_ml_modeling.md`
- `docs/27_local_baseline_ml_modeling_findings.md`
- `docs/26_local_feature_engineering_findings.md`

If they exist, also inspect:
- `local/derived/modeling/baseline_model_metrics.json`
- `local/derived/modeling/baseline_model_summary.json`
- `local/derived/modeling/baseline_confusion_matrix.csv`
- `local/derived/modeling/baseline_feature_importance.parquet`

Refinement choices must be grounded in actual baseline results.
Do not invent experiments randomly.

## Inputs
Primary local input:
- `local/derived/features/bluesky_engagement_features.parquet`

Baseline modeling artifacts:
- `local/derived/modeling/baseline_model_metrics.json`
- `local/derived/modeling/baseline_feature_importance.parquet`
- `local/derived/modeling/baseline_predictions_sample.parquet`

Use the already-built local feature dataset and baseline artifacts only.
Do not rebuild upstream phases in this phase.

## Deliverables
Create:

- `src/modeling/model_refinement.py`
- `notebooks/28_local_model_refinement_and_ablation.ipynb`
- `docs/28_local_model_refinement_and_ablation_findings.md`
- `tests/test_model_refinement.py`

Create local outputs:

- `local/derived/modeling/refined_model_metrics.json`
- `local/derived/modeling/model_ablation_results.parquet`
- `local/derived/modeling/refined_feature_importance.parquet`
- `local/derived/modeling/refined_predictions_sample.parquet`
- `data/samples/refined_predictions_sample_1000.csv`

Optional but preferred if useful:
- `local/derived/modeling/model_refinement_summary.json`
- `local/derived/modeling/refined_confusion_matrix.csv`

## Required implementation behavior

### 1. Inspect and document the actual baseline setup
Inspect the actual baseline artifacts and document:
- target column used
- feature groups available
- best baseline model selected in Phase 27
- main error patterns
- class-imbalance observations
- feature-importance observations
- any obvious issues from baseline findings such as weak minority-class recall or noisy feature groups

Do not assume which model won.
Use the actual results.

### 2. Limit refinement scope
Refinement must stay controlled.

Implement a small, explicit set of refinements grounded in baseline findings.
Examples of acceptable refinements:
- class weighting if imbalance hurt recall
- modest hyperparameter tuning for the best baseline family
- comparing two or three sensible tree depths / estimator counts
- improved missing-value handling if baseline issues showed feature sparsity pain
- simple probability-threshold or decision-policy adjustments only if clearly justified
- excluding weak/noisy/leakage-risk features based on baseline evidence
- testing a slightly different model family only if it remains lightweight and justified

Do NOT run a large search grid.
Do NOT add heavy models just to add them.

### 3. Define feature groups for ablation
Create explicit feature-group definitions such as:
- trend-match features
- post-text features
- actor/account features
- temporal features

If the actual feature table supports a different grouping structure, document it.
The groups must match the actual engineered schema.

### 4. Run ablation experiments
Run a clear set of ablation experiments to measure how feature groups affect performance.

At minimum include:
- full feature set
- remove trend-match features
- remove post-text features
- remove actor/account features if available
- remove temporal features if available

If some groups do not exist, document that and skip them explicitly.

Requirements:
- use the same evaluation setup for fair comparison
- write experiment results in a machine-readable format
- keep experiment naming explicit and stable

### 5. Reproducible evaluation strategy
Use a reproducible evaluation approach aligned with Phase 27.

Requirements:
- fixed random seed(s)
- documented split or CV approach
- consistent metric set across baseline and refinement experiments
- explicit comparison to the prior baseline

Do not silently change the evaluation framework in a way that makes comparison invalid.

### 6. Metrics
For each refinement and ablation experiment, report at minimum:
- accuracy
- balanced accuracy
- macro precision
- macro recall
- macro F1
- per-class precision/recall/F1 where practical

Also retain confusion matrix for the selected refined model.

### 7. Baseline-vs-refined comparison
Compare:
- original best baseline
- refined best model
- key ablation variants

Requirements:
- identify whether refinement produced a real improvement
- identify whether any improvements came with tradeoffs such as worse minority-class performance
- be explicit if gains are marginal or not worth the added complexity

### 8. Refined prediction and importance artifacts
Write outputs for the selected refined model, including:
- metrics JSON
- feature-importance artifact
- prediction sample
- optional confusion matrix export

Preserve enough auditability to inspect errors and top signals.

### 9. Notebook requirements
The notebook should:
- inspect actual baseline results first
- explain why each refinement experiment was chosen
- explain feature-group definitions for ablation
- compare baseline vs refined metrics
- summarize ablation findings
- show confusion matrix for the selected refined model
- include concise error-analysis follow-up
- end with a clear recommendation:
  - keep baseline as final
  - or use refined model as final
  - and explain why

Keep it readable and concise.

### 10. Findings markdown
Write:
- `docs/28_local_model_refinement_and_ablation_findings.md`

It should summarize:
- actual baseline model and issues observed
- exact refinement experiments run
- exact ablation experiments run
- metric outcomes and tradeoffs
- whether refinement materially improved the result
- which feature groups mattered most
- whether the final project should present the baseline or refined model
- known limitations
- whether the project is ready for final reporting/presentation artifacts

## Suggested module structure
`src/modeling/model_refinement.py` should expose small readable functions.

Suggested structure:
- baseline artifact reader/helper
- experiment configuration helper
- feature-group ablation helper
- refinement experiment runner
- metrics comparison helper
- artifact writer
- orchestration function

Keep it simple.
Do not build a framework.

## Guardrails
- Do not introduce heavy search or overfitting-prone experimentation
- Do not change many things at once without isolating the effect
- Do not hide poor results
- If refinement does not materially help, say so explicitly
- Keep the project story clean and defensible for class presentation

## Testing requirements
Create tests for:
- feature-group ablation column selection
- experiment configuration reproducibility
- metric comparison helpers
- refined-model pipeline run on small synthetic data
- artifact-writing schema
- baseline-vs-refined comparison logic
- deterministic outputs where practical

Tests should validate correctness and reproducibility, not model quality.

## Non-goals
This phase should NOT:
- touch Snowflake
- rerun any Bluesky collection/enrichment job
- rebuild upstream phases
- run large hyperparameter searches
- build final Tableau dashboards yet
- productionize the pipeline

## Definition of done
This phase is done when:
1. reusable refinement/ablation logic exists in `src/modeling/model_refinement.py`
2. refined-model and ablation artifacts are written locally
3. tests cover core experiment and artifact logic
4. notebook and markdown findings document exactly what was tested and what improved
5. the project is ready to move into final reporting/presentation artifacts