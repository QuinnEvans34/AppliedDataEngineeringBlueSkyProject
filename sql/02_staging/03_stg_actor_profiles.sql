-- Stable top-level flatten for actor profiles.
-- Keep `labels`, `associated`, and full `profile` as semi-structured in v1.

CREATE OR REPLACE VIEW STG_ACTOR_PROFILES AS
SELECT
  raw_payload:actor_run_id::STRING AS actor_run_id,
  raw_payload:did::STRING AS did,
  raw_payload:handle::STRING AS handle,
  raw_payload:display_name::STRING AS display_name,
  raw_payload:description::STRING AS description,
  raw_payload:followers_count::NUMBER AS followers_count,
  raw_payload:follows_count::NUMBER AS follows_count,
  raw_payload:posts_count::NUMBER AS posts_count,
  raw_payload:indexed_at::STRING AS indexed_at,
  raw_payload:created_at::STRING AS created_at,
  raw_payload:labels AS labels,
  raw_payload:associated AS associated,
  raw_payload:enriched_at::STRING AS enriched_at,
  raw_payload:profile AS profile,
  source_filename,
  source_file_row_number,
  source_run_tag,
  dataset_family,
  load_invocation_id,
  loaded_at
FROM LANDING_ACTOR_PROFILES;
