-- Task: ENHANCED.TASK_FLATTEN_LABELS (root of the enrichment-split chain)
-- Populates ENHANCED.STG_POST_LABELS by deduping RAW.LANDING_HYDRATED_POSTS
-- and flattening the hydrated labels array into moderation flags.
-- Carries the `hydrated_latest` + `hydrated_labels_latest` CTEs from the
-- monolithic TASK_ENRICH_POSTS in sql/05_tasks/00_tasks.sql.
-- Spec: docs/CLAUDE_PROMPTS_ENRICHMENT.md (Phase B) +
--       docs/PROMPT_ENRICHMENT_TASK_SPLIT.md (Target Topology)
--
-- Triggering: this is a TRIGGERED task, not a scheduled one. It has NO
-- SCHEDULE clause — the assignment forbids scheduled tasks — but it keeps
-- the `WHEN SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_TREND_MATCHES')`
-- predicate. Snowflake fires the task automatically whenever the stream
-- receives appended rows from the Snowpipe that loads
-- RAW.LANDING_TREND_MATCHES. Python does NOT need to call EXECUTE TASK
-- during live ingestion; it only needs to PUT the match files to the
-- stage. The three child tasks still chain via their AFTER clauses.
-- See docs/SQL_AUDIT_FIXES.md ("Triggered task (no SCHEDULE) on root").

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

CREATE OR REPLACE TASK ENHANCED.TASK_FLATTEN_LABELS
  WAREHOUSE = COMPUTE_WH
  WHEN SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_TREND_MATCHES')
AS
BEGIN
  -- Drain RAW.STRM_LANDING_TREND_MATCHES so its offset advances past the
  -- rows that triggered this run. Without a SELECT against the stream
  -- inside the task body, SYSTEM$STREAM_HAS_DATA would stay TRUE after
  -- the task completes and Snowflake would re-fire it in a loop.
  CREATE OR REPLACE TEMPORARY TABLE _stream_drain_trend_matches AS
    SELECT COUNT(*) AS n FROM RAW.STRM_LANDING_TREND_MATCHES;

  TRUNCATE TABLE ENHANCED.STG_POST_LABELS;

  INSERT INTO ENHANCED.STG_POST_LABELS (
    uri,
    is_adult_content,
    has_moderation_flag,
    moderation_label_count
  )
  WITH
  hydrated_latest AS (
    SELECT
      h.raw_payload:uri::STRING AS uri,
      COALESCE(h.raw_payload:labels, ARRAY_CONSTRUCT()) AS labels
    FROM RAW.LANDING_HYDRATED_POSTS h
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY h.raw_payload:uri::STRING
      ORDER BY h.loaded_at DESC, h.landing_id DESC
    ) = 1
  ),
  hydrated_labels_latest AS (
    SELECT
      h.uri AS uri,
      BOOLOR_AGG(
        f.value:val::STRING IN ('porn', 'sexual', 'nudity', 'graphic-media')
      ) AS is_adult_content
    FROM hydrated_latest h,
         LATERAL FLATTEN(
           input => h.labels,
           OUTER => TRUE
         ) f
    GROUP BY h.uri
  )
  SELECT
    h.uri,
    COALESCE(hll.is_adult_content, FALSE)       AS is_adult_content,
    ARRAY_SIZE(h.labels) > 0                    AS has_moderation_flag,
    COALESCE(ARRAY_SIZE(h.labels), 0)           AS moderation_label_count
  FROM hydrated_latest h
  LEFT JOIN hydrated_labels_latest hll
    ON hll.uri = h.uri;
END;
