# 25 Local Post-to-Trend Matching Findings

Date: 2026-04-04

## Scope
- Phase spec: `docs/25_local_post_to_trend_matching.md`
- Grounding inputs:
  - `docs/24_local_topic_extraction_candidate_generation.md`
  - `docs/24_local_topic_extraction_candidate_generation_findings.md`
  - `docs/22_local_twitter_trend_normalization_findings.md`
  - `docs/23_local_bluesky_text_preparation_findings.md`
- Mode: local-only (`0` Snowflake queries, `0` collection/enrichment reruns)

## Inputs and Schemas Used
Input files:
- `local/derived/bluesky/bluesky_topic_candidates.parquet`
- `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`

Candidate fields used for matching:
- `uri`
- `post_created_at`
- `candidate_phrase_clean`
- `candidate_phrase_alnum`
- `candidate_source_type`
- retained context fields in output: `post_text_raw`, `post_text_clean`, `candidate_phrase_raw`, `candidate_rank_in_post`

Trend fields used for matching:
- `name` (retained as `trend_name_raw`)
- `trend_name_clean`
- `normalized_key_no_hash` (retained as `trend_key_no_hash`)
- `normalized_date` (retained as `trend_date`)
- `counts` (retained as `trend_counts`)
- `num_hours` (retained as `trend_num_hours`)

## Matching Stages and Configuration
Implemented in `src/nlp/post_trend_matching.py` with staged progression for unresolved candidates only:

1. Exact normalized match
- candidate key: `candidate_phrase_alnum`
- trend key: `normalized_key_no_hash`
- equality condition after deterministic key normalization
- method metadata: `match_stage='exact'`, `match_method='normalized_equality'`, `match_score=1.0`

2. Fuzzy lexical match
- scorer: `difflib.SequenceMatcher(...).ratio()`
- threshold: `fuzzy_min_score = 0.88`
- method metadata: `match_stage='fuzzy'`, `match_method='difflib_sequence_ratio'`

3. Semantic fallback
- deterministic semantic-proxy score (no external model):
  - token cosine similarity on term-frequency vectors
  - char-trigram Jaccard similarity
  - combined score: `0.7 * token_cosine + 0.3 * trigram_jaccard`
- threshold: `semantic_min_score = 0.60`
- method metadata: `match_stage='semantic'`, `match_method='token_cosine_char_trigram'`

Config used:
- `date_window_days = 3`
- `fuzzy_min_score = 0.88`
- `semantic_min_score = 0.60`
- `max_stage_pool = 5000`
- `semantic_pool_top_k = 250`

## Temporal Narrowing Behavior
Temporal narrowing is implemented as:
1. try candidate date against trend date within `±3` days
2. if no trend rows remain, fall back to global trend pool

Observed in this local run:
- candidate dates: `2026-04-01` (single day)
- trend dates coverage ends at `2026-01-24`
- direct date overlap: none
- all candidate rows used fallback mode: `global_fallback_no_date_overlap`

## Outputs Written
- full candidate-level matches:
  - `local/derived/matching/bluesky_post_trend_matches.parquet`
- best per-post matches:
  - `local/derived/matching/bluesky_post_best_trend_matches.parquet`
- samples:
  - `data/samples/bluesky_post_trend_matches_sample_1000.parquet`
  - `data/samples/bluesky_post_trend_matches_sample_1000.csv`
- optional summary:
  - `local/derived/matching/bluesky_post_trend_matching_summary.json`

Best-match selection strategy (`bluesky_post_best_trend_matches.parquet`):
1. stage priority: `exact` > `fuzzy` > `semantic` > `unmatched`
2. higher `match_score`
3. higher `trend_counts`
4. lexical tie-break on `trend_name_clean`

## Stage-by-Stage Outcomes
From `bluesky_post_trend_matching_summary.json`:

Input volume:
- candidate rows: `237`
- unique candidate IDs: `237`
- unique posts: `19`

Full output:
- full match rows: `243`
- best rows (one per post): `19`

Candidate-level best stage counts:
- exact: `0`
- fuzzy: `2`
- semantic: `7`
- unmatched: `228`

Row-level stage counts (full output):
- exact: `0`
- fuzzy: `5`
- semantic: `10`
- unmatched: `228`

Post-level best stage counts:
- exact: `0`
- fuzzy: `2`
- semantic: `4`
- unmatched: `13`

Post matched rate:
- `0.3158` (6 of 19 posts have a matched best row)

Ambiguity:
- ambiguous candidate count: `4`
- ambiguous candidate rate: `0.0169`

## Example Observations
Representative fuzzy matches:
- `bbb26` -> `#bb26` (score `0.8889`, multiple trend-day rows)
- `ate everything` -> `date everything` (score `0.9655`)

Representative semantic matches:
- `day of visibility` -> `transgender day of visibility` (score `0.7729`)
- `broader conversation` -> `conversation` (score `0.6616`)
- `fucking boring` -> `boring` (score `0.6041`)

Representative unmatched patterns:
- longer sentence-fragment candidates with no close normalized trend key
- date-window mismatch forcing global fallback and weaker lexical precision

Major ambiguity/noise patterns:
- duplicate trend-name matches across multiple trend dates/rows (e.g., repeated `#bb26` rows)
- semantic over-broadness on short phrases (`don t` matching multiple trend variants)

## Limitations
- No exact matches in this local slice, likely due candidate phrasing and date mismatch against available trend window.
- Semantic fallback uses deterministic local proxy scoring, not transformer embeddings.
- Current match quality depends heavily on candidate phrase quality from Phase 24.
- Temporal narrowing currently always falls back globally for this dataset due no date overlap.

## Readiness for Phase 26
Ready for Phase 26 local feature engineering: **YES, with caveats**.

Reason:
- staged, deterministic matching pipeline is implemented and auditable
- full + best outputs are generated with explicit stage metadata and scores
- ambiguity and unmatched behavior are surfaced for feature engineering decisions

Caveat:
- low match yield (`228/237` unmatched candidates) means Phase 26 should include robust unmatched/low-confidence handling and likely threshold/strategy refinement loops.
