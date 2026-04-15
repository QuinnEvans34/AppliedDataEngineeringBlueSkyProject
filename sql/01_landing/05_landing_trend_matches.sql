-- Landing table for trend_matches append loads (Python FAISS match results).
-- Spec: docs/SCHEMA_MIGRATION.md
-- Credit rules: docs/SNOWFLAKE_CREDIT_STRATEGY.md

CREATE TABLE IF NOT EXISTS RAW.LANDING_TREND_MATCHES (
  landing_id             NUMBER AUTOINCREMENT PRIMARY KEY,
  raw_payload            VARIANT NOT NULL,
  source_filename        STRING NOT NULL,
  source_file_row_number NUMBER,
  source_run_tag         STRING NOT NULL,
  dataset_family         STRING NOT NULL DEFAULT 'trend_matches',
  load_invocation_id     STRING NOT NULL,
  loaded_at              TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- Reminder: suspend warehouse after running any load.
-- ALTER WAREHOUSE COMPUTE_WH SUSPEND;
