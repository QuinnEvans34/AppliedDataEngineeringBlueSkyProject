# Phase 2: State Store and Batch Writer Implementation

## Purpose

This phase implements the two most important shared foundations in the project:

1. the real SQLite-backed state layer
2. the real local batch-file writer layer

Nothing in this phase should depend on fully implemented firehose decoding or hydration API logic yet.

The goal is to make the project capable of:
- creating and tracking runs
- tracking captured posts in SQLite
- claiming mature posts for hydration
- tracking batch files
- writing local `.jsonl.gz` output files safely
- rotating files by row count or elapsed time
- supporting clean reruns and restart recovery

This phase should leave the firehose and hydration business logic mostly unimplemented, but it should make the core plumbing real.

---

## Scope of this phase

### In scope
- implement `state/sqlite_store.py`
- finalize `state/schema.py` if needed
- implement `batching/writer.py`
- implement small supporting helpers if required
- make the state store and writer testable in isolation
- add focused tests or smoke scripts if useful

### Out of scope
- no firehose WebSocket decoding yet
- no CAR parsing yet
- no real hydration API calling yet
- no end-to-end 1M capture run yet
- no Snowflake work
- no uploader work

---

## Required outcomes

At the end of this phase, the project should be able to do all of the following:

### SQLite state layer
- create a capture run
- update capture run progress
- mark a capture run complete or failed
- create a hydrate run
- update hydrate run progress
- mark a hydrate run complete or failed
- insert captured post rows idempotently by `uri`
- track hydration state per post
- claim mature posts safely for hydration
- release expired claims
- mark hydration outcomes safely
- track batch file lifecycle in SQLite

### Batch writer layer
- buffer rows in memory
- write JSONL lines to gzip-compressed files
- rotate on row count or elapsed time
- use temp-file then finalize/rename semantics
- expose file metadata needed for SQLite tracking
- cleanly close files on shutdown

---

## SQLite design requirements

SQLite is the control plane for the pipeline.

It must be treated as the source of truth for:
- run lifecycle
- batch file lifecycle
- per-post lifecycle
- hydration claims
- hydration retry status

### General requirements
- use one SQLite database file under `data/state/`
- use `sqlite3` only
- enable foreign keys if they are used
- commit explicitly at logical boundaries
- prefer simple SQL over over-engineered abstractions
- keep code readable and easy to audit

---

## Tables and expectations

The schema from Phase 1 already exists.  
In this phase, Codex may refine it if needed, but it should not redesign the project.

### `capture_runs`
Tracks one firehose capture run.

Expected behavior:
- one row per run
- starts as active/running
- progress count updates over time
- ends in a terminal state

Expected statuses:
- `running`
- `completed`
- `failed`

### `hydrate_runs`
Tracks one hydration worker run.

Expected behavior:
- one row per run
- associated with a single capture run
- tracks total selected, hydrated, missing, failed counts
- ends in a terminal state

Expected statuses:
- `running`
- `completed`
- `failed`

### `batch_files`
Tracks each output file created by a writer.

Expected behavior:
- one row per physical file
- created when a writer opens a new file
- updated as rows are written
- marked closed/finalized when file is complete

Suggested statuses:
- `open`
- `closed`
- `failed`

### `captured_posts`
Tracks each captured post and its hydration lifecycle.

This table is critical.

Expected rules:
- `uri` is the primary key
- one row per unique captured post
- duplicate insert attempts should not create duplicate rows
- hydration state drives all later work

---

## Hydration state model

Use explicit states and keep them strict.

### Allowed values
- `pending`
- `claimed`
- `hydrated`
- `retryable`
- `missing`
- `failed`

### State meanings

#### `pending`
Fresh captured post.  
Not yet claimed and not yet hydrated.

#### `claimed`
A hydrator worker has selected this row and is actively processing it.

#### `hydrated`
A terminal success state.  
The hydrated dataset row was written successfully.

#### `retryable`
A temporary failure occurred and the row can be retried later.

#### `missing`
A terminal state for posts that repeatedly do not return from hydration.

