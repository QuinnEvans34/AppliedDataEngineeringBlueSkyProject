-- Materialized enriched posts table: one row per post with all cleaned,
-- joined, and computed columns needed for analysis and ML.
-- Spec: docs/ENHANCED_CURATED_TASKS.md (Table 1)
-- Credit rules: docs/SNOWFLAKE_CREDIT_STRATEGY.md

CREATE TABLE IF NOT EXISTS ENHANCED.POSTS_ENRICHED (
  -- ── Identity ──
  uri                     STRING NOT NULL,
  repo_did                STRING,
  author_did              STRING,

  -- ── Clean text ──
  post_text_clean         STRING,
  was_profanity_redacted  BOOLEAN,

  -- ── Engagement metrics (NULL if not hydrated yet) ──
  reply_count             NUMBER,
  repost_count            NUMBER,
  like_count              NUMBER,
  quote_count             NUMBER,
  engagement_total        NUMBER,

  -- ── Text features ──
  post_length             NUMBER,
  post_word_count         NUMBER,
  hashtag_count           NUMBER,
  mention_count           NUMBER,
  url_count               NUMBER,
  exclamation_count       NUMBER,
  question_count          NUMBER,

  -- ── Temporal features ──
  post_created_at_ts      TIMESTAMP_NTZ,
  post_hour_utc           NUMBER,
  post_day_of_week        NUMBER,

  -- ── Moderation flags ──
  is_adult_content        BOOLEAN,
  has_moderation_flag     BOOLEAN,
  moderation_label_count  NUMBER,

  -- ── Actor features ──
  followers_count         NUMBER,
  follows_count           NUMBER,
  posts_count             NUMBER,
  follower_tier           STRING,
  account_age_days        NUMBER,
  follow_follower_ratio   FLOAT,
  posts_per_day           FLOAT,

  -- ── Bot detection ──
  is_bot_suspect          BOOLEAN,
  is_spam_suspect         BOOLEAN,

  -- ── Trend match (NULL if no match found) ──
  has_trend_match         BOOLEAN,
  matched_trend_name      STRING,
  matched_trend_date      DATE,
  matched_tweet_volume    NUMBER,
  matched_trend_rank      NUMBER,
  trend_match_method      STRING,
  trend_match_score       FLOAT,

  -- ── Profanity metrics ──
  severity_max            STRING,
  redaction_count         NUMBER,

  -- ── Metadata ──
  enriched_at             TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);

-- ════════════════════════════════════════════════════════════════════
-- VALIDATION QUERY — run manually after deployment (LIMIT per credit rules)
-- ════════════════════════════════════════════════════════════════════
/*
SELECT COUNT(*) AS row_count FROM ENHANCED.POSTS_ENRICHED;
-- Expected: 0 (table definition only, no data yet)

DESCRIBE TABLE ENHANCED.POSTS_ENRICHED;
-- Expected: 41 columns
*/

-- Reminder: suspend warehouse after running validation queries.
-- ALTER WAREHOUSE COMPUTE_WH SUSPEND;
