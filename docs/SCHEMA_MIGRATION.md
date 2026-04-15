# SCHEMA_MIGRATION.md
## Spec: Schema Migration — PUBLIC → RAW / ENHANCED / CURATED

---

### Overview
All objects currently live in PUBLIC schema. This migration
restructures the database into three purpose-built schemas
that match the project's data engineering architecture.

```
BEFORE                          AFTER
──────────────────────          ──────────────────────────────
PUBLIC                          RAW
  LANDING_* (tables)     →        LANDING_* (tables)
  Stages                 →        Stages
  Pipes                  →        Pipes
  Streams                →        Streams
  File formats           →        File formats
  LOADER_FILE_MANIFEST   →        LOADER_FILE_MANIFEST
  CLEAN_PROFANITY (UDF)  →        CLEAN_PROFANITY (UDF)

                                ENHANCED
  STG_* (views, drop)             POSTS_ENRICHED (TABLE)
  CURATED_POSTS_* (drop)          Task (stream-triggered)

                                CURATED
  CURATED_ML_READY (drop)         ML_READY (TABLE)
                                  Task (chain-triggered)
```

---

### Schema Definitions

#### RAW Schema
Purpose: Holds all raw ingested data exactly as received.
No transformations. Append-only.

```sql
CREATE SCHEMA IF NOT EXISTS BLUESKYDATAENGINEERINGPROJECT.RAW
    COMMENT = 'Raw ingestion layer — landing tables, stages, pipes, streams';
```

#### ENHANCED Schema
Purpose: Cleaned, enriched, joined data. Tasks process
streams from RAW and write materialized tables here.

```sql
CREATE SCHEMA IF NOT EXISTS BLUESKYDATAENGINEERINGPROJECT.ENHANCED
    COMMENT = 'Enhanced layer — cleaned posts, enriched features, trend joins';
```

#### CURATED Schema
Purpose: ML-ready data only. Final feature vector table
consumed by Python model training.

```sql
CREATE SCHEMA IF NOT EXISTS BLUESKYDATAENGINEERINGPROJECT.CURATED
    COMMENT = 'Curated layer — ML-ready feature table with labels and train/test split';
```

---

### Step 1: Recreate File Format in RAW

```sql
CREATE OR REPLACE FILE FORMAT RAW.BLUESKY_JSONL_GZ
    TYPE = JSON
    COMPRESSION = GZIP
    STRIP_OUTER_ARRAY = FALSE
    COMMENT = 'Gzip-compressed JSONL for all Bluesky pipeline data';
```

---

### Step 2: Move Landing Tables to RAW

Use ALTER TABLE ... RENAME TO for zero-copy migration.
No data is moved — only the schema reference changes.

```sql
ALTER TABLE PUBLIC.LANDING_RAW_POSTS          RENAME TO RAW.LANDING_RAW_POSTS;
ALTER TABLE PUBLIC.LANDING_HYDRATED_POSTS      RENAME TO RAW.LANDING_HYDRATED_POSTS;
ALTER TABLE PUBLIC.LANDING_HYDRATION_MISSES    RENAME TO RAW.LANDING_HYDRATION_MISSES;
ALTER TABLE PUBLIC.LANDING_ACTOR_PROFILES      RENAME TO RAW.LANDING_ACTOR_PROFILES;
ALTER TABLE PUBLIC.LANDING_TWITTER_TRENDS      RENAME TO RAW.LANDING_TWITTER_TRENDS;
ALTER TABLE PUBLIC.LOADER_FILE_MANIFEST        RENAME TO RAW.LOADER_FILE_MANIFEST;
```

---

### Step 3: Recreate Stages in RAW

Stages cannot be renamed — must DROP and CREATE.
Old PUBLIC stages stay until new RAW stages are confirmed.

```sql
CREATE STAGE IF NOT EXISTS RAW.BLUESKY_RAW_POSTS_STAGE
    FILE_FORMAT = RAW.BLUESKY_JSONL_GZ;

CREATE STAGE IF NOT EXISTS RAW.BLUESKY_HYDRATED_POSTS_STAGE
    FILE_FORMAT = RAW.BLUESKY_JSONL_GZ;

CREATE STAGE IF NOT EXISTS RAW.BLUESKY_HYDRATION_MISSES_STAGE
    FILE_FORMAT = RAW.BLUESKY_JSONL_GZ;

CREATE STAGE IF NOT EXISTS RAW.BLUESKY_ACTOR_PROFILES_STAGE
    FILE_FORMAT = RAW.BLUESKY_JSONL_GZ;

CREATE STAGE IF NOT EXISTS RAW.BLUESKY_TWITTER_TRENDS_STAGE
    FILE_FORMAT = RAW.BLUESKY_JSONL_GZ;
```

Also add the trend matches stage for Python write-back:
```sql
CREATE STAGE IF NOT EXISTS RAW.BLUESKY_TREND_MATCHES_STAGE
    FILE_FORMAT = RAW.BLUESKY_JSONL_GZ;
```

