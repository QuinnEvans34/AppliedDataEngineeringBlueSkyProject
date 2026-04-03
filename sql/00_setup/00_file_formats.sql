-- Snowflake loader v1 setup: JSONL.GZ format + idempotency manifest.

CREATE FILE FORMAT IF NOT EXISTS BLUESKY_JSONL_GZ
  TYPE = 'JSON'
  COMPRESSION = 'GZIP'
  STRIP_OUTER_ARRAY = FALSE
  STRIP_NULL_VALUES = FALSE
  REPLACE_INVALID_CHARACTERS = FALSE;

CREATE TABLE IF NOT EXISTS LOADER_FILE_MANIFEST (
  manifest_id NUMBER AUTOINCREMENT START 1 INCREMENT 1,
  dataset_family STRING NOT NULL,
  source_run_tag STRING NOT NULL,
  local_file_path STRING NOT NULL,
  stage_file_name STRING NOT NULL,
  local_row_count NUMBER NOT NULL,
  local_byte_size NUMBER NOT NULL,
  landing_rows_loaded NUMBER NOT NULL,
  load_invocation_id STRING NOT NULL,
  loaded_at TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT uq_loader_file_manifest UNIQUE (dataset_family, source_run_tag, local_file_path)
);
