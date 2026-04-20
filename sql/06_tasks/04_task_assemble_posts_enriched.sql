-- Task: ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED
-- Assembler: MERGEs the four ENHANCED.STG_* staging tables (populated by
-- the Phase B per-concern tasks) into ENHANCED.POSTS_ENRICHED, applying
-- the same moderation filter as the old monolithic TASK_ENRICH_POSTS.
-- Identity set = ENHANCED.STG_POST_TEXT_FEATURES (one row per uri).
-- The four staging tables + RAW landing tables (for repo_did / author_did /
-- engagement counts / post_created_at) feed the 40-column MERGE.
-- Spec: docs/CLAUDE_PROMPTS_ENRICHMENT.md (Phase C) +
--       docs/PROMPT_ENRICHMENT_TASK_SPLIT.md (Work-to-do step 2c).
-- Column parity: must exactly match the old sql/05_tasks/00_tasks.sql
-- lines 305-378. severity_max / redaction_count are not in any staging
-- table, so the assembler recomputes them by re-calling CLEAN_PROFANITY
-- on the deduped RAW.LANDING_RAW_POSTS text (small compute cost, keeps
-- Phase A/B artifacts untouched).

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

CREATE OR REPLACE TASK ENHANCED.TASK_ASSEMBLE_POSTS_ENRICHED
  WAREHOUSE = COMPUTE_WH
  AFTER ENHANCED.TASK_TEXT_FEATURES,
        ENHANCED.TASK_ACTOR_FEATURES,
        ENHANCED.TASK_TREND_MATCH
