# Twitter Trend Normalization Phase

## Purpose
This phase exists to convert the locally saved Twitter trending dataset into a cleaned, normalized, downstream-ready dataset for later matching against Bluesky post text.

The local profiling phase should already be complete.
This phase must use only local files.

The goal is to create a repeatable normalization pipeline that:
- preserves the raw trend name
- creates cleaned comparison fields
- adds helper columns for later exact, fuzzy, and semantic matching
- writes a normalized local output for downstream development

---

## Hard constraints

- Do not query Snowflake in this phase
- Do not re-pull the marketplace dataset
- Do not rerun snapshot extraction
- Do not start post-to-trend matching in this phase
- Do not start ML in this phase
- Work only from validated local files
- Keep the normalization logic deterministic, reusable, and testable

---

## Inputs

Expected local inputs:
- `local/reference_snapshots/twitter_trending/twitter_trending_full.parquet`
- `data/samples/twitter_trending_sample_1000.parquet`
- `docs/22_twitter_trending_profile_findings.md`

If the local snapshot or profiling findings are missing, stop and report that the prior phase is incomplete.

---

## Required outputs

### 1. Reusable normalization module
Create:

- `src/nlp/trend_normalization.py`

This module should contain reusable functions for cleaning and normalizing trend names.

### 2. Local normalization notebook
Create:

- `notebooks/02_trend_normalization.ipynb`

This notebook should demonstrate the normalization logic on the local sample and local snapshot.

### 3. Normalized local outputs
Create:

- `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`
- `data/samples/twitter_trending_sample_1000_normalized.parquet`
- `data/samples/twitter_trending_sample_1000_normalized.csv`

### 4. Unit tests
Create:

- `tests/test_trend_normalization.py`

### 5. Phase summary markdown
Create:

- `docs/24_twitter_trend_normalization_findings.md`

---

## Main objectives

This phase must produce a stable local normalization layer for Twitter trend names.

At minimum, the prepared output should preserve enough information to support later exact, fuzzy, and semantic matching.

Conceptually, create fields equivalent to:

- `trend_name_raw`
- `trend_name_clean`
- `trend_name_clean_no_hash`
- `trend_name_alnum`
- `trend_name_token_count`
- `trend_name_char_count`
- `is_hashtag`
- `has_special_chars`
- `normalized_date` or a preserved normalized date field

If the source schema already uses different names, preserve the original columns and add these as new derived fields rather than overwriting source data.

---

## Recommended normalization logic

The exact implementation should follow the profiling findings, but should likely include:

- lowercasing
- trimming leading/trailing whitespace
- collapsing repeated internal whitespace
- Unicode normalization if needed
- punctuation normalization
- preserving hashtags in one cleaned field
- removing hashtags in a second cleaned field
- alphanumeric-only helper field for comparison
- stable token counting
- stable character counting
- flags for hashtag presence and special-character presence

Do not aggressively destroy meaning.
The goal is to improve matching readiness, not to erase useful distinctions.

---

## Rules for implementation

- Preserve original source columns
- Add derived normalization columns
- Keep transformations deterministic
- Keep the module reusable from later notebook/script phases
- Do not hard-code logic that is specific to one sample only
- Do not add semantic similarity yet
- Do not add fuzzy matching yet
- Do not join to Bluesky posts yet

---

## Notebook expectations

The notebook should include sections such as:

1. Load local raw snapshot
2. Load profiling findings context
3. Apply normalization functions to sample data
4. Inspect before/after examples
5. Validate helper columns
6. Apply normalization to the full local snapshot
7. Save normalized outputs
8. Summarize recommended next step

The notebook should show representative examples of:
- hashtags
- punctuation-heavy trends
- multi-word phrases
- noisy strings
- case variants

---

## Test expectations

Tests should cover:
- lowercase normalization
- whitespace normalization
- hashtag preservation/removal behavior
- punctuation handling
- alphanumeric helper generation
- token counts
- special-character flags
- null/empty string handling

The goal is to make later matching behavior stable and explainable.

---

## Summary markdown expectations

The summary markdown should include:
- what fields were added
- what normalization rules were implemented
- examples of before/after trend names
- any edge cases discovered
- any risks or limitations that remain
- what the next phase should implement

Be explicit about whether the normalized fields appear strong enough for:
- exact match
- fuzzy match candidate generation
- semantic fallback preparation

---

## Definition of done

This phase is done only when:
- the normalization module exists
- the notebook exists
- normalized local outputs exist
- unit tests exist
- the summary markdown exists
- the normalized trend dataset is ready for the later local Bluesky text preparation and matching phases