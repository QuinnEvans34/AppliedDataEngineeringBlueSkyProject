# Phase 4: Hydration Implementation

## Purpose

This phase implements the real hydration pipeline for previously captured Bluesky posts.

By the end of this phase, the project should be able to:

- read mature captured posts from SQLite
- claim them safely for processing
- batch AT-URIs into valid `getPosts` API requests
- call the public Bluesky AppView hydration endpoint
- normalize returned post views into the hydrated output schema
- write hydrated rows into rotating local `.jsonl.gz` files
- write optional miss rows for unresolved posts
- update per-post hydration state in SQLite
- run as a polling worker until no eligible work remains

This phase is about **hydration only**.

Do not redesign firehose ingestion in this phase.

---

## Scope of this phase

### In scope
- implement the real hydration API client
- implement mature-row selection and claiming integration
- implement hydrated-row normalization
- implement miss-row normalization
- wire `main_hydrate.py` into a working polling hydration loop
- integrate with the existing SQLite store
- integrate with the existing rotating batch writer
- add retry/backoff, progress logging, and clean shutdown behavior

### Out of scope
- no changes to Snowflake logic
- no uploader work
- no model logic
- no authenticated Bluesky actions
- no redesign of capture schema/state model
- no firehose redesign except small compatibility fixes if truly necessary

---

## End state for this phase

At the end of Phase 4, `main_hydrate.py` should be able to run a real hydration job that:

1. starts a hydrate run in SQLite
2. polls SQLite for mature captured posts
3. claims eligible rows safely
4. requests post views from `getPosts`
5. normalizes returned hydrated rows
6. writes hydrated rows to local gzip JSONL files
7. writes miss rows when needed
8. updates SQLite hydration states correctly
9. logs progress continuously
10. exits cleanly when no eligible work remains, or continues polling if configured

---

## Hydration target

Use the public Bluesky AppView endpoint for:

- `app.bsky.feed.getPosts`

This phase should use the public read-only endpoint already chosen in the project design.

The hydrator must be built around the API contract that `getPosts` accepts only a limited number of URIs per request.

### Required request limit
- maximum **25 URIs per request**

This limit must be respected by the implementation.

---

## High-level hydration flow

The hydration pipeline must follow this structure:

1. poll SQLite for mature rows:
   - `captured_at <= now - maturity_window`
   - `hydration_status IN ('pending', 'retryable')`
2. claim a batch of rows
3. split claimed rows into request chunks of at most 25 URIs
4. call `getPosts`
5. match returned post views back to requested URIs
6. normalize returned rows into hydrated output schema
7. write hydrated rows to the hydrated dataset
8. identify requested URIs not returned by the API
9. mark those as retryable or missing based on retry policy
10. continue until the queue is empty or polling is configured to continue

---

## Modules to implement in this phase

This phase should make these modules real:

### `hydrate/client.py`
Responsible for:
- building `getPosts` requests
- enforcing max 25 URIs per request
- executing public API calls
- handling retries and backoff
- surfacing structured hydration results

### `hydrate/selector.py`
Responsible for:
- polling SQLite for mature rows
- claiming rows safely through the store
- releasing expired claims when appropriate
- exposing clean work units to the caller

### `hydrate/normalizer.py`
Responsible for:
- converting hydrated post views into the stable hydrated output schema
- converting unresolved requested URIs into miss-row schema
- tolerating optional/missing fields

### `main_hydrate.py`
Responsible for:
- orchestration only
- opening SQLite store and writers
- starting the hydrate run
- polling mature rows
- calling the hydration client
- writing hydrated rows and miss rows
- updating SQLite state
- exiting or sleeping based on worker mode

---

## Hydration module contracts

The exact class/function names can vary, but the responsibilities below must exist.

### `hydrate/client.py`
Should expose a simple interface for:
- accepting a list of requested URIs
- chunking them into batches of at most 25
- calling the public `getPosts` endpoint
- returning structured results for:
  - returned hydrated posts
  - requested URIs not returned
  - request-level errors

The rest of the project should not have to know raw HTTP details.

### `hydrate/selector.py`
Should expose a simple interface for:
- releasing expired claims
- claiming mature posts for the current worker
- returning enough metadata for later state updates

The selector should use the existing SQLite store methods rather than bypassing them.

