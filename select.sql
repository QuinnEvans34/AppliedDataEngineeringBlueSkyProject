select * from raw.landing_raw_posts;
select * from raw.LANDING_ACTOR_PROFILES;


SELECT SYSTEM$PIPE_STATUS('RAW.BLUESKY_RAW_POSTS_PIPE');
LIST @RAW.BLUESKY_RAW_POSTS_STAGE;


-- Suspend both tasks
ALTER TASK ENHANCED.TASK_BUILD_ML_READY SUSPEND;
ALTER TASK ENHANCED.TASK_ENRICH_POSTS SUSPEND;

-- Suspend warehouse
ALTER WAREHOUSE COMPUTE_WH SUSPEND;

-- Confirm both tasks are suspended
SHOW TASKS IN SCHEMA ENHANCED;


Select * from raw.landing_trend_matches;


SHOW TASKS IN SCHEMA ENHANCED;


SELECT SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_RAW_POSTS');


SHOW STREAMS IN SCHEMA RAW;
SHOW TASKS IN SCHEMA ENHANCED;


SELECT SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_RAW_POSTS');



-- Check stream has data
SELECT SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_RAW_POSTS');

-- Check task ran successfully
SELECT NAME, STATE, ERROR_MESSAGE
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
    SCHEDULED_TIME_RANGE_START => DATEADD('minute', -5, CURRENT_TIMESTAMP()),
    TASK_NAME => 'TASK_ENRICH_POSTS'
))
ORDER BY SCHEDULED_TIME DESC
LIMIT 3;

-- Check ENHANCED has rows
SELECT COUNT(*) FROM ENHANCED.POSTS_ENRICHED;


SHOW TASKS IN SCHEMA ENHANCED;





-- Does the UDF exist at all?
SHOW USER FUNCTIONS IN SCHEMA RAW;
SHOW USER FUNCTIONS IN DATABASE BLUESKYDATAENGINEERINGPROJECT;

-- What role is the task running as?
SHOW TASKS IN SCHEMA ENHANCED;


SHOW USER FUNCTIONS LIKE 'CLEAN_PROFANITY' IN ACCOUNT;



-- 1. Run 03_udfs.sql to create the UDF in ENHANCED

-- 2. Verify it exists
SHOW USER FUNCTIONS IN SCHEMA ENHANCED;

-- 3. Suspend, redeploy tasks, resume
ALTER TASK ENHANCED.TASK_BUILD_ML_READY SUSPEND;
ALTER TASK ENHANCED.TASK_ENRICH_POSTS SUSPEND;
-- Run updated 00_tasks.sql
ALTER TASK ENHANCED.TASK_BUILD_ML_READY RESUME;
ALTER TASK ENHANCED.TASK_ENRICH_POSTS RESUME;

-- 4. Fire manually
EXECUTE TASK ENHANCED.TASK_ENRICH_POSTS;

-- 5. Check result
SELECT COUNT(*) FROM ENHANCED.POSTS_ENRICHED;


-- 6. Check task history for errors
SELECT STATE, ERROR_MESSAGE
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
    TASK_NAME => 'TASK_ENRICH_POSTS',
    SCHEDULED_TIME_RANGE_START => DATEADD('minute', -5, CURRENT_TIMESTAMP())
))
ORDER BY SCHEDULED_TIME DESC LIMIT 3;



-- 1. Suspend both tasks
ALTER TASK ENHANCED.TASK_BUILD_ML_READY SUSPEND;
ALTER TASK ENHANCED.TASK_ENRICH_POSTS SUSPEND;



-- 2. Resume child first then parent
ALTER TASK ENHANCED.TASK_BUILD_ML_READY RESUME;
ALTER TASK ENHANCED.TASK_ENRICH_POSTS RESUME;

-- 3. Fire manually
EXECUTE TASK ENHANCED.TASK_ENRICH_POSTS;

select count(*) from enhanced.posts_enriched;



DESCRIBE TASK ENHANCED.TASK_ENRICH_POSTS;


SELECT COUNT(*) FROM RAW.LANDING_TREND_MATCHES;



SELECT NAME, STATE, SCHEDULED_TIME, COMPLETED_TIME, ERROR_MESSAGE
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
  TASK_NAME => 'ENHANCED.TASK_ENRICH_POSTS',
  SCHEDULED_TIME_RANGE_START => DATEADD('hour', -1, CURRENT_TIMESTAMP())
))
ORDER BY SCHEDULED_TIME DESC;


