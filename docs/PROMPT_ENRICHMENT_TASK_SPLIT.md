# PROMPT_ENRICHMENT_TASK_SPLIT.md
## Claude-Extension Prompt — Split the Monolithic Enrichment Task

Paste this file's **Prompt** section into the Claude extension to drive
the refactor. The rest of this document is background for humans
reviewing or adjusting the prompt later.

---

### Why This Refactor

Today `ENHANCED.TASK_ENRICH_POSTS` is a single task that runs a
10-CTE, 38-column `MERGE INTO ENHANCED.POSTS_ENRICHED`. That is the
"god task" anti-pattern:

- Any failure (bad timestamp parse, unexpected label shape, UDF
  regression) rolls back **all** enrichment concerns in one shot.
- Warehouse profiling is coarse — impossible to tell whether the
  label flatten, the trend join, or the actor window is dominating
  runtime.
- Reruns are all-or-nothing. We cannot rebuild actor features after a
  profile reload without re-cleaning every post's text.
- Reading the SQL is slow — onboarding engineers have to load the
  whole CTE stack into their head.

Splitting the task into staged per-concern tasks, each writing to a
staging table, plus a final assembler that MERGEs them into
`ENHANCED.POSTS_ENRICHED`, gives us: independent reruns, per-concern
observability, smaller PR surface area for future changes, and
atomic-per-concern error handling.

---

### Target Topology

```
RAW.STRM_LANDING_TREND_MATCHES
        │ WHEN stream has data
        ▼
TASK_STG_FLATTEN_LABELS      → ENHANCED.STG_POST_LABELS
        │
        ├──▶ TASK_STG_TEXT_FEATURES     → ENHANCED.STG_POST_TEXT_FEATURES
        │        (calls CLEAN_PROFANITY + text regex counts)
        │
        ├──▶ TASK_STG_ACTOR_FEATURES    → ENHANCED.STG_ACTOR_FEATURES
        │        (follower tier, age, ratios, bot flags)
        │
        └──▶ TASK_STG_TREND_MATCH       → ENHANCED.STG_POST_TREND_MATCH
                 (join trend_matches to canonical trends)
                          │
                          ▼
                 TASK_ASSEMBLE_POSTS_ENRICHED (MERGE all staging tables)
                          │
                          ▼
                 TASK_BUILD_ML_READY (unchanged, AFTER assembler)
```

Each `STG_*` table is a **materialized** table (not a view) so reruns
of downstream tasks don't re-execute upstream CTEs. Each staging table
has `uri` (or `did` for actor) as the primary identity column and a
`stg_computed_at` timestamp.

Staging tables we will create (all in `ENHANCED`):

| Table | Grain | Columns |
|---|---|---|
| `STG_POST_LABELS` | 1 row per post uri | `uri`, `is_adult_content`, `has_moderation_flag`, `moderation_label_count`, `stg_computed_at` |
| `STG_POST_TEXT_FEATURES` | 1 row per post uri | `uri`, `post_text_clean`, `was_profanity_redacted`, `post_length`, `post_word_count`, `hashtag_count`, `mention_count`, `url_count`, `exclamation_count`, `question_count`, `stg_computed_at` |
| `STG_ACTOR_FEATURES` | 1 row per did | `did`, `followers_count`, `follows_count`, `posts_count`, `follower_tier`, `account_age_days`, `follow_follower_ratio`, `posts_per_day`, `has_actor_label`, `is_bot_suspect`, `is_spam_suspect`, `stg_computed_at` |
| `STG_POST_TREND_MATCH` | 1 row per post uri (only if matched) | `post_uri`, `matched_trend_name`, `matched_trend_date`, `matched_tweet_volume`, `matched_trend_rank`, `trend_match_method`, `trend_match_score`, `stg_computed_at` |

The assembler does the final `MERGE` into `ENHANCED.POSTS_ENRICHED`
and keeps the existing moderation filter
(`is_adult_content = FALSE AND is_bot_suspect = FALSE AND post_text_clean IS NOT NULL`).

---

### Prompt (paste into Claude extension)

