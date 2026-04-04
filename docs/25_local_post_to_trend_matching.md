# 25 — Local Post-to-Trend Matching

## Objective
Match locally generated Bluesky topic candidates to normalized local Twitter trend names using a staged matching pipeline so downstream feature engineering can use structured trend-match signals.

This phase is local-only.

## Why this phase exists
Phase 24 produced candidate topic phrases from prepared Bluesky post text.
The next step is to compare those candidate phrases against normalized Twitter trend text and identify plausible matches.

This phase introduces the actual matching layer.
It should produce structured match outputs, not yet final ML features.

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the Bluesky firehose
- Do NOT rerun hydration
- Do NOT rerun actor/profile enrichment
- Do NOT create new collection runs
- Do NOT modify raw source files in place
- Keep all work local and reproducible
- Preserve raw and normalized source values in outputs where useful
- Keep the matching pipeline readable, testable, and threshold-driven
- Do NOT train ML yet

## Required context to read first
Before implementing anything, read:

- `docs/24_local_topic_extraction_candidate_generation.md`
- `docs/24_local_topic_extraction_candidate_generation_findings.md`
- `docs/22_local_twitter_trend_normalization_findings.md`
- `docs/23_local_bluesky_text_preparation_findings.md`

Also inspect the actual schemas of the local candidate and normalized trend outputs.

## Inputs
Primary local inputs:

- `local/derived/bluesky/bluesky_topic_candidates.parquet`
- `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`

Related context if helpful:
- `local/derived/bluesky/bluesky_posts_prepared.parquet`

Do not assume column names blindly.
Use the actual schemas produced by the earlier phases.

## Deliverables
Create:

- `src/nlp/post_trend_matching.py`
- `notebooks/25_local_post_to_trend_matching.ipynb`
- `docs/25_local_post_to_trend_matching_findings.md`
- `tests/test_post_trend_matching.py`

Create local outputs:

- `local/derived/matching/bluesky_post_trend_matches.parquet`
- `local/derived/matching/bluesky_post_best_trend_matches.parquet`
- `data/samples/bluesky_post_trend_matches_sample_1000.parquet`
- `data/samples/bluesky_post_trend_matches_sample_1000.csv`

Optional if useful:
- `local/derived/matching/bluesky_post_trend_matching_summary.json`

## Required implementation behavior

### 1. Inspect and document actual schemas used
Inspect the actual local schemas and document:
- candidate phrase field used
- candidate normalized field used if available
- post identifier field used
- any candidate source/type field used
- any post timestamp/date field retained
- trend raw text field used
- trend normalized text field used
- trend date field used
- trend count/volume/duration fields available for retention

Do not hardcode assumptions without checking the real outputs.

### 2. Match in explicit staged order
Implement a staged matching pipeline in this order:

1. exact normalized match
2. fuzzy lexical match
3. semantic similarity fallback

The first acceptable match stage should win unless a later step is explicitly designed as a ranked comparison mode and clearly documented.

Keep the logic explicit and readable.

### 3. Exact normalized match
At minimum:
- compare normalized candidate phrases to normalized trend phrases
- allow exact string equality after prior normalization
- capture all exact matches if multiple trend rows qualify
- preserve enough metadata to inspect ambiguity

### 4. Fuzzy lexical match
Implement deterministic fuzzy lexical matching using a lightweight approach such as RapidFuzz.

Requirements:
- threshold-driven
- explicit scorer choice
- easy to inspect and tune
- applied only to candidates not already matched exactly
- preserve score and match method

Do not hide threshold values.
Document them clearly.

### 5. Semantic similarity fallback
Implement a semantic fallback only for unresolved candidates after exact and fuzzy matching.

Preferred direction:
- Sentence Transformers or similarly lightweight local embedding approach
- deterministic inference path for repeated runs given the same model/config

Requirements:
- keep this fallback gated and clearly documented
- preserve similarity score
- preserve model/config name used
- avoid unnecessary large-scale pairwise explosion if the trend dataset is large
- use a practical candidate narrowing strategy before semantic scoring if needed

