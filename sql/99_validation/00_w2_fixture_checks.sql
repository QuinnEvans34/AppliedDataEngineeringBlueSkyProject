-- Week 2 fixture validation checks (Snowpipe/COPY RAW landing).
-- Update RUN_TAG if you used a non-default fixture output run root name.

SET RUN_TAG = 'w2_fixture_25';

-- 1) Stage file presence by family/prefix (expect >= 1 file per family after upload/load).
LIST @BLUESKY_RAW_POSTS_STAGE/$RUN_TAG/raw_posts;
LIST @BLUESKY_HYDRATED_POSTS_STAGE/$RUN_TAG/hydrated_posts;
LIST @BLUESKY_HYDRATION_MISSES_STAGE/$RUN_TAG/hydration_misses;
LIST @BLUESKY_ACTOR_PROFILES_STAGE/$RUN_TAG/actor_profiles;

-- 2) Landing counts (expect 25 rows per family for first successful fixture load).
SELECT 'raw_posts' AS dataset_family, COUNT(*) AS landing_rows
FROM LANDING_RAW_POSTS
WHERE source_run_tag = $RUN_TAG
UNION ALL
SELECT 'hydrated_posts' AS dataset_family, COUNT(*) AS landing_rows
FROM LANDING_HYDRATED_POSTS
WHERE source_run_tag = $RUN_TAG
UNION ALL
SELECT 'hydration_misses' AS dataset_family, COUNT(*) AS landing_rows
FROM LANDING_HYDRATION_MISSES
WHERE source_run_tag = $RUN_TAG
UNION ALL
SELECT 'actor_profiles' AS dataset_family, COUNT(*) AS landing_rows
FROM LANDING_ACTOR_PROFILES
WHERE source_run_tag = $RUN_TAG;

-- 3) Manifest row counts by family (expect 1 file entry per family for this fixture run).
SELECT
  dataset_family,
  COUNT(*) AS manifest_file_entries,
  SUM(landing_rows_loaded) AS manifest_rows_loaded
FROM LOADER_FILE_MANIFEST
WHERE source_run_tag = $RUN_TAG
GROUP BY dataset_family
ORDER BY dataset_family;

-- 4) Recent Snowpipe copy history proof (no manual UI loading required).
SELECT TABLE_NAME, FILE_NAME, STATUS, ROW_COUNT, LAST_LOAD_TIME
FROM TABLE(
  INFORMATION_SCHEMA.COPY_HISTORY(
    START_TIME=>DATEADD('HOUR', -2, CURRENT_TIMESTAMP())
  )
)
WHERE FILE_NAME ILIKE CONCAT('%/', $RUN_TAG, '/%')
ORDER BY LAST_LOAD_TIME DESC;
