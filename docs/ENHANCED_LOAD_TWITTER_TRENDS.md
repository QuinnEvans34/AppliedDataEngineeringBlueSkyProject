# ENHANCED_LOAD_TWITTER_TRENDS.md
## Spec: Load Twitter Trends into RAW.LANDING_TWITTER_TRENDS

---

### Overview
The Twitter trending topics snapshot exists locally as a Parquet
file. It must be converted to gzip JSONL and loaded into
RAW.LANDING_TWITTER_TRENDS via Snowpipe so the ENHANCED task
can join posts to trends by date.

This is a one-time load for the demo. The full dataset has
101,731 rows covering 2024-01-01 to 2026-01-24.

---

### Source File
```
Local path to find: search for twitter_trending_normalized.parquet
Look in: local/reference_snapshots/twitter_trending/
         data/samples/
         data/
```

Use twitter_trending_normalized.parquet (5.6 MB) — NOT the
full or sample versions.

---

### Source Columns
The Parquet file has these columns:
- num_hours: int — how many hours the topic trended
- date: string — date in YYYY-MM-DD format
- name: string — raw trend name (e.g. "#SuperBowl2026")
- counts: float — tweet volume

---

### Output JSONL Schema
Each line in the output file must be a JSON object with these
exact field names — chosen to match what the Snowflake task
reads from raw_payload:

```json
{
    "trend_name": "superbowl2026",
    "trend_name_raw": "#SuperBowl2026",
    "trend_date": "2026-02-09",
    "tweet_volume": 1262842,
    "num_hours": 11,
    "rank": null
}
```

Field mapping from source:
| Output Field | Source Column | Transformation |
|---|---|---|
| trend_name | name | LOWER(TRIM(REPLACE(name, '#', ''))) |
| trend_name_raw | name | As-is |
| trend_date | date | As-is (YYYY-MM-DD string) |
| tweet_volume | counts | int(counts) if not null else 0 |
| num_hours | num_hours | As-is |
| rank | (none) | Always null — no rank in source |

Why trend_name is normalized: The Snowflake task joins on
trend name. Normalizing to lowercase without # ensures the
join works regardless of hashtag casing.

---

### Output File Location
```
data/twitter_trends/full/twitter_trends_000001.jsonl.gz
```

Write all 101,731 rows to a single file.
Use gzip compression. One JSON object per line.

---

### Stage Path for PUT
```
@RAW.BLUESKY_TWITTER_TRENDS_STAGE/full/twitter_trends/load/
```

This path must match the pipe PATTERN:
```
PATTERN = '^.*/twitter_trends/[^/]+/[^/]+\\.jsonl\\.gz$'
```

Path breakdown:
- full = source_run_tag (first segment)
- twitter_trends = literal directory (matches pattern)
- load = run_id subdirectory (matches [^/]+)
- twitter_trends_000001.jsonl.gz = filename (matches [^/]+\.jsonl\.gz)

---

### Script to Create
File: scripts/demo/load_twitter_trends.py

This is a standalone script — not part of demo_load.py.
It only needs to run once to load the full trends dataset.

```python
"""
load_twitter_trends.py
Converts the local Twitter trends Parquet snapshot to gzip JSONL
and loads it into RAW.LANDING_TWITTER_TRENDS via Snowpipe.

Usage:
    python scripts/demo/load_twitter_trends.py
"""
```

Steps the script must perform:
1. Find the Parquet file — search common locations, error clearly if not found
2. Read with pandas
3. Convert each row to the output schema defined above
4. Write to data/twitter_trends/full/twitter_trends_000001.jsonl.gz
5. Connect to Snowflake using .env credentials
6. Remove any existing files from the stage path (REMOVE)
7. PUT the file to the stage path
8. Run ALTER PIPE RAW.BLUESKY_TWITTER_TRENDS_PIPE REFRESH
9. Sleep 60 seconds
10. Query RAW.LANDING_TWITTER_TRENDS COUNT(*) and print result
11. Print a sample of 3 rows to confirm structure

---

### Snowflake Credentials
Read from environment variables using dotenv — same pattern
as demo_load.py. The script must load .env at startup.

Required env vars:
- SNOWFLAKE_ACCOUNT
- SNOWFLAKE_USER
- SNOWFLAKE_PASSWORD
- SNOWFLAKE_ROLE
- SNOWFLAKE_WAREHOUSE
- SNOWFLAKE_DATABASE
- SNOWFLAKE_SCHEMA

---

### Validation Query
Run in Snowflake after script completes:

```sql
-- Row count
SELECT COUNT(*) AS total_trends FROM RAW.LANDING_TWITTER_TRENDS;
-- Expected: ~101,731

-- Sample rows
SELECT
    raw_payload:trend_name::STRING AS trend_name,
    raw_payload:trend_name_raw::STRING AS trend_name_raw,
    raw_payload:trend_date::DATE AS trend_date,
    raw_payload:tweet_volume::NUMBER AS tweet_volume,
    raw_payload:num_hours::NUMBER AS num_hours
FROM RAW.LANDING_TWITTER_TRENDS
LIMIT 5;

-- Date range check
SELECT
    MIN(raw_payload:trend_date::DATE) AS earliest_date,
    MAX(raw_payload:trend_date::DATE) AS latest_date,
    COUNT(DISTINCT raw_payload:trend_date::DATE) AS unique_dates
FROM RAW.LANDING_TWITTER_TRENDS;
-- Expected: ~749 unique dates, 2024-01-01 to 2026-01-24
```

---

### Task SQL Field Names
The ENHANCED task reads trends with these exact paths —
confirm the output JSON uses these same keys:

```sql
t.raw_payload:date::DATE          -- use trend_date NOT date
t.raw_payload:trend_name::STRING  -- normalized name
t.raw_payload:tweet_volume::NUMBER
t.raw_payload:rank::NUMBER
```

IMPORTANT: The task currently reads raw_payload:date but the
output schema above uses trend_date. The task SQL must be
updated to read raw_payload:trend_date. This is handled in
ENHANCED_FIX_TASK_SQL.md.

---

### What NOT to Do
- Do not load the sample CSV — use the full Parquet
- Do not use the non-normalized parquet (twitter_trending_full.parquet)
- Do not modify any existing pipeline files
- Do not add this logic to demo_load.py — keep it separate
- Do not run COPY INTO — use Snowpipe REFRESH only