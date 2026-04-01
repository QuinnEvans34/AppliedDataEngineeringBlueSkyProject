# Phase 3: Firehose Ingestion Implementation

## Purpose

This phase implements the real Bluesky firehose ingestion path for raw post capture.

By the end of this phase, the project should be able to:

- connect to the Bluesky relay firehose
- consume firehose frames continuously
- decode firehose events
- keep only `app.bsky.feed.post` **create** operations
- extract the post record from commit/CAR data
- normalize each matching post into the raw output schema
- insert each post idempotently into SQLite using `uri` as the dedupe key
- write normalized rows into rotating local `.jsonl.gz` raw-post files
- stop when exactly **1,000,000 unique posts** have been captured

This phase is about **raw capture only**.

Do not implement real hydration API logic in this phase.

---

## Scope of this phase

### In scope
- implement the real firehose client
- implement real firehose frame decoding
- implement commit/op filtering
- implement extraction of post-create records from commit data
- implement raw-post normalization
- wire `main_firehose.py` into a working capture loop
- integrate with the existing SQLite store
- integrate with the existing rotating batch writer
- add reconnect logic, progress logging, and safe shutdown behavior

### Out of scope
- no real hydration API calling yet
- no hydrate worker orchestration yet
- no Snowflake work
- no uploader work
- no model logic
- no authenticated Bluesky actions

---

## End state for this phase

At the end of Phase 3, `main_firehose.py` should be able to run a real capture job that:

1. starts a capture run in SQLite
2. opens the firehose connection
3. processes incoming firehose events continuously
4. extracts unique post-create records
5. writes normalized raw rows to local gzip JSONL files
6. updates SQLite state as posts are captured
7. logs progress continuously
8. exits cleanly after 1,000,000 unique captured posts

---

## Firehose target

Use the Bluesky relay firehose for:

- `com.atproto.sync.subscribeRepos`

This phase should use the relay-based firehose endpoint already chosen in the project design.

The firehose consumer must be built to handle long-running streaming behavior and reconnect safely.

---

## High-level event flow

The firehose pipeline must follow this structure:

1. receive raw WebSocket frame
2. decode frame into structured firehose event
3. ignore non-commit events
4. inspect commit operations
5. keep only:
   - `action = create`
   - collection/path = `app.bsky.feed.post`
6. extract the actual post record from the commit/CAR data
7. build the stable normalized raw row
8. insert into SQLite using `uri` as the dedupe key
9. if the row is new:
   - append it to the raw writer
   - count it toward the capture target
10. if duplicate:
   - skip writing
   - log or count duplicate occurrence
11. continue until target reached

---

## Modules to implement in this phase

This phase should make these modules real:

### `firehose/client.py`
Responsible for:
- establishing the WebSocket connection
- reconnecting on disconnect/failure
- yielding raw frames/events to the caller
- applying retry/backoff behavior

### `firehose/decoder.py`
Responsible for:
- decoding firehose frames into structured event payloads
- separating commit events from non-commit events
- exposing a clear decoded-event contract to the extractor

### `firehose/extractor.py`
Responsible for:
- scanning commit operations
- identifying `app.bsky.feed.post` create operations
- decoding commit/CAR record content
- returning extracted post payloads in a clean intermediate structure

### `firehose/normalizer.py`
Responsible for:
- converting extracted post payloads into the stable raw output schema
- promoting convenience fields
- tolerating optional/missing fields

### `main_firehose.py`
Responsible for:
- orchestration only
- opening SQLite store and writer
- starting the capture run
- driving the firehose loop
- inserting captured posts
- updating progress
- stopping at exactly 1,000,000 unique posts
- closing/finalizing everything cleanly

---

## Firehose module contracts

The exact class/function names can vary, but the responsibilities below should exist.

### `firehose/client.py`
Should expose a simple interface for:
- opening a stream connection
- iterating raw firehose frames
- reconnecting with bounded retry/backoff

The rest of the project should not have to know WebSocket connection details.

### `firehose/decoder.py`
Should expose a simple interface that takes a raw firehose frame and returns a structured decoded event, such as:
- event type / kind
- sequence number if present
- timestamp if present
- commit metadata if present

If a frame cannot be decoded:
- log/count the error
- skip it
- continue processing

The decoder should not decide whether the event is a target post.

### `firehose/extractor.py`
Should accept decoded commit events and return zero or more extracted post-create objects.

It must:
- iterate commit ops
- ignore non-create operations
- ignore non-post collections
- decode the referenced record from the commit payload/CAR data
- return only valid `app.bsky.feed.post` create records

The extractor should be where repo DID, rkey, uri, cid, and record payload are assembled into a usable structure.

### `firehose/normalizer.py`
Should convert extracted post-create objects into the raw-row schema.

The normalizer must produce rows containing at least:

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

It should preserve the original `record` object as much as possible.

---

## Raw output schema requirements

The normalized raw row written to the raw dataset should look like this shape:

