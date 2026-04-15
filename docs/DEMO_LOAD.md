# DEMO_LOAD.md
## Spec: Friday Demo Script — Live 25-Post RAW Layer Load

---

### Purpose
A single standalone script that pulls 25 live posts from
the Bluesky API, fetches their actor profiles, and loads
both datasets directly into Snowflake RAW landing tables.
Designed to be run live in front of a professor to demonstrate
the full RAW ingestion layer working end to end.

Total expected runtime: 2-3 minutes.

---

### Script Location
```
scripts/demo/demo_load.py
```

---

### What It Does — Step by Step

```
1. Validate environment (Snowflake credentials, venv)
2. Connect to Bluesky firehose WebSocket
3. Capture exactly 25 unique posts, then disconnect
4. Extract unique author DIDs from the 25 posts
5. Call Bluesky getProfiles API for those DIDs
6. Write posts to: data/demo/raw_posts/demo_raw_posts.jsonl.gz
7. Write actors to: data/demo/actor_profiles/demo_actor_profiles.jsonl.gz
8. COPY INTO RAW.LANDING_RAW_POSTS from stage
9. COPY INTO RAW.LANDING_ACTOR_PROFILES from stage
10. Query both tables and print confirmation row counts
11. Print a clean summary table
```

---

### Output Format

Each post written to JSONL must match the exact same schema
the main firehose pipeline produces — same field names,
same nesting, same VARIANT structure. The landing table
schema expects this exact format.

Each actor profile must match the exact same schema the
main actor enrichment pipeline produces.

Read main_firehose.py and main_actor_enrich.py to confirm
the exact output schema before writing anything.

---

### Snowflake Load Pattern

Use COPY INTO directly — not Snowpipe.
The demo needs immediate confirmation, not async ingestion.

```sql
-- Upload file to stage first
PUT file://data/demo/raw_posts/demo_raw_posts.jsonl.gz
    @RAW.BLUESKY_RAW_POSTS_STAGE
    AUTO_COMPRESS = FALSE
    OVERWRITE = TRUE;

-- Load into table
COPY INTO RAW.LANDING_RAW_POSTS (
    raw_payload,
    source_filename,
    source_file_row_number,
    source_run_tag,
    dataset_family,
    load_invocation_id
)
FROM (
    SELECT
        $1,
        METADATA$FILENAME,
        METADATA$FILE_ROW_NUMBER,
        'demo_run',
        'raw_posts',
        'demo'
    FROM @RAW.BLUESKY_RAW_POSTS_STAGE/demo_raw_posts.jsonl.gz
)
FILE_FORMAT = (FORMAT_NAME = RAW.BLUESKY_JSONL_GZ)
ON_ERROR = CONTINUE;
```

Repeat same pattern for actor profiles.

---

### Terminal Output During Demo
The script must print clear status lines so the professor
can follow what is happening in real time:

```
============================================================
  BLUESKY PIPELINE — LIVE DEMO LOAD
============================================================

[1/5] Connecting to Bluesky firehose...
      ✅ Connected to wss://bsky.network

[2/5] Capturing 25 live posts...
      Post 1/25 captured: at://did:plc:abc.../post/xyz
      Post 2/25 captured: at://did:plc:def.../post/xyz
      ...
      Post 25/25 captured
      ✅ 25 posts captured. Disconnecting from firehose.

[3/5] Fetching actor profiles for 25 authors...
      ✅ 25 actor profiles retrieved

[4/5] Loading to Snowflake RAW layer...
      Uploading raw posts to stage...    ✅
      COPY INTO RAW.LANDING_RAW_POSTS... ✅ 25 rows loaded
      Uploading actor profiles to stage... ✅
      COPY INTO RAW.LANDING_ACTOR_PROFILES... ✅ 25 rows loaded

[5/5] Confirming data in Snowflake...

  ┌─────────────────────────────────┬────────────┐
  │ Table                           │ Row Count  │
  ├─────────────────────────────────┼────────────┤
  │ RAW.LANDING_RAW_POSTS           │         25 │
  │ RAW.LANDING_ACTOR_PROFILES      │         25 │
  └─────────────────────────────────┴────────────┘

============================================================
  DEMO COMPLETE — Live Bluesky data is now in Snowflake
============================================================
```

---

### Demo Data Isolation
Write demo data to a separate directory so it does not
mix with real pipeline data:

```
data/demo/
  raw_posts/
    demo_raw_posts.jsonl.gz
  actor_profiles/
    demo_actor_profiles.jsonl.gz
```

Use source_run_tag = 'demo_run' so demo rows are easily
identified and can be cleaned up after:

```sql
-- Cleanup after demo if needed
DELETE FROM RAW.LANDING_RAW_POSTS
WHERE source_run_tag = 'demo_run';

DELETE FROM RAW.LANDING_ACTOR_PROFILES
WHERE source_run_tag = 'demo_run';
```

Include these cleanup statements as comments at the bottom
of the script.

---

### Error Handling
The demo must not crash in front of the professor.
Wrap every step in a clear try/except with a friendly
error message:

```python
try:
    # step
except Exception as e:
    print(f"\n  ❌ Step failed: {e}")
    print(f"  Check your connection and Snowflake credentials")
    sys.exit(1)
```

---

### Dependencies
Uses only what is already installed in the project venv:
- websockets (firehose connection)
- httpx (actor API calls)
- snowflake-connector-python (Snowflake load)
- Standard library only beyond these three

No new dependencies needed.

---

### Reusability
The script must be safe to run multiple times.
Each run uses OVERWRITE = TRUE on the stage upload
and ON_ERROR = CONTINUE on COPY INTO.
Demo rows are tagged with source_run_tag = 'demo_run'
so they can be identified and cleaned up.

---

### Files to Deliver
```
scripts/demo/demo_load.py    ← standalone demo script
```

One file. No supporting modules needed.
Everything self-contained so it is easy to run and explain.

---

### Pre-Demo Checklist
Include this as a printed comment block at the top of
the script:

```
PRE-DEMO CHECKLIST:
  [ ] Virtual environment activated
  [ ] Snowflake credentials in environment or .env
  [ ] RAW schema deployed in Snowflake
  [ ] LANDING_RAW_POSTS table exists
  [ ] LANDING_ACTOR_PROFILES table exists
  [ ] RAW.BLUESKY_RAW_POSTS_STAGE exists
  [ ] RAW.BLUESKY_ACTOR_PROFILES_STAGE exists
  [ ] Internet connection active
  Run: python scripts/demo/demo_load.py
```