If semantic fallback must be scoped conservatively for local performance, do so and document the tradeoff.

### 6. Temporal awareness where possible
If the Bluesky records retain a usable post date/timestamp and the trend dataset has a usable trend date:
- implement a date-aware narrowing strategy before matching, preferably same-day or a clearly documented small window
- make the window configurable and document the default

If reliable post date information is not available, document that and use the most conservative fallback available.

Do not invent temporal logic if the source data does not support it.

### 7. Match output schema
The match output should be candidate-granular or otherwise preserve enough detail to audit the match decisions.

At minimum retain fields equivalent to:
- post identifier
- raw post text if available
- prepared post text if available
- candidate phrase
- candidate normalized phrase if available
- candidate source/type
- matched trend raw text
- matched trend normalized text
- trend date if available
- trend count/volume if available
- match stage/method (`exact`, `fuzzy`, `semantic`)
- numeric match score
- optional rank among competing trend matches
- optional ambiguity flag if multiple plausible matches remain

Use stable and explicit column names.

### 8. Best-match output
In addition to the full candidate-level match output, create a post-level or best-match summary output.

This should provide a practical downstream table with one best retained match per post, or another clearly documented best-match strategy.

The best-match strategy must be explicit, reproducible, and documented.
Examples:
- highest-priority stage wins, then highest score
- exact over fuzzy over semantic
- tie-break by trend count or other documented field if appropriate

Do not leave best-match selection implicit.

### 9. Match profiling
Measure and document at minimum:
- total candidates processed
- exact match count
- fuzzy match count
- semantic fallback count
- unmatched candidate count
- post-level matched rate
- common exact matches
- representative fuzzy matches
- representative semantic matches
- representative false positives / questionable matches
- ambiguity rate if applicable

### 10. Notebook requirements
The notebook should:
- inspect actual input schemas
- explain the staged matching strategy
- show stage-by-stage match counts
- show representative examples from each stage
- show representative unmatched cases
- show ambiguous or questionable cases
- summarize threshold and configuration choices
- clearly state what should be refined before feature engineering if needed

Keep it readable and concise.

### 11. Findings markdown
Write:
- `docs/25_local_post_to_trend_matching_findings.md`

It should summarize:
- exact schemas/fields used
- exact matching stages implemented
- thresholds/configuration used
- temporal narrowing behavior if used
- match-rate outcomes
- major ambiguity/noise findings
- known limitations
- whether the project is ready for Phase 26 local feature engineering

## Suggested module structure
`src/nlp/post_trend_matching.py` should expose small readable functions.

Suggested structure:
- exact match helper
- fuzzy match helper
- semantic fallback helper
- optional temporal candidate narrowing helper
- best-match selection helper
- dataframe-level orchestration function

Keep it simple.
Do not build a framework.

## Performance guidance
- Avoid wasteful all-to-all semantic comparisons if the local trend dataset is large
- Narrow candidates before semantic scoring where possible
- Keep memory usage reasonable
- Prefer clear threshold-driven filtering over hidden heuristics

## Testing requirements
Create tests for:
- exact match success
- fuzzy match success above threshold
- fuzzy non-match below threshold
- semantic fallback invocation only when earlier stages fail
- stage priority ordering
- best-match selection behavior
- temporal narrowing behavior if implemented
- ambiguous-match handling where relevant
- deterministic outputs across repeated runs
- several real edge cases discovered in the local data

Tests should validate both correctness and stage ordering.

## Non-goals
This phase should NOT:
- touch Snowflake
- rerun any Bluesky collection/enrichment job
- build final ML features
- train a model
- build Tableau outputs yet

## Definition of done
This phase is done when:
1. reusable matching logic exists in `src/nlp/post_trend_matching.py`
2. candidate-level and best-match local outputs are written
3. tests cover the staged matching behavior and priorities
4. notebook and markdown findings document exactly how matching works
5. the project is ready to move into local feature engineering