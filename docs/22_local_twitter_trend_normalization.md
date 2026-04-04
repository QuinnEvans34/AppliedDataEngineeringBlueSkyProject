# 22 — Local Twitter Trend Normalization

## Objective
Implement reusable, deterministic normalization logic for the validated local Twitter trending-topics snapshot so downstream matching can operate on consistent normalized trend text instead of noisy raw names.

This phase is local-only.

## Why this phase exists
Phase 21 profiled the local Twitter snapshot and identified the exact naming noise, duplicate patterns, and normalization needs in the dataset.

This phase turns those profiling findings into actual normalization logic and normalized local outputs.

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the marketplace extraction
- Do NOT modify the raw snapshot in place
- Do NOT start Bluesky matching yet
- Do NOT train ML yet
- Keep all work local and reproducible
- Normalization must be deterministic and testable
- Preserve raw values alongside normalized values

## Required context to read first
Before implementing anything, read:

- `docs/21_local_twitter_dataset_profiling.md`
- `docs/21_local_twitter_dataset_profiling_findings.md`

If profiling produced a JSON summary, use it too:

- `local/reference_snapshots/twitter_trending/twitter_trending_profile_summary.json`

Normalization rules must follow observed profiling findings.
Do not invent extra transformations unless they are clearly justified by the profiling output.

## Inputs
Primary raw input:

- `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`

Related local artifacts:

- `local/reference_snapshots/twitter_trending/twitter_trending_snapshot_metadata.json`
- `local/reference_snapshots/twitter_trending/twitter_trending_validation_report.json`
- `data/samples/twitter_trending_sample_1000.parquet`
- `data/samples/twitter_trending_sample_1000.csv`

## Deliverables
Create:

- `src/nlp/trend_normalization.py`
- `notebooks/22_local_twitter_trend_normalization.ipynb`
- `docs/22_local_twitter_trend_normalization_findings.md`

Create normalized local outputs:

- `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`
- `data/samples/twitter_trending_normalized_sample_1000.parquet`
- `data/samples/twitter_trending_normalized_sample_1000.csv`

Create tests:

- `tests/test_trend_normalization.py`

Optional if useful:
- `local/reference_snapshots/twitter_trending/twitter_trending_normalization_summary.json`

## Required implementation behavior

### 1. Preserve raw source fields
Do not overwrite the original trend/topic text field.

The normalized dataset should preserve:
- original raw trend/topic text
- any original columns needed later for date, count, duration, or metadata

### 2. Add normalized fields
Add explicit derived columns for normalization outputs.

At minimum create fields equivalent to:
- raw trend/topic text
- normalized trend/topic text
- optional intermediate cleaned text if useful
- optional flags describing transformations applied

Use column names that are clear and stable.

### 3. Normalization rules
Implement the exact rules justified by profiling findings.

Typical examples may include:
- unicode normalization
- trimming leading/trailing whitespace
- collapsing repeated internal whitespace
- lowercasing
- normalizing repeated punctuation/separators
- handling hashtags consistently
- handling URLs consistently
- handling obvious low-information formatting artifacts
- preserving semantically meaningful tokens where appropriate

Important:
- Do not strip meaning aggressively
- Do not remove information that could matter for downstream matching unless profiling clearly showed it should be normalized away
- Keep behavior deterministic

### 4. Null / blank handling
Handle nulls and blank strings explicitly.
The normalization pipeline should not crash on missing text values.

### 5. Duplicate analysis after normalization
Measure how normalization changes duplicates.

At minimum compare:
- duplicate counts before normalization
- duplicate counts after normalization
- examples of raw values that collapse into the same normalized form

### 6. Output writing
Write normalized outputs locally only.
Do not mutate the raw parquet.

The normalized full parquet should be written to:
- `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`

Also write lightweight sample outputs for inspection.

### 7. Notebook requirements
The notebook should:
- show the normalization rules used
- demonstrate before/after examples
- summarize duplicate reduction or consolidation effects
- show edge-case examples
- remain readable and concise
- end with a clear statement on whether the dataset is ready for Phase 23 post-to-trend matching preparation

### 8. Findings markdown
Write:
- `docs/22_local_twitter_trend_normalization_findings.md`

It should summarize:
- exact rules implemented
- why those rules were chosen
- what changed materially after normalization
- duplicate consolidation impact
- edge cases handled
- known limitations
- whether the dataset is ready for the next phase

## Suggested module structure
`src/nlp/trend_normalization.py` should expose small readable functions.

Suggested structure:
- a single-value normalization function for trend text
- a dataframe-level application helper
- optional helper functions for specific transformations
- optional transformation flags / audit metadata generation

Keep it simple.
Do not build a framework.

## Testing requirements
Create tests for:
- null input
- blank input
- whitespace normalization
- case normalization
- punctuation/separator cleanup where justified
- hashtag handling where justified
- URL handling where justified
- at least several real edge cases discovered during profiling

Tests should validate deterministic outputs.

## Non-goals
This phase should NOT:
- touch Snowflake
- rerun marketplace extraction
- join to Bluesky posts
- implement fuzzy matching yet
- implement semantic similarity yet
- train a model

## Definition of done
This phase is done when:
1. reusable normalization logic exists in `src/nlp/trend_normalization.py`
2. normalized local parquet/sample outputs are written
3. tests cover the main normalization rules and edge cases
4. notebook and markdown findings document what changed
5. the project is ready to move into local Bluesky text preparation and later matching