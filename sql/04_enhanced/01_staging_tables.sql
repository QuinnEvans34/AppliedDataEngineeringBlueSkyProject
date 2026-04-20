-- Per-concern staging tables backing the enrichment split.
-- Phase A of docs/CLAUDE_PROMPTS_ENRICHMENT.md: DDL only. Empty tables
-- created here become the write targets for the four per-concern tasks
-- introduced in Phase B; the assembler MERGE in Phase C reads from them.
-- Spec: docs/PROMPT_ENRICHMENT_TASK_SPLIT.md (Target Topology)
-- Credit rules: docs/SNOWFLAKE_CREDIT_STRATEGY.md

-- ════════════════════════════════════════════════════════════════════
-- STG_POST_LABELS — 1 row per post uri; moderation-label flags
-- Populated by: ENHANCED.TASK_FLATTEN_LABELS (Phase B)
-- ════════════════════════════════════════════════════════════════════
CREATE OR REPLACE TABLE ENHANCED.STG_POST_LABELS (
  uri                       STRING PRIMARY KEY,
  is_adult_content          BOOLEAN,
  has_moderation_flag       BOOLEAN,
  moderation_label_count    NUMBER,
  stg_computed_at           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP
)
COMMENT = 'Staging: one row per post uri. Moderation-label flags flattened from hydrated payloads. Populated by ENHANCED.TASK_FLATTEN_LABELS (root of the enrichment chain).';

-- ════════════════════════════════════════════════════════════════════
-- STG_POST_TEXT_FEATURES — 1 row per post uri; cleaned text + regex features
-- Populated by: ENHANCED.TASK_TEXT_FEATURES (Phase B)
-- ════════════════════════════════════════════════════════════════════
CREATE OR REPLACE TABLE ENHANCED.STG_POST_TEXT_FEATURES (
  uri                       STRING PRIMARY KEY,
  post_text_clean           STRING,
  was_profanity_redacted    BOOLEAN,
  post_length               NUMBER,
  post_word_count           NUMBER,
  hashtag_count             NUMBER,
  mention_count             NUMBER,
  url_count                 NUMBER,
  exclamation_count         NUMBER,
  question_count            NUMBER,
  stg_computed_at           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP
)
COMMENT = 'Staging: one row per post uri. CLEAN_PROFANITY() output plus regex-derived text feature counts. Populated by ENHANCED.TASK_TEXT_FEATURES.';

-- ════════════════════════════════════════════════════════════════════
-- STG_ACTOR_FEATURES — 1 row per did; derived actor features + bot flags
-- Populated by: ENHANCED.TASK_ACTOR_FEATURES (Phase B)
-- ════════════════════════════════════════════════════════════════════
CREATE OR REPLACE TABLE ENHANCED.STG_ACTOR_FEATURES (
  did                       STRING PRIMARY KEY,
  followers_count           NUMBER,
  follows_count             NUMBER,
  posts_count               NUMBER,
  follower_tier             STRING,
  account_age_days          NUMBER,
  follow_follower_ratio     FLOAT,
  posts_per_day             FLOAT,
  has_actor_label           BOOLEAN,
  is_bot_suspect            BOOLEAN,
  is_spam_suspect           BOOLEAN,
  stg_computed_at           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP
)
COMMENT = 'Staging: one row per actor did. Normalized profile metrics (follower_tier, account_age_days, ratios) and bot/spam suspect flags. Populated by ENHANCED.TASK_ACTOR_FEATURES.';

-- ════════════════════════════════════════════════════════════════════
-- STG_POST_TREND_MATCH — 1 row per matched post uri (no rows for unmatched)
-- Populated by: ENHANCED.TASK_TREND_MATCH (Phase B)
-- ════════════════════════════════════════════════════════════════════
CREATE OR REPLACE TABLE ENHANCED.STG_POST_TREND_MATCH (
  post_uri                  STRING PRIMARY KEY,
  matched_trend_name        STRING,
  matched_trend_date        DATE,
  matched_tweet_volume      NUMBER,
  matched_trend_rank        NUMBER,
  trend_match_method        STRING,
  trend_match_score         FLOAT,
  stg_computed_at           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP
)
COMMENT = 'Staging: one row per matched post uri (unmatched posts are excluded, not written with FALSE). Trend-match results joined to the canonical twitter_trends dimension. Populated by ENHANCED.TASK_TREND_MATCH.';


-- ════════════════════════════════════════════════════════════════════
-- VALIDATION QUERY — run manually after deployment (LIMIT per credit rules)
-- ════════════════════════════════════════════════════════════════════
/*
SHOW TABLES LIKE 'STG_%' IN SCHEMA ENHANCED;
-- Expected: 4 tables (STG_POST_LABELS, STG_POST_TEXT_FEATURES,
--                     STG_ACTOR_FEATURES, STG_POST_TREND_MATCH)

SELECT COUNT(*) FROM ENHANCED.STG_POST_LABELS;        -- expect 0
SELECT COUNT(*) FROM ENHANCED.STG_POST_TEXT_FEATURES; -- expect 0
SELECT COUNT(*) FROM ENHANCED.STG_ACTOR_FEATURES;     -- expect 0
SELECT COUNT(*) FROM ENHANCED.STG_POST_TREND_MATCH;   -- expect 0
*/

-- Reminder: suspend warehouse after running validation queries.
-- ALTER WAREHOUSE COMPUTE_WH SUSPEND;