---

### Step 4: Add LANDING_TREND_MATCHES Table

New landing table for Python FAISS match results.
Same schema pattern as all other landing tables.

```sql
CREATE TABLE IF NOT EXISTS RAW.LANDING_TREND_MATCHES (
    landing_id             NUMBER AUTOINCREMENT PRIMARY KEY,
    raw_payload            VARIANT NOT NULL,
    source_filename        STRING NOT NULL,
    source_file_row_number NUMBER,
    source_run_tag         STRING NOT NULL,
    dataset_family         STRING NOT NULL DEFAULT 'trend_matches',
    load_invocation_id     STRING NOT NULL,
    loaded_at              TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
```

---

### Step 5: Recreate Pipes in RAW

Pipes cannot be renamed — must DROP and CREATE.
Reference RAW tables and RAW stages.
All pipes created with AUTO_INGEST = FALSE (manual COPY INTO).

```sql
CREATE PIPE IF NOT EXISTS RAW.BLUESKY_RAW_POSTS_PIPE
    AUTO_INGEST = FALSE
    AS COPY INTO RAW.LANDING_RAW_POSTS (
        raw_payload, source_filename, source_file_row_number,
        source_run_tag, dataset_family, load_invocation_id
    )
    FROM (
        SELECT
            $1,
            METADATA$FILENAME,
            METADATA$FILE_ROW_NUMBER,
            SPLIT_PART(METADATA$FILENAME, '/', 2),
            'raw_posts',
            'snowpipe'
        FROM @RAW.BLUESKY_RAW_POSTS_STAGE
    )
    FILE_FORMAT = (FORMAT_NAME = RAW.BLUESKY_JSONL_GZ);
```

Repeat the same pattern for:
- RAW.BLUESKY_HYDRATED_POSTS_PIPE → RAW.LANDING_HYDRATED_POSTS
- RAW.BLUESKY_HYDRATION_MISSES_PIPE → RAW.LANDING_HYDRATION_MISSES
- RAW.BLUESKY_ACTOR_PROFILES_PIPE → RAW.LANDING_ACTOR_PROFILES
- RAW.BLUESKY_TWITTER_TRENDS_PIPE → RAW.LANDING_TWITTER_TRENDS
- RAW.BLUESKY_TREND_MATCHES_PIPE → RAW.LANDING_TREND_MATCHES

---

### Step 6: Recreate Streams in RAW

Streams watch RAW landing tables for new rows.
They feed the ENHANCED layer tasks.

```sql
CREATE STREAM IF NOT EXISTS RAW.STRM_LANDING_RAW_POSTS
    ON TABLE RAW.LANDING_RAW_POSTS
    APPEND_ONLY = TRUE
    COMMENT = 'Detects new raw posts for ENHANCED processing';

CREATE STREAM IF NOT EXISTS RAW.STRM_LANDING_HYDRATED_POSTS
    ON TABLE RAW.LANDING_HYDRATED_POSTS
    APPEND_ONLY = TRUE;

CREATE STREAM IF NOT EXISTS RAW.STRM_LANDING_ACTOR_PROFILES
    ON TABLE RAW.LANDING_ACTOR_PROFILES
    APPEND_ONLY = TRUE;

CREATE STREAM IF NOT EXISTS RAW.STRM_LANDING_TREND_MATCHES
    ON TABLE RAW.LANDING_TREND_MATCHES
    APPEND_ONLY = TRUE;
```

---

### Step 7: Move UDF to RAW

UDFs are schema-scoped. Recreate in RAW schema.
The ENHANCED task will call RAW.CLEAN_PROFANITY().

```sql
CREATE OR REPLACE FUNCTION RAW.CLEAN_PROFANITY(post_text STRING)
RETURNS OBJECT
LANGUAGE JAVASCRIPT
AS $$
    if (!POST_TEXT || POST_TEXT.trim() === "") {
        return { post_text_clean: POST_TEXT, was_profanity_redacted: false };
    }
    const PROFANITY_LIST = [
        "ass", "asshole", "bastard", "bitch", "bollocks",
        "bullshit", "cock", "crap", "cunt", "damn", "dick",
        "dickhead", "douche", "douchebag", "dyke", "fag",
        "faggot", "fuck", "fucker", "fucking", "goddamn",
        "hell", "horseshit", "jackass", "jerk", "motherfucker",
        "nigga", "nigger", "piss", "prick", "pussy", "shit",
        "shithead", "slut", "twat", "wanker", "whore"
    ];
    const URL_PATTERN = /https?:\/\/\S+/gi;
    const urls = [];
    let masked = POST_TEXT.replace(URL_PATTERN, function(url) {
        urls.push(url);
        return "__URL_" + (urls.length - 1) + "__";
    });
    let wasRedacted = false;
    for (const word of PROFANITY_LIST) {
        const regex = new RegExp("\\b" + word + "\\b", "gi");
        if (regex.test(masked)) {
            wasRedacted = true;
            regex.lastIndex = 0;
            masked = masked.replace(regex, "[Profanity]");
        }
    }
    masked = masked.replace(/__URL_(\d+)__/g, function(_, i) {
        return urls[parseInt(i)];
    });
    return { post_text_clean: masked, was_profanity_redacted: wasRedacted };
$$;
```

