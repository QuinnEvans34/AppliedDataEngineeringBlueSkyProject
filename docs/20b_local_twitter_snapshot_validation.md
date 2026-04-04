# 20b — Local Twitter Snapshot Validation

## Objective
Validate that the already-saved local Twitter trending-topics snapshot artifacts are present, internally consistent, and usable for downstream local NLP work.

This phase is local-only.

## Why this phase exists
The project has already:
- collected Bluesky raw/hydrated/account data
- proven enough Snowflake loader plumbing for current purposes
- saved the Twitter/X trending-topics snapshot locally

The current blocker is not warehouse access.
The current blocker is local artifact confidence and environment reproducibility.

Before profiling, normalization, or matching, we need to verify that the local snapshot is trustworthy and that the local Python environment can load the required parquet tooling.

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the Twitter marketplace extraction
- Do NOT connect to Snowflake
- Do NOT add warehouse validation work
- Treat the local snapshot as the source of truth unless artifacts are missing or corrupt
- Keep implementation lightweight and deterministic

## Expected inputs
These artifacts should already exist:

- `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`
- `local/reference_snapshots/twitter_trending/twitter_trending_snapshot_metadata.json`
- `data/samples/twitter_trending_sample_1000.parquet`
- `data/samples/twitter_trending_sample_1000.csv`

## Deliverables
Create:

- `scripts/validate_twitter_snapshot_local.py`
- `scripts/preflight_local_data_env.py`
- `local/reference_snapshots/twitter_trending/twitter_trending_validation_report.json`
- `docs/20b_local_twitter_snapshot_validation_findings.md`

Optional:
- lightweight tests if the repo already has a clean test pattern for scripts/utilities

## Required validation checks

### 1. Artifact presence
Verify that all expected files exist.

### 2. Parquet readability
Verify that the full parquet file can be loaded locally without error.

### 3. Sample readability
Verify that the sample parquet and sample CSV can be loaded locally without error.

### 4. Metadata sanity
Load the metadata JSON and confirm it is parseable and contains expected top-level fields.

### 5. Metadata vs parquet agreement
Compare the metadata against the loaded full parquet wherever possible, including:
- row count if present in metadata
- column names if present in metadata
- snapshot identifiers or timestamps if present
- file path / artifact references if present

Do not invent strict checks for metadata fields that do not exist.
Be adaptive and report which checks were performed vs skipped.

### 6. Basic dataframe sanity
Report at minimum:
- row count
- column count
- column names
- null counts by column
- duplicate row count if feasible
- a small preview summary in the report metadata, without printing huge outputs

### 7. Local environment imports
Verify importability of:
- `pandas`
- `pyarrow`
- `snowflake.connector`

Important:
`snowflake.connector` is import-only validation.
Do not create a connection.
Do not read credentials.
Do not perform any SQL.

## Output requirements

### JSON report
Write a machine-readable JSON report to:

`local/reference_snapshots/twitter_trending/twitter_trending_validation_report.json`

The report should include:
- timestamp
- overall status (`pass`, `warn`, or `fail`)
- artifact existence results
- import check results
- parquet/sample load results
- metadata parse results
- metadata-vs-parquet comparison results
- dataset summary stats
- warnings
- failures
- recommended next step

### Findings markdown
Write a concise human-readable summary to:

`docs/20b_local_twitter_snapshot_validation_findings.md`

The summary should include:
- what was checked
- what passed
- what failed or warned
- whether the project can proceed to local profiling
- exact blockers if it cannot proceed

## Implementation guidance
- Prefer small, readable functions
- Fail clearly
- Do not hide missing-file or import issues
- Avoid overengineering
- Keep console output concise and useful
- Make the scripts runnable from the repo root
- Use pathlib instead of hardcoded string concatenation
- Make report generation deterministic

## Suggested script split

### `scripts/preflight_local_data_env.py`
Purpose:
- validate imports only
- print concise status
- optionally emit a small JSON-compatible summary structure

### `scripts/validate_twitter_snapshot_local.py`
Purpose:
- validate files
- load parquet/csv/json artifacts
- compare metadata to parquet where possible
- generate validation report JSON
- print concise terminal summary

## Non-goals
This phase should NOT:
- profile trend semantics in depth
- design normalization rules
- modify the snapshot
- write normalized outputs
- run matching or ML
- query Snowflake

## Definition of done
This phase is done when:
1. the validation script runs locally
2. the JSON validation report is written
3. the findings markdown is written
4. the team can clearly answer whether the local snapshot is safe to use for profiling next