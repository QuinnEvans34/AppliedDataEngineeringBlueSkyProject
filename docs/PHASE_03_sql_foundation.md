# Phase 03 — Fix Landing SQL Foundations and Operational Mismatches

## Goal
Remove structural SQL inconsistencies that will keep breaking downstream logic even if the enhanced task is rewritten.

## Why this phase exists
The audit found multiple base-layer SQL mismatches:
- `LANDING_TWITTER_TRENDS` is created unqualified while tasks expect `RAW.LANDING_TWITTER_TRENDS`
- many landing table scripts depend on session context instead of explicit schema qualification
- task runner ops script targets the wrong task schema
- append-only landing tables need explicit deterministic assumptions for later dedupe

If the foundation layer is inconsistent, enhanced-layer work will remain brittle.

## Required SQL changes

### Change 1 — Fully qualify landing objects in SQL
Files likely involved:
- `sql/01_landing/00_landing_raw_posts.sql`
- `sql/01_landing/01_landing_hydrated_posts.sql`
- `sql/01_landing/02_landing_hydration_misses.sql`
- `sql/01_landing/03_landing_actor_profiles.sql`
- `sql/01_landing/04_landing_twitter_trends.sql`
- `sql/01_landing/05_landing_trend_matches.sql`

Requirement:
- ensure all landing table DDL uses explicit `RAW.` qualification
- remove reliance on session schema context for object creation

Critical fix:
- `RAW.LANDING_TWITTER_TRENDS` must be explicitly created as that exact object name

### Change 2 — Verify streams align to corrected landing objects
Files likely involved:
- `sql/02_streams/00_streams.sql`

Requirement:
- confirm streams point to the intended fully qualified landing tables
- do not add unnecessary streams unless required by design

### Change 3 — Fix operational task schema mismatch
Files likely involved:
- `scripts/ops/resume_tasks.py`

Requirement:
- update the script to target the actual task names and schemas
- audit any other ops scripts that reference outdated task paths

Known mismatch to fix:
- script targets `CURATED.TASK_BUILD_ML_READY`
- actual task is `ENHANCED.TASK_BUILD_ML_READY`

## Required outputs
Codex must:
1. patch all landing DDL to explicit schema qualification
2. patch ops/task control scripts to correct schema/object names
3. identify any remaining SQL object references that rely on implicit session context

## Acceptance criteria
This phase is done only when:
- all landing tables are created as explicitly qualified `RAW.*` objects
- task/ops scripts target the correct task objects
- stream definitions point to the corrected landing objects
- no base SQL object required by enhanced layer depends on accidental session schema

## Test conditions
Run these checks after changes:

```sql
SHOW TABLES IN SCHEMA RAW;
SHOW STREAMS IN SCHEMA RAW;
SHOW TASKS IN SCHEMA ENHANCED;

SELECT TABLE_SCHEMA, TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_NAME IN (
  'LANDING_RAW_POSTS',
  'LANDING_HYDRATED_POSTS',
  'LANDING_HYDRATION_MISSES',
  'LANDING_ACTOR_PROFILES',
  'LANDING_TWITTER_TRENDS',
  'LANDING_TREND_MATCHES'
)
ORDER BY TABLE_SCHEMA, TABLE_NAME;

-- Confirm task names exist where the ops scripts expect them
SHOW TASKS LIKE 'TASK_ENRICH_POSTS' IN SCHEMA ENHANCED;
SHOW TASKS LIKE 'TASK_BUILD_ML_READY' IN SCHEMA ENHANCED;
```
