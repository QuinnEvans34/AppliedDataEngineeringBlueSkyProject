# Snowflake Loader Phase Plan

## Purpose
This document defines the implementation scope for the Snowflake warehouse/loading phase of the Bluesky data engineering project.

This phase exists to move the current local pipeline outputs into Snowflake in a structured, repeatable, and validated way.

This phase does **not** include NLP, translation, profanity cleaning, porn-bot filtering, marketplace trend joins, or Snowpipe Streaming.

---

## Current project state

The current Python pipeline already produces four dataset families under a run-scoped output root:

- `raw_posts/`
- `hydrated_posts/`
- `hydration_misses/`
- `actor_profiles/`

Expected layout:

```text
data/output/<run_tag>/
  raw_posts/
  hydrated_posts/
  hydration_misses/
  actor_profiles/
  logs/
  state/



  The current operational model must be preserved during this phase:
real runs use a fresh run-specific SQLite DB
hydration and actor completion are driven by repeated one-shot drain loops until completion checks pass
account/profile counts are account-level and are not expected to match post counts
the raw parity issue from preflight (20000 reported captured vs 19994 staged/file rows) is still unresolved and must be accounted for in loader validation
Locked scope for this phase
In scope
Add Snowflake SQL project structure to the repo
Add Python Snowflake loader structure to the repo
Create SQL for:
file formats
internal stages
landing tables
staging views/tables
first curated merged post-level table
initial streams/tasks scaffolding
Add loader execution order and operator documentation
Add load validation and parity checks
Keep everything grounded in the current emitted Bluesky output contracts
Out of scope
NLP
translation
language filtering
profanity cleaning
porn-bot filtering
marketplace trend joins
Snowpipe Streaming
redesign of the existing collection pipeline
changing the firehose/hydrate/actor business logic
Architectural decisions for v1
Warehouse layers
Layer 1 — Internal stages
One internal stage per dataset family:
raw posts
hydrated posts
hydration misses
actor profiles
Later, NLP outputs can get their own stage.
Layer 2 — Landing tables
One landing table per dataset family.
Each landing table should:
store the full JSON row in a VARIANT column
store load metadata such as:
source_filename
source_run_tag
loaded_at
dataset_family
optional file row number / file hash if added later
Landing tables are append-oriented audit surfaces, not the final analytics model.
Layer 3 — Staging views/tables
Flatten only stable top-level fields from the current JSON contracts.
Do not over-flatten nested objects in v1.
Treat fields like record, profile, associated, labels arrays, and similar nested structures as semi-structured unless there is a clear stable reason to flatten them now.
Layer 4 — Curated core table
Create one merged post-level curated object that joins:
raw posts on uri
hydrated posts on uri
actor profiles on actor DID semantics
This is the first analytics-ready core object.
Layer 5 — Later enrichment
NLP outputs and marketplace trend enrichment happen only after the core curated layer exists and is validated.
Output contracts that must remain unchanged
The Snowflake layer must adapt to the current repo output contracts, not force the current pipeline to change.
Preserve:
file/folder layout under data/output/<run_tag>/...
one-record-per-line gzip JSONL output format
current top-level field names emitted by the normalizers
join key semantics:
uri for raw to hydrated
actor DID semantics for post to actor joins
run lineage fields already emitted by the pipeline:
capture_run_id
hydrate_run_id
actor_run_id
current status semantics in SQLite and drain workflow behavior
fresh run-specific DB operational practice for real runs
Repo structure to add
snowflake_loader/
  __init__.py
  config.py
  connection.py
  stage_upload.py
  copy_into.py
  validate_load.py
  manifest.py
  main_load_run.py

sql/
  00_setup/
    00_file_formats.sql
    01_internal_stages.sql

  01_landing/
    00_landing_raw_posts.sql
    01_landing_hydrated_posts.sql
    02_landing_hydration_misses.sql
    03_landing_actor_profiles.sql

  02_staging/
    00_stg_raw_posts.sql
    01_stg_hydrated_posts.sql
    02_stg_hydration_misses.sql
    03_stg_actor_profiles.sql

  03_curated/
    00_curated_posts_core.sql

  04_tasks_streams/
    00_streams.sql
    01_tasks.sql

docs/
  14_snowflake_loader_phase_plan.md
  15_snowflake_loader_runbook.md
Loader behavior requirements
Main loader behavior
The loader should support loading a specific run root from local output files into Snowflake.
Example conceptual flow:
identify finalized .jsonl.gz files under a chosen run root
group them by dataset family
upload them to the correct internal stage with PUT
run COPY INTO into the correct landing table
run validation queries
emit a clear load summary
File discovery policy
For v1, use filesystem scanning of finalized .jsonl.gz files as the canonical source for what gets loaded.
If DB or batch_files metadata is available, it can be used for reconciliation/reporting, but do not make the loader depend on that table to function.
Reason:
the current parity concern is about file-vs-count durability
the actual warehouse load should be grounded in finalized files that exist on disk
Load-complete gate
A run should not be considered safely loaded unless all of the following pass:
hydration and actor drain completion checks are satisfied
finalized local file counts are computed successfully
Snowflake stage counts match expected uploaded files
landing table row counts match staged file row counts
parity summary is emitted for each dataset family
Validation scope
At minimum, validate:
raw posts
hydrated posts
hydration misses
actor profiles
Validation should report:
file count
file row count
stage row count
landing row count
distinct business keys where applicable
pass/fail parity result
Dataset-family modeling decisions
Raw posts
grain: post-level
main join key: uri
keep full row in landing VARIANT
flatten stable top-level fields in staging
Hydrated posts
grain: post-level
main join key: uri
keep full row in landing VARIANT
flatten stable top-level fields in staging
Hydration misses
grain: miss/error-level
load as a first-class landing and staging object in v1
reason: it is part of the operational record and useful for audits
Actor profiles
grain: account-level
main join key: did
do not force actor rows to artificially match post counts
keep full row in landing VARIANT
flatten stable top-level fields in staging
Versioning and history policy
For v1:
landing tables are append-oriented
staging can remain view-based or table-based depending on implementation simplicity
curated layer should avoid double-counting by using stable business keys and latest-record logic where needed
Do not over-engineer historical SCD logic in this phase.
Get the landing + staging + first curated merged table correct first.
Streams and tasks policy
Include initial scaffolding for streams/tasks, but keep it simple.
This phase is primarily about:
deterministic loading
clear SQL structure
validation
repeatable execution
Do not build a full autonomous streaming architecture in this phase.
Non-negotiable constraints for implementation
Do not modify the ingestion pipeline’s core behavior unless absolutely required
Do not change current emitted field names without explicit review
Do not begin NLP work in this phase
Do not begin marketplace trend joins in this phase
Do not implement Snowpipe Streaming in this phase
Do not move SQL logic primarily into the Snowflake web UI
Keep SQL as repo code
Keep the design grounded in the current repo’s actual file outputs and join keys
Deliverables for this phase
Snowflake loader Python scaffolding
SQL setup/landing/staging/curated/task-stream files
Loader runbook
Validation/parity logic
A dry-run-ready path for loading one known run into Snowflake
Definition of done for this phase
This phase is done when:
the repo has the Snowflake SQL structure
the repo has the Python loader structure
a known run can be loaded from local finalized files into Snowflake
landing tables receive the data correctly
staging objects expose the stable top-level fields
the curated merged post-level object works
validation/parity output exists
the work does not break or redesign the existing collection pipeline
Only after this is complete should the project move to NLP and later trend enrichment.
