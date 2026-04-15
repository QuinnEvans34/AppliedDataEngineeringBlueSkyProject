# SQL_TWITTER_TRENDS.md
## Spec: LANDING_TWITTER_TRENDS + STG_TWITTER_TRENDS

---

### What This Is
New RAW and ENHANCED layer objects for the Twitter trending topics
data. This data already exists as a local Parquet snapshot from a
previous pipeline run. These SQL objects provide the Snowflake home
for that data so it can be joined to Bluesky posts.

---

### Data Source
Local file: already captured via snapshot_twitter_trending.py
Format: Parquet (and CSV sample)
DO NOT query the Snowflake Marketplace during development.
Load from the local snapshot file only.

---

### Output Objects

#### RAW Layer
- Name: `BLUESKYDATAENGINEERINGPROJECT.PUBLIC.LANDING_TWITTER_TRENDS`
- Type: TABLE
- File: `sql/01_landing/04_landing_twitter_trends.sql`

#### ENHANCED Layer
- Name: `BLUESKYDATAENGINEERINGPROJECT.PUBLIC.STG_TWITTER_TRENDS`
- Type: VIEW
- File: `sql/02_staging/06_stg_twitter_trends.sql`

---

### LANDING_TWITTER_TRENDS Schema
Follows the same pattern as all other landing tables:

```sql
CREATE TABLE IF NOT EXISTS LANDING_TWITTER_TRENDS (
    landing_id        NUMBER AUTOINCREMENT PRIMARY KEY,
    raw_payload       VARIANT NOT NULL,
    source_filename   STRING NOT NULL,
    source_file_row_number NUMBER,
    source_run_tag    STRING NOT NULL,
    dataset_family    STRING NOT NULL DEFAULT 'twitter_trends',
    load_invocation_id STRING NOT NULL,
    loaded_at         TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
```

This matches the schema of LANDING_RAW_POSTS exactly — same
loader infrastructure works without modification.

---

### STG_TWITTER_TRENDS Columns
Extract these fields from raw_payload VARIANT:

| Column | Type | Source Path | Notes |
|---|---|---|---|
| trend_date | DATE | TRY_CAST(raw_payload:date::STRING AS DATE) | Join key to posts |
| trend_name | STRING | raw_payload:trend_name::STRING | Raw trend string |
| trend_name_clean | STRING | LOWER(TRIM(trend_name)) | Normalized for matching |
| woeid | NUMBER | raw_payload:woeid::NUMBER | World location ID |
| tweet_volume | NUMBER | raw_payload:tweet_volume::NUMBER | Popularity signal |
| rank | NUMBER | raw_payload:rank::NUMBER | Position in trending list |
| source_run_tag | STRING | Pass through from landing | |
| loaded_at | TIMESTAMP_TZ | Pass through from landing | |

---

### Join Key Design
The join between Bluesky posts and Twitter trends will be:

```sql
DATE(p.post_created_at_ts) = t.trend_date
```

This is a date-level join — posts from a given day are matched
to trends that were trending on that same day. This prevents
a post from being matched to trends that didn't exist yet when
it was posted.

trend_name_clean (lowercased, trimmed) is the text field that
the FAISS/TF-IDF Python matching writes back against. Keep it
consistent with whatever normalization the Python pipeline uses.

---

### Internal Stage for Loading
Add a new internal stage following existing convention:

```sql
CREATE STAGE IF NOT EXISTS BLUESKY_TWITTER_TRENDS_STAGE
    FILE_FORMAT = BLUESKY_JSONL_GZ;
```

File: `sql/01_landing/05_twitter_trends_stage.sql`

---

### COPY INTO Pattern (comment out during development)
```sql
-- Run only when local snapshot file is ready to load
-- COPY INTO LANDING_TWITTER_TRENDS (raw_payload, source_filename,
--     source_file_row_number, source_run_tag, load_invocation_id)
-- FROM @BLUESKY_TWITTER_TRENDS_STAGE
-- FILE_FORMAT = (FORMAT_NAME = BLUESKY_JSONL_GZ)
-- ON_ERROR = CONTINUE;
```

---

### Validation Query
```sql
SELECT
    trend_date,
    trend_name,
    trend_name_clean,
    tweet_volume,
    rank
FROM STG_TWITTER_TRENDS
ORDER BY trend_date DESC, rank ASC
LIMIT 100;
```

---

### File Naming
- `sql/01_landing/04_landing_twitter_trends.sql`
- `sql/01_landing/05_twitter_trends_stage.sql`
- `sql/02_staging/06_stg_twitter_trends.sql`