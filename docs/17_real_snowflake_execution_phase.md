# Real Snowflake Execution Phase

## Purpose
This phase exists to prove that the Snowflake loader works in a real environment.

The loader scaffolding already exists.
The missing step is real execution and validation.

This phase is not about adding more architecture, more scaffolding, or NLP.
This phase is about:
- connecting to Snowflake
- creating the Snowflake objects
- loading one real run root
- validating parity
- confirming curated outputs
- confirming rerun idempotency

---

## Why this phase is required

The current project is blocked from a real Snowflake validation run because:
- required `SNOWFLAKE_*` environment variables were not set
- the previously selected run root was incomplete for full validation
- the previous attempt used a cross-run state DB override, which is not clean enough for first real validation

Because of that, the project is still **not ready for NLP**.

---

## Locked scope

### In scope
1. Set up the real Snowflake execution prerequisites
2. Identify one self-consistent run root for first real validation
3. Execute Snowflake SQL setup in the correct order
4. Run the loader in non-dry mode
5. Validate local vs stage vs landing parity
6. Validate the curated post-level object
7. Validate rerun behavior for skip-loaded-file semantics
8. Apply only the minimum fixes required to complete this phase

### Out of scope
- NLP
- translation
- topic normalization experiments beyond what is needed for current load validation
- trend enrichment implementation
- machine learning implementation
- firehose redesign
- new architecture redesign
- major refactors

---

## Non-negotiable constraints

- Do not begin NLP in this phase
- Do not use a mixed run-root/state-DB combination unless there is no alternative and the reason is explicitly documented
- Prefer one run root that is internally consistent:
  - finalized `.jsonl.gz` files
  - its own usable state DB
  - ideally raw posts, hydrated posts, and actor profiles
- Preserve strict DB-backed completion gating
- Preserve idempotent rerun behavior that skips already-loaded files
- Preserve existing SQL object structure unless a real execution blocker requires a fix
- Preserve current curated join logic:
  - raw ↔ hydrated on `uri`
  - actor join on `COALESCE(h.author_did, r.repo_did) = a.did`

---

## Prerequisites that must be checked first

### Snowflake environment
Confirm the following env vars exist and are non-empty:
- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER`
- `SNOWFLAKE_PASSWORD`
- `SNOWFLAKE_ROLE`
- `SNOWFLAKE_WAREHOUSE`
- `SNOWFLAKE_DATABASE`
- `SNOWFLAKE_SCHEMA`

Credentials must be loaded from a local, gitignored shell env file before execution.
Do not place live secrets in tracked docs or committed config files.

Recommended shell pattern:

```bash
set -a
source local/snowflake.env
set +a
```

### Python dependency
Confirm:
- `snowflake-connector-python` is installed

### Run-root requirements
Find one run root that:
- has finalized `.jsonl.gz` files
- has no lingering `.tmp` files
- has a usable state DB
- passes strict completion gating
- is as complete as possible for raw, hydrated, actor, and miss coverage

If a fully complete run root does not exist, choose the best available one and say exactly what is missing.

Current best available candidate for first real execution:
- `data/phase6_diagnostic_20260401`

Current coverage in that run root:
- raw posts: present
- hydrated posts: present
- hydration misses: absent
- actor profiles: absent

---

## Required work order

### Step 1 — inspect available run roots
Find candidate run roots under the project data output area.

For each candidate, report:
- run root path
- finalized file counts by dataset family
- presence/absence of `.tmp` files
- available state DB path
- whether strict completion gating passes
- whether the run root is self-consistent

Then choose the best candidate for first real execution.

### Step 2 — validate Snowflake prerequisites
Verify:
- connector installed
- env vars present
- loader can resolve object names and connection config

If blocked, stop and report exactly what is missing.

### Step 3 — execute SQL setup in Snowflake
Run the SQL files in this order:
1. `sql/00_setup/00_file_formats.sql`
2. `sql/00_setup/01_internal_stages.sql`
3. `sql/01_landing/00_landing_raw_posts.sql`
4. `sql/01_landing/01_landing_hydrated_posts.sql`
5. `sql/01_landing/02_landing_hydration_misses.sql`
6. `sql/01_landing/03_landing_actor_profiles.sql`
7. `sql/02_staging/00_stg_raw_posts.sql`
8. `sql/02_staging/01_stg_hydrated_posts.sql`
9. `sql/02_staging/02_stg_hydration_misses.sql`
10. `sql/02_staging/03_stg_actor_profiles.sql`
11. `sql/03_curated/00_curated_posts_core.sql`
12. `sql/04_tasks_streams/00_streams.sql`
13. `sql/04_tasks_streams/01_tasks.sql`

If any SQL file fails, fix only what is necessary.

### Step 4 — run first real non-dry load
Run the loader against the selected run root in non-dry mode.

The run must:
- discover finalized files
- upload them to the correct stages
- execute `COPY INTO`
- populate landing tables
- preserve skip-loaded-file behavior

For this phase pass, proceed with the best available self-consistent run root, explicitly document missing families, and avoid fabricating cross-run completeness.

### Step 5 — validate reconciliation
For each dataset family:
- raw posts
- hydrated posts
- hydration misses
- actor profiles

Report:
- finalized local file count
- finalized local row count
- stage row count
- landing row count
- distinct business-key count where relevant
- pass/fail parity

### Step 6 — validate curated object
Report at minimum:
- total rows
- distinct `uri`
- hydrated coverage
- actor coverage
- unmatched actor cases
- duplicate/null anomalies if present

### Step 7 — validate rerun idempotency
Run the loader again on the same run root and confirm:
- already-loaded files are skipped
- landing counts do not duplicate unexpectedly
- manifest/control behavior matches intended design

---

## Minimum acceptable output

The implementation response for this phase must include:

1. The chosen run root and why it was selected
2. The exact commands used
3. SQL execution results
4. Loader execution results
5. Reconciliation/parity results
6. Curated validation results
7. Rerun idempotency results
8. Any blockers or mismatches
9. Final recommendation:
   - ready to move to NLP
   - not ready to move to NLP

---

## Definition of done

This phase is done only if:
- Snowflake connection worked
- SQL setup executed in a real environment
- one real run root loaded successfully
- parity output exists
- curated validation exists
- rerun idempotency was tested
- the result is strong enough to decide whether NLP can begin

This phase is not done if execution is blocked before connection or if only dry-run behavior is shown.

This phase pass alone does not make the project NLP-ready unless the missing families are later validated or explicitly judged unnecessary.
