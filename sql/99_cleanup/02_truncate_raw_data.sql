-- ============================================================================
-- WARNING: THIS DELETES ALL DATA. OBJECTS ARE PRESERVED.
-- DO NOT RUN THIS UNLESS YOU INTEND TO RELOAD EVERYTHING.
--
-- This script removes all row data from RAW landing tables, purges all
-- staged files, and truncates downstream ENHANCED / CURATED tables so
-- the entire pipeline is clean end-to-end.
--
-- Nothing is dropped — tables, stages, pipes, streams, tasks, and UDFs
-- all remain intact and ready for the next load.
-- ============================================================================

USE ROLE SYSADMIN;
USE DATABASE BLUESKYDATAENGINEERINGPROJECT;

-- ────────────────────────────────────────────────────────────────────────────
-- 1. TRUNCATE RAW LANDING TABLES
-- ────────────────────────────────────────────────────────────────────────────

TRUNCATE TABLE RAW.LANDING_RAW_POSTS;
TRUNCATE TABLE RAW.LANDING_HYDRATED_POSTS;
TRUNCATE TABLE RAW.LANDING_HYDRATION_MISSES;
TRUNCATE TABLE RAW.LANDING_ACTOR_PROFILES;
TRUNCATE TABLE RAW.LANDING_TWITTER_TRENDS;
TRUNCATE TABLE RAW.LANDING_TREND_MATCHES;
TRUNCATE TABLE RAW.LOADER_FILE_MANIFEST;

-- ────────────────────────────────────────────────────────────────────────────
-- 2. REMOVE ALL FILES FROM RAW STAGES
-- ────────────────────────────────────────────────────────────────────────────

REMOVE @RAW.BLUESKY_RAW_POSTS_STAGE;
REMOVE @RAW.BLUESKY_HYDRATED_POSTS_STAGE;
REMOVE @RAW.BLUESKY_HYDRATION_MISSES_STAGE;
REMOVE @RAW.BLUESKY_ACTOR_PROFILES_STAGE;
REMOVE @RAW.BLUESKY_TWITTER_TRENDS_STAGE;
REMOVE @RAW.BLUESKY_TREND_MATCHES_STAGE;

-- ────────────────────────────────────────────────────────────────────────────
-- 3. TRUNCATE DOWNSTREAM ENHANCED & CURATED TABLES
-- ────────────────────────────────────────────────────────────────────────────

TRUNCATE TABLE ENHANCED.POSTS_ENRICHED;
TRUNCATE TABLE CURATED.ML_READY;

-- ────────────────────────────────────────────────────────────────────────────
-- 4. VALIDATION QUERIES (run these to confirm everything is empty)
-- ────────────────────────────────────────────────────────────────────────────

-- -- RAW landing table counts (all should return 0)
-- SELECT 'LANDING_RAW_POSTS'       AS table_name, COUNT(*) AS row_count FROM RAW.LANDING_RAW_POSTS
-- UNION ALL
-- SELECT 'LANDING_HYDRATED_POSTS',                 COUNT(*)             FROM RAW.LANDING_HYDRATED_POSTS
-- UNION ALL
-- SELECT 'LANDING_HYDRATION_MISSES',               COUNT(*)             FROM RAW.LANDING_HYDRATION_MISSES
-- UNION ALL
-- SELECT 'LANDING_ACTOR_PROFILES',                 COUNT(*)             FROM RAW.LANDING_ACTOR_PROFILES
-- UNION ALL
-- SELECT 'LANDING_TWITTER_TRENDS',                 COUNT(*)             FROM RAW.LANDING_TWITTER_TRENDS
-- UNION ALL
-- SELECT 'LANDING_TREND_MATCHES',                  COUNT(*)             FROM RAW.LANDING_TREND_MATCHES
-- UNION ALL
-- SELECT 'LOADER_FILE_MANIFEST',                   COUNT(*)             FROM RAW.LOADER_FILE_MANIFEST;

-- -- Downstream table counts (all should return 0)
-- SELECT 'POSTS_ENRICHED' AS table_name, COUNT(*) AS row_count FROM ENHANCED.POSTS_ENRICHED
-- UNION ALL
-- SELECT 'ML_READY',                    COUNT(*)             FROM CURATED.ML_READY;

-- -- Stage file listings (all should return empty results)
-- LIST @RAW.BLUESKY_RAW_POSTS_STAGE;
-- LIST @RAW.BLUESKY_HYDRATED_POSTS_STAGE;
-- LIST @RAW.BLUESKY_HYDRATION_MISSES_STAGE;
-- LIST @RAW.BLUESKY_ACTOR_PROFILES_STAGE;
-- LIST @RAW.BLUESKY_TWITTER_TRENDS_STAGE;
-- LIST @RAW.BLUESKY_TREND_MATCHES_STAGE;
