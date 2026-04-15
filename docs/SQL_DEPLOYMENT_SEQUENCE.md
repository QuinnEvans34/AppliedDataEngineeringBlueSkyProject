# SQL_DEPLOYMENT_SEQUENCE.md
## Snowflake Deployment Sequence — Full Infrastructure

---

### Overview
This document defines the exact order to deploy all SQL objects
to Snowflake. Run files in this order exactly. Do not skip steps.
Do not run COPY INTO statements until explicitly told to in Step 3.

All deployments run on COMPUTE_WH (X-SMALL).
Suspend the warehouse after each session.

---

### Pre-Deployment Checklist
Before running anything in Snowflake, confirm:

- [ ] All 8 SQL files exist at their correct paths
- [ ] `04_stg_enhanced_posts.sql` has the FLATTEN label fix applied
- [ ] `02_curated_posts_with_trends.sql` has the length guard applied
- [ ] You are connected to BLUESKYDATAENGINEERINGPROJECT database
- [ ] You are using the PUBLIC schema
- [ ] Warehouse is X-SMALL

Run this to confirm your context before anything else:
```sql
SELECT CURRENT_DATABASE(), CURRENT_SCHEMA(), CURRENT_WAREHOUSE();
```
Expected: BLUESKYDATAENGINEERINGPROJECT | PUBLIC | COMPUTE_WH

---

### Step 1: Deploy Infrastructure Objects
These create the stage and landing table for Twitter trends.
Run each file in order.

**1a. Twitter Trends Stage**
File: `sql/01_landing/05_twitter_trends_stage.sql`
```sql
-- Run the full file contents
-- Expected output: Stage BLUESKY_TWITTER_TRENDS_STAGE created
```

**1b. Twitter Trends Landing Table**
File: `sql/01_landing/04_landing_twitter_trends.sql`
```sql
-- Run the full file contents
-- Expected output: Table LANDING_TWITTER_TRENDS created
-- The COPY INTO in this file must be commented out — do not run it
```

Validate:
```sql
SHOW TABLES LIKE 'LANDING_TWITTER_TRENDS';
SHOW STAGES LIKE 'BLUESKY_TWITTER_TRENDS_STAGE';
```

---

### Step 2: Deploy Enhanced Layer Views
These build on existing STG_ views. Run in order.

**2a. Enhanced Posts**
File: `sql/02_staging/04_stg_enhanced_posts.sql`
```sql
-- Run the full file contents
-- Expected output: View STG_ENHANCED_POSTS created
```

Validate immediately:
```sql
SELECT
    uri,
    post_text,
    post_length,
    hashtag_count,
    is_adult_content,
    has_any_label
FROM STG_ENHANCED_POSTS
WHERE post_text IS NOT NULL
LIMIT 20;
```
Expected: post_text should contain readable post content,
not NULL and not raw JSON strings.

**2b. Enhanced Actors**
File: `sql/02_staging/05_stg_enhanced_actors.sql`
```sql
-- Run the full file contents
-- Expected output: View STG_ENHANCED_ACTORS created
```

Validate immediately:
```sql
SELECT
    did,
    handle,
    follower_tier,
    is_bot_suspect,
    account_age_days,
    follow_follower_ratio
FROM STG_ENHANCED_ACTORS
LIMIT 20;
```
Expected: follower_tier values should be HIGH/MID/LOW/MICRO only.

**2c. Twitter Trends Staging**
File: `sql/02_staging/06_stg_twitter_trends.sql`
```sql
-- Run the full file contents
-- Expected output: View STG_TWITTER_TRENDS created
```

Validate immediately:
```sql
SELECT COUNT(*) FROM STG_TWITTER_TRENDS;
```
Expected: 0 rows — no data loaded yet, but view should create
without error.

---

### Step 3: Deploy Curated Layer Views
These build on CURATED_POSTS_CORE and the enhanced views above.
Run in order — each depends on the previous.

