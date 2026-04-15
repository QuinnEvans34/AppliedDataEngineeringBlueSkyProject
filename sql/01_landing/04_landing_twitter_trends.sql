-- Landing table for twitter_trends append loads.
-- Spec: docs/SQL_TWITTER_TRENDS.md
-- Credit rules: docs/SNOWFLAKE_CREDIT_STRATEGY.md

CREATE TABLE IF NOT EXISTS RAW.LANDING_TWITTER_TRENDS (
  landing_id             NUMBER AUTOINCREMENT PRIMARY KEY,
  raw_payload            VARIANT NOT NULL,
  source_filename        STRING NOT NULL,
  source_file_row_number NUMBER,
  source_run_tag         STRING NOT NULL,
  dataset_family         STRING NOT NULL DEFAULT 'twitter_trends',
  load_invocation_id     STRING NOT NULL,
  loaded_at              TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- ════════════════════════════════════════════════════════════════════
-- COPY INTO — run only when local snapshot file is staged and ready
-- ════════════════════════════════════════════════════════════════════
-- COPY INTO RAW.LANDING_TWITTER_TRENDS (raw_payload, source_filename,
--     source_file_row_number, source_run_tag, load_invocation_id)
-- FROM @RAW.BLUESKY_TWITTER_TRENDS_STAGE
-- FILE_FORMAT = (FORMAT_NAME = RAW.BLUESKY_JSONL_GZ)
-- ON_ERROR = CONTINUE;

-- Reminder: suspend warehouse after running any load.
-- ALTER WAREHOUSE COMPUTE_WH SUSPEND;
