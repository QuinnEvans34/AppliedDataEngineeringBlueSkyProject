-- Task chain: ENHANCED.TASK_ENRICH_POSTS → ENHANCED.TASK_BUILD_ML_READY
-- Stream-driven enrichment pipeline. The parent task fires when
-- RAW.STRM_LANDING_TREND_MATCHES has data (trend-match readiness is the
-- correct signal — raw posts alone arrive before actor/trend inputs are
-- ready and would produce rows with NULL enrichment). The child task
-- chains AFTER it.
-- Both tasks are deployed RESUMED (child first, then parent).
-- Depends on: ENHANCED.POSTS_ENRICHED, CURATED.ML_READY, RAW.STRM_LANDING_RAW_POSTS
-- Pattern matches docs/reference.sql (TASK_ADD_ZIPCODE → TASK_ADD_WEATHER).
-- Spec: docs/ENHANCED_CURATED_TASKS.md

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

-- ════════════════════════════════════════════════════════════════════
-- TASK 1: ENHANCED.TASK_ENRICH_POSTS
-- Fires when RAW.STRM_LANDING_TREND_MATCHES has new data — i.e. once
-- trend-match results have landed, which happens last in the demo flow
-- and signals that posts + actors + trend matches are all ready.
-- MERGE INTO ENHANCED.POSTS_ENRICHED from all RAW landing tables.
-- ════════════════════════════════════════════════════════════════════


CREATE OR REPLACE TASK ENHANCED.TASK_ENRICH_POSTS
  WAREHOUSE = COMPUTE_WH
  SCHEDULE  = '1 MINUTE'
  WHEN SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_TREND_MATCHES')
