# Phase 06 — Deterministic Reload and End-to-End Validation

## Goal
Run the full pipeline in deterministic order and prove that the project works end-to-end from demo load through enhanced and curated output.

## Why this phase exists
Even correct code can still fail if data is loaded in the wrong order or stale append-only landing data contaminates the result set.
This phase proves the repaired system actually works.

## Required execution order

### Step 1 — Reset or isolate test data
Requirement:
- either truncate relevant landing/enhanced/curated objects or isolate using a run scope policy
- remove ambiguity from old demo runs where possible

### Step 2 — Reload in deterministic order
Required order:
1. twitter trends
2. raw posts + actor profiles
3. hydrated posts if part of the demo path
4. trend matches
5. resume / execute enhanced task
6. resume / execute curated task

### Step 3 — Run the full validation checklist
Validate:
- object existence
- landing counts
- canonical key duplication levels
- trend key consistency
- enhanced uniqueness
- curated output health
- task histories

## Acceptance criteria
This phase is done only when:
- demo loaders complete successfully
- landing tables contain expected demo data
- enhanced task succeeds
- curated task succeeds
- `ENHANCED.POSTS_ENRICHED` has one row per `uri`
- `CURATED.ML_READY` rebuilds successfully
- trend matches flow through into enhanced/curated as expected

## Test conditions
Run all of these:

```sql
-- Object existence
SHOW TABLES IN SCHEMA RAW;
SHOW TABLES IN SCHEMA ENHANCED;
SHOW TABLES IN SCHEMA CURATED;
SHOW STREAMS IN SCHEMA RAW;
SHOW TASKS IN SCHEMA ENHANCED;

-- Landing row counts
SELECT 'RAW_POSTS', COUNT(*) FROM RAW.LANDING_RAW_POSTS
UNION ALL SELECT 'HYDRATED', COUNT(*) FROM RAW.LANDING_HYDRATED_POSTS
UNION ALL SELECT 'ACTOR', COUNT(*) FROM RAW.LANDING_ACTOR_PROFILES
UNION ALL SELECT 'TRENDS', COUNT(*) FROM RAW.LANDING_TWITTER_TRENDS
UNION ALL SELECT 'MATCHES', COUNT(*) FROM RAW.LANDING_TREND_MATCHES;

-- Enhanced uniqueness
SELECT COUNT(*) AS total_rows, COUNT(DISTINCT uri) AS distinct_uri
FROM ENHANCED.POSTS_ENRICHED;

SELECT uri, COUNT(*) AS c
FROM ENHANCED.POSTS_ENRICHED
GROUP BY 1
HAVING COUNT(*) > 1;

-- Trend coverage
SELECT
  COUNT(*) AS total_posts,
  COUNT_IF(has_trend_match) AS matched_posts,
  AVG(IFF(has_trend_match, 1, 0)) AS matched_rate
FROM ENHANCED.POSTS_ENRICHED;

SELECT COUNT(*) AS bad_trend_rows
FROM ENHANCED.POSTS_ENRICHED
WHERE has_trend_match = TRUE
  AND (matched_trend_name IS NULL OR matched_trend_date IS NULL);

-- Curated validation
SELECT COUNT(*) FROM CURATED.ML_READY;
SELECT dataset_split, COUNT(*) FROM CURATED.ML_READY GROUP BY 1;
SELECT engagement_label, COUNT(*) FROM CURATED.ML_READY GROUP BY 1;

-- Task histories
SELECT *
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
  TASK_NAME => 'ENHANCED.TASK_ENRICH_POSTS',
  SCHEDULED_TIME_RANGE_START => DATEADD('hour', -24, CURRENT_TIMESTAMP())
))
ORDER BY SCHEDULED_TIME DESC;

SELECT *
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
  TASK_NAME => 'ENHANCED.TASK_BUILD_ML_READY',
  SCHEDULED_TIME_RANGE_START => DATEADD('hour', -24, CURRENT_TIMESTAMP())
))
ORDER BY SCHEDULED_TIME DESC;
```

## Final proof conditions
The project is considered working as expected only when:
1. upstream demo scripts load data without schema drift
2. trend matching rows join cleanly to trend metadata
3. enhanced task compiles and runs
4. enhanced table is unique on `uri`
5. curated task compiles and runs
6. curated table rebuilds with expected row count and populated features
