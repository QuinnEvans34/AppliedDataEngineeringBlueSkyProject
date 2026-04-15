# ENHANCED_CURATED_TASKS.md
## Spec: ENHANCED.POSTS_ENRICHED + CURATED.ML_READY + Task Chain

---

### Overview
Two materialized tables and two Snowflake tasks that populate them.
Tasks are stream-triggered and chain automatically.
Both tasks are created SUSPENDED — resumed manually at load time.

```
RAW.STRM_LANDING_RAW_POSTS (stream detects new rows)
        ↓
TASK: ENHANCED.TASK_ENRICH_POSTS
        ↓ writes to
ENHANCED.POSTS_ENRICHED (materialized table)
        ↓ triggers
TASK: CURATED.TASK_BUILD_ML_READY
        ↓ writes to
CURATED.ML_READY (materialized table)
        ↓ suspends itself
```

---

### Table 1: ENHANCED.POSTS_ENRICHED

#### Purpose
One materialized row per post. Contains every cleaned,
enriched, and joined column needed for analysis and ML.
This is the single source of truth for processed data.

#### Grain
One row per post URI. Deduplication via ROW_NUMBER()
PARTITION BY uri ORDER BY loaded_at DESC = 1.

#### Creation Pattern
```sql
CREATE TABLE IF NOT EXISTS ENHANCED.POSTS_ENRICHED (
    -- Identity
    uri                     STRING NOT NULL,
    repo_did                STRING,
    author_did              STRING,

    -- Clean text
    post_text_clean         STRING,
    was_profanity_redacted  BOOLEAN,

    -- Engagement metrics (NULL if not hydrated yet)
    reply_count             NUMBER,
    repost_count            NUMBER,
    like_count              NUMBER,
    quote_count             NUMBER,
    engagement_total        NUMBER,

    -- Text features
    post_length             NUMBER,
    post_word_count         NUMBER,
    hashtag_count           NUMBER,
    mention_count           NUMBER,
    url_count               NUMBER,
    exclamation_count       NUMBER,
    question_count          NUMBER,

    -- Temporal features
    post_created_at_ts      TIMESTAMP_NTZ,
    post_hour_utc           NUMBER,
    post_day_of_week        NUMBER,

    -- Moderation flags
    is_adult_content        BOOLEAN,
    has_moderation_flag     BOOLEAN,
    moderation_label_count  NUMBER,

    -- Actor features
    followers_count         NUMBER,
    follows_count           NUMBER,
    posts_count             NUMBER,
    follower_tier           STRING,
    account_age_days        NUMBER,
    follow_follower_ratio   FLOAT,
    posts_per_day           FLOAT,

    -- Bot detection
    is_bot_suspect          BOOLEAN,
    is_spam_suspect         BOOLEAN,

    -- Trend match (NULL if no match found)
    has_trend_match         BOOLEAN,
    matched_trend_name      STRING,
    matched_trend_date      DATE,
    matched_tweet_volume    NUMBER,
    matched_trend_rank      NUMBER,
    trend_match_method      STRING,  -- 'exact', 'fuzzy', 'semantic', 'sql'
    trend_match_score       FLOAT,

    -- Metadata
    enriched_at             TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);
```

#### How the Task Populates It
The task uses INSERT OVERWRITE or MERGE to avoid duplicates.
Use MERGE on uri as the key:

```sql
MERGE INTO ENHANCED.POSTS_ENRICHED AS target
USING (
    -- Full join query here
    SELECT ...
    FROM RAW.LANDING_RAW_POSTS r
    LEFT JOIN RAW.LANDING_HYDRATED_POSTS h
        ON r.raw_payload:uri::STRING = h.raw_payload:uri::STRING
    LEFT JOIN RAW.LANDING_ACTOR_PROFILES a
        ON COALESCE(
            h.raw_payload:author:did::STRING,
            r.raw_payload:did::STRING
        ) = a.raw_payload:did::STRING
    LEFT JOIN RAW.LANDING_TREND_MATCHES tm
        ON r.raw_payload:uri::STRING = tm.raw_payload:post_uri::STRING
    LEFT JOIN RAW.LANDING_TWITTER_TRENDS t
        ON tm.raw_payload:trend_date::DATE = t.raw_payload:date::DATE
        AND tm.raw_payload:trend_name::STRING = t.raw_payload:trend_name::STRING
) AS source
ON target.uri = source.uri
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...;
```

#### Moderation Filter
Exclude from ENHANCED.POSTS_ENRICHED:
- is_adult_content = TRUE
- is_bot_suspect = TRUE
- post_text_clean IS NULL OR post_text_clean = ''

These posts are filtered at write time — they never enter
the ENHANCED table. RAW data is untouched and still has them.

#### Profanity Cleaning in the Task
Call RAW.CLEAN_PROFANITY() inside the task SELECT:

```sql
RAW.CLEAN_PROFANITY(
    r.raw_payload:record:text::STRING
):post_text_clean::STRING        AS post_text_clean,

RAW.CLEAN_PROFANITY(
    r.raw_payload:record:text::STRING
):was_profanity_redacted::BOOLEAN AS was_profanity_redacted,
```

Use LATERAL JOIN to call UDF once per row:
```sql
LEFT JOIN LATERAL (
    SELECT RAW.CLEAN_PROFANITY(
        r.raw_payload:record:text::STRING
    ) AS cp
) cp_result ON TRUE
```

Then reference:
```sql
cp_result.cp:post_text_clean::STRING     AS post_text_clean,
cp_result.cp:was_profanity_redacted::BOOLEAN AS was_profanity_redacted,
```