#### `failed`
A terminal state for unrecoverable repeated errors.

---

## State transition rules

These transitions should be enforced by store methods.

### Valid transitions

- `pending -> claimed`
- `claimed -> hydrated`
- `claimed -> retryable`
- `claimed -> missing`
- `claimed -> failed`
- `retryable -> claimed`

### Recovery transition
- `claimed -> pending` only when claim expiration recovery is being performed

### Invalid transitions
Do not allow random direct transitions such as:
- `pending -> hydrated`
- `hydrated -> pending`
- `missing -> claimed`
- `failed -> claimed`

If strict enforcement is too heavy for this phase, then at minimum the store methods must only perform valid transitions by design.

---

## Claiming model

The hydration job will need safe row claiming.

### Claim requirements
- only mature rows can be claimed
- only rows in `pending` or `retryable` can be claimed
- claims must mark:
  - `hydration_status = claimed`
  - `claimed_by_worker`
  - `claim_expires_at`
  - `last_hydration_attempt_at`
  - increment `hydration_attempt_count`

### Claim expiration
A claimed row may be abandoned if a worker dies.

The store must support reclaiming expired claims:
- expired `claimed` rows can be reset to `pending`
- this should happen through a dedicated recovery method

### Claim batch behavior
The store should support:
- selecting up to `N` mature rows
- marking them claimed atomically enough for a single-worker design
- returning the claimed rows to the caller

This project is not currently targeting distributed multi-node coordination, so keep the design simple and readable.

---

## Maturity rule

Hydration maturity must be based on:

- `captured_at <= now - maturity_window`

Do **not** base eligibility on `record_created_at`.

`captured_at` is the scheduler clock.

---

## Duplicate handling

### Capture duplicate rule
`uri` is the dedupe key.

If the same `uri` is seen again:
- do not create a second row
- do not count it again toward the capture goal

The store should expose insert behavior that returns whether the row was newly inserted or already existed.

### Hydration duplicate rule
If a row is already terminal:
- do not claim it again
- do not write another hydrated row for it unless manually reset outside the normal flow

---

## SQLiteStore methods to implement

Codex should implement real methods in `state/sqlite_store.py`.

The exact method names can vary slightly, but the responsibilities below must exist.

### Run lifecycle methods

#### Capture run methods
- `create_capture_run(...)`
- `update_capture_run_progress(...)`
- `complete_capture_run(...)`
- `fail_capture_run(...)`
- `get_capture_run(...)`

#### Hydrate run methods
- `create_hydrate_run(...)`
- `update_hydrate_run_progress(...)`
- `complete_hydrate_run(...)`
- `fail_hydrate_run(...)`
- `get_hydrate_run(...)`

### Batch file methods
- `create_batch_file(...)`
- `update_batch_file_progress(...)`
- `close_batch_file(...)`
- `fail_batch_file(...)`
- `get_batch_file(...)`

### Captured post methods
- `insert_captured_post(...)`
- `get_captured_post(...)`
- `count_captured_posts_for_run(...)`
- `count_pending_mature_posts(...)`

### Claiming / hydration methods
- `claim_mature_posts(...)`
- `release_expired_claims(...)`
- `mark_posts_hydrated(...)`
- `mark_posts_retryable(...)`
- `mark_posts_missing(...)`
- `mark_posts_failed(...)`

The implementation should prioritize correctness and simplicity.

---

## Insert contract for captured posts

`insert_captured_post(...)` should support idempotent insert behavior.

### Expected inputs
At minimum:
- `uri`
- `capture_run_id`
- `repo_did`
- `rkey`
- `cid_at_capture`
- `seq`
- `record_created_at`
- `captured_at`
- `capture_file_id`

### Expected behavior
- insert the row if `uri` does not already exist
- initialize hydration state to `pending`
- return a boolean or result object indicating whether the insert was new

This method is important because it controls the unique post count.

---

## Batch writer implementation requirements

Implement the writer for real in `batching/writer.py`.

