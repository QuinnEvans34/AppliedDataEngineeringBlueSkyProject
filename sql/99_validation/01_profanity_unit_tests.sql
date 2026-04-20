-- Unit tests for ENHANCED.CLEAN_PROFANITY.
-- Deploy the rendered UDF (sql/00_setup/_generated/03_udfs.rendered.sql)
-- before running this file. Every row below must return result = 'PASS'.
-- Any FAIL blocks progression to Phase D.

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

-- 01 — clean text unchanged
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('This is a normal post'):post_text_clean::STRING
    = 'This is a normal post'
    THEN 'PASS' ELSE 'FAIL' END AS result, '01_clean_text_unchanged' AS test;

-- 02 — clean text reports was_profanity_redacted = FALSE
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('This is a normal post'):was_profanity_redacted::BOOLEAN
    = FALSE
    THEN 'PASS' ELSE 'FAIL' END AS result, '02_clean_text_flag_false' AS test;

-- 03 — NULL input safe
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY(NULL):post_text_clean IS NULL
    THEN 'PASS' ELSE 'FAIL' END AS result, '03_null_safe' AS test;

-- 04 — empty-string input safe
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY(''):post_text_clean::STRING = ''
    THEN 'PASS' ELSE 'FAIL' END AS result, '04_empty_string_safe' AS test;

-- 05 — empty-string redaction_count = 0
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY(''):redaction_count::NUMBER = 0
    THEN 'PASS' ELSE 'FAIL' END AS result, '05_empty_string_count_zero' AS test;

-- 06 — mild tier severity reported
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('hell no'):severity_max::STRING = 'mild'
    THEN 'PASS' ELSE 'FAIL' END AS result, '06_mild_tier' AS test;

-- 07 — strong tier text redacted
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('This is bullshit honestly'):post_text_clean::STRING
    = 'This is [Profanity] honestly'
    THEN 'PASS' ELSE 'FAIL' END AS result, '07_strong_tier_redaction' AS test;

-- 08 — strong tier severity
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('This is bullshit honestly'):severity_max::STRING
    = 'strong'
    THEN 'PASS' ELSE 'FAIL' END AS result, '08_strong_tier_severity' AS test;

-- 09 — Sussex (whitelist) unchanged
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('Sussex is lovely'):post_text_clean::STRING
    = 'Sussex is lovely'
    THEN 'PASS' ELSE 'FAIL' END AS result, '09_whitelist_sussex_unchanged' AS test;

-- 10 — Sussex (whitelist) flag FALSE
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('Sussex is lovely'):was_profanity_redacted::BOOLEAN
    = FALSE
    THEN 'PASS' ELSE 'FAIL' END AS result, '10_whitelist_sussex_flag_false' AS test;

-- 11 — separator tolerance: f*ck
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('What the f*ck is going on'):post_text_clean::STRING
    = 'What the [Profanity] is going on'
    THEN 'PASS' ELSE 'FAIL' END AS result, '11_separator_f_star_ck' AS test;

-- 12 — leetspeak: sh1t
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('look at that sh1t'):post_text_clean::STRING
    = 'look at that [Profanity]'
    THEN 'PASS' ELSE 'FAIL' END AS result, '12_leetspeak_sh1t' AS test;

-- 13 — leetspeak: a$$
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('what an a$$'):post_text_clean::STRING
    = 'what an [Profanity]'
    THEN 'PASS' ELSE 'FAIL' END AS result, '13_leetspeak_a_dollar_dollar' AS test;

-- 14 — repetition collapse: fuuuuck
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('fuuuuck this'):post_text_clean::STRING
    = '[Profanity] this'
    THEN 'PASS' ELSE 'FAIL' END AS result, '14_repetition_fuuuuck' AS test;

-- 15 — full separator tolerance: f.u.c.k
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('f.u.c.k man'):post_text_clean::STRING
    = '[Profanity] man'
    THEN 'PASS' ELSE 'FAIL' END AS result, '15_separator_f_dot_u_dot_c_dot_k' AS test;

-- 16 — URL preserved in output text
SELECT CASE WHEN CONTAINS(
        ENHANCED.CLEAN_PROFANITY('Check out https://example.com/classic-assets today'):post_text_clean::STRING,
        'https://example.com/classic-assets')
    THEN 'PASS' ELSE 'FAIL' END AS result, '16_url_preserved' AS test;

-- 17 — mixed case: HELL
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('What the HELL is going on'):post_text_clean::STRING
    = 'What the [Profanity] is going on'
    THEN 'PASS' ELSE 'FAIL' END AS result, '17_mixed_case_hell' AS test;

-- 18 — multiple profanity counts correctly
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('shit and more shit'):redaction_count::NUMBER = 2
    THEN 'PASS' ELSE 'FAIL' END AS result, '18_multiple_redaction_count' AS test;

-- 19 — severity_max picks slur over mild when both present
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('Damn this nigger'):severity_max::STRING = 'slur'
    THEN 'PASS' ELSE 'FAIL' END AS result, '19_severity_ordering_slur_beats_mild' AS test;

-- 20 — multiple whitelist terms in one input → no redaction flag
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('passage classic assets'):was_profanity_redacted::BOOLEAN
    = FALSE
    THEN 'PASS' ELSE 'FAIL' END AS result, '20_multi_whitelist_flag_false' AS test;

-- 21 — whitelist: assembly and glasses preserved
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('I love assembly and glasses'):post_text_clean::STRING
    = 'I love assembly and glasses'
    THEN 'PASS' ELSE 'FAIL' END AS result, '21_whitelist_assembly_glasses' AS test;

-- 22 — strict word-boundary: "cunty" (no space boundary) must not match "cunt"
-- Locks in behavior that separator-tolerance + leetspeak still respect the
-- trailing boundary. If this fails, the boundary lookahead is broken.
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('this is cunty language'):severity_max IS NULL
    THEN 'PASS' ELSE 'FAIL' END AS result, '22_strict_word_boundary_no_inner_match' AS test;

-- 23 — mild tier standalone severity
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('what a crap day'):severity_max::STRING = 'mild'
    THEN 'PASS' ELSE 'FAIL' END AS result, '23_mild_tier_crap' AS test;

-- 24 — mixed repetition and mild in the same string: count = 2
SELECT CASE WHEN ENHANCED.CLEAN_PROFANITY('DAMN that fuuuuucking guy'):redaction_count::NUMBER = 2
    THEN 'PASS' ELSE 'FAIL' END AS result, '24_mixed_repetition_plus_mild' AS test;

-- If any row above shows FAIL, stop the deploy and investigate.
