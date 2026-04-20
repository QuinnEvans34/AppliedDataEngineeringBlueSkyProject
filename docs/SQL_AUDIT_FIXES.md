# SQL_AUDIT_FIXES.md
## Fixes required before the fresh Snowflake deploy

This doc is the action list from the `sql/` audit. Context: Snowflake
has been wiped and the pipeline will be redeployed end-to-end with
the Python side pulling fresh data from the Bluesky API. Three
blockers prevent a clean deploy today. Several legacy files and stale
comments need cleanup. Fix everything below, in order, before running
any SQL in Snowflake.

Scope: SQL files only. Python pipeline is untouched. Docker is
deferred until professor approval.

---

### Blocker 1 — Pipe deploy order is wrong

**Current state.** `sql/00_setup/02_pipes.sql` creates six Snowpipes
whose `COPY INTO` bodies reference `RAW.LANDING_*` tables. Those
tables are created in `sql/01_landing/*.sql`. If a deploy walks the
folders in numeric order (`00_setup/` → `01_landing/`), the pipe file
executes **before** the landing tables exist and Snowflake rejects
every `CREATE PIPE` with "table does not exist."

**Fix.** Move the pipes file out of `00_setup/` so its deploy position
is after `01_landing/`. Create a new folder `sql/02_pipes/` and move
the file:

```
sql/00_setup/02_pipes.sql  →  sql/02_pipes/00_pipes.sql
```

Then renumber the downstream folders to keep numeric order intact:

```
sql/02_streams/    →  sql/03_streams/
sql/03_enhanced/   →  sql/04_enhanced/
sql/04_curated/    →  sql/05_curated/
sql/05_tasks/      →  sql/06_tasks/
```

**Update references** after the renames:

- `docs/SQL_FOLDER_OUTLINE.md` — folder map block and every table of
  files per subfolder.
- Any comment inside a SQL file that cites a path like
  `sql/05_tasks/00_tasks.sql` (several tasks reference this).
- `docs/SQL_DEPLOYMENT_SEQUENCE.md` if it exists.

**Alternative (lower-churn).** Leave files in place; document an
explicit deploy order in a new `sql/DEPLOY_ORDER.md` and have
the human (or a runner script) execute files in the documented
sequence instead of by folder sort. Picks up zero rename cost but
loses the "numbered subfolders encode deployment order" principle
that is currently a stated design rule in `docs/SQL_FOLDER_OUTLINE.md`.

**Recommendation:** do the folder rename. The design principle of
numeric sort = deploy order is valuable and the rename is
mechanical.

---

### Blocker 2 — UDF template is unrunnable; render step is missing

**Current state.** `sql/00_setup/03_udfs.sql` is a **template**, not
runnable SQL. It contains:

- A `1/0` "template guard" at the top that intentionally errors if
  the file is executed without rendering.
- Two placeholders `{{PROFANITY_TERMS_JSON}}` and
  `{{PROFANITY_WHITELIST_JSON}}` that must be substituted.

The substitution is done by `scripts/render_profanity_udf.py`, which
emits the runnable output to `sql/00_setup/_generated/03_udfs.rendered.sql`.
That directory does not exist in the repo yet — **the UDF has never
been rendered**.

There is also a deploy-order issue: the render script's
`--from-snowflake` mode reads from `ENHANCED.PROFANITY_TERMS` and
`ENHANCED.PROFANITY_WHITELIST`, so those tables (seeded by
`sql/00_setup/04_profanity_config.sql`) must exist **before** the
render. File numbering today has `03_udfs.sql` (template) before
`04_profanity_config.sql` (seeds), which is backwards from the
actual render-then-deploy sequence.

**Fix.** Two edits:

1. **Swap the numeric ordering** so the config file seeds first:

   ```
   sql/00_setup/03_udfs.sql            →  sql/00_setup/04_udfs_template.sql
   sql/00_setup/04_profanity_config.sql →  sql/00_setup/03_profanity_config.sql
   ```

   After the rename, `03_profanity_config.sql` (seed) runs before
   `04_udfs_template.sql` (template — still not runnable on its own,
   but numbered after its dependency).

