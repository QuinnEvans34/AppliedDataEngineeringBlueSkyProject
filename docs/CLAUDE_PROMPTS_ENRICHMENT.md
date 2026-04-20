# CLAUDE_PROMPTS_ENRICHMENT.md
## Phased Prompts — Split the Monolithic Enrichment Task

Work through the phases in order. One phase per Claude session.
Review the diff and run the verification between phases.

Full design lives in `docs/PROMPT_ENRICHMENT_TASK_SPLIT.md`.

**Note on ordering.** Do these phases AFTER the profanity
refactor if you can — Phase C here re-touches the MERGE, and it's
easier when the new UDF output keys are already stable.

---

## Phase A — Create the four staging tables in `ENHANCED`

**Scope:** DDL only. No tasks, no data movement, no behavior change.
This phase gives us the tables to point at in Phase B.

```
>>> PROMPT START >>>
Read these files before editing:
  - docs/SQL_FOLDER_OUTLINE.md
  - docs/PROMPT_ENRICHMENT_TASK_SPLIT.md (especially the "Target
    Topology" table with staging-table schemas)
  - sql/06_tasks/00_tasks.sql (so you understand which CTEs feed
    which staging tables in Phase B)

Do ONLY Phase A of the enrichment split:

1. Create sql/04_enhanced/01_staging_tables.sql with CREATE OR
   REPLACE TABLE statements for FOUR tables in the ENHANCED schema:

   ENHANCED.STG_POST_LABELS
     uri                       STRING  PRIMARY KEY
     is_adult_content          BOOLEAN
     has_moderation_flag       BOOLEAN
     moderation_label_count    NUMBER
     stg_computed_at           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP

   ENHANCED.STG_POST_TEXT_FEATURES
     uri                       STRING  PRIMARY KEY
     post_text_clean           STRING
     was_profanity_redacted    BOOLEAN
     post_length               NUMBER
     post_word_count           NUMBER
     hashtag_count             NUMBER
     mention_count             NUMBER
     url_count                 NUMBER
     exclamation_count         NUMBER
     question_count            NUMBER
     stg_computed_at           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP

   ENHANCED.STG_ACTOR_FEATURES
     did                       STRING  PRIMARY KEY
     followers_count           NUMBER
     follows_count             NUMBER
     posts_count               NUMBER
     follower_tier             STRING
     account_age_days          NUMBER
     follow_follower_ratio     FLOAT
     posts_per_day             FLOAT
     has_actor_label           BOOLEAN
     is_bot_suspect            BOOLEAN
     is_spam_suspect           BOOLEAN
     stg_computed_at           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP

   ENHANCED.STG_POST_TREND_MATCH
     post_uri                  STRING  PRIMARY KEY
     matched_trend_name        STRING
     matched_trend_date        DATE
     matched_tweet_volume      NUMBER
     matched_trend_rank        NUMBER
     trend_match_method        STRING
     trend_match_score         FLOAT
     stg_computed_at           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP

   Every table gets a COMMENT = '...' describing its grain and
   which task will own its population (use placeholder names:
   TASK_FLATTEN_LABELS, TASK_TEXT_FEATURES, TASK_ACTOR_FEATURES,
   TASK_TREND_MATCH — we create these tasks in Phase B).

2. Add a validation query block at the bottom:
     SHOW TABLES LIKE 'STG_%' IN SCHEMA ENHANCED;
     SELECT COUNT(*) FROM ENHANCED.STG_POST_LABELS;       -- expect 0
     SELECT COUNT(*) FROM ENHANCED.STG_POST_TEXT_FEATURES;
     SELECT COUNT(*) FROM ENHANCED.STG_ACTOR_FEATURES;
     SELECT COUNT(*) FROM ENHANCED.STG_POST_TREND_MATCH;

3. Update docs/SQL_FOLDER_OUTLINE.md — add a row in the
   03_enhanced/ section describing the new staging-tables file.

Do NOT edit sql/06_tasks/00_tasks.sql. Do NOT create any new
tasks. Do NOT drop anything. The existing TASK_ENRICH_POSTS
keeps running and keeps writing to POSTS_ENRICHED.

Stop and report when done. Tell me: (a) the exact CREATE TABLE
statements you wrote, (b) any column type you chose that differs
from the spec above and why.
<<< PROMPT END <<<
```

**Verify after Phase A:**

