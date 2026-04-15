# PYTHON_RAW_SCHEMA_AND_TREND_WRITEBACK.md
## Spec: Python Loader RAW Schema Update + Trend Match Write-Back

---

### Overview
Two Python changes required:

1. **Loader schema update** — The Snowflake loader currently
   writes to PUBLIC schema. All references must change to RAW.

2. **Trend match write-back** — The FAISS/TF-IDF trend matching
   pipeline currently produces results only in local Python memory.
   It must write results as JSONL files so they can be loaded into
   RAW.LANDING_TREND_MATCHES and joined in Snowflake.

---

## Part 1: Python Loader Schema Update

### Files to Audit and Update
Read every file in the snowflake_loader/ directory and find
every hardcoded reference to:
- Schema name 'PUBLIC' or "PUBLIC"
- Unqualified table names that assume PUBLIC schema
- Any connection default_schema set to PUBLIC

Change all of these to RAW.

### Key Places to Look
Based on the codebase structure these are the likely locations:

**snowflake_loader/config.py or connection.py**
```python
# Before
schema = "PUBLIC"
default_schema = "PUBLIC"

# After
schema = "RAW"
default_schema = "RAW"
```

**snowflake_loader/loader.py or main_load.py**
Any SQL strings that reference table names without schema:
```python
# Before
f"COPY INTO LANDING_RAW_POSTS ..."
f"SELECT * FROM LOADER_FILE_MANIFEST ..."

# After
f"COPY INTO RAW.LANDING_RAW_POSTS ..."
f"SELECT * FROM RAW.LOADER_FILE_MANIFEST ..."
```

**Any argparse defaults**
```python
# Before
parser.add_argument("--schema", default="PUBLIC")

# After
parser.add_argument("--schema", default="RAW")
```

### Connection String
Snowflake Python connector connection string:
```python
# Before
conn = snowflake.connector.connect(
    ...
    schema="PUBLIC"
)

# After
conn = snowflake.connector.connect(
    ...
    schema="RAW"
)
```

### Rule
Do not change any logic — only change schema references.
The loader behavior must be identical, just targeting RAW
instead of PUBLIC.

---

## Part 2: Trend Match Write-Back

### What Needs to Happen
The FAISS/TF-IDF matching in post_trend_matching.py currently
produces match results but never writes them to a file that
Snowflake can ingest. A new write-back step must be added that:

1. Takes the match results from post_trend_matching.py
2. Formats each match as a JSON object
3. Writes them as a gzip JSONL file
4. The Snowflake loader then loads this file into
   RAW.LANDING_TREND_MATCHES

### Output Schema Per Match Record
Each line in the output JSONL must be a JSON object with
these fields:

```json
{
    "post_uri": "at://did:plc:abc123/app.bsky.feed.post/xyz",
    "trend_name": "#SuperBowl2026",
    "trend_date": "2026-03-15",
    "match_method": "semantic",
    "match_score": 0.87,
    "matched_at": "2026-04-09T12:00:00Z"
}
```

| Field | Type | Source |
|---|---|---|
| post_uri | STRING | uri from the post record |
| trend_name | STRING | matched trend name |
| trend_date | DATE string | date the trend was trending |
| match_method | STRING | 'exact', 'fuzzy', or 'semantic' |
| match_score | FLOAT | similarity score (1.0 for exact) |
| matched_at | TIMESTAMP string | when matching was run |

### Output File Location
```
data/trend_matches/{run_id}/trend_matches_{sequence}.jsonl.gz
```

Follow the same output pattern as hydrated_posts and actor_profiles:
- One run directory per matching run named by timestamp
- Files named with sequence numbers
- Gzip compressed JSONL

### New Module Location
```
bluesky_pipeline/text_prep/trend_match_writer.py
```

### TrendMatchWriter Class

```python
class TrendMatchWriter:
    def __init__(self, output_dir: Path, run_id: str,
                 flush_row_count: int = 10000):
        """
        Writes trend match results to gzip JSONL files.
        output_dir: base directory (e.g. data/trend_matches/)
        run_id: unique run identifier for subdirectory
        flush_row_count: rows before rotating to next file
        """

    def write_matches(self, matches: list[dict]) -> None:
        """
        Accepts a list of match dicts, each with:
        post_uri, trend_name, trend_date, match_method,
        match_score, matched_at
        Buffers and flushes to gzip JSONL automatically.
        """

    def close(self) -> list[Path]:
        """
        Flushes remaining buffer, closes file handles.
        Returns list of Path objects for all files written.
        """
```

### Integration Point in post_trend_matching.py
After the matching loop completes and before the function
returns, add the write-back call:

```python
from bluesky_pipeline.text_prep.trend_match_writer import TrendMatchWriter

# After matching is done
writer = TrendMatchWriter(
    output_dir=Path("data/trend_matches"),
    run_id=run_id
)

for post_uri, matches in all_matches.items():
    for match in matches:
        writer.write_matches([{
            "post_uri": post_uri,
            "trend_name": match["trend_name"],
            "trend_date": match["trend_date"],
            "match_method": match["method"],
            "match_score": float(match["score"]),
            "matched_at": datetime.utcnow().isoformat() + "Z"
        }])

written_files = writer.close()
```

### Loader Integration
After writing the trend match files, the existing Snowflake
loader must be called to load them into RAW.LANDING_TREND_MATCHES.
The loader already handles this pattern for other dataset families.
Add 'trend_matches' as a new dataset_family in the loader config:

```python
# In loader config
DATASET_FAMILIES = {
    "raw_posts":          "RAW.LANDING_RAW_POSTS",
    "hydrated_posts":     "RAW.LANDING_HYDRATED_POSTS",
    "hydration_misses":   "RAW.LANDING_HYDRATION_MISSES",
    "actor_profiles":     "RAW.LANDING_ACTOR_PROFILES",
    "twitter_trends":     "RAW.LANDING_TWITTER_TRENDS",
    "trend_matches":      "RAW.LANDING_TREND_MATCHES",  # NEW
}
```

---

### What NOT to Change
- Do not change any matching logic in post_trend_matching.py
- Do not change FAISS index building or threshold values
- Do not change any other pipeline workers
- Do not change SQLite state store logic
- Only change schema references in loader files
- Only ADD the write-back — do not restructure matching code

---

### Files to Deliver
1. Updated snowflake_loader/config.py (or equivalent)
   - All PUBLIC → RAW schema references changed
2. Any other snowflake_loader/ files with PUBLIC references
   - Same change, nothing else
3. bluesky_pipeline/text_prep/trend_match_writer.py
   - New TrendMatchWriter class
   - Follows same pattern as existing batch writers
4. Updated bluesky_pipeline/text_prep/post_trend_matching.py
   - Write-back integration point added
   - trend_matches added as dataset family in loader config

---

### Testing
After changes, run the existing loader tests to confirm
nothing is broken:
```bash
pytest tests/test_snowflake_loader*.py -v
```

If tests reference PUBLIC schema in fixtures, update those
references to RAW as well.