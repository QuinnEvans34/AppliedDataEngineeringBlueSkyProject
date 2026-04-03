-- Stable top-level flatten for hydration misses.

CREATE OR REPLACE VIEW STG_HYDRATION_MISSES AS
SELECT
  raw_payload:hydrate_run_id::STRING AS hydrate_run_id,
  raw_payload:capture_run_id::STRING AS capture_run_id,
  raw_payload:uri::STRING AS uri,
  raw_payload:cid_at_capture::STRING AS cid_at_capture,
  raw_payload:captured_at::STRING AS captured_at,
  raw_payload:status::STRING AS status,
  raw_payload:reason::STRING AS reason,
  raw_payload:checked_at::STRING AS checked_at,
  raw_payload:attempt_count::NUMBER AS attempt_count,
  source_filename,
  source_file_row_number,
  source_run_tag,
  dataset_family,
  load_invocation_id,
  loaded_at
FROM LANDING_HYDRATION_MISSES;