```sql
SHOW TABLES LIKE 'STG_%' IN SCHEMA ENHANCED;
-- expect 4 tables

DESC TABLE ENHANCED.STG_POST_TEXT_FEATURES;
-- confirm columns + types match the spec
```

Commit. No behavior changed.

---

## Phase B — Build the four per-concern staging-populating tasks

**Scope:** create tasks that WRITE to the staging tables, but do
NOT yet drive `POSTS_ENRICHED` off them. The old monolithic task
continues to run and remains the source of truth.

```
>>> PROMPT START >>>
Phase A is complete — ENHANCED.STG_POST_LABELS,
ENHANCED.STG_POST_TEXT_FEATURES, ENHANCED.STG_ACTOR_FEATURES,
ENHANCED.STG_POST_TREND_MATCH exist and are empty. Read:
  - docs/PROMPT_ENRICHMENT_TASK_SPLIT.md (Work-to-do step 2,
    task-by-task breakdown)
  - sql/06_tasks/00_tasks.sql (to copy the CTE logic)

Do ONLY Phase B:

1. Create these four new task files. Each task:
   - WAREHOUSE = COMPUTE_WH
   - Does TRUNCATE TABLE then INSERT INTO the staging table
   - Carries the corresponding CTEs from the existing
     TASK_ENRICH_POSTS body

   sql/06_tasks/00_task_flatten_labels.sql
     Task: ENHANCED.TASK_FLATTEN_LABELS  (the ROOT task)
     Trigger: SCHEDULE = '1 MINUTE'
              WHEN SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_TREND_MATCHES')
     Body: TRUNCATE ENHANCED.STG_POST_LABELS;
           INSERT using the hydrated_latest + hydrated_labels_latest
           CTEs from the existing task, producing
           (uri, is_adult_content, has_moderation_flag,
            moderation_label_count).

   sql/06_tasks/01_task_text_features.sql
     Task: ENHANCED.TASK_TEXT_FEATURES
     Trigger: AFTER ENHANCED.TASK_FLATTEN_LABELS
     Body: TRUNCATE + INSERT using raw_posts_latest, post_text_cleaned,
           and the text regex features from merge_source.

   sql/06_tasks/02_task_actor_features.sql
     Task: ENHANCED.TASK_ACTOR_FEATURES
     Trigger: AFTER ENHANCED.TASK_FLATTEN_LABELS  (parallel)
     Body: TRUNCATE + INSERT using actor_latest_normalized plus
           the is_bot_suspect / is_spam_suspect boolean expressions
           from merge_source.

   sql/06_tasks/03_task_trend_match.sql
     Task: ENHANCED.TASK_TREND_MATCH
     Trigger: AFTER ENHANCED.TASK_FLATTEN_LABELS  (parallel)
     Body: TRUNCATE + INSERT using trend_matches_latest,
           twitter_trends_canonical, trend_enriched. Insert ONLY
           matched rows (do not write has_trend_match=FALSE rows).

2. Do NOT yet create TASK_ASSEMBLE_POSTS_ENRICHED — Phase C
   handles the assembler and the retirement of the old task.

3. At the BOTTOM of 03_task_trend_match.sql, add the task-resume
   statements in the correct order (children first):
     ALTER TASK ENHANCED.TASK_TREND_MATCH RESUME;
     ALTER TASK ENHANCED.TASK_ACTOR_FEATURES RESUME;
     ALTER TASK ENHANCED.TASK_TEXT_FEATURES RESUME;
     ALTER TASK ENHANCED.TASK_FLATTEN_LABELS RESUME;

4. CRITICAL: sql/06_tasks/00_tasks.sql must stay in place and
   its tasks (TASK_ENRICH_POSTS, TASK_BUILD_ML_READY) must stay
   RESUMED. We are running the new and old pipelines in parallel
   during Phase B to compare outputs before cutting over.
   POSTS_ENRICHED is still owned by TASK_ENRICH_POSTS; the new
   staging tables are a PARALLEL computation we'll compare
   against before switching.

5. Update docs/SQL_FOLDER_OUTLINE.md — add the four new task
   files to the 05_tasks/ section. Note that the chain is running
   in parallel with the old monolithic task pending Phase C.

Stop and report when done. Tell me: (a) any CTE logic you
duplicated across tasks (expected: the dedup QUALIFY patterns)
and whether that bothers you, (b) the actual task dependency
DAG you deployed.
<<< PROMPT END <<<
```

