Use this as the **first MD file**.

Suggested filename: `docs/00_project_blueprint.md`

````md
# Bluesky Pipeline Project Blueprint

## Purpose

This project builds the **Python-side data pipeline only** for collecting and later hydrating Bluesky posts.

The system has two separate jobs:

1. **Firehose capture job**
   - Connect to the AT Protocol firehose
   - Decode incoming events
   - Keep only `app.bsky.feed.post` **create** events
   - Normalize them into a stable raw-post schema
   - Write them to local compressed `.jsonl.gz` files
   - Track job and post state in SQLite
   - Stop when **1,000,000 unique posts** have been captured

2. **Hydration job**
   - Read previously captured posts from SQLite
   - Wait until each post is at least **24 hours old based on `captured_at`**
   - Call Bluesky `getPosts` using the saved AT-URIs
   - Normalize hydrated post views and interaction counts
   - Write them to separate local compressed `.jsonl.gz` files
   - Mark hydration state in SQLite so reruns are safe

This repo should stop at producing clean local batch files.  
Snowflake loading, SQL transformations, joins, feature engineering, and modeling happen later outside this Python project.

---

## Core design decisions

### Included
- Public Bluesky firehose ingestion
- Post-create filtering only
- Local file output only
- SQLite for lightweight state and coordination
- Separate raw and hydrated datasets
- Per-post maturity-based hydration
- Full-language capture, no language filtering
- Safe reruns and restart tolerance
- Logging, retry, and progress tracking

### Excluded
- No Snowflake SQL
- No warehouse transforms
- No model training
- No authenticated posting / liking / account actions
- No Postgres
- No Jetstream implementation
- No deployment packaging beyond a normal Python project structure

---

## High-level system behavior

### Firehose job
The firehose job runs until it captures **1,000,000 unique post-create events**.

Processing flow:

1. Open WebSocket connection to the Bluesky firehose
2. Read frames continuously
3. Decode firehose messages
4. Ignore non-commit events
5. Scan commit operations
6. Keep only:
   - `action = create`
   - collection = `app.bsky.feed.post`
7. Extract the post record from the CAR blocks
8. Normalize the record into the raw output schema
9. Insert/update state in SQLite
10. Append rows to rolling compressed local files
11. Stop after 1,000,000 unique post URIs

### Hydration job
The hydration job runs independently and works off SQLite state.

Processing flow:

1. Query SQLite for captured posts that:
   - have not been hydrated
   - are at least 24 hours old based on `captured_at`
2. Claim a batch of eligible URIs
3. Request hydrated post views from `getPosts`
4. Normalize returned post views
5. Write hydrated rows to separate compressed local files
6. Mark each post as hydrated, retryable, failed, or missing
7. Continue until no eligible work remains

The hydrator should be built as a polling worker, not a one-time giant batch process.

---

## Data model overview

### Dataset A: raw captured posts
Stored locally in a raw dataset folder.

Each row represents one normalized post-create event from the firehose.

Top-level fields should include:
- `capture_run_id`
- `seq`
- `repo_did`
- `event_time`
- `operation`
- `collection`
- `rkey`
- `uri`
- `cid`
- `record_created_at`
- `has_reply`
- `has_embed`
- `captured_at`
- `record`

`record` should preserve the original post record as much as possible, including optional fields when present.

### Dataset B: hydrated post views
Stored locally in a separate hydrated dataset folder.

Each row represents one hydrated post lookup result.

Top-level fields should include:
- `hydrate_run_id`
- `capture_run_id`
- `uri`
- `cid`
- `indexed_at`
- `author_did`
- `author_handle`
- `author_display_name`
- `reply_count`
- `repost_count`
- `like_count`
- `quote_count`
- `labels`
- `hydrated_at`
- `record`

### Dataset C: hydration misses
Optional but recommended.

This dataset stores posts that were eligible for hydration but were not returned or could not be resolved cleanly after retries.

This is for audit/debugging, not for the main warehouse join.

---

## Join key expectations

The Python jobs do not perform the final join, but they must preserve the fields needed for it.

### Primary join key
- `uri`

### Secondary validation key
- `cid`

The warehouse join later should be based on `uri`.

---

## Local output layout

The project should write to local folders only.

Recommended layout:

