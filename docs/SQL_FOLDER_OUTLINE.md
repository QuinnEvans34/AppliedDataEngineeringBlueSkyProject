# SQL_FOLDER_OUTLINE.md
## Full Outline of `sql/` — Bluesky Data Engineering Project

This document is the authoritative map of everything that lives under
`sql/`. It is the reference to cite in refactor prompts, onboarding
docs, and deployment runbooks. When you add, rename, move, or delete a
file in `sql/`, update this doc in the same PR.

---

### Design Principles

1. **Numbered subfolders encode deployment order.** `00_setup` is
   first; `99_cleanup` is last. A human reading the directory should
   be able to infer the sequence without opening any file.
2. **Schema separation is load-bearing.** `RAW` owns landed data,
   `ENHANCED` owns derived/cleaned feature tables and UDFs, `CURATED`
   owns ML-ready outputs. Nothing in `ENHANCED` reads from `CURATED`.
3. **Stream-driven, not time-driven.** The root task
   `TASK_FLATTEN_LABELS` is a Snowflake *triggered task* — it has no
   `SCHEDULE` (the assignment forbids scheduled tasks), only a
   `WHEN SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_TREND_MATCHES')`
   predicate. Snowflake fires it automatically when the Snowpipe-fed
   trend-match stream receives append rows, and the task body drains the
   stream so it doesn't re-fire on the same data. See
   `docs/SQL_AUDIT_FIXES.md` → "Triggered task (no SCHEDULE) on root".
4. **Every object has one home file.** If a UDF, stream, or task is
   created in more than one place, that is a bug.

---

### Top-Level Folder Map

```
sql/
├── 00_setup/        Infrastructure — database, file formats, stages, profanity config, UDF template
├── 01_landing/      RAW.LANDING_* tables (append-only, VARIANT payloads)
├── 02_pipes/        Snowpipes that COPY INTO RAW.LANDING_* (deploys after landing tables)
├── 03_streams/      APPEND_ONLY streams that signal readiness for enrichment
├── 04_enhanced/     ENHANCED.POSTS_ENRICHED — the derived feature table
├── 05_curated/      CURATED.ML_READY — the labeled, split, ML-facing table
├── 06_tasks/        Task chain that drives 04 + 05 populations
├── 99_cleanup/      Truncate utility (one-shot operational reset)
└── 99_validation/   Post-deploy smoke tests (profanity unit tests, etc.)
```

---

### 00_setup/ — Infrastructure

These files establish the database, file formats, stages, profanity
config tables, and the UDF template that everything downstream depends
on. Snowpipes are deployed separately under `02_pipes/` (see below) so
they sequence after the landing tables.

| File | Creates | Depends on |
|---|---|---|
| `00_bootstrap_database_schema.sql` | Database `BLUESKYDATAENGINEERINGPROJECT`; schemas `RAW`, `ENHANCED`, `CURATED` | Nothing (bootstrap) |
| `00_file_formats.sql` | `RAW.BLUESKY_JSONL_GZ` (JSON, gzip, JSONL); `RAW.LOADER_FILE_MANIFEST` audit table | `RAW` schema |
| `01_internal_stages.sql` | Six internal stages in `RAW`: `BLUESKY_RAW_POSTS_STAGE`, `BLUESKY_HYDRATED_POSTS_STAGE`, `BLUESKY_HYDRATION_MISSES_STAGE`, `BLUESKY_ACTOR_PROFILES_STAGE`, `BLUESKY_TWITTER_TRENDS_STAGE`, `BLUESKY_TREND_MATCHES_STAGE` | File format |
| `03_profanity_config.sql` | `ENHANCED.PROFANITY_TERMS` (99 seed rows across mild/strong/sexual/slur) and `ENHANCED.PROFANITY_WHITELIST` (14 false-positive substrings). Backing store for the rendered `CLEAN_PROFANITY` UDF. | `ENHANCED` schema |
| `04_udfs_template.sql` | Template for `ENHANCED.CLEAN_PROFANITY(post_text STRING) RETURNS OBJECT` (JavaScript UDF, URL-preserving). Not runnable as-is — must be rendered. | `03_profanity_config.sql` (seeds the rows the renderer reads) |

