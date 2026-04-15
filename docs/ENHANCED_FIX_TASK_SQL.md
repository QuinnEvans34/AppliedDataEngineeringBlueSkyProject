# ENHANCED_FIX_TASK_SQL.md
## Spec: Fix Task SQL Field Names + Validate Enhanced Layer End to End

---

### Overview
The ENHANCED.TASK_ENRICH_POSTS SQL has field name mismatches
between what the task reads from raw_payload and what the
loading scripts actually write. This spec defines every fix
needed and the exact validation sequence to confirm the full
enhanced layer is working end to end.

---

### Fix 1: Twitter Trends Field Name in trend_best CTE

The task currently reads:
```sql
t.raw_payload:date::DATE           AS matched_trend_date,
t.raw_payload:tweet_volume::NUMBER AS matched_tweet_volume,
t.raw_payload:rank::NUMBER         AS matched_trend_rank,
```

But ENHANCED_LOAD_TWITTER_TRENDS.md writes:
```json
{
    "trend_date": "2026-02-09",
    "tweet_volume": 1262842,
    "rank": null
}
```

The field name for date must change from `:date` to `:trend_date`.
The tweet_volume and rank fields match correctly.

Change in sql/05_tasks/00_tasks.sql inside trend_best CTE:
```sql
-- BEFORE
t.raw_payload:date::DATE           AS matched_trend_date,

-- AFTER
t.raw_payload:trend_date::DATE     AS matched_trend_date,
```

Also update the JOIN condition in trend_best CTE:
```sql
-- BEFORE
ON tm.raw_payload:trend_date::DATE   = t.raw_payload:date::DATE

-- AFTER
ON tm.raw_payload:trend_date::DATE   = t.raw_payload:trend_date::DATE
```

---

### Fix 2: Twitter Trends Name Join Field

The task joins trend matches to twitter trends on trend name:
```sql
AND tm.raw_payload:trend_name::STRING = t.raw_payload:trend_name::STRING
```

