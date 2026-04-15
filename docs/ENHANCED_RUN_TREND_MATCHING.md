# ENHANCED_RUN_TREND_MATCHING.md
## Spec: Run NLP Trend Matching on Demo Posts + Load to Snowflake

---

### Overview
After 25 posts are in RAW.LANDING_RAW_POSTS and Twitter trends
are in RAW.LANDING_TWITTER_TRENDS, the NLP matching pipeline
must run on the 25 posts to produce match results. Those results
get loaded into RAW.LANDING_TREND_MATCHES so the ENHANCED task
can join on them.

The matching pipeline already exists in the codebase. This spec
defines how to run it on the demo posts and load the output.

---

### Existing Pipeline Components
These files already exist and must be used as-is:

| File | Purpose |
|---|---|
| src/nlp/post_normalization.py | Cleans raw post text |
| src/nlp/topic_candidate_generation.py | Extracts topic phrases from posts |
| src/nlp/post_trend_matching.py | Runs 3-stage matching (exact/TF-IDF/FAISS) |
| bluesky_pipeline/text_prep/trend_match_writer.py | Writes match results to gzip JSONL |

Do not modify any of these files.

---

### The Three-Stage Matching Process
The matching pipeline runs as a cascade:

Stage 1 — Exact matching
- Normalizes post text and trend names to alphanumeric lowercase
- Looks up exact matches in a prebuilt dict index
- Score is always 1.0
- If matches found, skip stages 2 and 3

Stage 2 — TF-IDF fuzzy matching
- Builds char_wb ngram (2,3) TF-IDF matrix over all trend keys
- Uses token overlap blocking to narrow candidate pool
- Applies SequenceMatcher for fuzzy scoring
- Minimum score: 0.88
- If matches found, skip stage 3

Stage 3 — FAISS semantic matching
- Encodes post text with all-MiniLM-L6-v2
- Searches FAISS IndexFlatIP over trend embeddings
- Combined score: 0.7 * token_cosine + 0.3 * char_trigram_jaccard
- Minimum combined score: 0.60

---

### Script to Create
File: scripts/demo/run_trend_matching.py

This is a standalone script that:
1. Reads the 25 demo posts from data/demo/raw_posts/demo_raw_posts.jsonl.gz
2. Reads the Twitter trends from local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet
3. Runs the full NLP pipeline on the posts
4. Writes match results to data/trend_matches/{run_id}/
5. Loads the results to RAW.LANDING_TREND_MATCHES via Snowpipe

---

### Step 1: Read Demo Posts
```python
import gzip, json
from pathlib import Path

posts = []
post_file = Path("data/demo/raw_posts/demo_raw_posts.jsonl.gz")
with gzip.open(post_file, "rt", encoding="utf-8") as f:
    for line in f:
        posts.append(json.loads(line))

print(f"Loaded {len(posts)} demo posts")
```

Each post has a "record" key containing a dict with "text" field:
```python
post_text = post["record"]["text"]  # raw post text
post_uri = post["uri"]
post_created_at = post["record_created_at"]  # or post["captured_at"]
```

---

### Step 2: Read Twitter Trends
```python
import pandas as pd

trends_df = pd.read_parquet(
    "local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet"
)
```

---

### Step 3: Run NLP Pipeline
Import and run the existing pipeline in sequence:

```python
# Text normalization
from src.nlp.post_normalization import normalize_posts
normalized_posts = normalize_posts(posts)

# Topic candidate generation
from src.nlp.topic_candidate_generation import generate_candidates
candidates = generate_candidates(normalized_posts)

# Trend matching — this is the expensive step
# Builds TF-IDF index + FAISS index over all trends (takes ~2-5 min first run)
from src.nlp.post_trend_matching import match_post_candidates_to_trends
full_matches_df, best_matches_df, summary = match_post_candidates_to_trends(
    candidates_df=candidates,
    trends_df=trends_df,
)
```

Note: The FAISS index build over 101K trends takes 2-5 minutes
the first time. This is expected. Print a message before starting.

---

### Step 4: Write Match Results via TrendMatchWriter
The TrendMatchWriter already exists and produces the correct
schema for RAW.LANDING_TREND_MATCHES.