---

### Step 8: Drop Old PUBLIC Objects

Run LAST — only after RAW objects are confirmed working.
Order matters: views before tables, tables before stages.

```sql
-- Drop views
DROP VIEW IF EXISTS PUBLIC.CURATED_ML_READY;
DROP VIEW IF EXISTS PUBLIC.CURATED_POSTS_WITH_TRENDS;
DROP VIEW IF EXISTS PUBLIC.CURATED_POSTS_LABELED;
DROP VIEW IF EXISTS PUBLIC.CURATED_POSTS_CORE;
DROP VIEW IF EXISTS PUBLIC.STG_ENHANCED_ACTORS;
DROP VIEW IF EXISTS PUBLIC.STG_ENHANCED_POSTS;
DROP VIEW IF EXISTS PUBLIC.STG_TWITTER_TRENDS;
DROP VIEW IF EXISTS PUBLIC.STG_ACTOR_PROFILES;
DROP VIEW IF EXISTS PUBLIC.STG_HYDRATION_MISSES;
DROP VIEW IF EXISTS PUBLIC.STG_HYDRATED_POSTS;
DROP VIEW IF EXISTS PUBLIC.STG_RAW_POSTS;

-- Drop UDF from PUBLIC
DROP FUNCTION IF EXISTS PUBLIC.CLEAN_PROFANITY(STRING);

-- Drop old stages
DROP STAGE IF EXISTS PUBLIC.BLUESKY_RAW_POSTS_STAGE;
DROP STAGE IF EXISTS PUBLIC.BLUESKY_HYDRATED_POSTS_STAGE;
DROP STAGE IF EXISTS PUBLIC.BLUESKY_HYDRATION_MISSES_STAGE;
DROP STAGE IF EXISTS PUBLIC.BLUESKY_ACTOR_PROFILES_STAGE;
DROP STAGE IF EXISTS PUBLIC.BLUESKY_TWITTER_TRENDS_STAGE;
```

---

### File Structure After Migration

```
sql/
  00_setup/
    00_bootstrap_database_schema.sql  ← CREATE all 3 schemas
    00_file_formats.sql               ← RAW.BLUESKY_JSONL_GZ
    01_internal_stages.sql            ← RAW.BLUESKY_*_STAGE (6 stages)
    02_pipes.sql                      ← RAW.BLUESKY_*_PIPE (6 pipes)
    03_udfs.sql                       ← RAW.CLEAN_PROFANITY
  01_landing/
    00_landing_raw_posts.sql          ← RAW schema
    01_landing_hydrated_posts.sql     ← RAW schema
    02_landing_hydration_misses.sql   ← RAW schema
    03_landing_actor_profiles.sql     ← RAW schema
    04_landing_twitter_trends.sql     ← RAW schema
    05_landing_trend_matches.sql      ← RAW schema (NEW)
  02_streams/
    00_streams.sql                    ← RAW schema streams (NEW FILE)
  03_enhanced/
    01_posts_enriched.sql             ← ENHANCED.POSTS_ENRICHED TABLE (NEW)
  04_curated/
    01_ml_ready.sql                   ← CURATED.ML_READY TABLE (NEW)
  05_tasks/
    00_tasks.sql                      ← All task definitions (NEW)
  99_cleanup/
    00_drop_public_objects.sql        ← Drop old PUBLIC objects (NEW)
```

---

### Deployment Order
1. 00_bootstrap_database_schema.sql  — create schemas
2. 00_file_formats.sql               — RAW file format
3. 01_internal_stages.sql            — RAW stages
4. 00_landing_*.sql (all 6)          — rename/create landing tables
5. 02_pipes.sql                      — RAW pipes
6. 00_streams.sql                    — RAW streams
7. 03_udfs.sql                       — RAW UDF
8. 03_enhanced/01_posts_enriched.sql — ENHANCED table definition
9. 04_curated/01_ml_ready.sql        — CURATED table definition
10. 05_tasks/00_tasks.sql            — task definitions (PAUSED)
11. 99_cleanup/00_drop_public_objects.sql — drop PUBLIC (LAST)

---

### Critical Rules
- Do NOT activate tasks — all tasks created with SUSPEND
- Do NOT run COPY INTO statements
- Do NOT drop PUBLIC objects until RAW is confirmed working
- Landing tables use ALTER TABLE RENAME (zero-copy, no data loss)
- Stages and pipes must be dropped and recreated (cannot rename)
- Run cleanup script ONLY after full validation