```json
{
  "capture_run_id": "cap_20260401_100000",
  "seq": 123456789,
  "repo_did": "did:plc:exampledid",
  "event_time": "2026-04-01T18:00:00Z",
  "operation": "create",
  "collection": "app.bsky.feed.post",
  "rkey": "3ltpostkey",
  "uri": "at://did:plc:exampledid/app.bsky.feed.post/3ltpostkey",
  "cid": "bafy...",
  "record_created_at": "2026-04-01T17:59:55Z",
  "has_reply": false,
  "has_embed": false,
  "captured_at": "2026-04-01T18:00:02Z",
  "record": {
    "$type": "app.bsky.feed.post",
    "text": "Example post text",
    "createdAt": "2026-04-01T17:59:55Z",
    "langs": ["en"],
    "facets": [],
    "reply": null,
    "embed": null,
    "labels": null,
    "tags": ["ai", "ml"]
  }
}



Notes
record should preserve optional fields when present
record_created_at should be promoted to the top level
has_reply and has_embed should be cheap promoted convenience booleans
captured_at should be generated by this system at normalization time
use consistent snake_case at the top level
Dedupe and counting rules
Primary dedupe key
uri
Required behavior
every extracted row must be inserted into SQLite through the idempotent insert_captured_post(...) path
only rows newly inserted by uri count toward the 1,000,000 target
duplicate uri rows must not be written again to the raw dataset
duplicate uri rows must not increment run progress
This rule is mandatory.
Do not count raw firehose matches directly.
Count only successful new inserts.
Stop condition
The firehose job must stop when:
exactly 1,000,000 unique posts have been captured for the run
That means:
progress is based on SQLite-confirmed unique inserts
the loop should stop promptly once the target is hit
the writer must finalize any buffered rows before exit
the capture run must be marked completed in SQLite
Integration with SQLite
This phase must fully use the Phase 2 state layer.
Capture run lifecycle
The firehose entrypoint should:
create a capture run on startup
update run progress periodically
mark run completed on clean success
mark run failed on fatal error
Captured post insertion
For each normalized row:
create the post metadata payload needed by insert_captured_post(...)
insert idempotently
if inserted:
append raw row to writer
increment counters
if duplicate:
skip writer append
Batch file tracking
The firehose entrypoint should integrate finalized writer output with SQLite batch_files tracking.
Recommended pattern:
create/open batch tracking row when a new writer file is opened if practical
finalize the file through writer
update SQLite with final path, row count, byte size, close status
If the current writer design is caller-driven, keep it simple and update SQLite when files finalize.
Progress logging requirements
The firehose job should log useful operational counters.
Required metrics:
total raw frames received
total decoded events
total commit events
total commit ops scanned
total post-create matches
total duplicates skipped
total unique posts written
current rows/sec
target remaining / percent complete
These do not need to be fancy, but they must exist.
Error handling requirements
Decode errors
If a frame cannot be decoded:
log the failure
increment a decode error counter
continue
Extract errors
If a commit event is malformed or record extraction fails:
log the failure
continue unless the failure is fatal to the whole process
Connection loss
If the WebSocket disconnects:
reconnect with backoff
continue processing
do not lose already written state
Writer or SQLite errors
If the writer or SQLite fails in a way that makes safe progress impossible:
shut down cleanly
finalize what can be finalized
mark the run failed
Reconnect behavior
The firehose client must support reconnect behavior.
Required behavior
detect disconnects/errors
retry connection with backoff
keep the implementation simple and readable
avoid hot-loop reconnect spam
Perfect exactly-once resume across disconnect boundaries is not required in this phase, because dedupe by uri will protect the output dataset.
That said, the implementation should not be sloppy.
Safe shutdown behavior
The firehose job should support clean shutdown on:
keyboard interrupt
normal target completion
fatal exception
On shutdown:
flush/finalize the writer
update any outstanding batch file state
update run status in SQLite
release resources cleanly
Firehose configuration expectations
This phase should wire config.py into real firehose capture settings.
At minimum, configuration should support:
firehose endpoint
target unique post count
reconnect backoff settings
raw output directory
writer row threshold
writer time threshold
progress log interval
If config fields are missing, Codex may add them cleanly.
Intermediate extracted-post contract
Before normalization, it is useful to have a clean extracted-post structure.
Codex may define a dataclass or typed dictionary for an extracted post that includes:
seq
repo_did
event_time
operation
collection
rkey
uri
cid
record
This is recommended because it keeps decoder/extractor/normalizer boundaries clean.
Validation requirements for this phase
Codex should validate the firehose implementation in practical ways.
Minimum validation
modules import correctly
main_firehose.py runs without syntax/runtime bootstrap errors
the firehose pipeline can process at least a small real sample or a realistic mocked sample
duplicates by uri are skipped correctly
raw rows written match the intended schema
writer rotation still works under real capture integration
progress updates hit SQLite correctly
Preferred validation
If practical, run a small capture test such as:
capture first few hundred or first few thousand unique posts
verify local raw files exist
verify SQLite post count matches file row count
verify duplicate count is non-negative and sensible
verify clean shutdown works
Do not attempt the full 1,000,000 capture yet unless explicitly requested after this phase.
What Codex should not do in this phase
Codex should not:
implement the hydrator API logic
implement getPosts
build end-to-end 24h hydration orchestration
add uploader/cloud logic
redesign the schema/state model
overbuild abstractions that are not necessary
This phase is only about making raw firehose capture real.
Deliverables for this phase
At the end of this phase, Codex should provide:
implemented firehose modules:
firehose/client.py
firehose/decoder.py
firehose/extractor.py
firehose/normalizer.py
updated main_firehose.py wired into the real ingestion loop
any minimal supporting changes to config/models needed for clean implementation
practical validation results
a short summary of:
what was implemented
what assumptions were made
what remains before Phase 4
Definition of done
Phase 3 is complete when:
the firehose job can run a real capture loop
only app.bsky.feed.post create records are kept
raw rows are normalized correctly
dedupe by uri is enforced through SQLite
raw rows are written to rotating local .jsonl.gz files
progress is tracked in SQLite
the process can reconnect and continue safely
the project is ready for Phase 4 hydration implementation