AS
MERGE INTO ENHANCED.POSTS_ENRICHED AS tgt
USING (
  WITH

  -- Latest trend-match row per post_uri (stable landing table, not a stream).
  -- Drives the identity set for this run.
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

  -- Latest landed row per post URI (stable landing table, not a stream).
  raw_posts_latest AS (
    SELECT
      r.raw_payload:uri::STRING AS uri,
      COALESCE(r.raw_payload:repo_did::STRING, r.raw_payload:did::STRING) AS repo_did,
      r.raw_payload:record:text::STRING AS post_text,
      COALESCE(r.raw_payload:record:createdAt::STRING, r.raw_payload:record_created_at::STRING) AS post_created_at_raw,
      r.loaded_at AS loaded_at,
      r.landing_id AS landing_id
    FROM RAW.LANDING_RAW_POSTS r
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY r.raw_payload:uri::STRING
      ORDER BY r.loaded_at DESC, r.landing_id DESC
    ) = 1
  ),

  -- Identity set = all latest raw posts. One row per uri.
  -- Trend matches (and hydrated/actor data) join downstream as optional
  -- LEFT JOIN enrichment, so unmatched posts still flow into ENHANCED.
  ready_posts AS (
    SELECT
      rpl.uri,
      rpl.repo_did,
      rpl.post_text,
      rpl.post_created_at_raw,
      rpl.loaded_at,
      rpl.landing_id
    FROM raw_posts_latest rpl
  ),

  post_text_cleaned AS (
    SELECT
      rnp.uri AS uri,
      BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY(
        rnp.post_text
      ) AS cp
    FROM ready_posts rnp
  ),

  hydrated_latest AS (
    SELECT
      h.raw_payload:uri::STRING AS uri,
      COALESCE(h.raw_payload:author_did::STRING, h.raw_payload:author:did::STRING) AS author_did,
      COALESCE(h.raw_payload:reply_count::NUMBER, h.raw_payload:replyCount::NUMBER) AS reply_count,
      COALESCE(h.raw_payload:repost_count::NUMBER, h.raw_payload:repostCount::NUMBER) AS repost_count,
      COALESCE(h.raw_payload:like_count::NUMBER, h.raw_payload:likeCount::NUMBER) AS like_count,
      COALESCE(h.raw_payload:quote_count::NUMBER, h.raw_payload:quoteCount::NUMBER) AS quote_count,
      COALESCE(h.raw_payload:labels, ARRAY_CONSTRUCT()) AS labels,
      COALESCE(h.raw_payload:record_created_at::STRING, h.raw_payload:record:createdAt::STRING) AS record_created_at
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
  ),

  actor_latest_normalized AS (
    SELECT
      raw_payload:did::STRING AS did,
      COALESCE(raw_payload:followers_count::NUMBER, raw_payload:followersCount::NUMBER) AS followers_count,
      COALESCE(raw_payload:follows_count::NUMBER, raw_payload:followsCount::NUMBER) AS follows_count,
      COALESCE(raw_payload:posts_count::NUMBER, raw_payload:postsCount::NUMBER) AS posts_count,
      TRY_CAST(
        COALESCE(raw_payload:created_at::STRING, raw_payload:createdAt::STRING)
        AS TIMESTAMP_NTZ
      ) AS created_at_ts,
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
        WHEN COALESCE(raw_payload:followers_count::NUMBER, raw_payload:followersCount::NUMBER) >= 1000 THEN 'MID'
        WHEN COALESCE(raw_payload:followers_count::NUMBER, raw_payload:followersCount::NUMBER) >= 100 THEN 'LOW'
        ELSE 'MICRO'
      END AS follower_tier,
      COALESCE(ARRAY_SIZE(raw_payload:labels) > 0, FALSE) AS has_actor_label
    FROM RAW.LANDING_ACTOR_PROFILES
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY raw_payload:did::STRING
      ORDER BY loaded_at DESC, landing_id DESC
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
      tm.post_uri AS post_uri,
      tm.trend_name AS matched_trend_name,
      tm.trend_date AS matched_trend_date,
      t.tweet_volume AS matched_tweet_volume,
      t.trend_rank AS matched_trend_rank,
      tm.match_method AS trend_match_method,
      tm.match_score AS trend_match_score
    FROM trend_matches_latest tm
    LEFT JOIN twitter_trends_canonical t
      ON tm.trend_date = t.trend_date
     AND tm.trend_key_no_hash = t.trend_key_no_hash
  ),

  merge_source AS (
    SELECT
      -- ── Identity ──
      rnp.uri AS uri,
      rnp.repo_did AS repo_did,
      COALESCE(h.author_did, rnp.repo_did) AS author_did,

      -- ── Clean text (pre-computed in post_text_cleaned CTE) ──
      ptc.cp:post_text_clean::STRING AS post_text_clean,
      ptc.cp:was_profanity_redacted::BOOLEAN AS was_profanity_redacted,

      -- ── Engagement metrics ──
      h.reply_count AS reply_count,
      h.repost_count AS repost_count,
      h.like_count AS like_count,
      h.quote_count AS quote_count,
      COALESCE(h.reply_count, 0)
        + COALESCE(h.repost_count, 0)
        + COALESCE(h.like_count, 0)
        + COALESCE(h.quote_count, 0) AS engagement_total,

      -- ── Text features ──
      LENGTH(rnp.post_text) AS post_length,
      ARRAY_SIZE(SPLIT(TRIM(rnp.post_text), ' ')) AS post_word_count,
      REGEXP_COUNT(rnp.post_text, '#[A-Za-z0-9_]+') AS hashtag_count,
      REGEXP_COUNT(rnp.post_text, '@[A-Za-z0-9._]+') AS mention_count,
      REGEXP_COUNT(rnp.post_text, 'https?://') AS url_count,
      REGEXP_COUNT(rnp.post_text, '!') AS exclamation_count,
      REGEXP_COUNT(rnp.post_text, '\\?') AS question_count,

      -- ── Temporal features ──
      TRY_CAST(rnp.post_created_at_raw AS TIMESTAMP_NTZ) AS post_created_at_ts,
      EXTRACT(HOUR FROM TRY_CAST(rnp.post_created_at_raw AS TIMESTAMP_NTZ)) AS post_hour_utc,
      DAYOFWEEK(TRY_CAST(rnp.post_created_at_raw AS TIMESTAMP_NTZ)) AS post_day_of_week,

      -- ── Moderation flags ──
      COALESCE(hll.is_adult_content, FALSE) AS is_adult_content,
      COALESCE(ARRAY_SIZE(h.labels) > 0, FALSE) AS has_moderation_flag,
      COALESCE(ARRAY_SIZE(h.labels), 0) AS moderation_label_count,

      -- ── Actor features ──
      a.followers_count,
      a.follows_count,
      a.posts_count,
      a.follower_tier,
      a.account_age_days,
      a.follow_follower_ratio,
      a.posts_per_day,

      -- ── Bot detection ──
      (
        COALESCE(a.follow_follower_ratio > 20, FALSE)
        OR COALESCE(a.followers_count < 10 AND a.posts_count > 500, FALSE)
        OR COALESCE(a.account_age_days < 30 AND a.posts_per_day > 50, FALSE)
        OR COALESCE(a.has_actor_label, FALSE)
      ) AS is_bot_suspect,
      (
        COALESCE(a.follow_follower_ratio > 20, FALSE)
        OR COALESCE(a.followers_count < 10 AND a.posts_count > 500, FALSE)
        OR COALESCE(a.account_age_days < 30 AND a.posts_per_day > 50, FALSE)
        OR COALESCE(a.has_actor_label, FALSE)
      )
      AND COALESCE(a.posts_per_day > 100, FALSE) AS is_spam_suspect,

      -- ── Trend match ──
      te.post_uri IS NOT NULL AS has_trend_match,
      te.matched_trend_name,
      te.matched_trend_date,
      te.matched_tweet_volume,
      te.matched_trend_rank,
      te.trend_match_method,
      te.trend_match_score
    FROM ready_posts rnp
    LEFT JOIN hydrated_latest h
      ON rnp.uri = h.uri
    LEFT JOIN hydrated_labels_latest hll
      ON rnp.uri = hll.uri
    LEFT JOIN actor_latest_normalized a
      ON COALESCE(
           h.author_did,
           rnp.repo_did
         ) = a.did
    LEFT JOIN trend_enriched te
      ON rnp.uri = te.post_uri
    LEFT JOIN post_text_cleaned ptc
      ON rnp.uri = ptc.uri
  )

  -- ── Moderation filter: excluded rows never enter ENHANCED ──
  SELECT *
  FROM merge_source
  WHERE COALESCE(is_adult_content, FALSE) = FALSE
    AND COALESCE(is_bot_suspect, FALSE)   = FALSE
    AND post_text_clean IS NOT NULL
    AND post_text_clean != ''

) AS src
ON tgt.uri = src.uri

