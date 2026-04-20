# SQL_DEPLOYMENT_SEQUENCE.md
## Snowflake Deployment Sequence — Fresh Deploy

This is the exact sequence for a fresh Snowflake deploy against the
current `sql/` folder layout (post-`docs/SQL_AUDIT_FIXES.md` cleanup).
Run files in this order exactly. Numeric sort of the folder structure
is the deploy order — if a file moves, this list moves with it.

All deployments run on `COMPUTE_WH` (X-SMALL). Suspend the warehouse
at the end of every session.

---

### Pre-deploy context check

Before running anything, confirm your session context:

```sql
SELECT CURRENT_DATABASE(), CURRENT_SCHEMA(), CURRENT_WAREHOUSE();
```

After step 1 below, the answer should be
`BLUESKYDATAENGINEERINGPROJECT | RAW | COMPUTE_WH`.

---

### Deploy order

```
 1.  sql/00_setup/00_bootstrap_database_schema.sql
 2.  sql/00_setup/00_file_formats.sql
 3.  sql/00_setup/01_internal_stages.sql
 4.  sql/00_setup/03_profanity_config.sql     # seed profanity tables
 5.  sql/01_landing/00_landing_raw_posts.sql
 6.  sql/01_landing/01_landing_hydrated_posts.sql
 7.  sql/01_landing/02_landing_hydration_misses.sql
 8.  sql/01_landing/03_landing_actor_profiles.sql
 9.  sql/01_landing/04_landing_twitter_trends.sql
10.  sql/01_landing/05_landing_trend_matches.sql
11.  sql/02_pipes/00_pipes.sql                # pipes reference landing tables
12.  sql/03_streams/00_streams.sql
13.  sql/04_enhanced/00_posts_enriched_table.sql
14.  sql/04_enhanced/01_staging_tables.sql
15.  sql/05_curated/00_ml_ready_table.sql
16.  python scripts/render_profanity_udf.py --from-snowflake
      → emits sql/00_setup/_generated/03_udfs.rendered.sql
17.  sql/00_setup/_generated/03_udfs.rendered.sql    # deploy rendered UDF
18.  sql/06_tasks/00_task_flatten_labels.sql
19.  sql/06_tasks/01_task_text_features.sql
20.  sql/06_tasks/02_task_actor_features.sql
21.  sql/06_tasks/03_task_trend_match.sql     # resumes 4 stream-gated tasks
22.  sql/06_tasks/04_task_assemble_posts_enriched.sql
23.  sql/06_tasks/05_task_build_ml_ready.sql  # resumes assembler + ml_ready
24.  sql/99_validation/01_profanity_unit_tests.sql    # every row = 'PASS'
25.  ALTER WAREHOUSE COMPUTE_WH SUSPEND;
```

---

### Notes on individual steps

- **Step 4 before step 11.** The profanity config tables are seeded
  early so the renderer (step 16) has rows to read at deploy time.
- **Step 11 after step 10.** Snowpipes' `COPY INTO` bodies reference
  `RAW.LANDING_*`, so all six landing tables must exist first.
- **Step 16 — render the UDF template.** Run from a shell, not from
  Snowflake. The script reads `ENHANCED.PROFANITY_TERMS` and
  `ENHANCED.PROFANITY_WHITELIST`, substitutes the placeholders in
  `sql/00_setup/04_udfs_template.sql`, and writes the runnable output
  to `sql/00_setup/_generated/03_udfs.rendered.sql` (the `_generated/`
  folder is `.gitignore`'d).
- **Step 17.** Open the rendered file in Snowflake and run it. Do
  *not* run `04_udfs_template.sql` directly — it has a guard row that
  emits a JSON instruction message instead of creating the function.
- **Steps 21 + 23 — resume blocks.** The bottoms of
  `03_task_trend_match.sql` and `05_task_build_ml_ready.sql` resume
  the dependent tasks in the order Snowflake requires (children before
  parent).
- **Step 24.** All rows in `01_profanity_unit_tests.sql` must come
  back `PASS`. Any `FAIL` means the rendered UDF disagrees with the
  seeded term tables — re-render and re-deploy.

After step 25 the Snowflake side is ready. Start the Python pipeline
(firehose, hydrate, trend scraper, trend matcher); the task chain
fires automatically when trend matches land.

---

### Operational reset (separate from deploy)

`sql/99_cleanup/02_truncate_raw_data.sql` empties every RAW landing
table, purges the stages, and truncates downstream feature tables.
Tables, stages, pipes, streams, tasks, and UDFs are *not* dropped.
Run by hand only when you intend to reload everything.
