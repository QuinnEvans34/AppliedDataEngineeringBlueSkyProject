# Bluesky Local Text Preparation Phase

## Purpose
This phase exists to prepare local Bluesky post text for downstream topic extraction and later matching against the normalized Twitter trend dataset.

The Snowflake work for this phase is already out of scope.
The Twitter trend normalization phase should already be complete.
This phase must work only from local Bluesky files that already exist.

The goal is to create a repeatable local preprocessing layer that:
- extracts usable post text from the existing Bluesky data
- normalizes post text in a deterministic way
- preserves original text
- adds helper fields for later topic extraction and match candidate generation
- writes clean local outputs for downstream NLP and matching work

---

## Hard constraints

- Do not query Snowflake in this phase
- Do not rerun the firehose
- Do not rerun Bluesky APIs
- Do not start post-to-trend matching in this phase
- Do not start ML in this phase
- Work only from existing local Bluesky data already present in the repo/workspace
- Keep the preprocessing deterministic, reusable, and testable

---

## Inputs

Expected local inputs should come from already existing Bluesky outputs, likely from:
- local run-root files under project data/output areas
- local raw post files
- local hydrated post files if useful for labels or text checks
- the normalized Twitter trend outputs from the previous phase:
  - `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`
  - `data/samples/twitter_trending_sample_1000_normalized.parquet`
- the prior phase summary:
  - `docs/23_twitter_trend_normalization_findings.md`

This phase must identify the best available local Bluesky text source and document what was used.

If no usable local Bluesky text files exist, stop and report that clearly.

---

## Required outputs

### 1. Reusable post normalization module
Create a Python module at:

- `src/nlp/post_normalization.py`

This module should contain reusable functions for extracting and normalizing Bluesky post text.

### 2. Local text-prep notebook
Create a notebook at:

- `notebooks/03_bluesky_text_prep.ipynb`

This notebook should demonstrate local Bluesky text extraction and preprocessing.

### 3. Cleaned local Bluesky outputs
Create local outputs for downstream matching work:

- `local/reference_snapshots/bluesky/bluesky_posts_text_prepared.parquet`
- `data/samples/bluesky_posts_text_prepared_sample.parquet`
- `data/samples/bluesky_posts_text_prepared_sample.csv`

### 4. Unit tests
Create tests at:

- `tests/test_post_normalization.py`

### 5. Phase summary markdown
Create a short summary at:

- `docs/25_bluesky_text_preparation_findings.md`

---

## Main objectives

This phase must produce a stable local text-preparation layer for Bluesky posts.

At minimum, the prepared output should preserve enough information to support later topic extraction and matching.

Conceptually, create fields equivalent to:

- `uri`
- `post_created_at` or equivalent timestamp
- `post_text_raw`
- `post_text_clean`
- `post_text_alnum`
- `post_token_count`
- `post_char_count`
- `has_hashtag`
- `has_url`
- `has_mention`
- `has_special_chars`
- `has_non_ascii`
- `source_run_tag` if available

If source files already use different field names, preserve the originals and add derived fields rather than overwriting them.

---

## Recommended preprocessing logic

The exact implementation should follow the actual Bluesky file structure, but will likely include:

- extracting the usable text field from the source record
- preserving original raw post text
- lowercasing
- trimming leading/trailing whitespace
- collapsing repeated internal whitespace
- optional Unicode normalization
- URL detection and optional stripped-text helper field
- mention detection
- hashtag detection
- punctuation normalization
- alphanumeric-only helper field
- stable token counts
- stable character counts
- flags for special-character and non-ASCII content

Do not destroy meaning.
The goal is to make topic extraction and candidate generation easier later.

---

## Rules for implementation

- Preserve original source fields
- Add derived normalization fields
- Keep logic deterministic
- Keep the module reusable for later phases
- Do not hard-code logic around one single sample row
- Do not join to Twitter trends yet
- Do not add fuzzy or semantic matching yet
- Do not over-clean away hashtags or entity-like text that may matter later

---

## Notebook expectations

The notebook should include sections such as:

1. Identify and load local Bluesky source files
2. Inspect source schema and pick text source field(s)
3. Apply normalization functions to sample rows
4. Inspect before/after examples
5. Validate helper fields
6. Apply preprocessing to the selected local dataset
7. Save prepared outputs
8. Summarize readiness for the next phase

The notebook should show representative examples of:
- plain text posts
- hashtag-heavy posts
- posts with URLs
- posts with mentions
- punctuation-heavy posts
- noisy or malformed text

---

## Test expectations

Tests should cover:
- text extraction from the selected source schema
- lowercase normalization
- whitespace normalization
- URL detection
- mention detection
- hashtag detection
- punctuation handling
- alphanumeric helper generation
- token counts
- special-character flags
- null/empty handling

The goal is to make later topic extraction stable and explainable.

---

## Summary markdown expectations

The summary markdown should include:
- what Bluesky source files were used
- what text field(s) were extracted
- what derived fields were added
- what preprocessing rules were implemented
- before/after examples
- edge cases discovered
- risks or limitations that remain
- whether the data now looks ready for topic extraction

Be explicit about whether the prepared Bluesky text appears strong enough for:
- local topic extraction
- exact trend matching candidate generation
- later fuzzy and semantic fallback

---

## Definition of done

This phase is done only when:
- the post normalization module exists
- the notebook exists
- prepared local Bluesky outputs exist
- tests exist
- the summary markdown exists
- the local Bluesky text is clean enough for the next topic-extraction phase