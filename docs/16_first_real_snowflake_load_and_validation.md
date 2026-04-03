# First Real Snowflake Load and Validation

## Purpose
This document defines the next phase after the v1 Snowflake loader scaffolding.

The goal of this phase is not to add more scaffolding.
The goal is to prove that the loader works end to end against a real run root and a real Snowflake environment.

This phase must validate:
- Snowflake object setup
- Python loader execution
- stage upload behavior
- `COPY INTO` behavior
- landing/staging/curated population
- reconciliation across local files, Snowflake stages, and Snowflake tables

This phase is the gate before any NLP work begins.

---

## Why this phase exists

The repo now has v1 Snowflake loader scaffolding, SQL objects, parity reporting, and tests for the loader layer. However, that is still scaffolding until it is executed in a real Snowflake environment against a real run root. NLP and marketplace work remain deferred. :contentReference[oaicite:0]{index=0}

There is also still an unresolved raw parity concern from preflight:
- firehose reported `20,000` unique captured
- staged/file raw rows showed `19,994`

That issue is not closed and must be surfaced cleanly by the loader validation layer before the project moves to NLP. :contentReference[oaicite:1]{index=1}

---

## Locked scope for this phase

### In scope
1. Verify Python dependencies and Snowflake connection requirements
2. Verify SQL execution order
3. Execute SQL setup in a real Snowflake environment
4. Select one known run root for first real load
5. Run the loader against that run root
6. Validate parity for each dataset family
7. Validate the curated merged object
8. Document any mismatches or blockers
9. Apply only the minimum fixes required to make the real-load path work

### Out of scope
- NLP
- translation
- marketplace trend joins
- Snowpipe Streaming
- redesign of the existing Bluesky collection pipeline
- unrelated refactors
- changing emitted file contracts unless a blocker forces a very small correction

---

## Non-negotiable constraints

- Do not begin NLP in this phase
- Do not start marketplace joins in this phase
- Do not redesign firehose, hydration, or actor enrichment logic
- Do not change current output folder layout
- Do not change current top-level field names without explicit need
- Keep SQL in the repo
- Keep the loader grounded in finalized local `.jsonl.gz` files
- Preserve strict DB-backed completion gating
- Preserve idempotent rerun behavior that skips already-loaded files
- Preserve current curated actor join logic:
  `COALESCE(h.author_did, r.repo_did) = a.did`

These constraints match the current implementation and prior locked decisions. :contentReference[oaicite:2]{index=2} :contentReference[oaicite:3]{index=3}

---

## Required execution order

### Step 1 — inspect and confirm prerequisites
Confirm:
- `snowflake-connector-python` is installed
- required `SNOWFLAKE_*` environment variables are present
- one known run root exists with finalized `.jsonl.gz` files
- the run root has a usable SQLite state DB
- the run root satisfies strict completion semantics for hydration and actor phases

If any of these fail, stop and report exactly what is missing.

### Step 2 — verify the exact SQL order
Produce and use a concrete execution order for:
1. `sql/00_setup/00_file_formats.sql`
2. `sql/00_setup/01_internal_stages.sql`
3. `sql/01_landing/*.sql`
4. `sql/02_staging/*.sql`
5. `sql/03_curated/*.sql`
6. `sql/04_tasks_streams/*.sql`

If any file must move or be adjusted due to dependency order, document it clearly.

### Step 3 — execute setup in Snowflake
Run the real SQL setup against the target Snowflake environment.
Confirm object creation success for:
- file formats
- internal stages
- landing tables
- staging views/tables
- curated object
- loader manifest/control object if required by implementation

### Step 4 — choose one first real run root
Use one known run root for the first real load.
Document:
- run root path
- dataset-family file counts
- state DB path
- whether hydration/actor completion checks pass
- whether any `.tmp` files still exist

Do not load a run root that fails safe-load gating.

### Step 5 — run a real load
Run the loader in non-dry mode against the selected run root.

The load must:
- discover finalized files
- upload files to the correct Snowflake stages
- `COPY INTO` the correct landing tables
- respect skip-loaded-file behavior
- emit a load summary

### Step 6 — validate parity and reconciliation
For each dataset family:
- raw posts
- hydrated posts
- hydration misses
- actor profiles

Report:
- finalized local file count
- finalized local row count
- Snowflake stage row count
- landing table row count
- distinct business-key count where applicable
- pass/fail parity result

### Step 7 — validate curated object
Validate the first curated post-level object with at least:
- total rows
- distinct `uri`
- matched hydrated rows
- matched actor rows
- unmatched actor cases
- obvious null/duplication checks

### Step 8 — resolve only real blockers
If the first real load fails, fix only what is necessary to make:
- SQL setup work
- loader execution work
- reconciliation work
- curated object validation work

Do not expand scope beyond this.

---

## Required reporting output

The implementation response for this phase must include all of the following.

### A. Real execution checklist
A concise checklist showing:
- dependency status
- env-var status
- selected run root
- DB gate result
- SQL setup result
- loader run result
- parity result by dataset family
- curated validation result

### B. Exact commands used
Show the exact commands used for:
- dependency install if needed
- SQL execution
- loader dry-run if repeated
- loader real run
- validation queries

### C. Reconciliation queries
Provide concrete SQL used to validate:
- stage row counts
- landing row counts
- curated row counts
- distinct `uri`
- distinct actor DID counts where relevant

### D. Mismatch report
If any mismatch exists, show:
- dataset family
- expected count
- observed count
- suspected cause
- whether it blocks moving on

### E. Go / no-go recommendation
End with a direct recommendation:
- ready for NLP
- not ready for NLP

Only say ready for NLP if the real-load path is functioning and the parity story is clean enough to trust.

---

## Definition of done

This phase is done only when:
- Snowflake setup has been executed successfully in a real environment
- one real run root has been loaded successfully
- loader rerun behavior is confirmed to skip already-loaded files
- parity summary has been produced for all dataset families
- curated object has been validated
- blockers, if any, are written clearly
- there is a direct recommendation on whether the project can move to NLP

This phase is not done merely because tests pass or because dry-run output looks correct.

---

## Exit rule

Do not move to NLP until this phase is complete.

The Snowflake layer must first prove:
- real environment execution
- real file loading
- real reconciliation
- understandable parity results