The writer should be generic enough to handle:
- raw post files
- hydrated post files
- hydration miss files

### Required behavior
- accept output directory
- accept file prefix
- accept flush row threshold
- accept flush time threshold
- buffer JSON-serializable rows
- write `.jsonl.gz`
- write one JSON object per line
- use UTF-8
- use temp file names while open
- finalize to a real `.jsonl.gz` file on rotate/close
- expose row count and file path metadata

### Rotation rules
Rotate when either:
- row count threshold reached
- elapsed time threshold reached

Recommended defaults:
- 10,000 rows
- 60 seconds

### File naming
Keep names simple and sortable.

Suggested pattern:
- `raw_posts_000001.jsonl.gz`
- `raw_posts_000002.jsonl.gz`
- `hydrated_posts_000001.jsonl.gz`

Temp files can use a suffix such as:
- `.tmp`

---

## Writer lifecycle expectations

### Open
When a writer opens a new file:
- create the temp file
- initialize gzip stream
- initialize counters
- record file-open metadata if integrated with SQLite later

### Append
When rows are appended:
- serialize each row to compact JSON
- write one line per row
- update in-memory counters

### Rotate
When thresholds are hit:
- flush gzip stream
- close file
- rename temp file to final file
- return metadata needed by the caller
- immediately open the next temp file

### Close
On explicit shutdown:
- finalize current open file if it has rows
- if current file has zero rows, it may be discarded cleanly

---

## Atomicity expectations

Full perfect atomicity is not required, but the design must be safe enough for local pipeline usage.

### Minimum required behavior
- never write directly to the final file name while the file is still open
- always close the gzip stream before final rename
- avoid leaving half-written final `.jsonl.gz` files
- keep file metadata available for SQLite updates after finalize

This phase should produce sane local durability behavior.

---

## Interaction between writer and SQLite

The writer does not need to write directly to SQLite by itself.

Instead, the higher-level job runner can do this flow:
1. create a batch file row in SQLite
2. writer opens temp file
3. rows are appended
4. writer finalizes file
5. caller updates SQLite with final path, row count, byte size, closed status

That separation is preferred.

Do not tightly couple the writer to the database in this phase unless there is a very strong reason.

---

## Error handling requirements

### SQLite layer
- raise clear exceptions for invalid operations
- keep transaction boundaries understandable
- do not swallow database errors silently

### Writer layer
- surface I/O failures clearly
- ensure `close()` attempts clean shutdown behavior
- do not leave corrupted final files silently

---

## Testing expectations

This phase should include practical validation.

At minimum, Codex should validate:

### SQLite
- schema bootstrap works
- capture run creation works
- hydrate run creation works
- captured post insert is idempotent by `uri`
- mature-row claim works
- expired-claim release works
- terminal hydration marking works

### Writer
- rows are written as valid gzip JSONL
- rotation works by row count
- rotation works by elapsed time
- final file names are correct
- empty temp files do not become junk output unless intended

Formal test framework is optional for this phase, but some kind of reproducible validation should exist.

---

## What not to do in this phase

Codex should not:
- build real firehose message parsing yet
- build real API hydration yet
- add end-to-end orchestration
- redesign the project structure
- add premature abstraction layers
- build a queue system
- introduce Postgres
- introduce cloud upload logic

This phase is shared plumbing only.

---

## Deliverables for this phase

At the end of this prompt, Codex should provide:

1. implemented `state/sqlite_store.py`
2. refined `state/schema.py` only if needed
3. implemented `batching/writer.py`
4. any minimal helper changes required to support them
5. a short summary of:
   - what methods were implemented
   - what assumptions were made
   - what still remains before Phase 3

---

## Definition of done

Phase 2 is complete when:
- SQLite store methods are real and usable
- writer is real and rotates files safely
- captured post dedupe is enforced by `uri`
- mature hydration claiming works
- claim recovery works
- output files are valid `.jsonl.gz`
- firehose and hydrator still remain separate entrypoints
- the project is ready for Phase 3 firehose ingestion logic