2. **Document the render step** as part of the deploy runbook (see
   "Deploy Order" section at the bottom of this doc). The rendered
   file at `sql/00_setup/_generated/03_udfs.rendered.sql` is what
   actually gets run in Snowflake — the template stays in the repo,
   the rendered output goes into the existing `.gitignore`'d
   `_generated/` folder.

3. **Make `04_udfs_template.sql`'s guard block clearer.** Replace
   the `1/0 AS force_failure` line with a `SELECT TO_VARIANT(PARSE_JSON('{"error": "template not rendered — run scripts/render_profanity_udf.py --from-snowflake"}'))`
   statement. Failing with a readable message beats a division-by-zero
   stack trace when someone inevitably pastes the wrong file into
   Snowflake.

---

### Blocker 3 — Legacy cleanup scripts will hard-fail

**Current state.** `sql/99_cleanup/` contains migration scripts from
the pre-RAW/ENHANCED/CURATED schema era. On a fresh Snowflake, two of
them cause trouble:

- `00_drop_public_objects.sql` — all `DROP IF EXISTS` statements, so
  harmless, but every object it references has never existed on a
  fresh deploy. Dead code.
- `01_rename_landing_tables.sql` — `ALTER TABLE PUBLIC.LANDING_* RENAME
  TO RAW.LANDING_*`. **This errors on fresh deploy** because
  `PUBLIC.LANDING_*` does not exist. If included in a deploy loop,
  Snowflake returns "SQL compilation error: Table PUBLIC.LANDING_RAW_POSTS
  does not exist" and the loop halts.

**Fix.** Delete both files:

```
sql/99_cleanup/00_drop_public_objects.sql
sql/99_cleanup/01_rename_landing_tables.sql
```

Keep `sql/99_cleanup/02_truncate_raw_data.sql` — it's a useful
operational reset script, not part of the deploy. One minor patch:
remove the two hardcoded `REMOVE @stage/demo_*.jsonl.gz` lines at
the top (lines 22-23); they only exist for an old demo flow and will
error if those specific files aren't staged.

---

### Legacy root-level files — delete

Three files at the project root are ad-hoc scratch pads from earlier
phases. They reference task names, schemas, or stages that no longer
exist. None is part of deploy.

```
cleanup.sql   # 0 bytes; empty
select.sql    # references TASK_ENRICH_POSTS, TASK_BUILD_ML_READY (old monolithic chain)
test.sql      # references PUBLIC.BLUESKY_*_STAGE, PUBLIC.LANDING_* (pre-migration schema)
```

Delete all three. If you want to keep a scratch pad for ad-hoc
queries, create a new one with the current schema names
(`RAW.LANDING_*`, `ENHANCED.TASK_*`).

Leave `docs/reference.sql` alone — it's the template project's
reference file, not something that runs against your database.

---

### Redundant file — optional delete

