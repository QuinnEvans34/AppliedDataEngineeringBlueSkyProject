# Week 2 RAW Snowpipe Validation Runbook (25-Row Fixtures)

Date: 2026-04-04

This is the smallest repeatable Week 2 demo path for RAW ingestion using deterministic fixtures across 4 families:
- `raw_posts`
- `hydrated_posts`
- `hydration_misses`
- `actor_profiles`

## 1) Load credentials
```bash
set -a
source local/snowflake.env
set +a
```

## 2) Apply SQL setup in order (run once)
1. `sql/00_setup/00_bootstrap_database_schema.sql` (for fresh environment bootstrap)
2. `sql/00_setup/00_file_formats.sql`
3. `sql/00_setup/01_internal_stages.sql`
4. `sql/00_setup/02_pipes.sql`
5. `sql/01_landing/00_landing_raw_posts.sql`
6. `sql/01_landing/01_landing_hydrated_posts.sql`
7. `sql/01_landing/02_landing_hydration_misses.sql`
8. `sql/01_landing/03_landing_actor_profiles.sql`

## 3) Verify objects exist before demo
Run in Snowsight SQL worksheet:
```sql
SHOW STAGES LIKE 'BLUESKY%STAGE';
SHOW PIPES LIKE 'BLUESKY%PIPE';
SHOW TABLES LIKE 'LANDING%';
SHOW TABLES LIKE 'LOADER_FILE_MANIFEST';
```

## 4) Run one demo command (fixtures + stage upload + Snowpipe load + summary)
Dry run:
```bash
python3 run_week2_raw_demo.py --dry-run --print-loader-json
```

Execute:
```bash
python3 run_week2_raw_demo.py --print-loader-json
```

Default demo behavior:
- deterministic `25` rows per family
- fixture run root `data/output/w2_fixture_25`
- load mode `snowpipe`
- completion gate bypass enabled for fixture/demo flow (`--skip-completion-gate`)

## 5) Validate in Snowsight (no UI file upload)
Run:
- `sql/99_validation/00_w2_fixture_checks.sql`

Show:
1. Stage `LIST` output includes `w2_fixture_25/<family>/...`.
2. Landing counts are `25` per family.
3. `LOADER_FILE_MANIFEST` has file-level entries and row totals.
4. `COPY_HISTORY` shows recent fixture loads.

## 6) Optional fallback proof (COPY mode still works)
```bash
python3 run_week2_raw_demo.py --load-mode copy --print-loader-json
```

## 7) Instructor check-in talking points
1. Internal stages are used (no UI upload wizard).
2. Snowpipe is internal-stage triggered via `ALTER PIPE ... REFRESH PREFIX`.
3. RAW landing tables receive payload + metadata columns.
4. Loader keeps COPY fallback for operational safety.
5. Demo is low-credit and reproducible using 4 fixture files (25 rows each).

## 8) Credit minimization checklist
- Use `data/output/w2_fixture_25` only for Week 2 check-in.
- Do not run large live collections for this demo.
- Reuse the same fixture run root for rerun and fallback checks.
