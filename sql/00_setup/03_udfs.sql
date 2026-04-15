-- Profanity redaction UDF: replaces profanity words with [Profanity],
-- preserves URLs, returns cleaned text + boolean flag.
-- Lives in ENHANCED schema; ENHANCED tasks call ENHANCED.CLEAN_PROFANITY().
-- Spec: docs/SCHEMA_MIGRATION.md
-- Credit rules: docs/SNOWFLAKE_CREDIT_STRATEGY.md (UDF creation = $0)

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

CREATE OR REPLACE FUNCTION BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY(post_text STRING)
RETURNS OBJECT
LANGUAGE JAVASCRIPT
AS $$
    // Return safe defaults for null/empty input
    if (!POST_TEXT || POST_TEXT.trim() === "") {
        return { post_text_clean: POST_TEXT, was_profanity_redacted: false };
    }

    // ── Profanity word list ───────────────────────────────────────────
    // All matching is case-insensitive and whole-word only.
    const PROFANITY_LIST = [
        "ass", "asshole", "bastard", "bitch", "bollocks",
        "bullshit", "cock", "crap", "cunt", "damn", "dick",
        "dickhead", "douche", "douchebag", "dyke", "fag",
        "faggot", "fuck", "fucker", "fucking", "goddamn",
        "hell", "horseshit", "jackass", "jerk", "motherfucker",
        "nigga", "nigger", "piss", "prick", "pussy", "shit",
        "shithead", "slut", "twat", "wanker", "whore"
    ];

    // ── URL masking ───────────────────────────────────────────────────
    // Extract URLs and replace with placeholders before redaction
    // so words inside URLs are never redacted.
    const URL_PATTERN = /https?:\/\/\S+/gi;
    const urls = [];
    let masked = POST_TEXT.replace(URL_PATTERN, function(url) {
        urls.push(url);
        return "__URL_" + (urls.length - 1) + "__";
    });

    // ── Redaction ─────────────────────────────────────────────────────
    let wasRedacted = false;
    for (const word of PROFANITY_LIST) {
        // \b = word boundary, gi = global + case insensitive
        const regex = new RegExp("\\b" + word + "\\b", "gi");
        if (regex.test(masked)) {
            wasRedacted = true;
            // Reset lastIndex after test() — test() advances it
            regex.lastIndex = 0;
            masked = masked.replace(regex, "[Profanity]");
        }
    }

    // ── Restore URLs ──────────────────────────────────────────────────
    masked = masked.replace(/__URL_(\d+)__/g, function(_, i) {
        return urls[parseInt(i)];
    });

    return {
        post_text_clean: masked,
        was_profanity_redacted: wasRedacted
    };
$$;

-- ════════════════════════════════════════════════════════════════════
-- VALIDATION QUERIES — run manually after deployment
-- ════════════════════════════════════════════════════════════════════
/*
-- Test 1: Clean text
SELECT BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY('This is a normal post')
    :post_text_clean::STRING AS cleaned,
    RAW.CLEAN_PROFANITY('This is a normal post')
    :was_profanity_redacted::BOOLEAN AS redacted;
-- Expected: 'This is a normal post', FALSE

-- Test 2: Profanity present
SELECT BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY('This is bullshit honestly')
    :post_text_clean::STRING AS cleaned,
    RAW.CLEAN_PROFANITY('This is bullshit honestly')
    :was_profanity_redacted::BOOLEAN AS redacted;
-- Expected: 'This is [Profanity] honestly', TRUE

-- Test 3: URL preserved
SELECT BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY('Check out https://example.com/classic-assets today')
    :post_text_clean::STRING AS cleaned;
-- Expected: URL intact, no [Profanity] in result

-- Test 4: NULL input
SELECT BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY(NULL)
    :post_text_clean::STRING AS cleaned,
    RAW.CLEAN_PROFANITY(NULL)
    :was_profanity_redacted::BOOLEAN AS redacted;
-- Expected: NULL, FALSE

-- Test 5: Case insensitive
SELECT BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY('What the HELL is going on')
    :post_text_clean::STRING AS cleaned;
-- Expected: 'What the [Profanity] is going on'
*/

-- Reminder: suspend warehouse after running validation queries.
-- ALTER WAREHOUSE COMPUTE_WH SUSPEND;