**Key note on `04_udfs_template.sql`.** This file is a template, not a
runnable script. It contains placeholder tokens for the term list and
whitelist that are substituted at deploy time by
`scripts/render_profanity_udf.py --from-snowflake`, which reads the
seeded rows from `ENHANCED.PROFANITY_TERMS` and
`ENHANCED.PROFANITY_WHITELIST` and writes the runnable output to
`sql/00_setup/_generated/03_udfs.rendered.sql`. Running the template
file directly is guarded by a `TO_VARIANT(PARSE_JSON(...))` row that
returns a human-readable instruction message instead of executing the
function definition.

---

### 01_landing/ — RAW Landing Tables

All six landing tables share the same shape and ingest pattern:
append-only, VARIANT payload, metadata columns for audit/traceability,
no deduplication, no primary key beyond `landing_id`. Dedup happens
downstream in the enrichment task via `QUALIFY ROW_NUMBER()`.

| File | Table | Holds |
|---|---|---|
| `00_landing_raw_posts.sql` | `RAW.LANDING_RAW_POSTS` | Raw firehose post records |
| `01_landing_hydrated_posts.sql` | `RAW.LANDING_HYDRATED_POSTS` | Engagement counts + moderation labels |
| `02_landing_hydration_misses.sql` | `RAW.LANDING_HYDRATION_MISSES` | Posts that failed to hydrate |
| `03_landing_actor_profiles.sql` | `RAW.LANDING_ACTOR_PROFILES` | Author profile snapshots |
| `04_landing_twitter_trends.sql` | `RAW.LANDING_TWITTER_TRENDS` | Daily Twitter/X trend snapshots |
| `05_landing_trend_matches.sql` | `RAW.LANDING_TREND_MATCHES` | Python FAISS vector-match results |

**Common schema (all six):**

```
landing_id               NUMBER AUTOINCREMENT PRIMARY KEY
raw_payload              VARIANT                  -- the JSON row
source_filename          STRING                   -- METADATA$FILENAME
source_file_row_number   NUMBER                   -- METADATA$FILE_ROW_NUMBER
source_run_tag           STRING                   -- pipeline run grouping
dataset_family           STRING NOT NULL          -- 'raw_posts', 'hydrated_posts', etc.
load_invocation_id       STRING                   -- single COPY INTO invocation
loaded_at                TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP
```

---

### 02_pipes/ — Snowpipes

Lives in its own numbered folder so it deploys *after* `01_landing/`
(its `COPY INTO` targets are `RAW.LANDING_*`, which must exist first).

| File | Creates | Depends on |
|---|---|---|
| `00_pipes.sql` | Six Snowpipes (one per stage → landing table), `AUTO_INGEST = TRUE`, `ON_ERROR = 'CONTINUE'`, capturing `METADATA$FILENAME` and `METADATA$FILE_ROW_NUMBER` | `01_landing/` tables + `00_setup/01_internal_stages.sql` |

---

### 03_streams/ — Readiness Signals

| File | Streams |
|---|---|
| `00_streams.sql` | `RAW.STRM_LANDING_RAW_POSTS`, `RAW.STRM_LANDING_HYDRATED_POSTS`, `RAW.STRM_LANDING_ACTOR_PROFILES`, `RAW.STRM_LANDING_TREND_MATCHES` — all `APPEND_ONLY = TRUE` |

**Trigger stream vs observability streams.** As of the "Triggered task
(no SCHEDULE) on root" refactor (see `docs/SQL_AUDIT_FIXES.md`), the four
streams split cleanly by role:

- **Trigger stream — `RAW.STRM_LANDING_TREND_MATCHES`.** Referenced by
  the root task `TASK_FLATTEN_LABELS` in its
  `WHEN SYSTEM$STREAM_HAS_DATA(...)` predicate. Every time the Snowpipe
  that loads `RAW.LANDING_TREND_MATCHES` appends rows, the stream becomes
  non-empty and Snowflake fires the task. The task body issues a
  `SELECT COUNT(*) FROM RAW.STRM_LANDING_TREND_MATCHES` into a temporary
  table so the stream offset advances and the task does not re-fire on
  the same rows. This stream must exist before `06_tasks/` is deployed —
  Snowflake validates the reference at `CREATE TASK` time.
