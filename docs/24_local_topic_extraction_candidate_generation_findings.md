# 24 Local Topic Extraction / Candidate Generation Findings

Date: 2026-04-04

## Scope
- Phase spec: `docs/24_local_topic_extraction_candidate_generation.md`
- Grounding inputs:
  - `docs/23_local_bluesky_text_preparation.md`
  - `docs/23_local_bluesky_text_preparation_findings.md`
  - `docs/22_local_twitter_trend_normalization_findings.md`
- Mode: local-only (`0` Snowflake queries, `0` collection/enrichment reruns)

## Inputs and Fields Used
Primary prepared input:
- `local/derived/bluesky/bluesky_posts_prepared.parquet`

Reference context input (not used for final matching):
- `local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet`

Prepared Bluesky fields used by extraction:
- post identifier: `uri`
- timestamp: `post_created_at`
- raw text: `post_text_raw`
- prepared text: `post_text_clean`
- alnum helper text: `post_text_alnum`

## Extraction Methods Implemented (Deterministic)
Implemented in `src/nlp/topic_candidate_generation.py`:

1. Candidate phrase normalization (`normalize_candidate_phrase`)
   - Unicode NFKC
   - curly apostrophe normalization
   - whitespace normalization
   - lowercase normalization
   - separator punctuation to spaces
   - alphanumeric helper generation

2. Hashtag extraction
   - regex on `post_text_clean`: `#...`
   - emits hash-aware candidate with no-hash helper key
   - source type: `hashtag`

3. Contiguous n-gram extraction from `post_text_alnum`
   - generates 4-gram, 3-gram, and 2-gram candidates
   - source types: `ngram_4`, `ngram_3`, `ngram_2`

4. Conservative unigram fallback
   - only when no multiword/hashtag candidate survives filtering for a post
   - source type: `unigram_fallback`

5. Intra-post dedupe and ranking
   - dedupe key: `(uri, candidate_phrase_alnum)`
   - source priority: `hashtag` > `ngram_4` > `ngram_3` > `ngram_2` > `unigram_fallback`
   - tie-break: earliest start index, then stable lexical order
   - deterministic cap: max `20` candidates per post

## Filtering Rules Implemented (Deterministic)
Applied candidate-level filters:
1. drop blank/empty normalized candidates
2. enforce char length: `3 <= candidate_char_count <= 64`
3. enforce token length: `1 <= candidate_token_count <= 4`
4. remove stopword-only candidates
5. remove n-grams starting or ending with stopwords (sentence-fragment control)
6. remove URL/domain artifact-heavy candidates (token blacklist):
   - `http`, `https`, `www`, `com`, `net`, `org`, `app`, `profile`, `shorts`, `bsky`
7. remove ID-like long mixed alphanumeric tokens (macro-like IDs), except hashtags
8. for unigram fallback, drop low-information unigram blocklist: `macro`

## Candidate Output Schema
Candidate output columns:
- `uri`
- `post_created_at`
- `post_text_raw`
- `post_text_clean`
- `post_text_alnum`
- `candidate_phrase_raw`
- `candidate_phrase_clean`
- `candidate_phrase_alnum`
- `candidate_phrase_no_hash`
- `candidate_source_type`
- `candidate_token_count`
- `candidate_char_count`
- `candidate_rank_in_post`
- `is_hashtag_candidate`
- `contains_digit`
- `is_unigram_fallback`
- `candidate_start_index`

## Volume and Quality Observations
From `local/derived/bluesky/bluesky_topic_candidate_summary.json`:
- total posts processed: `25`
- posts with >=1 candidate: `19`
- posts with no candidates: `6`
- total candidate rows: `237`
- average candidates per post (all posts): `9.48`
- average candidates per post (posts with candidates): `12.47`

Candidate source distribution:
- `ngram_4`: `99`
- `ngram_3`: `75`
- `ngram_2`: `59`
- `unigram_fallback`: `3`
- `hashtag`: `1`

Token-count distribution:
- 4-token: `99`
- 3-token: `75`
- 2-token: `59`
- 1-token: `4`

Representative useful candidates:
- `small businesses`
- `small businesses in east`
- `broad conversation about how`
- `effect of policies intended`
- `quantify the economic impact`

Representative noisy/edge patterns that remain:
- residual short-form URL-context phrase: `shorts mmokh great story`

Posts with no candidates were mostly expected low-signal rows:
- blank text rows
- emoji-only rows
- macro+ID artifact rows filtered by design

## Outputs Written
- `local/derived/bluesky/bluesky_topic_candidates.parquet`
- `data/samples/bluesky_topic_candidates_sample_1000.parquet`
- `data/samples/bluesky_topic_candidates_sample_1000.csv`
- `local/derived/bluesky/bluesky_topic_candidate_summary.json` (optional summary)

## Limitations
- This is candidate extraction only; no post-to-trend matching is performed in this phase.
- Candidate generation is intentionally lexical/rule-based and may still include some sentence-fragment n-grams.
- Dataset is still limited to the current local prepared Bluesky slice (`25` posts), so candidate diversity is constrained.

## Readiness for Phase 25
Ready for Phase 25 post-to-trend matching: **YES**.

Reason:
- deterministic candidate extraction is implemented and tested
- filtering and dedupe are explicit and reproducible
- required candidate outputs are written and profile summary is available
- remaining noise patterns are known and manageable for exact-first matching refinement
