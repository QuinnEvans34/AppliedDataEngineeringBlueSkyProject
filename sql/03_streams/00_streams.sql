-- Append-only streams on RAW landing tables.
--
-- Roles (as of the "Triggered task (no SCHEDULE) on root" refactor in
-- docs/SQL_AUDIT_FIXES.md):
--
--   * RAW.STRM_LANDING_TREND_MATCHES is the TRIGGER STREAM for the root
--     task ENHANCED.TASK_FLATTEN_LABELS. The task declares
--     `WHEN SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_TREND_MATCHES')`, so
--     every time the Snowpipe that loads RAW.LANDING_TREND_MATCHES
--     appends rows, Snowflake fires the task. The task body drains the
--     stream (SELECT against it) so the offset advances and the task
--     does NOT re-fire on the same rows.
--
--     IMPORTANT: this stream must exist BEFORE sql/06_tasks/00_task_flatten_labels.sql
--     is deployed. Snowflake validates the stream reference in the WHEN
--     clause at CREATE TASK time and will reject the task DDL otherwise.
--     Deploy order 03_streams/ -> 06_tasks/ is already enforced by the
--     numbered-folder convention.
--
--   * RAW.STRM_LANDING_RAW_POSTS, RAW.STRM_LANDING_HYDRATED_POSTS, and
--     RAW.STRM_LANDING_ACTOR_PROFILES are OBSERVABILITY-ONLY. No task
--     consumes them. Operators can run
--       SELECT SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_RAW_POSTS');
--     (or the others) to see if new data has landed since the last check.
--     They can be dropped at any time with no downstream impact.
--
-- Spec: docs/SCHEMA_MIGRATION.md
-- Credit rules: docs/SNOWFLAKE_CREDIT_STRATEGY.md

CREATE STREAM IF NOT EXISTS RAW.STRM_LANDING_RAW_POSTS
  ON TABLE RAW.LANDING_RAW_POSTS
  APPEND_ONLY = TRUE
  COMMENT = 'Detects new raw posts for ENHANCED processing';

CREATE STREAM IF NOT EXISTS RAW.STRM_LANDING_HYDRATED_POSTS
  ON TABLE RAW.LANDING_HYDRATED_POSTS
  APPEND_ONLY = TRUE;

CREATE STREAM IF NOT EXISTS RAW.STRM_LANDING_ACTOR_PROFILES
  ON TABLE RAW.LANDING_ACTOR_PROFILES
  APPEND_ONLY = TRUE;

CREATE STREAM IF NOT EXISTS RAW.STRM_LANDING_TREND_MATCHES
  ON TABLE RAW.LANDING_TREND_MATCHES
  APPEND_ONLY = TRUE;