- **Observability-only — the other three
  (`STRM_LANDING_RAW_POSTS`, `STRM_LANDING_HYDRATED_POSTS`,
  `STRM_LANDING_ACTOR_PROFILES`).** No task consumes them. Operators can
  still run `SELECT SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_RAW_POSTS');`
  (or the others) to check ad-hoc whether new data has landed since the
  last poll. These three can be dropped at any time with no downstream
  impact; they are kept today as cheap signals for the Python
  orchestrator's health checks.

Trend matches are the last input to arrive per run (raw posts → hydrated
posts + actor profiles → trend matches, all PUT from Python in that
sequence), so gating on `STRM_LANDING_TREND_MATCHES` guarantees the other
three inputs are already in their landing tables before enrichment
begins.

---

### 04_enhanced/ — Derived Feature Table

#### `00_posts_enriched_table.sql` — `ENHANCED.POSTS_ENRICHED` (41 cols)

Column groups:

- **Identity (3):** `uri`, `repo_did`, `author_did`
- **Clean text (2):** `post_text_clean`, `was_profanity_redacted` — outputs of `CLEAN_PROFANITY()`
- **Engagement (5):** `reply_count`, `repost_count`, `like_count`, `quote_count`, `engagement_total`
- **Text features (7):** `post_length`, `post_word_count`, `hashtag_count`, `mention_count`, `url_count`, `exclamation_count`, `question_count`
- **Temporal (3):** `post_created_at_ts`, `post_hour_utc`, `post_day_of_week`
- **Moderation (3):** `is_adult_content`, `has_moderation_flag`, `moderation_label_count`
- **Actor (7):** `followers_count`, `follows_count`, `posts_count`, `follower_tier`, `account_age_days`, `follow_follower_ratio`, `posts_per_day`
- **Bot detection (2):** `is_bot_suspect`, `is_spam_suspect`
- **Trend match (7):** `has_trend_match`, `matched_trend_name`, `matched_trend_date`, `matched_tweet_volume`, `matched_trend_rank`, `trend_match_method`, `trend_match_score`
- **Profanity (2):** `severity_max`, `redaction_count` — extra outputs of `CLEAN_PROFANITY()`; `severity_max` is promoted to `ML_READY`, `redaction_count` stays here for debugging
- **Audit (1):** `enriched_at`

The table is populated by `ENHANCED.TASK_ENRICH_POSTS` via `MERGE INTO`.

#### `01_staging_tables.sql` — Four `ENHANCED.STG_*` staging tables

Per-concern staging tables backing the enrichment split (Phase A of
`docs/CLAUDE_PROMPTS_ENRICHMENT.md`). All four are created empty; Phase
B introduces the per-concern tasks that `TRUNCATE + INSERT` into them,
and Phase C's assembler `MERGE`s them into `POSTS_ENRICHED`. The old
monolithic `TASK_ENRICH_POSTS` continues to own `POSTS_ENRICHED` until
Phase C retires it.

| Table | Grain | Future owner task | Columns |
|---|---|---|---|
| `STG_POST_LABELS` | 1 row per post `uri` | `TASK_FLATTEN_LABELS` | `uri`, `is_adult_content`, `has_moderation_flag`, `moderation_label_count`, `stg_computed_at` |
| `STG_POST_TEXT_FEATURES` | 1 row per post `uri` | `TASK_TEXT_FEATURES` | `uri`, `post_text_clean`, `was_profanity_redacted`, `post_length`, `post_word_count`, `hashtag_count`, `mention_count`, `url_count`, `exclamation_count`, `question_count`, `stg_computed_at` |
| `STG_ACTOR_FEATURES` | 1 row per `did` | `TASK_ACTOR_FEATURES` | `did`, `followers_count`, `follows_count`, `posts_count`, `follower_tier`, `account_age_days`, `follow_follower_ratio`, `posts_per_day`, `has_actor_label`, `is_bot_suspect`, `is_spam_suspect`, `stg_computed_at` |
| `STG_POST_TREND_MATCH` | 1 row per matched `post_uri` (unmatched excluded) | `TASK_TREND_MATCH` | `post_uri`, `matched_trend_name`, `matched_trend_date`, `matched_tweet_volume`, `matched_trend_rank`, `trend_match_method`, `trend_match_score`, `stg_computed_at` |

