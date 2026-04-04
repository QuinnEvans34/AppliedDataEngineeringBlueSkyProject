# 24 — Local Topic Extraction / Candidate Generation

## Objective
Extract deterministic candidate topics/phrases from prepared local Bluesky post text so the next phase can compare candidate post topics against normalized Twitter trend text.

This phase is local-only.

## Why this phase exists
Phase 23 prepared Bluesky post text into a consistent form.
The next step is to extract candidate phrases/topics from that prepared text before any final post-to-trend matching logic is introduced.

This phase is about generating plausible candidate topics from posts.
It is not the final matching phase.

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the Bluesky firehose
- Do NOT rerun hydration
- Do NOT rerun actor/profile enrichment
- Do NOT create new collection runs
- Do NOT modify raw source files in place
- Keep all work local and reproducible
- Keep candidate extraction deterministic and testable
- Prefer lightweight NLP / rule-based extraction over anything LLM-based
- Do NOT perform final post-to-trend matching yet

## Required context to read first
Before implementing anything, read:

- `docs/23_local_bluesky_text_preparation.md`
- `docs/23_local_bluesky_text_preparation_findings.md`
- `docs/22_local_twitter_trend_normalization_findings.md`

Also inspect the local prepared Bluesky output produced in the previous phase.

## Inputs
Primary prepared input:
- `local/derived/bluesky/bluesky_posts_prepared.parquet`

Relevant reference input:
- `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`

The Twitter normalized dataset is reference context only in this phase.
Do not perform final matching against it yet.

## Deliverables
Create:

- `src/nlp/topic_candidate_generation.py`
- `notebooks/24_local_topic_extraction_candidate_generation.ipynb`
- `docs/24_local_topic_extraction_candidate_generation_findings.md`
- `tests/test_topic_candidate_generation.py`

Create candidate outputs:

- `local/derived/bluesky/bluesky_topic_candidates.parquet`
- `data/samples/bluesky_topic_candidates_sample_1000.parquet`
- `data/samples/bluesky_topic_candidates_sample_1000.csv`

Optional if useful:
- `local/derived/bluesky/bluesky_topic_candidate_summary.json`

## Required implementation behavior

### 1. Use actual prepared Bluesky text fields
Inspect the prepared Bluesky dataset and document:
- which prepared text column is used
- which raw text column is retained
- which post identifier column is retained
- whether timestamp/date fields are carried forward

Do not assume column names blindly.
Use the actual output schema from Phase 23.

### 2. Candidate extraction should be deterministic
Use deterministic extraction methods only.

Acceptable approaches:
- spaCy tokenization / noun chunks if supported cleanly
- rule-based phrase extraction
- n-gram candidate generation with filtering
- lightweight heuristic filters for low-information phrases

Do not use LLMs.
Do not use semantic similarity yet.
Do not build a large framework.

### 3. Extract useful candidate topic phrases
Generate candidate topic strings that could plausibly match normalized Twitter trend names later.

Candidates should aim to preserve meaningful phrase units rather than only isolated single words where possible.

Reasonable examples may include:
- noun phrases
- cleaned hashtag phrases
- short multiword named entities if detectable
- filtered n-grams if supported by the observed data

### 4. Add candidate-level outputs
The output should be candidate-granular or otherwise make candidate inspection easy.

At minimum retain fields equivalent to:
- post identifier
- raw post text
- prepared post text
- extracted candidate phrase
- candidate normalized form if useful
- candidate source/type (for example: noun_chunk, hashtag, ngram, entity)
- optional rank/priority or confidence-like heuristic score
- optional metadata/flags used for filtering

Use stable and explicit column names.

### 5. Filtering and cleanup
Implement deterministic filters to reduce junk candidates, such as where justified:
- null / blank removal
- very short phrase filtering
- stopword-only candidate removal
- punctuation-only candidate removal
- low-information artifact removal
- duplicate candidate collapse within a post
- repeated whitespace cleanup
- optional normalization aligned with earlier text normalization strategy

Do not over-filter to the point that useful social-media phrases disappear.

### 6. Candidate profiling
Measure and document at minimum:
- total posts processed
- posts with at least one candidate
- total candidate rows
- average candidates per post
- distribution by candidate source/type
- common junk candidate patterns
- representative useful candidate examples
- representative false-positive / noisy examples

### 7. Notebook requirements
The notebook should:
- inspect the prepared Bluesky schema actually used
- explain the extraction strategy chosen
- show representative candidate examples
- summarize candidate counts and quality observations
- show how many posts produce no candidates
- identify what needs refinement before the matching phase

Keep it readable and concise.

### 8. Findings markdown
Write:
- `docs/24_local_topic_extraction_candidate_generation_findings.md`

It should summarize:
- which prepared Bluesky fields were used
- exact extraction methods implemented
- exact filtering rules implemented
- candidate volume and quality observations
- major noise patterns
- known limitations
- whether the project is ready for Phase 25 post-to-trend matching

## Suggested module structure
`src/nlp/topic_candidate_generation.py` should expose small readable functions.

Suggested structure:
- single-text candidate extraction function
- helper(s) for phrase cleanup / filtering
- dataframe-level application helper
- optional normalization helper for candidate phrases
- optional candidate typing / ranking helper

Keep it simple.
Do not build a framework.

## Testing requirements
Create tests for:
- null input
- blank input
- duplicate candidate collapse within a post
- short / junk phrase filtering
- preservation of useful multiword phrases
- hashtag-derived phrase handling if implemented
- deterministic behavior across repeated runs
- several real edge cases discovered from the prepared Bluesky text

Tests should validate deterministic outputs.

## Non-goals
This phase should NOT:
- touch Snowflake
- rerun any Bluesky collection/enrichment job
- perform final post-to-trend matching
- add fuzzy lexical matching yet
- add semantic similarity yet
- train a model

## Definition of done
This phase is done when:
1. reusable candidate extraction logic exists in `src/nlp/topic_candidate_generation.py`
2. candidate parquet/sample outputs are written
3. tests cover the main extraction and filtering behaviors
4. notebook and markdown findings document exactly what was done
5. the project is ready to move into local post-to-trend matching