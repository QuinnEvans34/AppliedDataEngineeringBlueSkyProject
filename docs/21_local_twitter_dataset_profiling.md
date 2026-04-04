# 21 — Local Twitter Dataset Profiling

## Objective
Profile the already-validated local Twitter trending-topics snapshot to understand dataset structure, data quality, duplicates, missingness, naming patterns, and the normalization work needed for downstream matching.

This phase is local-only.

## Why this phase exists
Phase 20b established that the local Twitter snapshot artifacts are present, readable, internally consistent, and safe to use.

The next job is not to modify the data yet.
The next job is to understand it well enough to define precise normalization rules and avoid guessing.

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the marketplace extraction
- Do NOT modify the raw snapshot in place
- Do NOT start matching against Bluesky yet
- Do NOT start ML work yet
- Keep all work local and reproducible
- Prefer lightweight deterministic profiling over exploratory sprawl

## Inputs
Use the validated local artifacts, with the full parquet as the primary source of truth:

- `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`
- `local/reference_snapshots/twitter_trending/twitter_trending_snapshot_metadata.json`
- `data/samples/twitter_trending_sample_1000.parquet`
- `data/samples/twitter_trending_sample_1000.csv`
- `local/reference_snapshots/twitter_trending/twitter_trending_validation_report.json`

## Deliverables
Create:

- `notebooks/21_local_twitter_dataset_profiling.ipynb`
- `docs/21_local_twitter_dataset_profiling_findings.md`

Optional but preferred if cleanly supported by repo patterns:
- `local/reference_snapshots/twitter_trending/twitter_trending_profile_summary.json`

## Required profiling questions

### 1. Dataset shape and schema
Determine:
- row count
- column count
- column names
- dtypes
- candidate primary-key or uniqueness patterns if any exist

### 2. Missingness
Profile null / missing / blank values by column.
Call out:
- columns with no missingness
- columns with partial missingness
- columns with severe missingness
- whether blank strings appear where nulls should be

### 3. Duplicates
Measure:
- full-row duplicates
- duplicates on likely business keys if they exist
- repeated trend names across dates
- repeated trend/date combinations if relevant

Do not invent a business key if the schema does not support one.
Be explicit about what duplicate definitions were checked.

### 4. Value distributions
Profile the main fields likely to matter later, such as:
- trend/topic name field(s)
- date field(s)
- mention/count/volume field(s)
- duration / num_hours field(s)

Show useful descriptive statistics where applicable.

### 5. Trend naming noise and normalization needs
Inspect naming patterns and identify normalization problems such as:
- case variation
- punctuation variation
- hashtags
- URLs
- emojis
- stopword-heavy names
- trailing spaces / leading spaces
- non-ASCII characters
- repeated separators
- special symbols
- very short / low-information trend names
- obvious near-duplicates that differ only lexically

This phase should identify the problems, not solve them yet.

### 6. Temporal structure
Inspect:
- date range covered
- daily row counts
- whether some dates appear sparse or missing
- whether the data appears consistent over time

### 7. Outliers / suspicious values
Check for suspicious values in numeric columns, including:
- zeros
- negatives where not expected
- extreme high values
- impossible or strange durations/counts if present

### 8. Profiling conclusions for normalization
Produce a concrete recommendation section answering:
- what exact normalization rules should be implemented next
- which columns should be preserved as raw
- which derived normalized fields should be added later
- what edge cases need tests

## Notebook requirements
The notebook should:
- run from repo root assumptions or clearly document path handling
- be readable and structured
- have markdown cells explaining what each section is doing
- avoid huge printed outputs
- use concise tables / summaries
- end with a clear “recommended normalization rules” section

## Markdown findings requirements
Write:
`docs/21_local_twitter_dataset_profiling_findings.md`

It should summarize:
- dataset shape
- major missingness findings
- duplicate findings
- naming/noise findings
- temporal findings
- suspicious numeric findings
- exact recommended normalization rules for Phase 22
- go/no-go decision for moving into normalization

## Optional JSON summary
If implemented, write:
`local/reference_snapshots/twitter_trending/twitter_trending_profile_summary.json`

This should include compact machine-readable summaries for:
- shape
- schema
- null counts
- duplicate metrics
- date range
- top naming issues
- recommended next step

## Non-goals
This phase should NOT:
- alter the validated snapshot
- write normalized outputs
- create final matching logic
- join to Bluesky posts
- train a model
- query Snowflake

## Definition of done
This phase is done when:
1. a reproducible local profiling notebook exists
2. profiling findings are documented in markdown
3. the team has a concrete normalization spec for the next phase
4. the project can move into trend normalization without guesswork