Every table uses `CREATE OR REPLACE TABLE` (tables are fully owned by
their populating task once Phase B lands — drop-and-recreate is safe).

---

### 05_curated/ — ML-Ready Output

#### `00_ml_ready_table.sql` — `CURATED.ML_READY` (21 cols)

This is what the model consumes. No identifiers, no raw text, only
numeric + categorical features plus target label + split assignment.

- **Target:** `engagement_label` (LOW/MEDIUM/HIGH via `NTILE(3)` on
  `engagement_total`), `engagement_total` (raw count, coalesced to 0)
- **Text (7):** pass-through from `POSTS_ENRICHED`
- **Temporal (2):** `post_hour_utc`, `post_day_of_week`
- **Actor (5):** `followers_count`, `follower_tier`, `account_age_days`, `follow_follower_ratio`, `posts_per_day`
- **Trend (3):** `has_trend_match`, `matched_tweet_volume` (→0), `matched_trend_rank` (→999)
- **Profanity (1):** `severity_max` — categorical tier from `CLEAN_PROFANITY()` (`mild`/`strong`/`sexual`/`slur`, NULL when nothing redacted)
- **Split:** `dataset_split` — deterministic `HASH(uri)` 80/20 train/test

Populated by `ENHANCED.TASK_BUILD_ML_READY` via `TRUNCATE + INSERT`.

---

### 06_tasks/ — Orchestration Chain

Six-node DAG after the Phase C cutover. Each task owns a single
concern; the assembler joins the four staging tables into
`POSTS_ENRICHED`, and `TASK_BUILD_ML_READY` chains after it.

```
ENHANCED.TASK_FLATTEN_LABELS            (root, triggered task — no SCHEDULE)
        │
        ├── ENHANCED.TASK_TEXT_FEATURES    (parallel child)
        ├── ENHANCED.TASK_ACTOR_FEATURES   (parallel child)
        └── ENHANCED.TASK_TREND_MATCH      (parallel child)
                       │
                       ▼  (all three predecessors)
        ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED
                       │
                       ▼
        ENHANCED.TASK_BUILD_ML_READY
```

**`00_task_flatten_labels.sql` — `ENHANCED.TASK_FLATTEN_LABELS`**
- Warehouse: `COMPUTE_WH`. No `SCHEDULE`. Keeps `WHEN SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_TREND_MATCHES')` — Snowflake's *triggered task* model. Snowflake fires the task whenever the trend-match stream receives appended rows from its Snowpipe; the task body includes a `SELECT` against the stream that advances its offset so the task does not re-fire on the same data.
- Body: stream-drain (temp table) + `TRUNCATE` + `INSERT` into `ENHANCED.STG_POST_LABELS`.
- CTEs: `hydrated_latest` + `hydrated_labels_latest`. Writes `(uri, is_adult_content, has_moderation_flag, moderation_label_count)`.

**`01_task_text_features.sql` — `ENHANCED.TASK_TEXT_FEATURES`**
- Warehouse: `COMPUTE_WH`, `AFTER ENHANCED.TASK_FLATTEN_LABELS`.
- Body: `TRUNCATE` + `INSERT` into `ENHANCED.STG_POST_TEXT_FEATURES`.
- CTEs: `raw_posts_latest` + `post_text_cleaned` (calls `CLEAN_PROFANITY()`). Writes `(uri, post_text_clean, was_profanity_redacted, post_length, post_word_count, hashtag_count, mention_count, url_count, exclamation_count, question_count)`.

**`02_task_actor_features.sql` — `ENHANCED.TASK_ACTOR_FEATURES`**
- Warehouse: `COMPUTE_WH`, `AFTER ENHANCED.TASK_FLATTEN_LABELS` (parallel with TEXT_FEATURES and TREND_MATCH).
- Body: `TRUNCATE` + `INSERT` into `ENHANCED.STG_ACTOR_FEATURES`.
- CTE: `actor_latest_normalized` + `is_bot_suspect` / `is_spam_suspect` booleans.