WHEN MATCHED THEN UPDATE SET
  tgt.repo_did               = src.repo_did,
  tgt.author_did             = src.author_did,
  tgt.post_text_clean        = src.post_text_clean,
  tgt.was_profanity_redacted = src.was_profanity_redacted,
  tgt.reply_count            = src.reply_count,
  tgt.repost_count           = src.repost_count,
  tgt.like_count             = src.like_count,
  tgt.quote_count            = src.quote_count,
  tgt.engagement_total       = src.engagement_total,
  tgt.post_length            = src.post_length,
  tgt.post_word_count        = src.post_word_count,
  tgt.hashtag_count          = src.hashtag_count,
  tgt.mention_count          = src.mention_count,
  tgt.url_count              = src.url_count,
  tgt.exclamation_count      = src.exclamation_count,
  tgt.question_count         = src.question_count,
  tgt.post_created_at_ts     = src.post_created_at_ts,
  tgt.post_hour_utc          = src.post_hour_utc,
  tgt.post_day_of_week       = src.post_day_of_week,
  tgt.is_adult_content       = src.is_adult_content,
  tgt.has_moderation_flag    = src.has_moderation_flag,
  tgt.moderation_label_count = src.moderation_label_count,
  tgt.followers_count        = src.followers_count,
  tgt.follows_count          = src.follows_count,
  tgt.posts_count            = src.posts_count,
  tgt.follower_tier          = src.follower_tier,
  tgt.account_age_days       = src.account_age_days,
  tgt.follow_follower_ratio  = src.follow_follower_ratio,
  tgt.posts_per_day          = src.posts_per_day,
  tgt.is_bot_suspect         = src.is_bot_suspect,
  tgt.is_spam_suspect        = src.is_spam_suspect,
  tgt.has_trend_match        = src.has_trend_match,
  tgt.matched_trend_name     = src.matched_trend_name,
  tgt.matched_trend_date     = src.matched_trend_date,
  tgt.matched_tweet_volume   = src.matched_tweet_volume,
  tgt.matched_trend_rank     = src.matched_trend_rank,
  tgt.trend_match_method     = src.trend_match_method,
  tgt.trend_match_score      = src.trend_match_score,
  tgt.enriched_at            = CURRENT_TIMESTAMP()