**3a. Curated Posts Labeled**
File: `sql/03_curated/01_curated_posts_labeled.sql`
```sql
-- Run the full file contents
-- Expected output: View CURATED_POSTS_LABELED created
```

Validate immediately:
```sql
SELECT
    engagement_label,
    COUNT(*) AS post_count,
    AVG(engagement_total) AS avg_engagement
FROM CURATED_POSTS_LABELED
GROUP BY engagement_label
ORDER BY engagement_label;
```
Expected: Three rows (HIGH, LOW, MEDIUM) with roughly equal counts.
If all rows are LOW or counts are wildly unequal, the hydration
data is still sparse — this is expected until the 1M run lands.

**3b. Curated Posts With Trends**
File: `sql/03_curated/02_curated_posts_with_trends.sql`
```sql
-- Run the full file contents
-- Expected output: View CURATED_POSTS_WITH_TRENDS created
```

Validate immediately:
```sql
SELECT
    has_trend_match,
    COUNT(*) AS posts,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
FROM CURATED_POSTS_WITH_TRENDS
GROUP BY has_trend_match;
```
Expected: has_trend_match is FALSE for all rows — no trend data
loaded yet. View should return rows without error.

**3c. Curated ML Ready**
File: `sql/03_curated/03_curated_ml_ready.sql`
```sql
-- Run the full file contents
-- Expected output: View CURATED_ML_READY created
```

Validate immediately:
```sql
SELECT
    split_bucket,
    engagement_label,
    COUNT(*) AS rows
FROM CURATED_ML_READY
GROUP BY split_bucket, engagement_label
ORDER BY split_bucket, engagement_label;
```
Expected: TRAIN ~80% of rows, TEST ~20%. Labels distributed
across both buckets.

---

### Step 4: Final End-to-End Validation
Run this after all views are deployed to confirm the full
chain is wired correctly:

```sql
-- Confirm all objects exist
SHOW VIEWS LIKE 'STG_ENHANCED%';
SHOW VIEWS LIKE 'STG_TWITTER%';
SHOW VIEWS LIKE 'CURATED_%';
SHOW TABLES LIKE 'LANDING_TWITTER%';
SHOW STAGES LIKE 'BLUESKY_TWITTER%';
```

Expected: All 6 views, 1 table, 1 stage visible.

```sql
-- Confirm row counts flow end to end
SELECT
    'STG_ENHANCED_POSTS'     AS view_name, COUNT(*) AS rows FROM STG_ENHANCED_POSTS     UNION ALL
    SELECT 'STG_ENHANCED_ACTORS',                COUNT(*) FROM STG_ENHANCED_ACTORS     UNION ALL
    SELECT 'CURATED_POSTS_LABELED',              COUNT(*) FROM CURATED_POSTS_LABELED   UNION ALL
    SELECT 'CURATED_POSTS_WITH_TRENDS',          COUNT(*) FROM CURATED_POSTS_WITH_TRENDS UNION ALL
    SELECT 'CURATED_ML_READY',                   COUNT(*) FROM CURATED_ML_READY
ORDER BY view_name;
```

Expected: All views return the same row count (they are all
filtering the same underlying posts). STG_ENHANCED_POSTS may
be higher due to no dedup — that is expected.

---

### Step 5: Suspend Warehouse
Always run this when done with a session:
```sql
ALTER WAREHOUSE COMPUTE_WH SUSPEND;
```

---

### After the 1M Run — Data Loading Sequence
When the 1M capture + hydration run is complete, load data
in this order:

```
1. Load raw posts         → LANDING_RAW_POSTS
2. Load hydrated posts    → LANDING_HYDRATED_POSTS
3. Load hydration misses  → LANDING_HYDRATION_MISSES
4. Load actor profiles    → LANDING_ACTOR_PROFILES
5. Load Twitter trends    → LANDING_TWITTER_TRENDS
```

Load Twitter trends last — it is referenced in the final
curated views and its absence does not block the others.

After loading, re-run the validation queries in Steps 2-4 to
confirm data is flowing through all layers correctly before
training the model.