**`03_task_trend_match.sql` — `ENHANCED.TASK_TREND_MATCH`**
- Warehouse: `COMPUTE_WH`, `AFTER ENHANCED.TASK_FLATTEN_LABELS` (parallel).
- Body: `TRUNCATE` + `INSERT` into `ENHANCED.STG_POST_TREND_MATCH`.
- CTEs: `trend_matches_latest` + `twitter_trends_canonical` + `trend_enriched`. Matched-only grain (unmatched posts never appear in `LANDING_TREND_MATCHES`).
- No resume block in this file — the full-chain `RESUME` sequence lives at the bottom of `05_task_build_ml_ready.sql`.

**`04_task_assemble_posts_enriched.sql` — `ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED`**
- Warehouse: `COMPUTE_WH`, `AFTER ENHANCED.TASK_TEXT_FEATURES, ENHANCED.TASK_ACTOR_FEATURES, ENHANCED.TASK_TREND_MATCH` (three-predecessor DAG join).
- Body: `MERGE INTO ENHANCED.POSTS_ENRICHED` with identity set `STG_POST_TEXT_FEATURES`, `LEFT JOIN`s to the other three staging tables plus deduped `RAW.LANDING_RAW_POSTS` (for `repo_did` / `post_created_at_*`) and `RAW.LANDING_HYDRATED_POSTS` (for `author_did` / engagement counts). Recomputes `severity_max` / `redaction_count` via `CLEAN_PROFANITY()` since those columns are not stored in `STG_POST_TEXT_FEATURES`.
- Moderation filter stays on this final MERGE: `is_adult_content = FALSE AND is_bot_suspect = FALSE AND post_text_clean IS NOT NULL AND post_text_clean != ''`.
- Writes 40 columns (`enriched_at = CURRENT_TIMESTAMP()`).

**`05_task_build_ml_ready.sql` — `ENHANCED.TASK_BUILD_ML_READY`**
- Warehouse: `COMPUTE_WH`, `AFTER ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED`.
- Body: `TRUNCATE TABLE CURATED.ML_READY` then `INSERT INTO ... SELECT` with `NTILE(3)` label and `HASH(uri)` 80/20 split.
- **Bottom of this file** holds the full-chain `RESUME` sequence — all six tasks resumed in children-first order (leaf tasks up through the root `TASK_FLATTEN_LABELS`).

