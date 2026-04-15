# Phase 05 — Validate and Stabilize the Curated Layer

## Goal
Ensure `CURATED.ML_READY` rebuilds correctly from the repaired enhanced layer and that the curated dataset is internally consistent for demo and downstream model work.

## Why this phase exists
`TASK_BUILD_ML_READY` is not the root compile failure, but curated output depends entirely on enhanced-layer correctness.
Once enhanced is repaired, curated must be validated for:
- row-count consistency
- null-rate sanity
- label generation
- dataset split generation
- rebuild behavior

## Required work

### Change 1 — Revalidate curated task references
Files likely involved:
- `sql/05_tasks/00_tasks.sql`
- any ops scripts that manage task execution

Requirement:
- ensure `ENHANCED.TASK_BUILD_ML_READY` references the repaired `ENHANCED.POSTS_ENRICHED`
- confirm task dependency chain remains correct

### Change 2 — Validate curated table schema against enhanced output
Files likely involved:
- `sql/04_curated/00_ml_ready_table.sql`
- `sql/05_tasks/00_tasks.sql`

Requirement:
- confirm curated columns match the repaired enhanced field names and semantics
- confirm curated build logic does not rely on broken pre-refactor aliases

### Change 3 — Validate full rebuild behavior
Requirement:
- `TRUNCATE + INSERT` rebuild must work cleanly after enhanced rows are present
- row count should match enhanced count unless intentional filtering exists

## Acceptance criteria
This phase is done only when:
- curated task runs successfully
- curated row count matches design expectation
- dataset splits are populated
- engagement labels are populated
- critical numeric features are non-null where expected

## Test conditions
Run these checks after enhanced is working:

```sql
-- Task execution
SELECT *
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
  TASK_NAME => 'ENHANCED.TASK_BUILD_ML_READY',
  SCHEDULED_TIME_RANGE_START => DATEADD('hour', -24, CURRENT_TIMESTAMP())
))
ORDER BY SCHEDULED_TIME DESC;

-- Row-count consistency
SELECT COUNT(*) AS enhanced_rows FROM ENHANCED.POSTS_ENRICHED;
SELECT COUNT(*) AS curated_rows FROM CURATED.ML_READY;

-- Split distribution
SELECT dataset_split, COUNT(*) AS c
FROM CURATED.ML_READY
GROUP BY 1
ORDER BY 1;

-- Label distribution
SELECT engagement_label, COUNT(*) AS c
FROM CURATED.ML_READY
GROUP BY 1
ORDER BY 1;

-- Basic null-rate checks
SELECT
  AVG(IFF(post_length IS NULL, 1, 0)) AS null_post_length_rate,
  AVG(IFF(followers_count IS NULL, 1, 0)) AS null_followers_count_rate,
  AVG(
    IFF(
      has_trend_match = TRUE
      AND matched_tweet_volume IS NULL
      AND matched_trend_rank IS NULL,
      1,
      0
    )
  ) AS bad_trend_feature_rate
FROM CURATED.ML_READY;
```