AS
MERGE INTO ENHANCED.POSTS_ENRICHED AS tgt
USING (
  WITH
  rp_latest AS (
    SELECT
      r.raw_payload:uri::STRING AS uri,
      COALESCE(r.raw_payload:repo_did::STRING, r.raw_payload:did::STRING) AS repo_did,
      r.raw_payload:record:text::STRING AS post_text,
      COALESCE(r.raw_payload:record:createdAt::STRING, r.raw_payload:record_created_at::STRING) AS post_created_at_raw
    FROM RAW.LANDING_RAW_POSTS r
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY r.raw_payload:uri::STRING
      ORDER BY r.loaded_at DESC, r.landing_id DESC
    ) = 1
  ),

  post_profanity AS (
    SELECT
      rp.uri AS uri,
      BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY(rp.post_text) AS cp
    FROM rp_latest rp
  ),

  hyd_latest AS (
    SELECT
      h.raw_payload:uri::STRING AS uri,
      COALESCE(h.raw_payload:author_did::STRING, h.raw_payload:author:did::STRING) AS author_did,
      COALESCE(h.raw_payload:reply_count::NUMBER,  h.raw_payload:replyCount::NUMBER)  AS reply_count,
      COALESCE(h.raw_payload:repost_count::NUMBER, h.raw_payload:repostCount::NUMBER) AS repost_count,
      COALESCE(h.raw_payload:like_count::NUMBER,   h.raw_payload:likeCount::NUMBER)   AS like_count,
      COALESCE(h.raw_payload:quote_count::NUMBER,  h.raw_payload:quoteCount::NUMBER)  AS quote_count
    FROM RAW.LANDING_HYDRATED_POSTS h
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY h.raw_payload:uri::STRING
      ORDER BY h.loaded_at DESC, h.landing_id DESC
    ) = 1
  ),

  merge_source AS (
    SELECT
      -- ── Identity ──
      stf.uri                                                    AS uri,
      rp.repo_did                                                AS repo_did,
      COALESCE(hyd.author_did, rp.repo_did)                      AS author_did,

      -- ── Clean text (from staging) + profanity audit (recomputed) ──
      stf.post_text_clean                                        AS post_text_clean,
      stf.was_profanity_redacted                                 AS was_profanity_redacted,
      pp.cp:severity_max::STRING                                 AS severity_max,
      pp.cp:redaction_count::NUMBER                              AS redaction_count,

      -- ── Engagement metrics ──
      hyd.reply_count                                            AS reply_count,
      hyd.repost_count                                           AS repost_count,
      hyd.like_count                                             AS like_count,
      hyd.quote_count                                            AS quote_count,
      COALESCE(hyd.reply_count, 0)
        + COALESCE(hyd.repost_count, 0)
        + COALESCE(hyd.like_count, 0)
        + COALESCE(hyd.quote_count, 0)                           AS engagement_total,

      -- ── Text features (from staging) ──
      stf.post_length                                            AS post_length,
      stf.post_word_count                                        AS post_word_count,
      stf.hashtag_count                                          AS hashtag_count,
      stf.mention_count                                          AS mention_count,
      stf.url_count                                              AS url_count,
      stf.exclamation_count                                      AS exclamation_count,
      stf.question_count                                         AS question_count,

      -- ── Temporal features ──
      TRY_CAST(rp.post_created_at_raw AS TIMESTAMP_NTZ)          AS post_created_at_ts,
      EXTRACT(HOUR FROM TRY_CAST(rp.post_created_at_raw AS TIMESTAMP_NTZ)) AS post_hour_utc,
      DAYOFWEEK(TRY_CAST(rp.post_created_at_raw AS TIMESTAMP_NTZ))         AS post_day_of_week,

      -- ── Moderation flags (from staging) ──
      COALESCE(lbl.is_adult_content,        FALSE)               AS is_adult_content,
      COALESCE(lbl.has_moderation_flag,     FALSE)               AS has_moderation_flag,
      COALESCE(lbl.moderation_label_count,  0)                   AS moderation_label_count,

      -- ── Actor features (from staging) ──
      af.followers_count                                         AS followers_count,
      af.follows_count                                           AS follows_count,
      af.posts_count                                             AS posts_count,
      af.follower_tier                                           AS follower_tier,
      af.account_age_days                                        AS account_age_days,
      af.follow_follower_ratio                                   AS follow_follower_ratio,
      af.posts_per_day                                           AS posts_per_day,
      COALESCE(af.is_bot_suspect,  FALSE)                        AS is_bot_suspect,
      COALESCE(af.is_spam_suspect, FALSE)                        AS is_spam_suspect,

      -- ── Trend match (from staging; has_trend_match derived from LEFT JOIN) ──
      tm.post_uri IS NOT NULL                                    AS has_trend_match,
      tm.matched_trend_name                                      AS matched_trend_name,
      tm.matched_trend_date                                      AS matched_trend_date,
      tm.matched_tweet_volume                                    AS matched_tweet_volume,
      tm.matched_trend_rank                                      AS matched_trend_rank,
      tm.trend_match_method                                      AS trend_match_method,
      tm.trend_match_score                                       AS trend_match_score
    FROM ENHANCED.STG_POST_TEXT_FEATURES stf
    LEFT JOIN ENHANCED.STG_POST_LABELS       lbl ON lbl.uri      = stf.uri
    LEFT JOIN rp_latest                      rp  ON rp.uri       = stf.uri
    LEFT JOIN post_profanity                 pp  ON pp.uri       = stf.uri
    LEFT JOIN hyd_latest                     hyd ON hyd.uri      = stf.uri
    LEFT JOIN ENHANCED.STG_ACTOR_FEATURES    af  ON af.did       = COALESCE(hyd.author_did, rp.repo_did)
    LEFT JOIN ENHANCED.STG_POST_TREND_MATCH  tm  ON tm.post_uri  = stf.uri
  )

  -- ── Moderation filter: excluded rows never enter ENHANCED ──
  SELECT *
  FROM merge_source
  WHERE COALESCE(is_adult_content, FALSE) = FALSE
    AND COALESCE(is_bot_suspect,   FALSE) = FALSE
    AND post_text_clean IS NOT NULL
    AND post_text_clean != ''

) AS src
ON tgt.uri = src.uri

WHEN MATCHED THEN UPDATE SET
  tgt.repo_did               = src.repo_did,
  tgt.author_did             = src.author_did,
  tgt.post_text_clean        = src.post_text_clean,
  tgt.was_profanity_redacted = src.was_profanity_redacted,
  tgt.severity_max           = src.severity_max,
  tgt.redaction_count        = src.redaction_count,
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
  trend_match_method, trend_match_score,
  severity_max, redaction_count
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
  src.trend_match_method, src.trend_match_score,
  src.severity_max, src.redaction_count
);