**Verify after Phase B:**

```sql
SHOW TASKS IN SCHEMA ENHANCED;
-- expect TASK_ENRICH_POSTS, TASK_BUILD_ML_READY (old)
-- plus TASK_FLATTEN_LABELS, TASK_TEXT_FEATURES,
-- TASK_ACTOR_FEATURES, TASK_TREND_MATCH (new). All state=started.

-- After one task chain fires, compare old vs new:
SELECT COUNT(*) AS enriched_rows FROM ENHANCED.POSTS_ENRICHED;
SELECT COUNT(*) AS stg_text_rows FROM ENHANCED.STG_POST_TEXT_FEATURES;
-- stg_text_rows should be >= enriched_rows (the moderation filter
-- in the old task drops rows at the end; staging has everything
-- pre-filter).

-- Sample a uri and confirm staging rows match the old task's output
WITH sample AS (SELECT uri FROM ENHANCED.POSTS_ENRICHED LIMIT 1)
SELECT
  p.uri,
  p.post_text_clean       AS old_clean,
  stf.post_text_clean     AS new_clean,
  p.post_length           AS old_len,
  stf.post_length         AS new_len
FROM sample s
JOIN ENHANCED.POSTS_ENRICHED p          ON p.uri = s.uri
JOIN ENHANCED.STG_POST_TEXT_FEATURES stf ON stf.uri = s.uri;
```

If values match across old vs new for sampled uris, Phase B is
green. Commit.

---

## Phase C — Add the assembler, retire the old monolithic task

**Scope:** write the assembler MERGE, rewire `TASK_BUILD_ML_READY`
to come after it, and suspend/drop the old task.

```
>>> PROMPT START >>>
Phases A and B are complete — the four staging tables are being
populated by their own tasks in parallel with the old
TASK_ENRICH_POSTS. Side-by-side validation has confirmed the
staging data matches. Read:
  - docs/PROMPT_ENRICHMENT_TASK_SPLIT.md (Work-to-do steps 2c, 3,
    4 — assembler, resume order, validation)
  - sql/06_tasks/00_tasks.sql (the old task we are retiring)

Do ONLY Phase C:

1. Create sql/06_tasks/04_task_assemble_posts_enriched.sql with:
   Task: ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED
   Trigger: AFTER ENHANCED.TASK_TEXT_FEATURES,
            ENHANCED.TASK_ACTOR_FEATURES,
            ENHANCED.TASK_TREND_MATCH
   (Snowflake supports multiple predecessors — declare all three.)
   Body: MERGE INTO ENHANCED.POSTS_ENRICHED AS tgt
         USING (
           SELECT ...
           FROM ENHANCED.STG_POST_TEXT_FEATURES stf
           LEFT JOIN ENHANCED.STG_POST_LABELS lbl ON lbl.uri = stf.uri
           LEFT JOIN RAW.LANDING_RAW_POSTS rp  -- for repo_did, post_created_at
                ...
           LEFT JOIN RAW.LANDING_HYDRATED_POSTS hyd  -- for author_did,
                                                    -- engagement counts
                ...
           LEFT JOIN ENHANCED.STG_ACTOR_FEATURES af ON af.did = ...
           LEFT JOIN ENHANCED.STG_POST_TREND_MATCH tm ON tm.post_uri = stf.uri
           WHERE COALESCE(lbl.is_adult_content, FALSE) = FALSE
             AND COALESCE(af.is_bot_suspect, FALSE) = FALSE
             AND stf.post_text_clean IS NOT NULL
             AND stf.post_text_clean != ''
         ) AS src
         ON tgt.uri = src.uri
         WHEN MATCHED THEN UPDATE SET ...
         WHEN NOT MATCHED THEN INSERT ... ;
   The MERGE column list MUST match exactly what the old task
   writes — refer to sql/06_tasks/00_tasks.sql lines 303-372.
   Use the same moderation filter. Preserve enriched_at = CURRENT_TIMESTAMP().

2. Create sql/06_tasks/05_task_build_ml_ready.sql containing the
   existing TASK_BUILD_ML_READY body, but change its AFTER clause
   to reference TASK_ASSEMBLE_POSTS_ENRICHED instead of
   TASK_ENRICH_POSTS.

3. Retire the old monolithic chain:
   - ALTER TASK ENHANCED.TASK_ENRICH_POSTS SUSPEND;
   - ALTER TASK ENHANCED.TASK_BUILD_ML_READY SUSPEND; (the OLD one)
   - DROP TASK ENHANCED.TASK_ENRICH_POSTS;
   - DROP TASK ENHANCED.TASK_BUILD_ML_READY; (the OLD one — confirm
     it's the task in sql/06_tasks/00_tasks.sql and NOT the new
     one from sql/06_tasks/05_task_build_ml_ready.sql; Snowflake
     task names are unique within schema, so this works but DO
     order your ALTER/DROP statements carefully: drop the old,
     then create the new.)
   Put these statements at the bottom of 05_task_build_ml_ready.sql
   in commented form with a clear banner — the human operator runs
   them after side-by-side validation is green, not automatically.

4. Delete sql/06_tasks/00_tasks.sql after the new file is in
   place — its logic now lives across 00_task_flatten_labels.sql
   through 05_task_build_ml_ready.sql.

5. Resume tasks in reverse-dependency order at the bottom of
   05_task_build_ml_ready.sql:
     ALTER TASK ENHANCED.TASK_BUILD_ML_READY RESUME;
     ALTER TASK ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED RESUME;
     -- (the other four child tasks are already RESUMED from Phase B)

6. Create sql/99_validation/00_enrichment_split.sql (the file
   specified in PROMPT_ENRICHMENT_TASK_SPLIT.md step 4). Include:
     - A baseline-capture query documented as a commented block
       that the operator runs BEFORE Phase C to snapshot row
       counts and distributions from the old chain.
     - A post-refactor assertion block that compares POSTS_ENRICHED
       row count, follower_tier distribution, has_trend_match
       rate, and is_bot_suspect rate against the captured baseline.

7. Update docs/SQL_FOLDER_OUTLINE.md:
   - 05_tasks/ section: reflect the new six-task chain.
   - Pain-points section: move "Monolithic TASK_ENRICH_POSTS"
     from "open" to "resolved in CLAUDE_PROMPTS_ENRICHMENT".

8. Update docs/SQL_DEPLOYMENT_SEQUENCE.md — patch the task-file
   references to the new filenames.

Stop and report when done. Tell me: (a) the exact MERGE column
list you produced (paste it in the response), (b) the TASK_HISTORY
query result showing the new chain fired end-to-end once,
(c) the baseline-vs-post diff from the validation file.
<<< PROMPT END <<<
```

