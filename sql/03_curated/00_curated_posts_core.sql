-- First curated merged post-level object.
-- Join semantics are preserved:
-- 1) raw -> hydrated by `uri`
-- 2) post -> actor by DID semantics using hydrated-first fallback

CREATE OR REPLACE VIEW CURATED_POSTS_CORE AS
WITH raw_latest AS (
  SELECT *
  FROM STG_RAW_POSTS
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY uri
    ORDER BY loaded_at DESC, source_filename DESC, source_file_row_number DESC
  ) = 1
),
hydrated_latest AS (
  SELECT *
  FROM STG_HYDRATED_POSTS
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY uri
    ORDER BY loaded_at DESC, source_filename DESC, source_file_row_number DESC
  ) = 1
),
actor_latest AS (
  SELECT *
  FROM STG_ACTOR_PROFILES
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY did
    ORDER BY loaded_at DESC, source_filename DESC, source_file_row_number DESC
  ) = 1
)
SELECT
  r.uri,
  r.cid AS raw_cid,
  h.cid AS hydrated_cid,
  r.repo_did,
  h.author_did,
  COALESCE(h.author_did, r.repo_did) AS join_actor_did,

  r.capture_run_id AS raw_capture_run_id,
  h.capture_run_id AS hydrated_capture_run_id,
  h.hydrate_run_id,
  a.actor_run_id,

  r.event_time,
  r.record_created_at,
  r.captured_at,
  h.indexed_at,
  h.hydrated_at,
  a.enriched_at,

  h.author_handle,
  h.author_display_name,
  a.handle AS actor_handle,
  a.display_name AS actor_display_name,
  a.description AS actor_description,

  h.reply_count,
  h.repost_count,
  h.like_count,
  h.quote_count,
  COALESCE(h.reply_count, 0)
    + COALESCE(h.repost_count, 0)
    + COALESCE(h.like_count, 0)
    + COALESCE(h.quote_count, 0) AS engagement_total,

  r.has_reply,
  r.has_embed,
  r.record AS raw_record,
  h.record AS hydrated_record,
  h.labels AS hydrated_labels,
  a.labels AS actor_labels,
  a.associated AS actor_associated,
  a.profile AS actor_profile,

  r.source_run_tag AS raw_source_run_tag,
  h.source_run_tag AS hydrated_source_run_tag,
  a.source_run_tag AS actor_source_run_tag,

  r.loaded_at AS raw_loaded_at,
  h.loaded_at AS hydrated_loaded_at,
  a.loaded_at AS actor_loaded_at
FROM raw_latest r
LEFT JOIN hydrated_latest h
  ON r.uri = h.uri
LEFT JOIN actor_latest a
  ON COALESCE(h.author_did, r.repo_did) = a.did;
