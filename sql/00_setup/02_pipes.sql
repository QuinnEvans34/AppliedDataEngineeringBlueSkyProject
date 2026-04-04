-- Snowflake loader v2 setup: one internal-stage Snowpipe per dataset family.
-- AUTO_INGEST remains FALSE; refresh/polling is handled by loader logic in later phases.

CREATE PIPE IF NOT EXISTS BLUESKY_RAW_POSTS_PIPE
  AUTO_INGEST = FALSE
AS
COPY INTO LANDING_RAW_POSTS
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
  FROM @BLUESKY_RAW_POSTS_STAGE
)
FILE_FORMAT = (FORMAT_NAME = 'BLUESKY_JSONL_GZ')
PATTERN = '^.*/raw_posts/[^/]+/[^/]+\\.jsonl\\.gz$'
ON_ERROR = 'CONTINUE';

CREATE PIPE IF NOT EXISTS BLUESKY_HYDRATED_POSTS_PIPE
  AUTO_INGEST = FALSE
AS
COPY INTO LANDING_HYDRATED_POSTS
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
  FROM @BLUESKY_HYDRATED_POSTS_STAGE
)
FILE_FORMAT = (FORMAT_NAME = 'BLUESKY_JSONL_GZ')
PATTERN = '^.*/hydrated_posts/[^/]+/[^/]+\\.jsonl\\.gz$'
ON_ERROR = 'CONTINUE';

CREATE PIPE IF NOT EXISTS BLUESKY_HYDRATION_MISSES_PIPE
  AUTO_INGEST = FALSE
AS
COPY INTO LANDING_HYDRATION_MISSES
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
  FROM @BLUESKY_HYDRATION_MISSES_STAGE
)
FILE_FORMAT = (FORMAT_NAME = 'BLUESKY_JSONL_GZ')
PATTERN = '^.*/hydration_misses/[^/]+/[^/]+\\.jsonl\\.gz$'
ON_ERROR = 'CONTINUE';

CREATE PIPE IF NOT EXISTS BLUESKY_ACTOR_PROFILES_PIPE
  AUTO_INGEST = FALSE
AS
COPY INTO LANDING_ACTOR_PROFILES
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
  FROM @BLUESKY_ACTOR_PROFILES_STAGE
)
FILE_FORMAT = (FORMAT_NAME = 'BLUESKY_JSONL_GZ')
PATTERN = '^.*/actor_profiles/[^/]+/[^/]+\\.jsonl\\.gz$'
ON_ERROR = 'CONTINUE';
