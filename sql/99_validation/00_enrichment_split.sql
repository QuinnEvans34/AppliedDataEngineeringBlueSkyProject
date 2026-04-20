-- Validation: enrichment-split cutover (Phase C)
-- Spec: docs/CLAUDE_PROMPTS_ENRICHMENT.md (Phase C, step 6) +
--       docs/PROMPT_ENRICHMENT_TASK_SPLIT.md (Work-to-do step 4).
--
-- How to use:
--   1. BEFORE dropping TASK_ENRICH_POSTS, run BLOCK 1 and paste the
--      numeric results into the "Baseline captured" comment below.
--   2. AFTER the new assembler has fired end-to-end, run BLOCK 2 and
--      eyeball-diff against the baseline. Tolerance: 0-row delta.
--   3. Run BLOCK 3 to assert POSTS_ENRICHED rows == the filtered
--      STG_POST_TEXT_FEATURES count.

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;

-- ════════════════════════════════════════════════════════════════════
-- BLOCK 1 — BASELINE CAPTURE (run BEFORE Phase C cutover)
-- ════════════════════════════════════════════════════════════════════
/*
SELECT COUNT(*) AS posts_enriched_rows FROM ENHANCED.POSTS_ENRICHED;
SELECT COUNT(*) AS ml_ready_rows       FROM CURATED.ML_READY;

SELECT follower_tier,   COUNT(*) AS n FROM ENHANCED.POSTS_ENRICHED GROUP BY 1 ORDER BY 1;
SELECT has_trend_match, COUNT(*) AS n FROM ENHANCED.POSTS_ENRICHED GROUP BY 1 ORDER BY 1;
SELECT is_bot_suspect,  COUNT(*) AS n FROM ENHANCED.POSTS_ENRICHED GROUP BY 1 ORDER BY 1;

-- Baseline captured (paste results here):
--   posts_enriched_rows = ____
--   ml_ready_rows       = ____
--   follower_tier:   HIGH=__, MID=__, LOW=__, MICRO=__
--   has_trend_match: TRUE=__, FALSE=__
--   is_bot_suspect:  TRUE=__, FALSE=__
*/

-- ════════════════════════════════════════════════════════════════════
-- BLOCK 2 — POST-REFACTOR ASSERTION (run AFTER the new chain has fired)
-- Compare these numbers against the baseline comment above.
-- Expected: exact match on row counts, identical distributions.
-- ════════════════════════════════════════════════════════════════════
SELECT COUNT(*) AS posts_enriched_rows FROM ENHANCED.POSTS_ENRICHED;
SELECT COUNT(*) AS ml_ready_rows       FROM CURATED.ML_READY;

SELECT follower_tier,   COUNT(*) AS n FROM ENHANCED.POSTS_ENRICHED GROUP BY 1 ORDER BY 1;
SELECT has_trend_match, COUNT(*) AS n FROM ENHANCED.POSTS_ENRICHED GROUP BY 1 ORDER BY 1;
SELECT is_bot_suspect,  COUNT(*) AS n FROM ENHANCED.POSTS_ENRICHED GROUP BY 1 ORDER BY 1;

-- ════════════════════════════════════════════════════════════════════
-- BLOCK 3 — STAGING-TO-ENRICHED EQUIVALENCE
-- POSTS_ENRICHED row count must equal the moderation-filtered row
-- count from the new staging pipeline. Any nonzero delta means the
-- assembler's filter and the old task's filter disagree.
-- ════════════════════════════════════════════════════════════════════
SELECT
  (SELECT COUNT(*) FROM ENHANCED.POSTS_ENRICHED)                      AS enriched_rows,
  (
    SELECT COUNT(*)
    FROM ENHANCED.STG_POST_TEXT_FEATURES stf
    LEFT JOIN ENHANCED.STG_POST_LABELS       lbl ON lbl.uri = stf.uri
    LEFT JOIN (
      SELECT
        r.raw_payload:uri::STRING AS uri,
        COALESCE(r.raw_payload:repo_did::STRING, r.raw_payload:did::STRING) AS repo_did
      FROM RAW.LANDING_RAW_POSTS r
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY r.raw_payload:uri::STRING
        ORDER BY r.loaded_at DESC, r.landing_id DESC
      ) = 1
    ) rp ON rp.uri = stf.uri
    LEFT JOIN (
      SELECT
        h.raw_payload:uri::STRING AS uri,
        COALESCE(h.raw_payload:author_did::STRING, h.raw_payload:author:did::STRING) AS author_did
      FROM RAW.LANDING_HYDRATED_POSTS h
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY h.raw_payload:uri::STRING
        ORDER BY h.loaded_at DESC, h.landing_id DESC
      ) = 1
    ) hyd ON hyd.uri = stf.uri
    LEFT JOIN ENHANCED.STG_ACTOR_FEATURES af ON af.did = COALESCE(hyd.author_did, rp.repo_did)
    WHERE COALESCE(lbl.is_adult_content, FALSE) = FALSE
      AND COALESCE(af.is_bot_suspect,    FALSE) = FALSE
      AND stf.post_text_clean IS NOT NULL
      AND stf.post_text_clean != ''
  )                                                                   AS staging_filtered_rows;
-- Expected: enriched_rows = staging_filtered_rows (zero-row delta).