```python
import datetime
from pathlib import Path
from bluesky_pipeline.text_prep.trend_match_writer import TrendMatchWriter

run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
writer = TrendMatchWriter(
    output_dir=Path("data/trend_matches"),
    run_id=run_id,
)

# Write only matched rows (is_matched = True)
matched = best_matches_df[best_matches_df["is_matched"] == True]
for _, row in matched.iterrows():
    writer.write_matches([{
        "post_uri": row["uri"],
        "trend_name": row["trend_name_raw"],
        "trend_date": str(row["trend_date"]),
        "match_method": row["match_method"],
        "match_score": float(row["match_score"]),
        "matched_at": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
    }])

written_files = writer.close()
print(f"Written {len(matched)} match records to {len(written_files)} files")
```

---

### Step 5: Load Match Results to Snowflake
PUT each written file to the stage and refresh the pipe:

```python
import snowflake.connector
from dotenv import load_dotenv
import os

load_dotenv()

conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"],
    user=os.environ["SNOWFLAKE_USER"],
    password=os.environ["SNOWFLAKE_PASSWORD"],
    role=os.environ["SNOWFLAKE_ROLE"],
    warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
    database=os.environ["SNOWFLAKE_DATABASE"],
    schema=os.environ["SNOWFLAKE_SCHEMA"],
    autocommit=True,
)
cur = conn.cursor()

STAGE = "RAW.BLUESKY_TREND_MATCHES_STAGE"

for file_path in written_files:
    stage_path = f"@{STAGE}/demo_run/trend_matches/{run_id}/"
    cur.execute(
        f"PUT 'file://{file_path.resolve()}' {stage_path} "
        f"AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
    )
    print(f"PUT {file_path.name} → {stage_path}")

cur.execute("ALTER PIPE RAW.BLUESKY_TREND_MATCHES_PIPE REFRESH")
print("Pipe refreshed — trend matches will load in ~60 seconds")

import time
time.sleep(60)

cur.execute("SELECT COUNT(*) FROM RAW.LANDING_TREND_MATCHES")
count = cur.fetchone()[0]
print(f"RAW.LANDING_TREND_MATCHES: {count} rows")

cur.close()
conn.close()
```

---

### Stage Path Pattern
The pipe PATTERN for trend matches is:
```
PATTERN = '^.*/trend_matches/[^/]+/[^/]+\\.jsonl\\.gz$'
```

The stage path demo_run/trend_matches/{run_id}/filename.jsonl.gz
satisfies this pattern:
- demo_run = source_run_tag
- trend_matches = literal directory
- {run_id} = matches [^/]+
- filename.jsonl.gz = matches [^/]+\.jsonl\.gz

---

### Output Schema per Match Record
Each JSONL line written by TrendMatchWriter:
```json
{
    "post_uri": "at://did:plc:abc.../app.bsky.feed.post/xyz",
    "trend_name": "#SuperBowl2026",
    "trend_date": "2026-02-09",
    "match_method": "semantic",
    "match_score": 0.87,
    "matched_at": "2026-04-11T22:00:00Z"
}
```

The Snowflake task reads:
```sql
tm.raw_payload:post_uri::STRING
tm.raw_payload:trend_name::STRING
tm.raw_payload:trend_date::DATE
tm.raw_payload:match_method::STRING
tm.raw_payload:match_score::FLOAT
```

These field names must match exactly.

---

### Terminal Output Expected
```
Loading 25 demo posts from data/demo/raw_posts/demo_raw_posts.jsonl.gz
Loading Twitter trends from parquet...
Running text normalization...
Generating topic candidates...
Building TF-IDF index over 101,731 trends... (this takes ~1 min)
Building FAISS index over 101,731 trends... (this takes ~2-5 min)
Running 3-stage trend matching...
Matching complete: X matched, Y unmatched out of 25 posts
Writing match results...
Written N match records to 1 file(s)
Loading to Snowflake...
PUT trend_matches_000001.jsonl.gz → @RAW.BLUESKY_TREND_MATCHES_STAGE/...
Pipe refreshed — trend matches will load in ~60 seconds
RAW.LANDING_TREND_MATCHES: N rows
Done.
```

---

### Dependencies Required
These must be installed in the virtual environment:
- faiss-cpu
- sentence-transformers
- scikit-learn
- pandas
- pyarrow (for reading Parquet)

Verify with:
```bash
python -c "import faiss, sentence_transformers, sklearn, pandas, pyarrow; print('all ok')"
```

---

### What NOT to Do
- Do not modify post_trend_matching.py
- Do not modify trend_match_writer.py
- Do not modify post_normalization.py
- Do not modify topic_candidate_generation.py
- Do not write unmatched posts to the output file
- Do not load this into Snowflake via COPY INTO — use pipe REFRESH only