The trends JSONL writes trend_name as the normalized lowercase
name (no #). The trend matches JSONL writes trend_name as the
raw name (with #). These will not match.

Fix: Normalize both sides of the join:
```sql
AND LOWER(TRIM(REPLACE(tm.raw_payload:trend_name::STRING, '#', '')))
    = t.raw_payload:trend_name::STRING
```

This strips # and lowercases the trend match name before comparing
to the already-normalized trend_name in the trends table.

---

### Fix 3: Actor Profile Field Names in actor_latest CTE

The task reads actor profiles with camelCase:
```sql
raw_payload:followersCount::NUMBER AS followers_count,
raw_payload:followsCount::NUMBER   AS follows_count,
raw_payload:postsCount::NUMBER     AS posts_count,
raw_payload:createdAt::STRING      AS created_at_ts (via TRY_CAST),
raw_payload:did::STRING            AS did,
```

After applying ENHANCED_FIX_ACTOR_FIELDS.md, the demo script
writes camelCase. These field names now match correctly.

No change needed to the task SQL for actor fields — the fix
is in the demo script, not the task.

---

### Fix 4: Raw Posts Text Field Path

The task reads post text from:
```sql
r.raw_payload:record:text::STRING
```

The demo script writes posts with:
```json
{
    "uri": "at://...",
    "record": {
        "text": "post content here",
        "createdAt": "2026-04-11T...",
        ...
    }
}
```

This path r.raw_payload:record:text is correct. No change needed.

---

### Fix 5: Raw Posts Timestamp Field Path

The task reads:
```sql
TRY_CAST(r.raw_payload:record:createdAt::STRING AS TIMESTAMP_NTZ)
```

The demo script writes:
```json
{
    "record_created_at": "2026-04-11T...",
    "record": {
        "createdAt": "2026-04-11T..."
    }
}
```

The path r.raw_payload:record:createdAt is correct — it reads
from inside the nested record object which contains createdAt.
No change needed.

---

### Summary of Changes to sql/05_tasks/00_tasks.sql

| Location | Change |
|---|---|
| trend_best CTE join condition | :date → :trend_date |
| trend_best CTE SELECT | :date → :trend_date |
| trend_best CTE join condition | Add LOWER/TRIM/REPLACE normalization on trend_name |

All other field paths are correct after the actor field fix
in the demo script.

---

### Deployment Order
Run these steps in exact order after all data is loaded:

```
STEP 1: Verify all four RAW tables have data
STEP 2: Drop and recreate tasks with fixes
STEP 3: Resume tasks (child first, then parent)
STEP 4: Wait for tasks to fire (up to 1 minute)
STEP 5: Validate ENHANCED.POSTS_ENRICHED has rows
STEP 6: Validate CURATED.ML_READY has rows
```

---

### Step 1: Verify RAW Layer is Ready
Run in Snowflake before resuming tasks:

```sql
SELECT 'RAW_POSTS'      AS table_name, COUNT(*) AS rows FROM RAW.LANDING_RAW_POSTS
UNION ALL
SELECT 'ACTOR_PROFILES', COUNT(*) FROM RAW.LANDING_ACTOR_PROFILES
UNION ALL
SELECT 'TWITTER_TRENDS', COUNT(*) FROM RAW.LANDING_TWITTER_TRENDS
UNION ALL
SELECT 'TREND_MATCHES',  COUNT(*) FROM RAW.LANDING_TREND_MATCHES;
```

Expected minimum before proceeding:
- RAW_POSTS: 25
- ACTOR_PROFILES: 23
- TWITTER_TRENDS: ~101,731
- TREND_MATCHES: > 0 (however many posts matched)

Do NOT resume tasks if any of these is 0.

---

### Step 2: Verify Stream Has Data
```sql
SELECT SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_RAW_POSTS') AS has_data;
```

Expected: TRUE — the 25 posts from the demo run should be
unread in the stream. If FALSE the stream has already been
consumed and the task will not fire automatically. In that
case run the MERGE manually (see Step 6 below).

---

### Step 3: Resume Tasks
```sql
-- Child task first
ALTER TASK ENHANCED.TASK_BUILD_ML_READY RESUME;
-- Parent task second
ALTER TASK ENHANCED.TASK_ENRICH_POSTS RESUME;

-- Confirm both are running
SHOW TASKS IN SCHEMA ENHANCED;
-- Both should show state = started
```

---

### Step 4: Monitor Task Execution
Tasks run on a 1-minute schedule. Wait 90 seconds then check:

```sql
-- Check task run history
SELECT
    NAME,
    STATE,
    SCHEDULED_TIME,
    COMPLETED_TIME,
    ERROR_CODE,
    ERROR_MESSAGE
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
    SCHEDULED_TIME_RANGE_START => DATEADD('minute', -10, CURRENT_TIMESTAMP()),
    TASK_NAME => 'TASK_ENRICH_POSTS'
))
ORDER BY SCHEDULED_TIME DESC
LIMIT 5;
```

Expected: STATE = SUCCEEDED for the most recent run.
If STATE = FAILED, ERROR_MESSAGE will show exactly what failed.

---

### Step 5: Validate ENHANCED Layer
```sql
-- Row count
SELECT COUNT(*) AS enriched_rows FROM ENHANCED.POSTS_ENRICHED;
-- Expected: up to 25 (fewer if moderation filter removed some)

-- Sample enriched post
SELECT
    uri,
    post_text_clean,
    was_profanity_redacted,
    post_length,
    hashtag_count,
    follower_tier,
    is_bot_suspect,
    has_trend_match,
    matched_trend_name,
    engagement_total
FROM ENHANCED.POSTS_ENRICHED
LIMIT 5;

-- Check that actor features are populated (not NULL)
SELECT
    uri,
    followers_count,
    follower_tier,
    account_age_days
FROM ENHANCED.POSTS_ENRICHED
WHERE followers_count IS NULL;
-- Expected: 0 rows (all actor features should be populated)

-- Check trend match rate
SELECT
    has_trend_match,
    COUNT(*) AS posts
FROM ENHANCED.POSTS_ENRICHED
GROUP BY has_trend_match;
```

---

### Step 6: Validate CURATED Layer
```sql
-- Row count
SELECT COUNT(*) AS ml_ready_rows FROM CURATED.ML_READY;
-- Expected: same as ENHANCED.POSTS_ENRICHED

-- Label distribution
SELECT
    engagement_label,
    dataset_split,
    COUNT(*) AS rows
FROM CURATED.ML_READY
GROUP BY engagement_label, dataset_split
ORDER BY engagement_label, dataset_split;
-- Expected: 3 label values (LOW/MEDIUM/HIGH), TRAIN/TEST split

-- Confirm no NULLs in key feature columns
SELECT COUNT(*) AS null_feature_rows
FROM CURATED.ML_READY
WHERE post_length IS NULL
   OR hashtag_count IS NULL
   OR follower_tier IS NULL;
-- Expected: 0
```

---

### If Tasks Do Not Fire (Stream Already Consumed)
If SYSTEM$STREAM_HAS_DATA returns FALSE, run the MERGE manually:

```sql
-- Manually trigger the ENHANCED task body
-- Copy the full MERGE statement from sql/05_tasks/00_tasks.sql
-- and run it directly in a Snowflake worksheet
-- Then manually run the CURATED INSERT
TRUNCATE TABLE CURATED.ML_READY;
INSERT INTO CURATED.ML_READY
SELECT ... FROM ENHANCED.POSTS_ENRICHED;
```

---

### Suspend After Validation
```sql
ALTER TASK ENHANCED.TASK_BUILD_ML_READY SUSPEND;
ALTER TASK ENHANCED.TASK_ENRICH_POSTS SUSPEND;
ALTER WAREHOUSE COMPUTE_WH SUSPEND;
```

---

### Files to Modify
| File | Change |
|---|---|
| sql/05_tasks/00_tasks.sql | Fix 1: :date → :trend_date in trend_best CTE |
| sql/05_tasks/00_tasks.sql | Fix 2: Normalize trend_name join condition |