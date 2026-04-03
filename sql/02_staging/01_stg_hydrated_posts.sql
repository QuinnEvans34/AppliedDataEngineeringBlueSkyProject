-- Stable top-level flatten for hydrated posts.
-- Keep `labels` and `record` as semi-structured in v1.

CREATE OR REPLACE VIEW STG_HYDRATED_POSTS AS
SELECT
  raw_payload:hydrate_run_id::STRING AS hydrate_run_id,
  raw_payload:capture_run_id::STRING AS capture_run_id,
  raw_payload:uri::STRING AS uri,
  raw_payload:cid::STRING AS cid,
  raw_payload:indexed_at::STRING AS indexed_at,
  raw_payload:author_did::STRING AS author_did,
  raw_payload:author_handle::STRING AS author_handle,
  raw_payload:author_display_name::STRING AS author_display_name,
  raw_payload:reply_count::NUMBER AS reply_count,
  raw_payload:repost_count::NUMBER AS repost_count,
  raw_payload:like_count::NUMBER AS like_count,
  raw_payload:quote_count::NUMBER AS quote_count,
  raw_payload:labels AS labels,
  raw_payload:hydrated_at::STRING AS hydrated_at,
  raw_payload:record AS record,
  source_filename,
  source_file_row_number,
  source_run_tag,
  dataset_family,
  load_invocation_id,
  loaded_at
FROM LANDING_HYDRATED_POSTS;