```text
data/
  raw_posts/
    <capture_run_id>/
      raw_posts_000001.jsonl.gz
      raw_posts_000002.jsonl.gz

  hydrated_posts/
    <hydrate_run_id>/
      hydrated_posts_000001.jsonl.gz
      hydrated_posts_000002.jsonl.gz

  hydration_misses/
    <hydrate_run_id>/
      hydration_misses_000001.jsonl.gz

  logs/
    firehose.log
    hydrate.log

  state/
    pipeline_state.db
````

All datasets must remain separate.

---

## SQLite is the control plane

SQLite is not just for counters.
It is the source of truth for run state, file state, captured post state, and hydration coordination.

### Required tables

#### `capture_runs`

Tracks a firehose capture run.

Suggested fields:

* `capture_run_id`
* `started_at`
* `completed_at`
* `status`
* `target_post_count`
* `written_post_count`
* `last_seq_seen`
* `notes`

#### `hydrate_runs`

Tracks a hydration run.

Suggested fields:

* `hydrate_run_id`
* `capture_run_id`
* `started_at`
* `completed_at`
* `status`
* `eligible_post_count`
* `hydrated_post_count`
* `missing_post_count`
* `failed_post_count`

#### `batch_files`

Tracks every local output file.

Suggested fields:

* `file_id`
* `job_type`
* `run_id`
* `dataset_type`
* `local_path`
* `row_count`
* `byte_size`
* `status`
* `created_at`
* `closed_at`

#### `captured_posts`

Tracks per-post lifecycle state.

Suggested fields:

* `uri` primary key
* `capture_run_id`
* `repo_did`
* `rkey`
* `cid_at_capture`
* `seq`
* `record_created_at`
* `captured_at`
* `capture_file_id`
* `hydration_status`
* `hydration_attempt_count`
* `last_hydration_attempt_at`
* `hydrated_at`
* `hydrate_run_id`
* `last_error`
* `claimed_by_worker`
* `claim_expires_at`

---

## Hydration status model

The hydrator should use explicit states.

Recommended states:

* `pending`
* `claimed`
* `hydrated`
* `retryable`
* `missing`
* `failed`

Recommended behavior:

* fresh captured post starts as `pending`
* worker claims mature rows as `claimed`
* successful hydration becomes `hydrated`
* temporary failures become `retryable`
* repeated unresolved misses become `missing`
* unrecoverable repeated errors become `failed`

---

## Repository structure to build first

This project should be created as a small service-style Python repo.

Recommended structure:

```text
bluesky_pipeline/
  config.py
  main_firehose.py
  main_hydrate.py
  models.py
  logging_config.py

  firehose/
    client.py
    decoder.py
    extractor.py
    normalizer.py

  hydrate/
    client.py
    selector.py
    normalizer.py

  batching/
    writer.py

  state/
    sqlite_store.py
    schema.py

  utils/
    time_utils.py
    retry.py
    gzip_jsonl.py
    ids.py

  data/
    raw_posts/
    hydrated_posts/
    hydration_misses/
    logs/
    state/

  docs/
    00_project_blueprint.md