### `hydrate/normalizer.py`
Should expose normalization logic for two outputs:

#### hydrated row
Converts a returned post view into the final hydrated dataset schema.

#### miss row
Converts a requested-but-not-returned post into an audit/debug row.

---

## Hydrated output schema requirements

The normalized hydrated row written to the hydrated dataset should look like this shape:

```json
{
  "hydrate_run_id": "hyd_20260402_180000",
  "capture_run_id": "cap_20260401_100000",
  "uri": "at://did:plc:exampledid/app.bsky.feed.post/3ltpostkey",
  "cid": "bafy...",
  "indexed_at": "2026-04-02T18:15:00Z",
  "author_did": "did:plc:exampledid",
  "author_handle": "example.bsky.social",
  "author_display_name": "Example User",
  "reply_count": 12,
  "repost_count": 5,
  "like_count": 87,
  "quote_count": 3,
  "labels": [],
  "hydrated_at": "2026-04-02T18:15:10Z",
  "record": {
    "$type": "app.bsky.feed.post",
    "text": "Example post text",
    "createdAt": "2026-04-01T17:59:55Z",
    "langs": ["en"],
    "facets": [],
    "reply": null,
    "embed": null,
    "tags": ["ai", "ml"]
  }
}


Notes
keep top-level fields in snake_case
preserve record if present in the hydrated response
preserve uri as the primary join key
preserve cid as secondary validation
preserve author metadata
interaction counts are required fields in the hydrated row contract when available
Hydration miss schema requirements
Miss rows are optional but strongly recommended.
The miss dataset should track requested URIs that were not returned or could not be resolved cleanly.
Suggested shape:
{
  "hydrate_run_id": "hyd_20260402_180000",
  "capture_run_id": "cap_20260401_100000",
  "uri": "at://did:plc:exampledid/app.bsky.feed.post/3ltpostkey",
  "cid_at_capture": "bafy...",
  "captured_at": "2026-04-01T18:00:02Z",
  "status": "missing",
  "reason": "not_returned_by_getPosts",
  "checked_at": "2026-04-02T18:15:10Z",
  "attempt_count": 3
}
This dataset is for debugging and auditability, not for the main Snowflake join.
Integration with SQLite
This phase must fully use the Phase 2 state layer.
Hydrate run lifecycle
The hydrator entrypoint should:
create a hydrate run on startup
update run progress periodically
mark run completed on clean success
mark run failed on fatal error
Claiming and selection
The hydrator should:
optionally release expired claims
claim mature rows for this worker
process only rows that were successfully claimed
Post outcome updates
After each request batch:
returned rows written successfully -> mark hydrated
temporary request or processing failures -> mark retryable
repeated unresolved rows beyond retry threshold -> mark missing
unrecoverable repeated errors -> mark failed
Batch file tracking
The hydrator entrypoint should integrate finalized writer output with SQLite batch_files tracking for:
hydrated output files
miss output files, if used
Retry and status policy
This phase must define and implement a concrete retry policy.
Recommended policy
Request-level failures
Examples:
network failure
timeout
429
transient 5xx
Behavior:
do not mark rows terminal
mark affected rows retryable
preserve last_error
allow later retry
Requested URI not returned
Behavior:
first unresolved attempt -> retryable
second unresolved attempt -> retryable
third unresolved attempt -> missing
That gives a simple default policy:
attempt_count < 3 -> retryable
attempt_count >= 3 and still unresolved -> missing
Repeated unrecoverable logic errors
Behavior:
mark failed
Keep the implementation simple.
Matching rules
The hydrator must not assume the API returns rows in the same order as requested.
Required behavior:
match responses back to requests by uri
determine missing/unresolved URIs by set difference:
requested URIs
returned URIs
This rule is mandatory.
Maturity rule
Hydration eligibility must be based on:
captured_at <= now - maturity_window
Do not use record_created_at for scheduling.
captured_at is the scheduler clock.
Polling model
The hydrator should run as a polling worker.
Required behavior
check for mature work
if work exists, process it
if no work exists:
either exit cleanly
or sleep and poll again if configured
The implementation should support a simple configurable mode such as:
run_once = true
or continuous_poll = true
For initial implementation, either is acceptable as long as behavior is explicit and configurable.
API client requirements
The hydration client must be simple and reliable.
Required behavior
use public read-only API
enforce request chunk size of 25 URIs max
support timeout configuration
support retry/backoff behavior
handle HTTP 429 and 5xx as retryable
surface enough structured information for the orchestrator to update row states
Suggested implementation
A simple synchronous HTTP client is acceptable if the code stays clean.
Async or concurrency is optional in this phase.
Given that this project is being built step by step, correctness is more important than maximizing throughput right now.
If concurrency is added, keep it bounded and simple.
Configuration expectations
This phase should wire config.py into real hydration settings.
At minimum, configuration should support:
hydration endpoint
maturity window
hydrate claim batch size
API URI chunk size (must default to 25 or lower)
request timeout
retry count / backoff settings
hydrate poll interval
continuous vs one-shot mode
hydrated output directory
miss output directory
writer row threshold
writer time threshold
progress log interval
If config fields are missing, Codex may add them cleanly.
Progress logging requirements
The hydration job should log useful operational counters.
Required metrics:
mature pending rows available
rows claimed
request batches sent
hydrated rows returned
requested URIs not returned
rows marked retryable
rows marked missing
rows marked failed
current processing rate
run progress totals
These do not need to be fancy, but they must exist.
Error handling requirements
API/network failures
If a request fails:
log the failure
mark the affected rows retryable
continue unless a fatal process-level condition occurs
Normalization failures
If a returned post cannot be normalized cleanly:
log the failure
mark affected rows failed or retryable based on whether retry makes sense
do not crash the whole worker unless the failure is systemic
SQLite or writer failures
If the writer or SQLite fails in a way that makes safe progress impossible:
shut down cleanly
finalize what can be finalized
mark the hydrate run failed
Safe shutdown behavior
The hydration job should support clean shutdown on:
keyboard interrupt
normal queue exhaustion
fatal exception
On shutdown:
flush/finalize writers
update any outstanding batch file state
update hydrate run status in SQLite
release or allow expiry of claims safely
close resources cleanly
Suggested implementation order
Codex should implement this phase in a practical order.
Step 1
Implement hydrate/client.py request logic and result parsing.
Step 2
Implement hydrate/selector.py integration with SQLite mature-row claiming.
Step 3
Implement hydrate/normalizer.py for:
hydrated row
miss row
Step 4
Wire main_hydrate.py into a real worker loop.
Step 5
Integrate writers and batch-file tracking.
Step 6
Validate with a small practical sample.
Validation requirements for this phase
Codex should validate the hydration implementation in practical ways.
Minimum validation
modules import correctly
main_hydrate.py runs without syntax/runtime bootstrap errors
mature-row claiming works through the full hydrator loop
request chunking respects 25 URIs max
returned hydrated rows match the intended schema
non-returned URIs are handled correctly
state transitions are correct
writer rotation still works under hydration integration
Preferred validation
If practical, run a small sample such as:
insert a small set of test captured posts into SQLite
make some of them mature
hydrate them using a mocked client or safe real public requests
verify:
hydrated rows written
retryable/missing states updated correctly
miss rows written when expected
hydrate run marked appropriately
Do not attempt a 1,000,000-scale hydration run yet unless explicitly requested after this phase.
What Codex should not do in this phase
Codex should not:
redesign firehose ingestion
add Snowflake logic
add uploader/cloud logic
over-engineer concurrency or queue systems
redesign the SQLite state model
collapse the two jobs into one process
This phase is only about making the hydration path real.
Deliverables for this phase
At the end of this phase, Codex should provide:
implemented hydration modules:
hydrate/client.py
hydrate/selector.py
hydrate/normalizer.py
updated main_hydrate.py wired into the real hydration loop
any minimal supporting changes to config/models needed for clean implementation
practical validation results
a short summary of:
what was implemented
what assumptions were made
what remains before Phase 5
Definition of done
Phase 4 is complete when:
the hydration job can run a real hydration loop
only mature captured posts are selected
requests respect the 25-URI limit
returned post views are normalized correctly
unresolved posts are handled with retry/missing logic
hydrated rows are written to rotating local .jsonl.gz files
state transitions are tracked correctly in SQLite
the project is ready for Phase 5 reliability and full-run hardening