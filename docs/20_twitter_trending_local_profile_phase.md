# Twitter Trending Local Profile Phase

## Purpose
This phase exists to profile the locally saved Twitter trending dataset and understand its structure before building normalization, matching, or NLP logic.

The full dataset should already be preserved locally from the snapshot phase.
This phase must work from local files only.

The goal is to answer:
- what columns exist
- what the data types look like
- how many rows and unique topics exist
- how noisy the trend names are
- whether duplicates or missing values exist
- what cleaning rules will be needed before matching against Bluesky post text

---

## Hard constraints

- Do not query Snowflake in this phase
- Do not re-pull the marketplace dataset
- Do not start NLP implementation in this phase
- Do not start matching implementation in this phase
- Do not start ML in this phase
- Work only from the local snapshot and local sample files
- Keep the work lightweight, inspectable, and reproducible

---

## Input data

Expected local inputs:
- `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`
- `data/samples/twitter_trending_sample_1000.parquet`
- `data/samples/twitter_trending_sample_1000.csv`
- `local/reference_snapshots/twitter_trending/twitter_trending_snapshot_metadata.json`

If the full local snapshot is missing, stop and report that the previous phase is incomplete.

---

## Required outputs

### 1. Profiling notebook
Create a local notebook at:

- `notebooks/01_profile_twitter_trending.ipynb`

The notebook should profile the local dataset only.

### 2. Profiling summary markdown
Create a short markdown summary at:

- `docs/21_twitter_trending_profile_findings.md`

This should summarize the main findings and recommended cleaning rules.

### 3. Optional reusable helper script
If useful, create a helper script at:

- `scripts/profile_twitter_trending.py`

This is optional, but acceptable if it helps keep logic reusable.

---

## Questions this phase must answer

### Dataset structure
- What columns exist?
- What data types do they have?
- Which fields appear most important for downstream use?
- Which columns are likely safe to keep as-is?
- Which columns may require cleaning or normalization?

### Volume and uniqueness
- Total row count from the local snapshot
- Number of unique topic names
- Number of unique dates
- Row counts per day
- Frequency distribution of repeated topics

### Data quality
- Missing value counts by column
- Duplicate row counts
- Duplicate counts for likely business keys such as `date + name`
- Outlier checks for numeric fields like trend volume or num_hours
- Strange or malformed trend names

### Text/noise analysis
- Distribution of topic/token lengths
- Hashtag frequency
- Special-character frequency
- Multi-word phrase frequency
- Case variation
- Punctuation/noise patterns
- Whether trends appear to need:
  - lowercasing
  - punctuation stripping
  - hashtag normalization
  - whitespace normalization
  - alphanumeric helper keys

### Downstream matching readiness
The notebook and summary should end with a concrete recommendation for:
- what normalized trend key to create
- what text cleaning rules to apply before matching
- whether exact matching alone is too weak
- whether fuzzy matching and semantic fallback will likely be needed

---

## Notebook expectations

The notebook should be organized clearly with sections such as:

1. Load local files
2. Dataset overview
3. Column inspection
4. Missing values and duplicates
5. Date and topic distributions
6. Trend-name noise analysis
7. Candidate normalization rules
8. Recommendations for the next phase

Use local pandas-based analysis.
Keep the notebook deterministic and readable.

Avoid:
- unnecessary visual clutter
- large or slow plots that do not add value
- broad experimentation that belongs to later phases

---

## Summary markdown expectations

The markdown summary should include:
- dataset size
- key columns
- duplicate findings
- missing-value findings
- trend-name noise findings
- recommended normalization rules
- risks for later matching
- exact recommendations for the next implementation phase

The summary should be direct and implementation-oriented.

---

## Definition of done

This phase is done only when:
- the notebook exists
- the notebook runs on the local snapshot
- the summary markdown exists
- the dataset structure and quality are clearly understood
- the likely trend-normalization rules are explicitly documented
- the next phase can move into trend normalization without guessing