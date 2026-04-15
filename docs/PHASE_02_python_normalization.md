# Phase 02 — Fix Python Output Normalization

## Goal
Make upstream Python outputs deterministic and aligned with the canonical data contracts so Snowflake does not need to guess field names or re-normalize ambiguous trend keys.

## Why this phase exists
The audit found these Python-side problems:
- actor profiles are written in mixed shapes depending on source path
- twitter trends use a simpler normalization than trend matching
- trend matches do not persist a canonical shared trend key
- timestamp formatting may be inconsistent
- SQL is compensating for Python shape drift

That is the wrong direction. Python should emit stable, canonical payloads so SQL can stay narrow and deterministic.

## Required code changes

### Change 1 — Normalize actor profile output to one schema
Files likely involved:
- `scripts/demo/demo_load.py`
- `bluesky_pipeline/actor/normalizer.py`

Requirement:
- choose one canonical actor schema and apply it everywhere
- preferred canonical naming: snake_case

Canonical actor payload fields:
- `did`
- `handle`
- `display_name`
- `followers_count`
- `follows_count`
- `posts_count`
- `created_at`
- `labels`

Rule:
- stop emitting mixed camelCase and snake_case variants into the same landing table

### Change 2 — Unify trend normalization logic
Files likely involved:
- `scripts/demo/load_twitter_trends.py`
- `src/nlp/trend_normalization.py`
- `src/nlp/post_trend_matching.py`

Requirement:
- twitter trend loader and trend matcher must use the exact same normalization function or equivalent logic
- both must produce and persist `trend_key_no_hash`

Canonical fields that must be written into `RAW.LANDING_TWITTER_TRENDS`:
- `trend_name`
- `trend_key_no_hash`
- `trend_date`
- `tweet_volume`
- `rank`

Canonical fields that must be written into `RAW.LANDING_TREND_MATCHES`:
- `post_uri`
- `trend_name`
- `trend_key_no_hash`
- `trend_date`
- `match_method`
- `match_score`
- `matched_at`

### Change 3 — Clean timestamp formatting
Requirement:
- ensure `matched_at` is written in clean ISO-8601 UTC format
- avoid malformed variants like `+00:00Z`

### Change 4 — Keep best-match selection in Python
Requirement:
- Python should continue to output one best row per `post_uri` per matching run
- Snowflake should only resolve cross-run duplicates, not select the best trend within a run

## Required outputs
Codex must:
1. identify the exact functions that build actor payloads
2. identify the exact functions that normalize trend names
3. modify loaders/writers so both trend tables share the same canonical key
4. confirm the final output shape written into landing JSONL for:
   - actor profiles
   - twitter trends
   - trend matches

## Acceptance criteria
This phase is done only when:
- actor profiles are emitted in one canonical schema
- twitter trends and trend matches both include `trend_key_no_hash`
- trend matching still writes one best row per `post_uri` per run
- timestamp formatting is clean and deterministic
- no downstream SQL needs to guess between snake_case and camelCase for new loads

## Test conditions
After changes, validate with these checks:

```sql
-- Actor profiles: new canonical schema present
SELECT
  COUNT(*) AS total_rows,
  COUNT_IF(raw_payload:followers_count IS NOT NULL) AS followers_count_rows,
  COUNT_IF(raw_payload:followersCount IS NOT NULL) AS followersCount_rows,
  COUNT_IF(raw_payload:created_at IS NOT NULL) AS created_at_rows,
  COUNT_IF(raw_payload:createdAt IS NOT NULL) AS createdAt_rows
FROM RAW.LANDING_ACTOR_PROFILES;

-- Trends: canonical trend key present
SELECT
  COUNT(*) AS total_rows,
  COUNT_IF(raw_payload:trend_key_no_hash IS NOT NULL) AS trend_key_rows
FROM RAW.LANDING_TWITTER_TRENDS;

-- Trend matches: canonical trend key present
SELECT
  COUNT(*) AS total_rows,
  COUNT_IF(raw_payload:trend_key_no_hash IS NOT NULL) AS trend_key_rows,
  COUNT_IF(raw_payload:match_score IS NOT NULL) AS match_score_rows
FROM RAW.LANDING_TREND_MATCHES;

-- Trend matches should still be one row per post per run output, then append-only in landing
SELECT
  raw_payload:post_uri::STRING AS post_uri,
  COUNT(*) AS c
FROM RAW.LANDING_TREND_MATCHES
GROUP BY 1
HAVING COUNT(*) > 1
ORDER BY c DESC;
```
