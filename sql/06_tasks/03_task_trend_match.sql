-- Task: ENHANCED.TASK_TREND_MATCH (parallel child of TASK_FLATTEN_LABELS)
-- Populates ENHANCED.STG_POST_TREND_MATCH with one row per matched post.
-- Carries the `trend_matches_latest` + `twitter_trends_canonical` +
-- `trend_enriched` CTEs from the monolithic TASK_ENRICH_POSTS in
-- sql/05_tasks/00_tasks.sql. Only matched posts land here — unmatched rows
-- are absent by construction (grain: matched-only).
-- Spec: docs/CLAUDE_PROMPTS_ENRICHMENT.md (Phase B) +
--       docs/PROMPT_ENRICHMENT_TASK_SPLIT.md (Target Topology)

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

CREATE OR REPLACE TASK ENHANCED.TASK_TREND_MATCH
  WAREHOUSE = COMPUTE_WH
  AFTER ENHANCED.TASK_FLATTEN_LABELS
AS
BEGIN
  TRUNCATE TABLE ENHANCED.STG_POST_TREND_MATCH;

  INSERT INTO ENHANCED.STG_POST_TREND_MATCH (
    post_uri,
    matched_trend_name,
    matched_trend_date,
    matched_tweet_volume,
    matched_trend_rank,
    trend_match_method,
    trend_match_score
  )
  WITH
  trend_matches_latest AS (
    SELECT
      tm.raw_payload:post_uri::STRING AS post_uri,
      tm.raw_payload:trend_name::STRING AS trend_name,
      COALESCE(
        tm.raw_payload:trend_key_no_hash::STRING,
        tm.raw_payload:normalized_key_no_hash::STRING,
        LOWER(TRIM(REPLACE(tm.raw_payload:trend_name::STRING, '#', '')))
      ) AS trend_key_no_hash,
      tm.raw_payload:trend_date::DATE AS trend_date,
      tm.raw_payload:match_method::STRING AS match_method,
      tm.raw_payload:match_score::FLOAT AS match_score
    FROM RAW.LANDING_TREND_MATCHES tm
    WHERE tm.raw_payload:post_uri IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY tm.raw_payload:post_uri::STRING
      ORDER BY tm.loaded_at DESC, tm.raw_payload:match_score::FLOAT DESC, tm.landing_id DESC
    ) = 1
  ),
  twitter_trends_canonical AS (
    SELECT
      t.raw_payload:trend_date::DATE AS trend_date,
      COALESCE(
        t.raw_payload:trend_key_no_hash::STRING,
        t.raw_payload:normalized_key_no_hash::STRING,
        LOWER(TRIM(REPLACE(COALESCE(t.raw_payload:trend_name::STRING, t.raw_payload:trend_name_raw::STRING), '#', '')))
      ) AS trend_key_no_hash,
      t.raw_payload:tweet_volume::NUMBER AS tweet_volume,
      t.raw_payload:rank::NUMBER AS trend_rank
    FROM RAW.LANDING_TWITTER_TRENDS t
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY
        t.raw_payload:trend_date::DATE,
        COALESCE(
          t.raw_payload:trend_key_no_hash::STRING,
          t.raw_payload:normalized_key_no_hash::STRING,
          LOWER(TRIM(REPLACE(COALESCE(t.raw_payload:trend_name::STRING, t.raw_payload:trend_name_raw::STRING), '#', '')))
        )
      ORDER BY t.loaded_at DESC, t.landing_id DESC
    ) = 1
  ),
  trend_enriched AS (
    SELECT
      tm.post_uri          AS post_uri,
      tm.trend_name        AS matched_trend_name,
      tm.trend_date        AS matched_trend_date,
      t.tweet_volume       AS matched_tweet_volume,
      t.trend_rank         AS matched_trend_rank,
      tm.match_method      AS trend_match_method,
      tm.match_score       AS trend_match_score
    FROM trend_matches_latest tm
    LEFT JOIN twitter_trends_canonical t
      ON tm.trend_date        = t.trend_date
     AND tm.trend_key_no_hash = t.trend_key_no_hash
  )
  SELECT
    post_uri,
    matched_trend_name,
    matched_trend_date,
    matched_tweet_volume,
    matched_trend_rank,
    trend_match_method,
    trend_match_score
  FROM trend_enriched;
END;

-- Resume sequence for the full task graph lives at the bottom of
-- sql/06_tasks/05_task_build_ml_ready.sql (children first, root last).