SELECT NAME, STATE, SCHEDULED_TIME, QUERY_ID, ERROR_MESSAGE
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(
  TASK_NAME => 'ENHANCED.TASK_ENRICH_POSTS',
  SCHEDULED_TIME_RANGE_START => DATEADD('hour', -2, CURRENT_TIMESTAMP())
))
ORDER BY SCHEDULED_TIME DESC;


SELECT
  COUNT(*) AS total_rows,
  COUNT_IF(has_trend_match) AS matched_rows,
  COUNT_IF(matched_trend_name IS NOT NULL) AS named_match_rows
FROM ENHANCED.POSTS_ENRICHED;


SELECT COUNT(*) AS raw_stream_rows
FROM RAW.STRM_LANDING_RAW_POSTS;


SELECT
  COUNT(*) AS total_rows,
  COUNT_IF(has_trend_match) AS matched_rows,
  COUNT_IF(matched_trend_name IS NOT NULL) AS named_match_rows
FROM ENHANCED.POSTS_ENRICHED;




DESCRIBE TASK ENHANCED.TASK_ENRICH_POSTS;




SELECT
  raw_payload:post_uri::STRING AS post_uri,
  raw_payload:trend_name::STRING AS trend_name,
  raw_payload:trend_key_no_hash::STRING AS trend_key_no_hash,
  raw_payload:trend_date::DATE AS trend_date,
  raw_payload:match_method::STRING AS match_method,
  raw_payload:match_score::FLOAT AS match_score,
  loaded_at
FROM RAW.LANDING_TREND_MATCHES
WHERE raw_payload:post_uri::STRING = 'at://did:plc:2hxoksaolyda7uke4hghfa3v/app.bsky.feed.post/3mjkn4d7ouk2d'
ORDER BY loaded_at DESC;




SELECT
  raw_payload:uri::STRING AS uri,
  COALESCE(raw_payload:repo_did::STRING, raw_payload:did::STRING) AS repo_did,
  raw_payload:record:text::STRING AS post_text,
  loaded_at
FROM RAW.LANDING_RAW_POSTS
WHERE raw_payload:uri::STRING = 'at://did:plc:2hxoksaolyda7uke4hghfa3v/app.bsky.feed.post/3mjkn4d7ouk2d'
ORDER BY loaded_at DESC;



SELECT *
FROM ENHANCED.POSTS_ENRICHED
WHERE uri = 'at://did:plc:2hxoksaolyda7uke4hghfa3v/app.bsky.feed.post/3mjkn4d7ouk2d';




WITH tm AS (
  SELECT
    raw_payload:post_uri::STRING AS post_uri,
    raw_payload:trend_name::STRING AS trend_name,
    COALESCE(
      raw_payload:trend_key_no_hash::STRING,
      raw_payload:normalized_key_no_hash::STRING,
      LOWER(TRIM(REPLACE(raw_payload:trend_name::STRING, '#', '')))
    ) AS trend_key_no_hash,
    raw_payload:trend_date::DATE AS trend_date
  FROM RAW.LANDING_TREND_MATCHES
  WHERE raw_payload:post_uri::STRING = 'at://did:plc:2hxoksaolyda7uke4hghfa3v/app.bsky.feed.post/3mjkn4d7ouk2d'
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY raw_payload:post_uri::STRING
    ORDER BY loaded_at DESC, landing_id DESC
  ) = 1
),
tt AS (
  SELECT
    raw_payload:trend_date::DATE AS trend_date,
    COALESCE(
      raw_payload:trend_key_no_hash::STRING,
      raw_payload:normalized_key_no_hash::STRING,
      LOWER(TRIM(REPLACE(COALESCE(raw_payload:trend_name::STRING, raw_payload:trend_name_raw::STRING), '#', '')))
    ) AS trend_key_no_hash,
    raw_payload:trend_name::STRING AS trend_name,
    raw_payload:tweet_volume::NUMBER AS tweet_volume,
    raw_payload:rank::NUMBER AS trend_rank,
    loaded_at
  FROM RAW.LANDING_TWITTER_TRENDS
)
SELECT
  tm.post_uri,
  tm.trend_name AS tm_trend_name,
  tm.trend_key_no_hash AS tm_key,
  tm.trend_date AS tm_date,
  tt.trend_name AS tt_trend_name,
  tt.trend_key_no_hash AS tt_key,
  tt.trend_date AS tt_date,
  tt.tweet_volume,
  tt.trend_rank,
  tt.loaded_at
FROM tm
LEFT JOIN tt
  ON tm.trend_date = tt.trend_date
 AND tm.trend_key_no_hash = tt.trend_key_no_hash;





Select * from raw.landing_raw_posts;