---

### Table 2: CURATED.ML_READY

#### Purpose
ML feature vector only. No raw text, no identifiers,
no metadata. Only what the model needs.

#### Creation Pattern
```sql
CREATE TABLE IF NOT EXISTS CURATED.ML_READY (
    -- Target variable
    engagement_label        STRING,   -- LOW / MEDIUM / HIGH
    engagement_total        NUMBER,   -- raw score

    -- Text features
    post_length             NUMBER,
    post_word_count         NUMBER,
    hashtag_count           NUMBER,
    mention_count           NUMBER,
    url_count               NUMBER,
    exclamation_count       NUMBER,
    question_count          NUMBER,

    -- Temporal features
    post_hour_utc           NUMBER,
    post_day_of_week        NUMBER,

    -- Actor features
    followers_count         NUMBER,
    follower_tier           STRING,
    account_age_days        NUMBER,
    follow_follower_ratio   FLOAT,
    posts_per_day           FLOAT,

    -- Trend features
    has_trend_match         BOOLEAN,
    matched_tweet_volume    NUMBER,
    matched_trend_rank      NUMBER,

    -- Split
    dataset_split           STRING    -- TRAIN / TEST
);
```

#### How the Task Populates It
Truncate and reload on every run — the ENHANCED table is
the source of truth, ML_READY is always derived from it:

```sql
TRUNCATE TABLE CURATED.ML_READY;

INSERT INTO CURATED.ML_READY
SELECT
    CASE NTILE(3) OVER (ORDER BY engagement_total ASC)
        WHEN 1 THEN 'LOW'
        WHEN 2 THEN 'MEDIUM'
        WHEN 3 THEN 'HIGH'
    END                                         AS engagement_label,
    engagement_total,
    post_length,
    post_word_count,
    hashtag_count,
    mention_count,
    url_count,
    exclamation_count,
    question_count,
    post_hour_utc,
    post_day_of_week,
    followers_count,
    follower_tier,
    account_age_days,
    follow_follower_ratio,
    posts_per_day,
    COALESCE(has_trend_match, FALSE)            AS has_trend_match,
    COALESCE(matched_tweet_volume, 0)           AS matched_tweet_volume,
    COALESCE(matched_trend_rank, 999)           AS matched_trend_rank,
    CASE
        WHEN ABS(MOD(HASH(uri), 100)) < 80 THEN 'TRAIN'
        ELSE 'TEST'
    END                                         AS dataset_split
FROM ENHANCED.POSTS_ENRICHED
WHERE engagement_total IS NOT NULL;
```

Note: uri is used for hashing the split but is NOT included
in the output table — it is not a feature.

---

### Task Chain

#### Task 1: ENHANCED.TASK_ENRICH_POSTS

```sql
CREATE OR REPLACE TASK ENHANCED.TASK_ENRICH_POSTS
    WAREHOUSE = COMPUTE_WH
    SCHEDULE = 'USING CRON 0 * * * * UTC'  -- fallback schedule
    WHEN SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_RAW_POSTS')
    AS
    -- Full MERGE INTO ENHANCED.POSTS_ENRICHED statement here
    -- (see ENHANCED table section above)
    ;

ALTER TASK ENHANCED.TASK_ENRICH_POSTS SUSPEND;
```

The WHEN clause means the task only executes if the stream
has unread rows. If no new data has landed, the task skips.

#### Task 2: CURATED.TASK_BUILD_ML_READY

```sql
CREATE OR REPLACE TASK CURATED.TASK_BUILD_ML_READY
    WAREHOUSE = COMPUTE_WH
    AFTER ENHANCED.TASK_ENRICH_POSTS
    AS
    -- TRUNCATE + INSERT INTO CURATED.ML_READY
    -- (see CURATED table section above)
    ;

ALTER TASK CURATED.TASK_BUILD_ML_READY SUSPEND;
```

AFTER clause chains it to Task 1 — CURATED task only runs
when ENHANCED task completes successfully.

#### Resuming the Chain
To start the pipeline after loading data to stages:

```sql
-- Resume in reverse order (child before parent)
ALTER TASK CURATED.TASK_BUILD_ML_READY RESUME;
ALTER TASK ENHANCED.TASK_ENRICH_POSTS RESUME;
```

#### Suspending After Run
Add this at the end of TASK_BUILD_ML_READY so both tasks
suspend themselves automatically after completion:

```sql
-- At end of TASK_BUILD_ML_READY body:
ALTER TASK ENHANCED.TASK_ENRICH_POSTS SUSPEND;
ALTER TASK CURATED.TASK_BUILD_ML_READY SUSPEND;
```

This means you resume once, it runs through the full chain,
and suspends itself. Zero manual intervention needed after
the resume command.

---

### File Locations
```
sql/03_enhanced/00_posts_enriched_table.sql   ← CREATE TABLE
sql/04_curated/00_ml_ready_table.sql          ← CREATE TABLE
sql/05_tasks/00_tasks.sql                     ← Both task definitions
```

---

### Deployment Order
1. sql/03_enhanced/00_posts_enriched_table.sql
2. sql/04_curated/00_ml_ready_table.sql
3. sql/05_tasks/00_tasks.sql
   (both tasks suspended on creation)

---

### Critical Rules
- Both tasks created SUSPENDED — never auto-start
- Tasks self-suspend after completion
- ENHANCED filters out bots and adult content at write time
- CURATED uses TRUNCATE + INSERT (always fresh from ENHANCED)
- RAW data is never modified
- No COPY INTO in any of these files
- All objects fully schema-qualified