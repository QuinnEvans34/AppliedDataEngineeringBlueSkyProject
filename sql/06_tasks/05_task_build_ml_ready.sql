-- Task: ENHANCED.TASK_BUILD_ML_READY
-- Final leaf of the enrichment chain: TRUNCATE + INSERT from
-- ENHANCED.POSTS_ENRICHED into CURATED.ML_READY with NTILE(3)
-- engagement labeling and HASH(uri)-based 80/20 train/test split.
-- Same body as the old sql/05_tasks/00_tasks.sql implementation;
-- only the AFTER clause changed (now chains after the assembler
-- instead of the retired TASK_ENRICH_POSTS).
-- Spec: docs/CLAUDE_PROMPTS_ENRICHMENT.md (Phase C).

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

CREATE OR REPLACE TASK ENHANCED.TASK_BUILD_ML_READY
  WAREHOUSE = COMPUTE_WH
  AFTER ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED
AS
BEGIN
  TRUNCATE TABLE CURATED.ML_READY;

  INSERT INTO CURATED.ML_READY
  SELECT
    -- ── Target variable ──
    CASE NTILE(3) OVER (ORDER BY COALESCE(engagement_total, 0) ASC)
      WHEN 1 THEN 'LOW'
      WHEN 2 THEN 'MEDIUM'
      WHEN 3 THEN 'HIGH'
    END                                         AS engagement_label,
    COALESCE(engagement_total, 0)               AS engagement_total,

    -- ── Text features ──
    post_length,
    post_word_count,
    hashtag_count,
    mention_count,
    url_count,
    exclamation_count,
    question_count,

    -- ── Temporal features ──
    post_hour_utc,
    post_day_of_week,

    -- ── Actor features ──
    followers_count,
    follower_tier,
    account_age_days,
    follow_follower_ratio,
    posts_per_day,

    -- ── Trend features ──
    COALESCE(has_trend_match, FALSE)            AS has_trend_match,
    COALESCE(matched_tweet_volume, 0)           AS matched_tweet_volume,
    COALESCE(matched_trend_rank, 999)           AS matched_trend_rank,

    -- ── Profanity categorical feature ──
    severity_max,

    -- ── Deterministic train/test split ──
    CASE
      WHEN ABS(MOD(HASH(uri), 100)) < 80 THEN 'TRAIN'
      ELSE 'TEST'
    END                                         AS dataset_split

  FROM ENHANCED.POSTS_ENRICHED;
END;

-- Resume the full chain: children first, root last.
-- Snowflake requires child tasks to be RESUMED before the root.
ALTER TASK ENHANCED.TASK_BUILD_ML_READY           RESUME;
ALTER TASK ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED  RESUME;
ALTER TASK ENHANCED.TASK_TREND_MATCH              RESUME;
ALTER TASK ENHANCED.TASK_ACTOR_FEATURES           RESUME;
ALTER TASK ENHANCED.TASK_TEXT_FEATURES            RESUME;
ALTER TASK ENHANCED.TASK_FLATTEN_LABELS           RESUME;
