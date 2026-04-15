-- Landing table for hydrated_posts append loads.

CREATE TABLE IF NOT EXISTS RAW.LANDING_HYDRATED_POSTS (
  landing_id NUMBER AUTOINCREMENT START 1 INCREMENT 1,
  raw_payload VARIANT NOT NULL,
  source_filename STRING NOT NULL,
  source_file_row_number NUMBER,
  source_run_tag STRING NOT NULL,
  dataset_family STRING NOT NULL,
  load_invocation_id STRING NOT NULL,
  loaded_at TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
