# Phase 04 — Refactor the Enhanced Layer Task

## Goal
Replace the current brittle enhanced-layer task with a deterministic, deduped, flattened merge pipeline that produces exactly one row per `uri` in `ENHANCED.POSTS_ENRICHED`.

## Why this phase exists
The current enhanced task is the main failure point.
Known issues:
- the raw-post stream is read twice
- hydrated posts are joined without latest-row dedupe
- actor profiles are joined with mixed field naming assumptions
- trend matches and twitter trends are joined without one canonical key
- labels are aggregated across hydration history instead of latest hydrated row
- merge-source uniqueness is not guaranteed
- current SQL shape is overly dense and difficult to validate

## Required refactor shape

### CTE 1 — `raw_new_posts`
Grain:
- one row per `uri`

Requirements:
- this must be the only CTE that reads `RAW.STRM_LANDING_RAW_POSTS`
- filter to insert rows only
- dedupe latest row per `uri`
- expose canonical aliases:
  - `uri`
  - `repo_did`
  - `post_text`
  - `post_created_at_raw`

### CTE 2 — `post_text_cleaned`
Grain:
- one row per `uri`

Requirements:
- built from `raw_new_posts`, not from the stream
- apply `ENHANCED.CLEAN_PROFANITY`
- expose cleaned text fields needed downstream

### CTE 3 — `hydrated_latest`
Grain:
- one row per `uri`

Requirements:
- read from `RAW.LANDING_HYDRATED_POSTS`
- normalize snake_case/camelCase field variants into canonical aliases
- dedupe latest row per `uri`

Required aliases:
- `uri`
- `author_did`
- `reply_count`
- `repost_count`
- `like_count`
- `quote_count`
- `labels`
- `record_created_at`

### CTE 4 — `hydrated_labels_latest`
Grain:
- one row per `uri`

Requirements:
- derive only from `hydrated_latest`
- flatten labels from latest row only
- compute `is_adult_content` only from latest labels

### CTE 5 — `actor_latest_normalized`
Grain:
- one row per `did`

Requirements:
- read from `RAW.LANDING_ACTOR_PROFILES`
- normalize camelCase and snake_case into canonical aliases
- dedupe latest row per `did`

### CTE 6 — `trend_matches_latest`
Grain:
- one row per `post_uri`

Requirements:
- dedupe `RAW.LANDING_TREND_MATCHES` across runs
- deterministic ordering:
  - `loaded_at DESC`
  - `match_score DESC`
- expose:
  - `post_uri`
  - `trend_name`
  - `trend_key_no_hash`
  - `trend_date`
  - `match_method`
  - `match_score`

### CTE 7 — `twitter_trends_canonical`
Grain:
- one row per `(trend_date, trend_key_no_hash)`

Requirements:
- read from `RAW.LANDING_TWITTER_TRENDS`
- use the same canonical key as trend matches
- dedupe latest row per `(trend_date, trend_key_no_hash)`

### CTE 8 — `trend_enriched`
Grain:
- one row per `post_uri`

Requirements:
- join `trend_matches_latest` to `twitter_trends_canonical`
- preserve 0/1 trend metadata row per post

### CTE 9 — `merge_source`
Grain:
- exactly one row per `uri`

Requirements:
- join:
  - `raw_new_posts`
  - `post_text_cleaned`
  - `hydrated_latest`
  - `hydrated_labels_latest`
  - `actor_latest_normalized`
  - `trend_enriched`
- final source must be unique on `uri`
- add an explicit duplicate check query during development

### Final MERGE
Requirements:
- merge from `merge_source` into `ENHANCED.POSTS_ENRICHED`
- one target row per `uri`
- preserve the intended business logic as closely as possible

## Additional requirements
- do not read the raw stream more than once
- do not aggregate labels across hydration history
- do not select best trend match in SQL within a run
- do not rely on raw `RAW.LANDING_HYDRATED_POSTS` or `RAW.LANDING_ACTOR_PROFILES` directly in final join without prior dedupe CTEs

## Acceptance criteria
This phase is done only when:
- `ENHANCED.TASK_ENRICH_POSTS` compiles successfully
- task run succeeds
- merge source has one row per `uri`
- `ENHANCED.POSTS_ENRICHED` has one row per `uri`
- trend enrichment is stable
- adult-content flag is based on latest hydrated labels only

## Test conditions
Use these checks after refactor:

```sql
-- Merge source uniqueness test
WITH merge_source AS (
  /* paste refactored merge_source query here */
  SELECT 1
)
SELECT COUNT(*) AS total_rows, COUNT(DISTINCT uri) AS distinct_uri
FROM merge_source;

WITH merge_source AS (
  /* paste refactored merge_source query here */
  SELECT 1
)
SELECT uri, COUNT(*) AS c
FROM merge_source
GROUP BY 1
HAVING COUNT(*) > 1;

-- Enhanced output uniqueness
SELECT COUNT(*) AS total_rows, COUNT(DISTINCT uri) AS distinct_uri
FROM ENHANCED.POSTS_ENRICHED;

SELECT uri, COUNT(*) AS c
FROM ENHANCED.POSTS_ENRICHED
GROUP BY 1
HAVING COUNT(*) > 1;

-- Enrichment coverage
SELECT
  COUNT(*) AS total_posts,
  COUNT_IF(repo_did IS NOT NULL) AS with_repo_did,
  COUNT_IF(post_text_clean IS NOT NULL AND post_text_clean <> '') AS with_clean_text,
  COUNT_IF(has_trend_match) AS with_trend_match
FROM ENHANCED.POSTS_ENRICHED;

-- Latest-label policy validation
SELECT
  COUNT(*) AS total_posts,
  COUNT_IF(is_adult_content) AS adult_posts
FROM ENHANCED.POSTS_ENRICHED;

-- Task execution
SELECT *
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
  TASK_NAME => 'ENHANCED.TASK_ENRICH_POSTS',
  SCHEDULED_TIME_RANGE_START => DATEADD('hour', -24, CURRENT_TIMESTAMP())
))
ORDER BY SCHEDULED_TIME DESC;
```
