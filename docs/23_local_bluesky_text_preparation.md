# 23 — Local Bluesky Text Preparation

## Objective
Prepare local Bluesky post text for downstream topic extraction and post-to-trend matching by building a deterministic, reusable text-preparation layer.

This phase is local-only.

## Why this phase exists
Phase 22 normalized Twitter trend text.
The next requirement is to prepare Bluesky post text into a consistent form so later matching is comparing normalized trend text against normalized post text instead of raw noisy social text.

This phase is preparation only.
It should not yet perform final matching.

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the Bluesky firehose
- Do NOT rerun hydration
- Do NOT rerun actor/profile enrichment
- Do NOT create new collection runs
- Do NOT modify raw source files in place
- Keep all work local and reproducible
- Preserve raw text alongside derived prepared text
- Keep transformations deterministic and testable

## Required context to read first
Before implementing anything, read:

- `docs/22_local_twitter_trend_normalization.md`
- `docs/22_local_twitter_trend_normalization_findings.md`

Also inspect the locally available Bluesky data artifacts and use the best available local run root as source of truth.

## Inputs
Primary local source:
- the best available local Bluesky run root containing post text from previously collected data

Possible families available under a run root:
- `raw_posts/`
- `hydrated_posts/`
- `actor_profiles/`
- `hydration_misses/`

Use the local run root already collected.
Do not fetch new data.

If multiple run roots exist, choose the one that gives the best usable post-text coverage for local NLP preparation and document the choice clearly.

## Deliverables
Create:

- `src/nlp/post_normalization.py`
- `notebooks/23_local_bluesky_text_preparation.ipynb`
- `docs/23_local_bluesky_text_preparation_findings.md`
- `tests/test_post_normalization.py`

Create prepared local outputs:

- `local/derived/bluesky/bluesky_posts_prepared.parquet`
- `data/samples/bluesky_posts_prepared_sample_1000.parquet`
- `data/samples/bluesky_posts_prepared_sample_1000.csv`

Optional if useful:
- `local/derived/bluesky/bluesky_posts_preparation_summary.json`

## Required implementation behavior

### 1. Discover and document the source data used
Identify the local Bluesky artifact(s) used for preparation and document:
- chosen run root
- chosen input family/families
- why that source was selected
- approximate row count loaded
- which field(s) contain the post text
- which record identifier field(s) are retained

Do not assume names blindly.
Inspect the actual local schema and document it.

### 2. Preserve raw fields
Do not overwrite raw text fields.

Retain at minimum:
- a stable post identifier if available
- raw post text
- any useful timestamp/date field if available
- any engagement/account keys needed later if easy to retain without bloating the output

### 3. Add prepared text fields
Add clear derived fields for downstream NLP.
At minimum create fields equivalent to:
- raw post text
- prepared/normalized post text
- optional lightweight cleaned text variant if intermediate states help readability
- optional transformation flags

Use stable and explicit column names.

### 4. Text preparation rules
Implement deterministic rules appropriate for social post text, such as where justified:
- null-safe handling
- trimming whitespace
- collapsing repeated internal whitespace
- unicode normalization
- lowercasing if that aligns with trend normalization strategy
- URL handling
- mention handling
- hashtag handling
- newline normalization
- removal or normalization of obvious formatting artifacts
- preservation of semantically useful words/tokens

Important:
- do not aggressively strip away meaning
- do not remove tokens that may matter for later trend/topic matching unless there is a clear reason
- keep behavior aligned with the Twitter trend normalization approach where sensible

### 5. Basic preparation profiling
Measure at minimum:
- row count loaded
- non-null text count
- blank/empty prepared text count
- duplicate text rates before and after preparation if useful
- common artifacts seen in raw text
- representative before/after examples

### 6. Output writing
Write prepared outputs locally only.

Primary output:
- `local/derived/bluesky/bluesky_posts_prepared.parquet`

Also write lightweight sample outputs for quick inspection.

### 7. Notebook requirements
The notebook should:
- clearly document the chosen local source
- inspect the actual text schema used
- show the preparation rules
- demonstrate before/after examples
- summarize common post-text artifacts
- identify any limitations relevant to the next phase

Keep it readable and concise.

### 8. Findings markdown
Write:
- `docs/23_local_bluesky_text_preparation_findings.md`

It should summarize:
- which local Bluesky source was used
- which text field was prepared
- exact preparation rules implemented
- common artifacts discovered
- major before/after observations
- known limitations
- whether the data is ready for Phase 24 candidate extraction

## Suggested module structure
`src/nlp/post_normalization.py` should expose small readable functions.

Suggested structure:
- single-value post text normalization function
- dataframe-level application helper
- optional helper functions for URLs/mentions/hashtags/whitespace cleanup
- optional transformation flags generation

Keep it simple.
Do not build a framework.

## Testing requirements
Create tests for:
- null input
- blank input
- whitespace cleanup
- newline cleanup
- URL handling
- mention handling
- hashtag handling
- case normalization if used
- at least several real edge cases discovered from the actual local Bluesky text

Tests should validate deterministic outputs.

## Non-goals
This phase should NOT:
- touch Snowflake
- rerun any Bluesky collection/enrichment job
- perform final trend matching
- add fuzzy matching
- add semantic similarity
- train a model

## Definition of done
This phase is done when:
1. reusable post preparation logic exists in `src/nlp/post_normalization.py`
2. prepared local parquet/sample outputs are written
3. tests cover the main text-preparation rules and edge cases
4. notebook and markdown findings document exactly what was done
5. the project is ready to move into local topic extraction / candidate generation