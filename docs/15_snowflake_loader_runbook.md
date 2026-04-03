# Snowflake Loader Runbook (Phase 15)

Date: 2026-04-02

This runbook defines operator usage for the Snowflake warehouse/loading v1 layer.

## Scope and Deferrals
Implemented in this phase:
- Snowflake SQL structure (setup, landing, staging, curated, stream/task scaffolding)
- Python loader for one run root
- Strict completion-gate checks using run-scoped SQLite state
- File/stage/landing parity checks per dataset family

Explicitly deferred:
- NLP/translation/language/profanity/porn-bot work
- Marketplace trend joins or enrichment
- Snowpipe Streaming and autonomous streaming architecture
- Any redesign of firehose/hydrate/actor pipeline behavior

## Prerequisites
1. A completed run root in standard layout:

```text
data/output/<run_tag>/
  raw_posts/
  hydrated_posts/
  hydration_misses/
  actor_profiles/
  state/
```

2. Snowflake credentials in environment:

```bash
export SNOWFLAKE_ACCOUNT='...'
export SNOWFLAKE_USER='...'
export SNOWFLAKE_PASSWORD='...'
export SNOWFLAKE_ROLE='...'
export SNOWFLAKE_WAREHOUSE='...'
export SNOWFLAKE_DATABASE='...'
export SNOWFLAKE_SCHEMA='...'
```

3. SQL objects created in this exact order.

## SQL Apply Order
Run these scripts in sequence:

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

## Loader Invocation
Dry run first (no Snowflake mutation):

```bash
python3 -m snowflake_loader.main_load_run \
  --run-root data/output/<run_tag> \
  --dry-run
```

Load run root into Snowflake:

```bash
python3 -m snowflake_loader.main_load_run \
  --run-root data/output/<run_tag>
```

Optional explicit DB path:

```bash
python3 -m snowflake_loader.main_load_run \
  --run-root data/output/<run_tag> \
  --state-db-path data/output/<run_tag>/state/run.db
```

## Execution Behavior
1. Discover finalized `.jsonl.gz` files from local filesystem under run root (canonical source).
2. Resolve run DB from `<run_root>/state/*.db` (or explicit path).
3. Enforce strict completion gates:
- hydration completion semantics aligned with `scripts/ops/stage_drain.py`
- actor completion semantics aligned with `scripts/ops/stage_drain.py`
4. Skip files already present in `LOADER_FILE_MANIFEST` for this `source_run_tag` and dataset family.
5. `PUT` pending files into family-specific internal stages.
6. `COPY INTO` landing tables with metadata columns and raw JSON in `VARIANT`.
7. Record loaded files in `LOADER_FILE_MANIFEST`.
8. Emit parity summary per dataset family.

## Parity Summary Interpretation
Per family, loader reports:
- `local_file_count`
- `local_row_count`
- `stage_file_count`
- `stage_row_count`
- `landing_row_count`
- `landing_distinct_business_keys`
- `parity_pass`

Expected pass condition:
- `local_file_count == stage_file_count`
- `local_row_count == stage_row_count == landing_row_count`

This validation is required to guard unresolved raw parity risk from preflight history.

## Idempotent Reruns
Reruns are idempotent at file level:
- `LOADER_FILE_MANIFEST` is checked first
- previously loaded local file paths are skipped
- landing remains append-oriented; reruns do not overwrite prior rows

## Curated Join Semantics (v1)
`CURATED_POSTS_CORE` preserves current semantics:
- raw to hydrated join on `uri`
- actor join on DID semantics using `COALESCE(h.author_did, r.repo_did) = a.did`
- latest-record logic by business key (`uri` for posts, `did` for actors)
