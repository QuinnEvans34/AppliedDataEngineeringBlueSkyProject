-- One Snowpipe per dataset family, all in RAW schema.
-- AUTO_INGEST = TRUE: pipes auto-ingest files as they land in their stages.
-- Pattern matches docs/reference.sql (CITYBIKE_PIPELINE.RAW.TRIPS_PIPE).
-- Spec: docs/SCHEMA_MIGRATION.md
-- Credit rules: docs/SNOWFLAKE_CREDIT_STRATEGY.md

CREATE OR REPLACE PIPE RAW.BLUESKY_RAW_POSTS_PIPE
  AUTO_INGEST = TRUE
AS
COPY INTO RAW.LANDING_RAW_POSTS
(
  raw_payload,
  source_filename,
  source_file_row_number,
  source_run_tag,
  dataset_family,
  load_invocation_id,
  loaded_at
)
FROM (
  SELECT
    $1,
    METADATA$FILENAME,
    METADATA$FILE_ROW_NUMBER,
    SPLIT_PART(METADATA$FILENAME, '/', 1),
    'raw_posts',
    'snowpipe',
    CURRENT_TIMESTAMP()
  FROM @RAW.BLUESKY_RAW_POSTS_STAGE
)
FILE_FORMAT = (FORMAT_NAME = 'RAW.BLUESKY_JSONL_GZ')
PATTERN = '^.*/raw_posts/[^/]+/[^/]+\\.jsonl\\.gz$'
ON_ERROR = 'CONTINUE';

CREATE OR REPLACE PIPE RAW.BLUESKY_HYDRATED_POSTS_PIPE
  AUTO_INGEST = TRUE
AS
COPY INTO RAW.LANDING_HYDRATED_POSTS
(
  raw_payload,
  source_filename,
  source_file_row_number,
  source_run_tag,
  dataset_family,
  load_invocation_id,
  loaded_at
)
FROM (
  SELECT
    $1,
    METADATA$FILENAME,
    METADATA$FILE_ROW_NUMBER,
    SPLIT_PART(METADATA$FILENAME, '/', 1),
    'hydrated_posts',
    'snowpipe',
    CURRENT_TIMESTAMP()
  FROM @RAW.BLUESKY_HYDRATED_POSTS_STAGE
)
FILE_FORMAT = (FORMAT_NAME = 'RAW.BLUESKY_JSONL_GZ')
PATTERN = '^.*/hydrated_posts/[^/]+/[^/]+\\.jsonl\\.gz$'
ON_ERROR = 'CONTINUE';

CREATE OR REPLACE PIPE RAW.BLUESKY_HYDRATION_MISSES_PIPE
  AUTO_INGEST = TRUE
AS
COPY INTO RAW.LANDING_HYDRATION_MISSES
(
  raw_payload,
  source_filename,
  source_file_row_number,
  source_run_tag,
  dataset_family,
  load_invocation_id,
  loaded_at
)
FROM (
  SELECT
    $1,
    METADATA$FILENAME,
    METADATA$FILE_ROW_NUMBER,
    SPLIT_PART(METADATA$FILENAME, '/', 1),
    'hydration_misses',
    'snowpipe',
    CURRENT_TIMESTAMP()
  FROM @RAW.BLUESKY_HYDRATION_MISSES_STAGE
)
FILE_FORMAT = (FORMAT_NAME = 'RAW.BLUESKY_JSONL_GZ')
PATTERN = '^.*/hydration_misses/[^/]+/[^/]+\\.jsonl\\.gz$'
ON_ERROR = 'CONTINUE';

CREATE OR REPLACE PIPE RAW.BLUESKY_ACTOR_PROFILES_PIPE
  AUTO_INGEST = TRUE
AS
COPY INTO RAW.LANDING_ACTOR_PROFILES
(
  raw_payload,
  source_filename,
  source_file_row_number,
  source_run_tag,
  dataset_family,
  load_invocation_id,
  loaded_at
)
FROM (
  SELECT
    $1,
    METADATA$FILENAME,
    METADATA$FILE_ROW_NUMBER,
    SPLIT_PART(METADATA$FILENAME, '/', 1),
    'actor_profiles',
    'snowpipe',
    CURRENT_TIMESTAMP()
  FROM @RAW.BLUESKY_ACTOR_PROFILES_STAGE
)
FILE_FORMAT = (FORMAT_NAME = 'RAW.BLUESKY_JSONL_GZ')
PATTERN = '^.*/actor_profiles/[^/]+/[^/]+\\.jsonl\\.gz$'
ON_ERROR = 'CONTINUE';

CREATE OR REPLACE PIPE RAW.BLUESKY_TWITTER_TRENDS_PIPE
  AUTO_INGEST = TRUE
AS
COPY INTO RAW.LANDING_TWITTER_TRENDS
(
  raw_payload,
  source_filename,
  source_file_row_number,
  source_run_tag,
  dataset_family,
  load_invocation_id,
  loaded_at
)
FROM (
  SELECT
    $1,
    METADATA$FILENAME,
    METADATA$FILE_ROW_NUMBER,
    SPLIT_PART(METADATA$FILENAME, '/', 1),
    'twitter_trends',
    'snowpipe',
    CURRENT_TIMESTAMP()
  FROM @RAW.BLUESKY_TWITTER_TRENDS_STAGE
)
FILE_FORMAT = (FORMAT_NAME = 'RAW.BLUESKY_JSONL_GZ')
PATTERN = '^.*/twitter_trends/[^/]+/[^/]+\\.jsonl\\.gz$'
ON_ERROR = 'CONTINUE';

CREATE OR REPLACE PIPE RAW.BLUESKY_TREND_MATCHES_PIPE
  AUTO_INGEST = TRUE
AS
COPY INTO RAW.LANDING_TREND_MATCHES
(
  raw_payload,
  source_filename,
  source_file_row_number,
  source_run_tag,
  dataset_family,
  load_invocation_id,
  loaded_at
)
FROM (
  SELECT
    $1,
    METADATA$FILENAME,
    METADATA$FILE_ROW_NUMBER,
    SPLIT_PART(METADATA$FILENAME, '/', 1),
    'trend_matches',
    'snowpipe',
    CURRENT_TIMESTAMP()
  FROM @RAW.BLUESKY_TREND_MATCHES_STAGE
)
FILE_FORMAT = (FORMAT_NAME = 'RAW.BLUESKY_JSONL_GZ')
PATTERN = '^.*/trend_matches/[^/]+/[^/]+\\.jsonl\\.gz$'
ON_ERROR = 'CONTINUE';
