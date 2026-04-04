# Local Twitter Snapshot Validation Phase

## Purpose
This phase exists to harden the project after the Twitter snapshot extraction succeeded.

The snapshot phase is already treated as complete.
The remaining risk is not Snowflake access.
The remaining risk is local artifact confidence and environment reproducibility.

This phase must:
- validate that the local Twitter snapshot artifacts are real, usable, and internally consistent
- validate that the local sample files match the snapshot workflow
- add minimal environment/preflight checks so the parquet/tooling setup does not silently break again
- avoid Snowflake entirely

After this phase, the project should move into local profiling using only local files.

---

## Context

The Twitter dataset was already loaded successfully in this workspace.
The full parquet snapshot exists locally.
The metadata exists locally.
The sample outputs exist locally.

The historical blocker was a dependency/environment issue involving parquet tooling, not a live Snowflake access problem.

Because of that:
- do not re-pull the Twitter dataset
- do not query Snowflake for this phase
- do not restart the snapshot phase
- do not burn credits revalidating a dataset that is already saved locally

---

## Hard constraints

- Do not query Snowflake
- Do not rerun the Twitter snapshot extraction
- Do not start NLP
- Do not start normalization
- Do not start matching
- Do not start ML
- Work only from local artifacts already present in the workspace
- Keep the validation lightweight, deterministic, and reusable

---

## Inputs

Expected local inputs:
- `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`
- `local/reference_snapshots/twitter_trending/twitter_trending_snapshot_metadata.json`
- `data/samples/twitter_trending_sample_1000.parquet`
- `data/samples/twitter_trending_sample_1000.csv`

If any of these are missing, report it clearly.

---

## Required outputs

### 1. Local snapshot validation script
Create:

- `scripts/validate_twitter_snapshot_local.py`

This script should validate the local snapshot artifacts without using Snowflake.

### 2. Environment preflight script
Create:

- `scripts/preflight_local_data_env.py`

This script should confirm the local Python environment can import the required packages for local parquet/data work.

### 3. Validation results JSON
Create:

- `local/reference_snapshots/twitter_trending/twitter_trending_validation_report.json`

This should capture the results of the local validation pass.

### 4. Phase summary markdown
Create:

- `docs/20b_local_twitter_snapshot_validation_findings.md`

This should summarize what was validated, what passed, what failed, and whether local profiling can proceed.

### 5. Optional tests
If useful, create lightweight tests for validation helpers at:

- `tests/test_validate_twitter_snapshot_local.py`

---

## What must be validated

### A. File existence
Confirm that all expected local artifacts exist:
- full parquet snapshot
- metadata json
- parquet sample
- csv sample

### B. Metadata consistency
Validate that metadata contains expected fields such as:
- source table name
- extraction timestamp
- row count
- column names
- column dtypes
- local file path
- sample file paths
- query count if present

### C. Full parquet loadability
Validate that:
- the full parquet file can be opened
- row count can be read locally
- columns can be read locally
- the file is not obviously corrupt

### D. Sample consistency
Validate that:
- sample parquet loads
- sample csv loads
- row counts are as expected
- columns are consistent with the snapshot
- the sample appears to have been derived from the snapshot workflow

### E. Metadata vs parquet agreement
Validate that:
- parquet row count matches metadata row count
- parquet column names match or are consistent with metadata column names
- sample file paths in metadata are correct if metadata stores them

### F. Local environment readiness
Validate that the local environment can import:
- `pandas`
- `pyarrow`
- `snowflake.connector` (import only; do not connect)
- any other local-only packages that are required for the next profiling phase

The goal is to catch the historical dependency issue before it breaks later notebook work again.

---

## Implementation rules

- Use zero Snowflake queries
- Do not connect to Snowflake
- Keep the scripts simple and auditable
- Prefer local checks over complicated abstractions
- Fail clearly when artifacts are missing or inconsistent
- Emit a structured validation report JSON
- Do not mutate the snapshot artifacts in this phase
- Do not regenerate the sample files unless the validation proves they are missing or corrupt

---

## Validation report expectations

The JSON report should include:
- timestamp
- file existence results
- metadata parse results
- parquet load results
- sample load results
- metadata/parquet consistency results
- environment import results
- overall pass/fail
- blocking issues if any

---

## Summary markdown expectations

The markdown summary should include:
- what files were checked
- whether the snapshot is usable
- whether metadata and parquet agree
- whether the local environment is ready
- any remaining risks
- direct recommendation on whether the next phase can proceed to local profiling

---

## Definition of done

This phase is done only when:
- local snapshot artifacts have been validated without Snowflake
- the environment preflight exists
- the validation report JSON exists
- the summary markdown exists
- there is a clear answer on whether local profiling can proceed safely