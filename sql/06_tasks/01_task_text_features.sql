-- Task: ENHANCED.TASK_TEXT_FEATURES (parallel child of TASK_FLATTEN_LABELS)
-- Populates ENHANCED.STG_POST_TEXT_FEATURES by deduping RAW.LANDING_RAW_POSTS,
-- cleaning profanity via CLEAN_PROFANITY(), and computing regex text features.
-- Carries the `raw_posts_latest` + `post_text_cleaned` CTEs plus the text-feature
-- regex expressions from the `merge_source` CTE in sql/05_tasks/00_tasks.sql.
-- Spec: docs/CLAUDE_PROMPTS_ENRICHMENT.md (Phase B) +
--       docs/PROMPT_ENRICHMENT_TASK_SPLIT.md (Target Topology)

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

CREATE OR REPLACE TASK ENHANCED.TASK_TEXT_FEATURES
  WAREHOUSE = COMPUTE_WH
  AFTER ENHANCED.TASK_FLATTEN_LABELS
AS
BEGIN
  TRUNCATE TABLE ENHANCED.STG_POST_TEXT_FEATURES;

  INSERT INTO ENHANCED.STG_POST_TEXT_FEATURES (
    uri,
    post_text_clean,
    was_profanity_redacted,
    post_length,
    post_word_count,
    hashtag_count,
    mention_count,
    url_count,
    exclamation_count,
    question_count
  )
  WITH
  raw_posts_latest AS (
    SELECT
      r.raw_payload:uri::STRING AS uri,
      r.raw_payload:record:text::STRING AS post_text
    FROM RAW.LANDING_RAW_POSTS r
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY r.raw_payload:uri::STRING
      ORDER BY r.loaded_at DESC, r.landing_id DESC
    ) = 1
  ),
  post_text_cleaned AS (
    SELECT
      rpl.uri       AS uri,
      rpl.post_text AS post_text,
      BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY(
        rpl.post_text
      ) AS cp
    FROM raw_posts_latest rpl
  )
  SELECT
    uri,
    cp:post_text_clean::STRING                       AS post_text_clean,
    cp:was_profanity_redacted::BOOLEAN               AS was_profanity_redacted,
    LENGTH(post_text)                                AS post_length,
    ARRAY_SIZE(SPLIT(TRIM(post_text), ' '))          AS post_word_count,
    REGEXP_COUNT(post_text, '#[A-Za-z0-9_]+')        AS hashtag_count,
    REGEXP_COUNT(post_text, '@[A-Za-z0-9._]+')       AS mention_count,
    REGEXP_COUNT(post_text, 'https?://')             AS url_count,
    REGEXP_COUNT(post_text, '!')                     AS exclamation_count,
    REGEXP_COUNT(post_text, '\\?')                   AS question_count
  FROM post_text_cleaned;
END;
