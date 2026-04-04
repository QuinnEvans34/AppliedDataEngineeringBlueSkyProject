# Twitter Snapshot Local-First Phase

## Purpose
This phase exists to preserve the Snowflake Marketplace Twitter trend dataset locally and then stop using Snowflake for day-to-day development.

The goal is to make one careful, low-credit extraction from the marketplace dataset and save:
- a full local Parquet snapshot
- a small tracked repo sample
- a metadata record of the extraction

After this phase, profiling, NLP, matching, feature engineering, and baseline ML should all happen locally.

---

## Source dataset

Snowflake Marketplace shared dataset:
- `DAILY_TWITTER_TOP_TRENDS.DIESEL.TWITTER_TRENDING`

This dataset is temporary-trial-backed, so the project needs a durable local snapshot before access changes or expires.

---

## Hard constraints

- Use Snowflake as little as possible
- Keep Snowflake query count intentionally minimal
- Do not run exploratory Snowflake profiling queries
- Do not build notebooks directly against Snowflake
- Do not repeatedly sample from the marketplace listing
- Do not create unnecessary extra Snowflake objects in this phase
- Do not start NLP in this phase
- Do not start feature engineering in this phase
- Do not start ML in this phase

---

## Credit-usage policy

This phase should touch Snowflake only for the minimum needed to preserve the dataset.

Preferred pattern:
1. connect once
2. run one data pull from `DAILY_TWITTER_TOP_TRENDS.DIESEL.TWITTER_TRENDING`
3. save full data locally as Parquet
4. derive the repo sample locally, not through additional Snowflake queries
5. compute counts and profile metadata locally, not in Snowflake
6. stop using Snowflake for this dataset until the later automation phase

Avoid:
- repeated `COUNT(*)` queries
- repeated preview queries
- exploratory SQL loops
- unnecessary CTAS / temp tables / extra staging during this phase

---

## Required outputs

### 1. Full local snapshot
Create a full local Parquet snapshot here:

- `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`

This file should be gitignored and treated as the durable backup.

### 2. Local metadata file
Create metadata here:

- `local/reference_snapshots/twitter_trending/twitter_trending_snapshot_metadata.json`

Include:
- source table name
- extraction timestamp
- row count
- column names
- column dtypes
- local file path
- sample file paths
- any extraction notes

### 3. Small tracked repo sample
Create a small sample dataset derived from the local snapshot, not from a second Snowflake query.

Suggested tracked sample size:
- first `1000` rows after local load, or another small deterministic sample

Save to:
- `data/samples/twitter_trending_sample_1000.parquet`
- `data/samples/twitter_trending_sample_1000.csv`

### 4. Reusable extraction script
Create a script that performs the one-time extraction carefully and reproducibly.

Suggested path:
- `scripts/snapshot_twitter_trending.py`

---

## Implementation rules

- Use Python, not ad hoc manual export steps
- Keep the extraction logic simple and auditable
- Use the Snowflake connector already available in the project environment
- Read from the shared dataset once
- Save everything else locally
- If schema inspection is needed, prefer getting it from the fetched dataframe instead of extra SQL
- If one minimal metadata query is unavoidable, document it clearly
- Do not add unnecessary notebook work in this phase

---

## Git rules

The full Parquet snapshot must not be committed.
Ensure gitignore covers:
- `local/`
- `*.env`

Only the small sample files should be eligible to live in the tracked repo.

---

## Definition of done

This phase is done only when:
- the full dataset has been saved locally as Parquet
- the metadata JSON exists
- the small repo sample exists
- the extraction script exists
- Snowflake usage for this phase was intentionally minimal
- future development can proceed locally without re-querying the marketplace listing