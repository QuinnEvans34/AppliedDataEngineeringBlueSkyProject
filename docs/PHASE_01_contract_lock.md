# Phase 01 — Lock Canonical Data Contracts

## Goal
Define one canonical contract for every upstream dataset that feeds the enhanced layer so all downstream SQL can rely on stable field names, stable join keys, and deterministic dedupe rules.

This phase is complete only when the project has a single agreed contract for:
- raw posts
- hydrated posts
- actor profiles
- twitter trends
- trend matches

## Why this phase exists
The enhanced layer is currently failing because the task logic is built on inconsistent upstream assumptions:
- raw posts use `repo_did`, while task SQL expects `did`
- hydrated posts are read with the wrong JSON paths and naming style
- actor profiles exist in mixed camelCase and snake_case shapes
- twitter trends and trend matches do not share one canonical normalized trend key
- append-only landing tables require explicit dedupe policy before any join

If this contract is not locked first, every downstream change is unstable.

## Required decisions
Codex must define and document the canonical contract for each table below.

### 1. RAW.LANDING_RAW_POSTS
Canonical grain:
- one raw post capture row per post event

Canonical business key:
- `uri`

Canonical fields used downstream:
- `raw_payload:uri::STRING`
- `COALESCE(raw_payload:repo_did::STRING, raw_payload:did::STRING)` as canonical post author DID
- `raw_payload:record:text::STRING`
- `raw_payload:record:createdAt::STRING`

Dedupe rule:
- latest row per `uri` by `loaded_at DESC`

### 2. RAW.LANDING_HYDRATED_POSTS
Canonical grain:
- one hydration snapshot row per `uri` per hydration run

Canonical business key:
- `uri`

Canonical downstream aliases that SQL must use:
- `uri`
- `author_did`
- `reply_count`
- `repost_count`
- `like_count`
- `quote_count`
- `labels`
- `record_created_at`

Fallback rule:
- allow snake_case/camelCase fallback only if required by historical data, but define one canonical alias layer for SQL

Dedupe rule:
- latest row per `uri` by `loaded_at DESC`

### 3. RAW.LANDING_ACTOR_PROFILES
Canonical grain:
- one actor snapshot row per `did` per actor run

Canonical business key:
- `did`

Canonical downstream aliases:
- `did`
- `handle`
- `display_name`
- `followers_count`
- `follows_count`
- `posts_count`
- `created_at`
- `labels`

Fallback rule:
- current data may contain both camelCase and snake_case, but downstream SQL must see a normalized alias layer only

Dedupe rule:
- latest row per `did` by `loaded_at DESC`

### 4. RAW.LANDING_TWITTER_TRENDS
Canonical grain:
- one trend metadata row per `(trend_date, trend_key_no_hash)` after dedupe

Canonical business key:
- `(trend_date, trend_key_no_hash)`

Canonical downstream aliases:
- `trend_date`
- `trend_name`
- `trend_key_no_hash`
- `tweet_volume`
- `rank`

Dedupe rule:
- latest row per `(trend_date, trend_key_no_hash)` by `loaded_at DESC`

### 5. RAW.LANDING_TREND_MATCHES
Canonical grain:
- one best matched trend row per `post_uri` per run

Canonical business key for enhanced layer:
- `post_uri`

Canonical downstream aliases:
- `post_uri`
- `trend_name`
- `trend_key_no_hash`
- `trend_date`
- `match_method`
- `match_score`
- `matched_at`

Dedupe rule:
- latest row per `post_uri` by `loaded_at DESC, match_score DESC`

## Required outputs
Codex must produce:
1. a contract table for each upstream landing table
2. a field-by-field mapping from current actual fields to canonical aliases
3. the exact dedupe policy for each table
4. a list of places in SQL and Python that violate the canonical contract
5. a recommendation for whether canonical normalization should happen:
   - in Python before load
   - in SQL alias CTEs
   - or both

## Acceptance criteria
This phase is done only when:
- each landing table has one canonical grain
- each landing table has one canonical key
- each landing table has one canonical normalized alias set
- trend joins have one canonical normalized key shared by both trends and trend matches
- dedupe rules are explicitly defined for every append-only source
- all known contract violations are identified by file path

## Test conditions
Use these checks after contract definitions are written:

```sql
-- Raw posts author DID path coverage
SELECT
  COUNT(*) AS total_rows,
  COUNT_IF(raw_payload:repo_did IS NOT NULL) AS repo_did_rows,
  COUNT_IF(raw_payload:did IS NOT NULL) AS did_rows
FROM RAW.LANDING_RAW_POSTS;

-- Hydrated rows key and alias coverage
SELECT
  COUNT(*) AS total_rows,
  COUNT_IF(raw_payload:uri IS NOT NULL) AS uri_rows,
  COUNT_IF(raw_payload:author_did IS NOT NULL) AS author_did_rows,
  COUNT_IF(raw_payload:author:did IS NOT NULL) AS author_colon_did_rows
FROM RAW.LANDING_HYDRATED_POSTS;

-- Actor profile mixed-shape coverage
SELECT
  COUNT(*) AS total_rows,
  COUNT_IF(raw_payload:did IS NOT NULL) AS did_rows,
  COUNT_IF(raw_payload:followers_count IS NOT NULL) AS followers_count_rows,
  COUNT_IF(raw_payload:followersCount IS NOT NULL) AS followersCount_rows
FROM RAW.LANDING_ACTOR_PROFILES;

-- Trend key duplication and normalization target
SELECT
  raw_payload:trend_date::DATE AS trend_date,
  LOWER(TRIM(REPLACE(raw_payload:trend_name::STRING, '#', ''))) AS simple_trend_key,
  COUNT(*) AS c
FROM RAW.LANDING_TWITTER_TRENDS
GROUP BY 1,2
HAVING COUNT(*) > 1
ORDER BY c DESC;

-- Trend match multiplicity
SELECT
  raw_payload:post_uri::STRING AS post_uri,
  COUNT(*) AS c
FROM RAW.LANDING_TREND_MATCHES
GROUP BY 1
HAVING COUNT(*) > 1
ORDER BY c DESC;
```
