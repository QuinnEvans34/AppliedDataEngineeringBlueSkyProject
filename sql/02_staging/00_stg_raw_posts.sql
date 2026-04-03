-- Stable top-level flatten for raw posts.
-- Keep nested `record` as semi-structured in v1.

CREATE OR REPLACE VIEW STG_RAW_POSTS AS
SELECT
  raw_payload:capture_run_id::STRING AS capture_run_id,
  raw_payload:seq::NUMBER AS seq,
  raw_payload:repo_did::STRING AS repo_did,
  raw_payload:event_time::STRING AS event_time,
  raw_payload:operation::STRING AS operation,
  raw_payload:collection::STRING AS collection,
  raw_payload:rkey::STRING AS rkey,
  raw_payload:uri::STRING AS uri,
  raw_payload:cid::STRING AS cid,
  raw_payload:record_created_at::STRING AS record_created_at,
  raw_payload:has_reply::BOOLEAN AS has_reply,
  raw_payload:has_embed::BOOLEAN AS has_embed,
  raw_payload:captured_at::STRING AS captured_at,
  raw_payload:record AS record,
  source_filename,
  source_file_row_number,
  source_run_tag,
  dataset_family,
  load_invocation_id,
  loaded_at
FROM LANDING_RAW_POSTS;
