-- Task: ENHANCED.TASK_ACTOR_FEATURES (parallel child of TASK_FLATTEN_LABELS)
-- Populates ENHANCED.STG_ACTOR_FEATURES by deduping RAW.LANDING_ACTOR_PROFILES
-- and appending the bot/spam suspect booleans.
-- Carries the `actor_latest_normalized` CTE and the is_bot_suspect /
-- is_spam_suspect expressions from the `merge_source` CTE in
-- sql/05_tasks/00_tasks.sql.
-- Spec: docs/CLAUDE_PROMPTS_ENRICHMENT.md (Phase B) +
--       docs/PROMPT_ENRICHMENT_TASK_SPLIT.md (Target Topology)

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

CREATE OR REPLACE TASK ENHANCED.TASK_ACTOR_FEATURES
  WAREHOUSE = COMPUTE_WH
  AFTER ENHANCED.TASK_FLATTEN_LABELS
AS
BEGIN
  TRUNCATE TABLE ENHANCED.STG_ACTOR_FEATURES;

  INSERT INTO ENHANCED.STG_ACTOR_FEATURES (
    did,
    followers_count,
    follows_count,
    posts_count,
    follower_tier,
    account_age_days,
    follow_follower_ratio,
    posts_per_day,
    has_actor_label,
    is_bot_suspect,
    is_spam_suspect
  )
  WITH
  actor_latest_normalized AS (
    SELECT
      raw_payload:did::STRING AS did,
      COALESCE(raw_payload:followers_count::NUMBER, raw_payload:followersCount::NUMBER) AS followers_count,
      COALESCE(raw_payload:follows_count::NUMBER,   raw_payload:followsCount::NUMBER)   AS follows_count,
      COALESCE(raw_payload:posts_count::NUMBER,     raw_payload:postsCount::NUMBER)     AS posts_count,
      DATEDIFF(
        'day',
        TRY_CAST(COALESCE(raw_payload:created_at::STRING, raw_payload:createdAt::STRING) AS TIMESTAMP_NTZ),
        CURRENT_TIMESTAMP()
      ) AS account_age_days,
      COALESCE(raw_payload:follows_count::NUMBER, raw_payload:followsCount::NUMBER)
        / NULLIF(COALESCE(raw_payload:followers_count::NUMBER, raw_payload:followersCount::NUMBER), 0)
        AS follow_follower_ratio,
      COALESCE(raw_payload:posts_count::NUMBER, raw_payload:postsCount::NUMBER)
        / NULLIF(
            DATEDIFF(
              'day',
              TRY_CAST(COALESCE(raw_payload:created_at::STRING, raw_payload:createdAt::STRING) AS TIMESTAMP_NTZ),
              CURRENT_TIMESTAMP()
            ),
            0
          ) AS posts_per_day,
      CASE
        WHEN COALESCE(raw_payload:followers_count::NUMBER, raw_payload:followersCount::NUMBER) >= 10000 THEN 'HIGH'
        WHEN COALESCE(raw_payload:followers_count::NUMBER, raw_payload:followersCount::NUMBER) >= 1000  THEN 'MID'
        WHEN COALESCE(raw_payload:followers_count::NUMBER, raw_payload:followersCount::NUMBER) >= 100   THEN 'LOW'
        ELSE 'MICRO'
      END AS follower_tier,
      COALESCE(ARRAY_SIZE(raw_payload:labels) > 0, FALSE) AS has_actor_label
    FROM RAW.LANDING_ACTOR_PROFILES
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY raw_payload:did::STRING
      ORDER BY loaded_at DESC, landing_id DESC
    ) = 1
  )
  SELECT
    did,
    followers_count,
    follows_count,
    posts_count,
    follower_tier,
    account_age_days,
    follow_follower_ratio,
    posts_per_day,
    has_actor_label,

    -- ── Bot detection (copied verbatim from merge_source) ──
    (
      COALESCE(follow_follower_ratio > 20, FALSE)
      OR COALESCE(followers_count < 10 AND posts_count > 500, FALSE)
      OR COALESCE(account_age_days < 30 AND posts_per_day > 50, FALSE)
      OR COALESCE(has_actor_label, FALSE)
    ) AS is_bot_suspect,

    (
      COALESCE(follow_follower_ratio > 20, FALSE)
      OR COALESCE(followers_count < 10 AND posts_count > 500, FALSE)
      OR COALESCE(account_age_days < 30 AND posts_per_day > 50, FALSE)
      OR COALESCE(has_actor_label, FALSE)
    )
    AND COALESCE(posts_per_day > 100, FALSE) AS is_spam_suspect
  FROM actor_latest_normalized;
END;