`sql/03_enhanced/02_add_severity_columns.sql` does
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS severity_max, redaction_count`.
Both columns are already in `00_posts_enriched_table.sql` as of the
Phase D profanity work. On a fresh deploy the ALTER is a no-op.

**Recommendation:** delete. The file was a one-shot migration for
already-deployed environments that pre-dated the refactor. Your
environment is fresh, so it has no reason to exist.

If you'd rather keep it defensively (in case you ever re-deploy
against an older Snowflake), that's fine — it's harmless.

---

### Stale comments — patch in place

These comments are out of date but not load-bearing. Fix them now
while you're editing the files, so the next engineer reading this
code gets an accurate picture.

**1.** `sql/00_setup/03_profanity_config.sql` (after the rename from
Blocker 2), header block, lines 3-4:

- Current: "Phase A of the profanity refactor — tables + seed rows only;
  the UDF in 03_udfs.sql is NOT rewritten here (Phase C)."
- Fix to: "Seeds ENHANCED.PROFANITY_TERMS (99 rows) and
  ENHANCED.PROFANITY_WHITELIST (14 rows). The rendered UDF in
  sql/00_setup/_generated/03_udfs.rendered.sql reads these values at
  deploy time via scripts/render_profanity_udf.py."

**2.** `sql/05_tasks/03_task_trend_match.sql` (or
`sql/06_tasks/03_task_trend_match.sql` after the folder rename),
footer comment block:

- Current: mentions "the old TASK_ENRICH_POSTS / TASK_BUILD_ML_READY
  chain in sql/05_tasks/00_tasks.sql stays RESUMED and continues to
  own POSTS_ENRICHED. These staging tasks run in PARALLEL pending the
  Phase C cutover."
- Fix to: "Resume order: children (TEXT_FEATURES, ACTOR_FEATURES,
  TREND_MATCH) first, then root (FLATTEN_LABELS). Snowflake requires
  child tasks to be RESUMED before their parent. The assembler and
  TASK_BUILD_ML_READY are resumed at the bottom of
  05_task_build_ml_ready.sql."

**3.** `sql/05_tasks/05_task_build_ml_ready.sql` (or
`sql/06_tasks/05_task_build_ml_ready.sql` after the folder rename),
footer comment block:

- Current: "RETIREMENT OF THE OLD MONOLITHIC CHAIN — RUN MANUALLY ...
  ALTER TASK ENHANCED.TASK_ENRICH_POSTS SUSPEND; DROP TASK ..."
- Fix to: **delete the entire retirement block** (~12 lines at the
  bottom). There is no old chain to retire on a fresh deploy. The
  `CREATE OR REPLACE TASK ENHANCED.TASK_BUILD_ML_READY` at the top
  of the file is the single source of truth now.

---

### Docs that also need updating

After all SQL changes above:

**`docs/SQL_FOLDER_OUTLINE.md`** — patch these sections:

- **Top-level folder map** — add `02_pipes/`, renumber
  `02_streams → 03_streams`, `03_enhanced → 04_enhanced`,
  `04_curated → 05_curated`, `05_tasks → 06_tasks`.
- **00_setup/ table** — remove the `02_pipes.sql` row (pipes have
  moved to their own folder); swap the order of `03_udfs.sql` and
  `04_profanity_config.sql` after the rename so the row labels match
  the new filenames (`03_profanity_config.sql` and `04_udfs_template.sql`).
- **"Key note on 03_udfs.sql"** paragraph — rewrite. Current text
  claims the profanity list is hardcoded and config-table backing
  is planned; in reality the config tables exist and the UDF is a
  template rendered from them. Point at `scripts/render_profanity_udf.py`.
- **99_cleanup/ table** — remove the two deleted files; keep
  `02_truncate_raw_data.sql` only.
- **Pain points section** — mark "Monolithic `TASK_ENRICH_POSTS`"
  and "Hardcoded profanity list" as resolved. Add a new entry if
  you want to track "Pipe deploy-order bug" → resolved in this pass.

**`docs/CLAUDE_PROMPTS_PROFANITY.md`, `docs/CLAUDE_PROMPTS_ENRICHMENT.md`,
`docs/CLAUDE_PROMPTS_DOCKER.md`** — any inline path reference like
`sql/00_setup/04_profanity_config.sql` or `sql/05_tasks/...` needs
updating to the new numbering. `grep -n` these docs for `sql/0` and
fix each hit.

---

### Deploy Order (to add to the runbook)

This is the exact sequence for a fresh Snowflake + the new folder
structure. Put this in `docs/SQL_DEPLOYMENT_SEQUENCE.md` (create or
replace that file as part of this work).

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

After step 25, Snowflake is ready. Start the Python side — firehose,
hydrate, trend scraper, trend matcher — and the chain runs
automatically when trend matches land.

---

### Acceptance checklist

Before merging these fixes:

- [ ] `find sql -type f -name '*.sql' | sort` shows files in the
      new numbered folder layout; no `02_pipes.sql` under `00_setup/`.
- [ ] `sql/00_setup/03_profanity_config.sql` exists (renamed);
      `sql/00_setup/04_udfs_template.sql` exists (renamed).
- [ ] `sql/99_cleanup/` contains only `02_truncate_raw_data.sql`.
- [ ] `cleanup.sql`, `select.sql`, `test.sql` at the project root
      are gone.
- [ ] `grep -rn "TASK_ENRICH_POSTS" sql/` returns no matches (only
      doc mentions in `docs/*.md` are OK).
- [ ] `grep -rn "sql/05_tasks/00_tasks.sql" .` returns no matches.
- [ ] `docs/SQL_FOLDER_OUTLINE.md` reflects the new folder layout.
- [ ] `docs/SQL_DEPLOYMENT_SEQUENCE.md` exists and matches the
      "Deploy Order" list above.
- [ ] `python scripts/render_profanity_udf.py --help` still works
      (no code change expected, just confirm we didn't break the path).
- [ ] A dry-run pass through the numbered deploy sequence above —
      each file opens cleanly, references the correct paths, and
      doesn't mention deleted files.

---

### Post-deploy fix: resume ordering

Surfaced during the first fresh deploy after this audit's changes
landed. With the original split (Phase-B resumes at the bottom of
`sql/06_tasks/03_task_trend_match.sql`, Phase-C resumes at the bottom
of `sql/06_tasks/05_task_build_ml_ready.sql`), re-running the deploy
to pick up a task-body change errored out with:

> Unable to update graph with root task ENHANCED.TASK_FLATTEN_LABELS
> since that root task is not suspended.

Snowflake refuses to modify any task inside a graph whose root task is
in the `started` state. Because `03_task_trend_match.sql` resumed the
root (`TASK_FLATTEN_LABELS`) before the assembler + build-ml-ready
tasks were even created, the next `CREATE OR REPLACE TASK
ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED` call — which adds a new node to
that same graph — got rejected.

**Fix.** Consolidate all `RESUME` statements into a single block at
the bottom of the last deploy file (`05_task_build_ml_ready.sql`).
That block covers every task in the DAG, in children-first order, and
only executes after every `CREATE OR REPLACE TASK` has landed:

```
ALTER TASK ENHANCED.TASK_BUILD_ML_READY           RESUME;
ALTER TASK ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED  RESUME;
ALTER TASK ENHANCED.TASK_TREND_MATCH              RESUME;
ALTER TASK ENHANCED.TASK_ACTOR_FEATURES           RESUME;
ALTER TASK ENHANCED.TASK_TEXT_FEATURES            RESUME;
ALTER TASK ENHANCED.TASK_FLATTEN_LABELS           RESUME;
```

The stale resume block (comment banner + four `ALTER TASK ... RESUME`
statements) at the bottom of `03_task_trend_match.sql` was removed
and replaced with a one-line pointer comment directing the reader to
`05_task_build_ml_ready.sql` for the resume sequence.

**Rule going forward.** All task graph mutations (`CREATE OR REPLACE`,
`ALTER ... SET`, etc.) must happen while the graph's root is
`suspended`. The single-block pattern enforces that: every deploy
re-runs each task DDL while the root is still suspended, then resumes
the graph in one shot at the very end.

---

### Triggered task (no SCHEDULE) on root

**Why.** The assignment forbids scheduled tasks — no `SCHEDULE` clause
anywhere in task DDL. Snowflake's *triggered task* feature lets us
satisfy that constraint while staying stream-event-driven: a task with
a `WHEN SYSTEM$STREAM_HAS_DATA(...)` predicate and **no** `SCHEDULE`
fires automatically whenever the referenced stream receives append
rows. That is exactly the shape we want — ingestion (Python → Snowpipe)
still lands rows into `RAW.LANDING_TREND_MATCHES`; the stream on that
table turns non-empty; Snowflake fires `TASK_FLATTEN_LABELS`; the
`AFTER`-chained descendants run.

**What changed.** On `sql/06_tasks/00_task_flatten_labels.sql`:
- Removed: `SCHEDULE = '1 MINUTE'`.
- Kept as-is: `WHEN SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_TREND_MATCHES')`.
- Added: a stream-drain temp table as the first statement inside the
  task body (see below).
- Header comment rewritten to document the triggered-task model.

Child tasks (`01_..05_*.sql`) and the stream file itself are unchanged.

**Why the stream-drain temp table exists.** A triggered task's
`WHEN SYSTEM$STREAM_HAS_DATA(...)` predicate stays TRUE until something
*consumes* the stream (any DML or DQL against it inside a transaction
advances its offset). Without a read of the stream inside the task
body, every run would leave the stream in the same "has data" state and
Snowflake would re-fire the task in a tight loop. The first statement
inside `BEGIN` is therefore:

```sql
CREATE OR REPLACE TEMPORARY TABLE _stream_drain_trend_matches AS
  SELECT COUNT(*) AS n FROM RAW.STRM_LANDING_TREND_MATCHES;
```

The temporary table is discarded when the task session ends; its only
purpose is to wrap a `SELECT` against the stream so the offset advances.
We use `COUNT(*)` rather than `SELECT *` so the drain is constant-time
regardless of batch size.

**How to verify after re-deploy.**
1. `SHOW TASKS IN SCHEMA BLUESKYDATAENGINEERINGPROJECT.ENHANCED;` — every
   row's `schedule` column must be `NULL`. The `predecessors` column
   separates root vs. children; the root row (`TASK_FLATTEN_LABELS`) will
   have an empty `predecessors` array and a non-null `condition` column
   containing the `WHEN SYSTEM$STREAM_HAS_DATA(...)` expression.
2. After the next Python trend-match run completes and Snowpipe ingests:
   ```sql
   SELECT name, state, scheduled_time, query_start_time, completed_time
   FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
     SCHEDULED_TIME_RANGE_START => DATEADD(hour, -1, CURRENT_TIMESTAMP())
   ))
   WHERE name IN ('TASK_FLATTEN_LABELS','TASK_TEXT_FEATURES','TASK_ACTOR_FEATURES',
                  'TASK_TREND_MATCH','TASK_ASSEMBLE_POSTS_ENRICHED','TASK_BUILD_ML_READY')
   ORDER BY scheduled_time DESC;
   ```
   Expect exactly one `SUCCEEDED` row per task per load cycle — not a
   1-minute cadence, and not a tight loop.

**Re-deploy command (paste once into Snowflake):**

```sql
USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

-- Snowflake refuses to modify a task graph while its root is resumed.
ALTER TASK ENHANCED.TASK_FLATTEN_LABELS SUSPEND;

-- Paste the full contents of sql/06_tasks/00_task_flatten_labels.sql
-- here (CREATE OR REPLACE TASK … WAREHOUSE = COMPUTE_WH
-- WHEN SYSTEM$STREAM_HAS_DATA(...) AS BEGIN … END;).

-- Resume footer from sql/06_tasks/05_task_build_ml_ready.sql
-- (children first, root last — Snowflake requirement):
ALTER TASK ENHANCED.TASK_BUILD_ML_READY           RESUME;
ALTER TASK ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED  RESUME;
ALTER TASK ENHANCED.TASK_TREND_MATCH              RESUME;
ALTER TASK ENHANCED.TASK_ACTOR_FEATURES           RESUME;
ALTER TASK ENHANCED.TASK_TEXT_FEATURES            RESUME;
ALTER TASK ENHANCED.TASK_FLATTEN_LABELS           RESUME;
```

**Python side.** `scripts/trigger_enrichment.py` stays in the repo but is
now marked deprecated — it is only useful for manual backfill runs
against already-landed data. Normal ingestion does not need to call it:
the triggered task handles that automatically.

---

### Out of scope

- Docker containerization — deferred until professor approval per
  current project direction.
- Further expanding the profanity word list — already at 99 terms,
  adequate for the demo.
- Rewriting the enrichment tasks — the split is in place and
  working; no further changes needed before the fresh run.
- `docs/reference.sql` — leave in place. It's reference material,
  not code we run.