**Deployment order:** Snowflake refuses to modify a task graph whose
root is already RESUMED ("Unable to update graph with root task … since
that root task is not suspended"), so the resume block is consolidated
at the bottom of the last deploy file (`05_task_build_ml_ready.sql`)
and run *after* every `CREATE OR REPLACE TASK` has landed. Children
are resumed before the root within that block as Snowflake requires.

---

### 99_cleanup/ — One-Shot Reset Utility

| File | Purpose | When to run |
|---|---|---|
| `02_truncate_raw_data.sql` | `REMOVE @stage` + `TRUNCATE TABLE` across all RAW tables and downstream feature tables | Full pipeline reload — keeps infrastructure, drops data |

This is a **destructive**, **one-shot** operation. Do not put it in CI.
Do not schedule it. Execute by hand with the deliberate confirmation
step documented in `docs/SQL_DEPLOYMENT_SEQUENCE.md`.

---

### 99_validation/ — Post-Deploy Smoke Tests

| File | Purpose | When to run |
|---|---|---|
| `00_enrichment_split.sql` | Baseline-capture + post-refactor assertion block for the Phase C cutover (row counts, `follower_tier`/`has_trend_match`/`is_bot_suspect` distributions, and staging-to-enriched equivalence check) | Before dropping `TASK_ENRICH_POSTS`, capture baseline; after the new chain fires, diff against it |
| `01_profanity_unit_tests.sql` | Unit tests for the `CLEAN_PROFANITY` UDF | After editing the UDF or its term tables |

---

### Data Flow at a Glance

```
 Local JSONL.gz files
          │
          ▼  PUT @stage
   RAW stages (6)
          │
          ▼  Snowpipe AUTO_INGEST
   RAW.LANDING_* tables (6)
          │
          ▼  APPEND_ONLY streams — STRM_LANDING_TREND_MATCHES is the task trigger;
   RAW.STRM_LANDING_* (4)          the other three are observability-only
          │
          ▼  triggered TASK_FLATTEN_LABELS fires on STRM_LANDING_TREND_MATCHES append
   ENHANCED.STG_POST_LABELS
          │
          ▼  three parallel children fire AFTER FLATTEN_LABELS
   ENHANCED.STG_POST_TEXT_FEATURES
   ENHANCED.STG_ACTOR_FEATURES
   ENHANCED.STG_POST_TREND_MATCH
          │
          ▼  TASK_ASSEMBLE_POSTS_ENRICHED joins all four (MERGE)
   ENHANCED.POSTS_ENRICHED
          │
          ▼  TASK_BUILD_ML_READY chains AFTER assembler
   CURATED.ML_READY (TRUNCATE + INSERT)
          │
          ▼
   Model training (Python, outside SQL)
```

---

### Pain Points Worth Tracking

1. **No containerization.** The Python firehose/hydration/trend
   matcher pieces run on the host venv. Not reproducible across
   machines, not production-deployable. Plan in
   `docs/PROMPT_DOCKER_PRODUCTION.md`.
2. **Validation is inline.** Each file has a `/* ... */` block of
   validation SQL that only runs if a human copy-pastes it. Worth
   formalizing into `99_validation/` scripts that CI can execute.

**Resolved**

- ~~Pipe deploy-order bug.~~ Resolved in `docs/SQL_AUDIT_FIXES.md`
  (2026-04-19). The Snowpipes file used to live at
  `sql/00_setup/02_pipes.sql` but its `COPY INTO` statements reference
  `RAW.LANDING_*` tables created in `01_landing/`, so a deploy walking
  folders in numeric order rejected every `CREATE PIPE` with "table
  does not exist". Moved to `sql/02_pipes/00_pipes.sql` so numeric
  sort still equals deploy order.
- ~~Schema migration files persisting in `99_cleanup/`.~~ Resolved in
  `docs/SQL_AUDIT_FIXES.md` (2026-04-19). The two pre-RAW/ENHANCED/CURATED
  migration files (`00_drop_public_objects.sql`,
  `01_rename_landing_tables.sql`) were deleted on the fresh-deploy pass.
  Only `02_truncate_raw_data.sql` remains.
- ~~Hardcoded profanity list.~~ Resolved in `docs/CLAUDE_PROMPTS_PROFANITY.md`
  Phases A–D (2026-04-19). Terms now live in `ENHANCED.PROFANITY_TERMS`
  with severity tiers and a `PROFANITY_WHITELIST` for false positives;
  the UDF body is a template rendered by
  `scripts/render_profanity_udf.py`; `severity_max` and `redaction_count`
  flow through to `POSTS_ENRICHED`, and `severity_max` becomes a
  categorical feature in `ML_READY`.
- ~~Monolithic `TASK_ENRICH_POSTS`.~~ Resolved in `docs/CLAUDE_PROMPTS_ENRICHMENT.md`
  Phases A–C (2026-04-19). The 10-CTE / 40-column MERGE is now split
  across six tasks (`TASK_FLATTEN_LABELS` → three parallel per-concern
  populators → `TASK_ASSEMBLE_POSTS_ENRICHED` → `TASK_BUILD_ML_READY`)
  with four `ENHANCED.STG_*` staging tables between them. Per-concern
  reruns are possible, failures no longer roll back the whole pipeline.

---

### Conventions to Keep

- Numbered prefixes on filenames (`00_`, `01_`, `02_`) inside every
  subfolder — they drive both sort order and deployment sequence.
- Fully qualified object names in DDL (`BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY(...)`).
  Never rely on `USE SCHEMA` alone for created-object identity.
- Validation queries in `/* ... */` comment blocks at the bottom of
  every non-trivial file, until `99_validation/` is built out.
- Suspend the warehouse (`ALTER WAREHOUSE COMPUTE_WH SUSPEND;`) at
  the end of any ad-hoc session — credits matter.