**Verify after Phase C:**

```sql
-- 1. Task chain structure
SHOW TASKS IN SCHEMA ENHANCED;
-- Expect exactly:
--   TASK_FLATTEN_LABELS         (root, stream-triggered, state=started)
--   TASK_TEXT_FEATURES          (after FLATTEN_LABELS, state=started)
--   TASK_ACTOR_FEATURES         (after FLATTEN_LABELS, state=started)
--   TASK_TREND_MATCH            (after FLATTEN_LABELS, state=started)
--   TASK_ASSEMBLE_POSTS_ENRICHED (after the three above, state=started)
--   TASK_BUILD_ML_READY         (after ASSEMBLE, state=started)
-- Old TASK_ENRICH_POSTS should NOT appear anymore.

-- 2. Row counts vs baseline
SELECT COUNT(*) FROM ENHANCED.POSTS_ENRICHED;
SELECT COUNT(*) FROM CURATED.ML_READY;
-- Both should match what you captured before Phase C (tolerance: 0
-- rows difference; the moderation filter is identical).

-- 3. Parallel execution evidence
SELECT name, scheduled_time, completed_time, state
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
    SCHEDULED_TIME_RANGE_START => DATEADD('HOUR', -1, CURRENT_TIMESTAMP())
))
WHERE database_name = 'BLUESKYDATAENGINEERINGPROJECT'
ORDER BY scheduled_time DESC;
-- TASK_TEXT_FEATURES, TASK_ACTOR_FEATURES, TASK_TREND_MATCH
-- should show overlapping scheduled_time → completed_time windows.

-- 4. Isolation test — rerun one child in place
EXECUTE TASK ENHANCED.TASK_ACTOR_FEATURES;
-- STG_ACTOR_FEATURES should refresh; STG_POST_TEXT_FEATURES and
-- STG_POST_LABELS should be untouched (check their stg_computed_at).
```

Commit. The enrichment split is done.