```

Folder names can vary slightly, but the separation of responsibility should remain the same.

---

## Module responsibilities

### `config.py`

Centralized configuration for:

* local paths
* batch size
* flush intervals
* API settings
* retry settings
* concurrency limits
* target capture count

### `main_firehose.py`

Entry point for:

* starting a capture run
* connecting to the firehose
* processing incoming messages
* writing raw batches
* updating SQLite state
* stopping at 1,000,000 unique posts

### `main_hydrate.py`

Entry point for:

* starting a hydration run
* polling for mature pending posts
* claiming rows safely
* requesting hydration batches
* writing hydrated batches
* updating SQLite state

### `firehose/client.py`

Responsible for:

* WebSocket connection
* reconnect logic
* raw frame streaming

### `firehose/decoder.py`

Responsible for:

* decoding firehose frames
* identifying event types
* passing structured commit events forward

### `firehose/extractor.py`

Responsible for:

* scanning commit ops
* filtering for post-create operations
* decoding records from CAR blocks
* extracting post payloads

### `firehose/normalizer.py`

Responsible for:

* converting extracted post data into the raw output schema
* promoting convenience fields

### `hydrate/client.py`

Responsible for:

* calling `getPosts`
* batching URIs into API-sized requests
* retry/backoff handling
* partial-failure handling

### `hydrate/selector.py`

Responsible for:

* querying mature posts
* claiming rows atomically
* returning work batches
* releasing or finalizing claims

### `hydrate/normalizer.py`

Responsible for:

* converting hydrated post views into the hydrated output schema
* generating miss/error rows where needed

### `batching/writer.py`

Responsible for:

* buffering rows
* rotating files by row count or time
* writing `.jsonl.gz`
* clean close/finalize behavior

### `state/sqlite_store.py`

Responsible for:

* all SQLite read/write operations
* run creation
* file tracking
* per-post state transitions
* claim/retry logic

### `state/schema.py`

Responsible for:

* creating database tables
* ensuring schema exists on startup

### `utils/`

Shared helpers only.
Keep this small and practical.

---

## File writing rules

All writers should follow safe local-file semantics.

### Rules

* Write JSONL
* Compress with gzip
* One JSON object per line
* Use temp-file then finalize/rename flow
* Track files in SQLite
* Keep raw and hydrated outputs separate

### Rotation defaults

Recommended defaults:

* flush every **10,000 rows**
* or every **60 seconds**
* whichever happens first

---

## Deduplication rules

Deduplication should happen at the captured post level.

### Capture dedupe key

* primary key: `uri`

Rules:

* only count unique `uri` values toward the 1,000,000 target
* skip duplicate firehose posts if the same `uri` is seen again
* do not rely on sequence number alone for uniqueness

### Hydration dedupe

* only select rows in non-terminal states
* do not re-hydrate rows already marked terminal unless explicitly reset

---

## Runtime model

The two jobs must remain separate.

### Firehose process

* one process
* one run
* exits after 1,000,000 unique posts

### Hydration process

* separate process
* polling worker
* can run independently
* keeps checking for newly mature posts
* exits when no work remains, or optionally continues polling if configured

Do not tightly couple the hydrator into the firehose runtime.

---

## Logging requirements

### Firehose logs should include

* total frames received
* commit events received
* commit ops scanned
* post-create ops matched
* decode failures
* duplicate URIs skipped
* unique rows written
* rows per second
* estimated progress toward 1,000,000

### Hydration logs should include

* mature pending rows found
* URI batches sent
* request success/failure counts
* returned post count
* missing post count
* retry count
* 429 count
* 5xx count
* hydrated rows written

---

## Reliability requirements

### Firehose job must support

* reconnect logic
* decode error tolerance
* safe shutdown
* progress persistence
* restart without corrupting output

### Hydration job must support

* retries with backoff
* partial-failure handling
* safe reruns
* claim expiration / recovery
* idempotent state transitions

---

## Implementation phases

This repo should be built in phases.

### Phase 1

Create project structure and scaffolding:

* folders
* entrypoints
* config
* logging setup
* SQLite schema
* writer abstractions

### Phase 2

Implement state and file plumbing:

* run tracking
* batch file tracking
* captured post lifecycle table
* local gzip JSONL writing

### Phase 3

Implement firehose ingestion:

* WebSocket client
* decode
* extraction
* normalization
* dedupe
* raw writing

### Phase 4

Implement hydrator core:

* mature-row selection
* URI claiming
* `getPosts` client
* normalization
* hydrated writing

### Phase 5

Implement reliability behavior:

* retries
* claim recovery
* partial-failure handling
* restart safety
* progress metrics

### Phase 6

Run smaller validation tests before full-scale run:

* sample capture
* sample hydration
* file output validation
* SQLite validation

### Phase 7

Run full capture:

* 1,000,000 unique posts
* hydration on mature posts
* final local datasets ready for Snowflake staging

---

## Success criteria

### Firehose job success

* captures exactly 1,000,000 unique post-create rows
* writes valid local `.jsonl.gz` raw files
* stores state safely in SQLite
* survives restart without corrupting output

### Hydration job success

* hydrates mature captured posts based on `captured_at`
* writes valid local `.jsonl.gz` hydrated files
* preserves `uri` as the join key
* marks statuses safely so reruns do not duplicate work

---

## What Codex should not do yet

At this stage, Codex should **not**:

* implement Snowflake SQL
* add model training code
* add unrelated feature engineering
* build a deployment stack
* add authentication/posting/liking code
* over-engineer beyond the structure and contracts above

The first goal is to create the correct repo structure and clean scaffolding that matches this blueprint.

````