WHEN NOT MATCHED THEN INSERT (
  uri, repo_did, author_did,
  post_text_clean, was_profanity_redacted,
  reply_count, repost_count, like_count, quote_count, engagement_total,
  post_length, post_word_count, hashtag_count, mention_count,
  url_count, exclamation_count, question_count,
  post_created_at_ts, post_hour_utc, post_day_of_week,
  is_adult_content, has_moderation_flag, moderation_label_count,
  followers_count, follows_count, posts_count, follower_tier,
  account_age_days, follow_follower_ratio, posts_per_day,
  is_bot_suspect, is_spam_suspect,
  has_trend_match, matched_trend_name, matched_trend_date,
  matched_tweet_volume, matched_trend_rank,
  trend_match_method, trend_match_score
) VALUES (
  src.uri, src.repo_did, src.author_did,
  src.post_text_clean, src.was_profanity_redacted,
  src.reply_count, src.repost_count, src.like_count, src.quote_count, src.engagement_total,
  src.post_length, src.post_word_count, src.hashtag_count, src.mention_count,
  src.url_count, src.exclamation_count, src.question_count,
  src.post_created_at_ts, src.post_hour_utc, src.post_day_of_week,
  src.is_adult_content, src.has_moderation_flag, src.moderation_label_count,
  src.followers_count, src.follows_count, src.posts_count, src.follower_tier,
  src.account_age_days, src.follow_follower_ratio, src.posts_per_day,
  src.is_bot_suspect, src.is_spam_suspect,
  src.has_trend_match, src.matched_trend_name, src.matched_trend_date,
  src.matched_tweet_volume, src.matched_trend_rank,
  src.trend_match_method, src.trend_match_score
);

/*
-- Development check: verify merge_source uniqueness before MERGE runs.
-- 1) Copy the WITH ... merge_source query from TASK_ENRICH_POSTS and run:
-- WITH merge_source AS ( ... )
-- SELECT COUNT(*) AS total_rows, COUNT(DISTINCT uri) AS distinct_uri
-- FROM merge_source;
--
-- 2) Confirm no duplicates:
-- WITH merge_source AS ( ... )
-- SELECT uri, COUNT(*) AS c
-- FROM merge_source
-- GROUP BY 1
-- HAVING COUNT(*) > 1
-- ORDER BY c DESC;
*/

-- ════════════════════════════════════════════════════════════════════
-- TASK 2: ENHANCED.TASK_BUILD_ML_READY
-- Triggered AFTER TASK_ENRICH_POSTS completes (child task).
-- TRUNCATE + INSERT from ENHANCED.POSTS_ENRICHED into CURATED.ML_READY.
-- COALESCE(engagement_total, 0) so demos with no hydrated_posts still
-- produce non-zero curated rows.
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE TASK ENHANCED.TASK_BUILD_ML_READY
  WAREHOUSE = COMPUTE_WH
  AFTER ENHANCED.TASK_ENRICH_POSTS
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

    -- ── Deterministic train/test split ──
    CASE
      WHEN ABS(MOD(HASH(uri), 100)) < 80 THEN 'TRAIN'
      ELSE 'TEST'
    END                                         AS dataset_split

  FROM ENHANCED.POSTS_ENRICHED;
END;

-- ════════════════════════════════════════════════════════════════════
-- DEPLOY RESUMED — child task first, then parent task.
-- Snowflake requires child tasks to be RESUMED before their parents.
-- The chain stays running and stream-driven (no self-suspend).
-- ════════════════════════════════════════════════════════════════════
ALTER TASK ENHANCED.TASK_BUILD_ML_READY RESUME;
ALTER TASK ENHANCED.TASK_ENRICH_POSTS RESUME;

-- ════════════════════════════════════════════════════════════════════
-- VALIDATION QUERIES — run manually after tasks complete
-- ════════════════════════════════════════════════════════════════════
/*
-- ENHANCED.POSTS_ENRICHED row count and sample
SELECT COUNT(*) AS enriched_rows FROM ENHANCED.POSTS_ENRICHED;
SELECT * FROM ENHANCED.POSTS_ENRICHED LIMIT 100;

-- CURATED.ML_READY distribution check
SELECT
    engagement_label,
    dataset_split,
    COUNT(*) AS rows
FROM CURATED.ML_READY
GROUP BY engagement_label, dataset_split
ORDER BY engagement_label, dataset_split;

-- Trend match rate
SELECT
    has_trend_match,
    COUNT(*) AS post_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
FROM ENHANCED.POSTS_ENRICHED
GROUP BY has_trend_match;
*/

-- Reminder: suspend warehouse after running validation queries.
-- ALTER WAREHOUSE COMPUTE_WH SUSPEND;