> You are implementing a refactor of the Bluesky Snowflake pipeline.
> The authoritative map of the SQL folder is `docs/SQL_FOLDER_OUTLINE.md` —
> read it first. The current monolithic task is `sql/05_tasks/00_tasks.sql`
> (`ENHANCED.TASK_ENRICH_POSTS`). Do not change behavior that the
> existing task produces — every column currently in
> `ENHANCED.POSTS_ENRICHED` must still be populated with the same
> values after the refactor.
>
> **Goal.** Replace the single `TASK_ENRICH_POSTS` with a fan-out of
> per-concern staging tasks plus a final assembler task, writing to
> staging tables in the `ENHANCED` schema. The task chain still fires
> on `RAW.STRM_LANDING_TREND_MATCHES` and
> `TASK_BUILD_ML_READY` still runs `AFTER` the assembler.
>
> **Work to do, in order:**
>
> 1. **Create the staging tables.** Add a new file
>    `sql/03_enhanced/01_staging_tables.sql` that creates four
>    `CREATE OR REPLACE TABLE` statements in `ENHANCED`:
>    `STG_POST_LABELS`, `STG_POST_TEXT_FEATURES`, `STG_ACTOR_FEATURES`,
>    `STG_POST_TREND_MATCH`. Use the column specs in the "Target
>    Topology" table of `docs/PROMPT_ENRICHMENT_TASK_SPLIT.md`. Every
>    staging table has a `stg_computed_at TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP`
>    column. Include `COMMENT = '...'` on each table explaining its
>    grain and owner task.
>
> 2. **Split the task file.** Replace
>    `sql/05_tasks/00_tasks.sql` with a new layout:
>    - `sql/05_tasks/00_task_flatten_labels.sql` — parent task, fires
>      on `SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_TREND_MATCHES')`.
>      `TRUNCATE` then `INSERT` into `ENHANCED.STG_POST_LABELS` using
>      the `hydrated_latest` + `hydrated_labels_latest` CTEs from the
>      current task (lines 94–123 of the old file). Add
>      `has_moderation_flag` (ARRAY_SIZE(labels) > 0) and
>      `moderation_label_count` (ARRAY_SIZE(labels)) to the INSERT.
>    - `sql/05_tasks/01_task_text_features.sql` — child task,
>      `AFTER ENHANCED.TASK_FLATTEN_LABELS`. `TRUNCATE` + `INSERT`
>      into `ENHANCED.STG_POST_TEXT_FEATURES` using the
>      `raw_posts_latest` + `post_text_cleaned` logic, plus the text
>      regex features from `merge_source` (post_length,
>      post_word_count, hashtag_count, mention_count, url_count,
>      exclamation_count, question_count).
>    - `sql/05_tasks/02_task_actor_features.sql` — child task,
>      `AFTER ENHANCED.TASK_FLATTEN_LABELS` (runs in parallel with
>      text_features). `TRUNCATE` + `INSERT` into
>      `ENHANCED.STG_ACTOR_FEATURES` using the current
>      `actor_latest_normalized` CTE plus the bot_suspect and
>      spam_suspect boolean expressions from `merge_source`.
>    - `sql/05_tasks/03_task_trend_match.sql` — child task,
>      `AFTER ENHANCED.TASK_FLATTEN_LABELS` (parallel with the other
>      two). `TRUNCATE` + `INSERT` into `ENHANCED.STG_POST_TREND_MATCH`
>      using `trend_matches_latest` + `twitter_trends_canonical` +
>      `trend_enriched` CTEs. Insert only rows where a match exists
>      (no `has_trend_match = FALSE` rows — that's derived later).
>    - `sql/05_tasks/04_task_assemble_posts_enriched.sql` — child
>      task, `AFTER ENHANCED.TASK_TEXT_FEATURES`,
>      `AFTER ENHANCED.TASK_ACTOR_FEATURES`, and
>      `AFTER ENHANCED.TASK_TREND_MATCH` (declared as a list of
>      predecessors — Snowflake supports DAG-style AFTER). This task
>      does the `MERGE INTO ENHANCED.POSTS_ENRICHED` by LEFT JOINing
>      all four staging tables onto `STG_POST_TEXT_FEATURES` (which
>      is the identity set — one row per uri) and `STG_POST_LABELS`.
>      The moderation filter stays on this final MERGE.
>    - `sql/05_tasks/05_task_build_ml_ready.sql` — same
>      `TASK_BUILD_ML_READY` as before but now
>      `AFTER ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED`.
>
> 3. **Get the deploy order right.** At the bottom of the last task
>    file, resume tasks in reverse-dependency order (leaves first,
>    root last): `TASK_BUILD_ML_READY` → `TASK_ASSEMBLE_POSTS_ENRICHED`
>    → each of the three parallel children → `TASK_FLATTEN_LABELS`.
>    Snowflake requires a child be RESUMED before a parent can
>    reference it.
>
> 4. **Write validation SQL.** Add
>    `sql/99_validation/00_enrichment_split.sql` with row-count
>    equivalence checks: every uri in `STG_POST_TEXT_FEATURES` should
>    appear in `STG_POST_LABELS` (LEFT JOIN count), the row count of
>    `POSTS_ENRICHED` should equal the filtered count from
>    `STG_POST_TEXT_FEATURES`, and distribution of `follower_tier`,
>    `is_bot_suspect`, `has_trend_match` should match the pre-split
>    run (capture a baseline before running the refactor). Include
>    the baseline capture query commented at the top.
>
> 5. **Update the deployment sequence doc.** Edit
>    `docs/SQL_DEPLOYMENT_SEQUENCE.md` to reference the new task
>    filenames and the new staging-tables file. Do not rewrite the
>    whole doc — just patch the deployment-order list.
>
> 6. **Update the outline.** Edit `docs/SQL_FOLDER_OUTLINE.md` — the
>    `05_tasks/` section and the pain-points section ("Monolithic
>    `TASK_ENRICH_POSTS`" moves from "open" to a reference to this
>    refactor).
>
> **Constraints:**
> - Do not change `ENHANCED.POSTS_ENRICHED` or `CURATED.ML_READY`
>   column lists. Downstream code (the Python model trainer, the
>   Snowflake runbook docs) assumes the existing schema.
> - Do not change the `CLEAN_PROFANITY` UDF — that's a separate
>   refactor (`docs/PROMPT_PROFANITY_EXPANSION.md`).
> - Preserve the moderation filter on the assembler's final MERGE.
> - Preserve the stream trigger on the root task — the chain must
>   still only fire once trend matches have landed.
> - Every task sets `WAREHOUSE = COMPUTE_WH`.
> - Every staging-populating task does `TRUNCATE` then `INSERT`, not
>   `MERGE`. Staging tables are rebuilt every run; only the final
>   assembler uses `MERGE` (so `POSTS_ENRICHED.enriched_at` is stable
>   across reruns when nothing changed).
>
> **What to return:**
> - The five new task files and the staging-tables file (all under
>   `sql/`).
> - The updated `docs/SQL_DEPLOYMENT_SEQUENCE.md` and
>   `docs/SQL_FOLDER_OUTLINE.md`.
> - The new `sql/99_validation/00_enrichment_split.sql`.
> - A short section in your final message listing any CTE logic that
>   had to be duplicated across staging tasks (we want to know where
>   DRY was sacrificed so we can audit it).
>
> Ask before you start if any of the following is unclear: the
> `has_actor_label` flag's role in bot detection, how
> `matched_trend_date` joins when the trend-match post_uri is not in
> `raw_posts_latest`, or whether parallel children should share a
> warehouse or each have their own (default: share `COMPUTE_WH`).

---

### Acceptance Checklist (for the human reviewer)

- [ ] `SHOW TABLES IN SCHEMA ENHANCED` includes the four new
      `STG_*` tables.
- [ ] `SHOW TASKS IN SCHEMA ENHANCED` shows the six-task chain, all
      `state = 'started'`.
- [ ] Row counts in `POSTS_ENRICHED` after the refactor match the
      baseline captured before it (within a tolerance of 0 rows —
      the moderation filter is identical).
- [ ] The parallel children (`TASK_TEXT_FEATURES`,
      `TASK_ACTOR_FEATURES`, `TASK_TREND_MATCH`) actually run in
      parallel — check `TASK_HISTORY` to confirm overlapping
      `scheduled_time` → `completed_time` windows.
- [ ] A forced rerun of just `TASK_ACTOR_FEATURES` (via
      `EXECUTE TASK`) does not disturb `STG_POST_TEXT_FEATURES` or
      `STG_POST_LABELS`.
- [ ] `sql/99_validation/00_enrichment_split.sql` passes every
      assertion.

---

### Out of Scope (Track Separately)

- Profanity list expansion — see `docs/PROMPT_PROFANITY_EXPANSION.md`.
- Containerizing the Python ingest/hydrate/match pieces — see
  `docs/PROMPT_DOCKER_PRODUCTION.md`.
- Moving validation from `/* ... */` comments to real scripts in
  `99_validation/` is done incidentally for this refactor but a full
  sweep is a separate task.
