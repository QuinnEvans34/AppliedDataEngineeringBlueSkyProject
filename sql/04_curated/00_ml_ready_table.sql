-- Materialized ML-ready feature table: numeric and categorical features only.
-- No raw text, no identifiers, no metadata — only what the model needs.
-- Spec: docs/ENHANCED_CURATED_TASKS.md (Table 2)
-- Credit rules: docs/SNOWFLAKE_CREDIT_STRATEGY.md

CREATE TABLE IF NOT EXISTS CURATED.ML_READY (
  -- ── Target variable ──
  engagement_label        STRING,
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
  post_hour_utc           NUMBER,
  post_day_of_week        NUMBER,

  -- ── Actor features ──
  followers_count         NUMBER,
  follower_tier           STRING,
  account_age_days        NUMBER,
  follow_follower_ratio   FLOAT,
  posts_per_day           FLOAT,

  -- ── Trend features ──
  has_trend_match         BOOLEAN,
  matched_tweet_volume    NUMBER,
  matched_trend_rank      NUMBER,

  -- ── Split ──
  dataset_split           STRING
);

-- ════════════════════════════════════════════════════════════════════
-- VALIDATION QUERY — run manually after deployment (LIMIT per credit rules)
-- ════════════════════════════════════════════════════════════════════
/*
SELECT COUNT(*) AS row_count FROM CURATED.ML_READY;
-- Expected: 0 (table definition only, no data yet)

DESCRIBE TABLE CURATED.ML_READY;
-- Expected: 20 columns
*/

-- Reminder: suspend warehouse after running validation queries.
-- ALTER WAREHOUSE COMPUTE_WH SUSPEND;
