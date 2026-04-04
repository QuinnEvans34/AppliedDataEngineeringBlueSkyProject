# Week 2 Phase 1 — Internal Stage Snowpipe Objects and Config Wiring

## Credit minimization requirement
Use the least amount of Snowflake credits possible.
- Do not create duplicate warehouses, schemas, or tables.
- Reuse existing database, schema, internal stages, file formats, and landing tables wherever possible.
- Only add the minimum new Snowflake objects required for Week 2.
- Do not perform any large test loads.
- Do not run any unnecessary COPY operations.
- Assume deterministic 25-row fixture files will be used later for testing.

## Objective
Add the minimum Snowflake SQL and Python config wiring required to support **internal-stage Snowpipe ingestion** for the Week 2 RAW assignment.

This phase is ONLY about:
1. validating/reusing the existing Snowflake setup
2. adding pipe objects
3. adding pipe-name mappings into loader config

Do NOT implement loader execution yet.
Do NOT implement fixtures yet.
Do NOT implement ML, React, moderation, ENHANCED, or CURATED logic.

## Current repo facts to align with
The audit found:
- internal stages already exist
- file format SQL already exists
- landing RAW tables already exist for:
  - LANDING_RAW_POSTS
  - LANDING_HYDRATED_POSTS
  - LANDING_HYDRATION_MISSES
  - LANDING_ACTOR_PROFILES
- current loader is COPY-first
- no pipe objects currently exist
- no pipe-name mappings currently exist in config
- Week 2 should keep COPY mode as fallback while adding Snowpipe mode

## Required design
We are using **internal stages**.
We are using **Snowpipe with internal stages**.
We will add one pipe per landing table.
AUTO_INGEST must be FALSE.

## Pipe design requirements
Create a new SQL file:
- `sql/00_setup/02_pipes.sql`

It must define one pipe per dataset family:
- raw posts
- hydrated posts
- hydration misses
- actor profiles

Use clear naming and keep it consistent with the current project naming scheme.

Each pipe should:
- load from the existing internal stage
- target the correct landing table
- be scoped to the correct prefix/family path
- load JSON payload into the raw payload column
- populate metadata columns using staged file metadata if the landing table requires them
- set a constant load_invocation_id value for Snowpipe mode if needed
- avoid changing existing table structure unless it is absolutely required for pipe compatibility

## Important implementation rule
Do not redesign the landing tables unless there is a hard blocker.
Prefer compatibility with the current schema over broad schema churn.

If a column like `load_invocation_id` is NOT NULL, set a clear fixed Snowpipe-mode value such as:
- `snowpipe`

Do not introduce unnecessary schema migrations in this phase.

## Config changes required
Update the Snowflake loader config so the loader can resolve pipe names by dataset family.

Expected result:
- the config should expose pipe names for:
  - raw_posts
  - hydrated_posts
  - hydration_misses
  - actor_profiles

Do not wire execution logic yet.
Only add the config surface needed for later phases.

## Deliverables
1. `sql/00_setup/02_pipes.sql`
2. config updates that expose pipe-name mappings
3. concise comments/docstrings explaining Snowpipe object purpose
4. no broad refactor

## Constraints
- preserve existing COPY-based behavior for now
- no implementation of Snowpipe refresh/polling yet
- no fixture generation yet
- no direct data mutation beyond object creation SQL
- least Snowflake credits possible

## Output expectations
At the end of this phase, return:
1. what SQL file was added
2. what config file(s) were changed
3. the pipe names introduced
4. any assumptions or blockers found