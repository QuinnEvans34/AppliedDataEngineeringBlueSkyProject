-- Profanity config + whitelist tables: backing store for the CLEAN_PROFANITY
-- UDF's word list. Seeds ENHANCED.PROFANITY_TERMS (99 rows) and
-- ENHANCED.PROFANITY_WHITELIST (14 rows). The rendered UDF in
-- sql/00_setup/_generated/03_udfs.rendered.sql reads these values at deploy
-- time via scripts/render_profanity_udf.py.
-- Plan: docs/PROMPT_PROFANITY_EXPANSION.md
-- Phase prompts: docs/CLAUDE_PROMPTS_PROFANITY.md
-- Credit rules: docs/SNOWFLAKE_CREDIT_STRATEGY.md (DDL + small INSERT = negligible)

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

-- ── PROFANITY_TERMS ───────────────────────────────────────────────────
-- One row per term. severity is one of: 'mild', 'strong', 'sexual', 'slur'.
-- allow_separators gates whether Phase C's UDF will tolerate a single
-- non-alphanumeric between each letter (e.g. "f.u.c.k"). Left FALSE for
-- every Phase A seed row — Phase B enables it on length >= 4 strong/sexual/slur.

CREATE OR REPLACE TABLE BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_TERMS (
    term              STRING NOT NULL,
    severity          STRING NOT NULL,
    allow_separators  BOOLEAN NOT NULL DEFAULT FALSE,
    added_at          TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP,
    added_by          STRING,
    notes             STRING,
    PRIMARY KEY (term)
);

-- ── PROFANITY_WHITELIST ───────────────────────────────────────────────
-- Common substrings that false-positive against short stems like "ass"
-- or "hell" (e.g. "sussex", "classic", "hellas"). Phase C's UDF masks
-- whitelist occurrences BEFORE scanning for profanity.

CREATE OR REPLACE TABLE BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_WHITELIST (
    term        STRING NOT NULL,
    reason      STRING,
    added_at    TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (term)
);

-- ── Seed PROFANITY_TERMS: 37 existing terms from 03_udfs.sql ──────────
-- Severity mapping is copied verbatim from the Phase A prompt in
-- docs/CLAUDE_PROMPTS_PROFANITY.md. Grouped by severity for readability.
-- All rows: allow_separators = FALSE, added_by = 'phase_a_seed'.

INSERT INTO BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_TERMS
    (term, severity, allow_separators, added_by)
VALUES
    -- mild (7)
    ('ass',          'mild',   FALSE, 'phase_a_seed'),
    ('crap',         'mild',   FALSE, 'phase_a_seed'),
    ('damn',         'mild',   FALSE, 'phase_a_seed'),
    ('hell',         'mild',   FALSE, 'phase_a_seed'),
    ('jerk',         'mild',   FALSE, 'phase_a_seed'),
    ('piss',         'mild',   FALSE, 'phase_a_seed'),
    ('bollocks',     'mild',   FALSE, 'phase_a_seed'),
    -- strong (19)
    ('asshole',      'strong', FALSE, 'phase_a_seed'),
    ('bastard',      'strong', FALSE, 'phase_a_seed'),
    ('bitch',        'strong', FALSE, 'phase_a_seed'),
    ('bullshit',     'strong', FALSE, 'phase_a_seed'),
    ('dick',         'strong', FALSE, 'phase_a_seed'),
    ('dickhead',     'strong', FALSE, 'phase_a_seed'),
    ('douche',       'strong', FALSE, 'phase_a_seed'),
    ('douchebag',    'strong', FALSE, 'phase_a_seed'),
    ('fuck',         'strong', FALSE, 'phase_a_seed'),
    ('fucker',       'strong', FALSE, 'phase_a_seed'),
    ('fucking',      'strong', FALSE, 'phase_a_seed'),
    ('goddamn',      'strong', FALSE, 'phase_a_seed'),
    ('horseshit',    'strong', FALSE, 'phase_a_seed'),
    ('jackass',      'strong', FALSE, 'phase_a_seed'),
    ('motherfucker', 'strong', FALSE, 'phase_a_seed'),
    ('prick',        'strong', FALSE, 'phase_a_seed'),
    ('shit',         'strong', FALSE, 'phase_a_seed'),
    ('shithead',     'strong', FALSE, 'phase_a_seed'),
    ('wanker',       'strong', FALSE, 'phase_a_seed'),
    -- sexual (6)
    ('cock',         'sexual', FALSE, 'phase_a_seed'),
    ('cunt',         'sexual', FALSE, 'phase_a_seed'),
    ('pussy',        'sexual', FALSE, 'phase_a_seed'),
    ('slut',         'sexual', FALSE, 'phase_a_seed'),
    ('twat',         'sexual', FALSE, 'phase_a_seed'),
    ('whore',        'sexual', FALSE, 'phase_a_seed'),
    -- slur (5)
    ('dyke',         'slur',   FALSE, 'phase_a_seed'),
    ('fag',          'slur',   FALSE, 'phase_a_seed'),
    ('faggot',       'slur',   FALSE, 'phase_a_seed'),
    ('nigga',        'slur',   FALSE, 'phase_a_seed'),
    ('nigger',       'slur',   FALSE, 'phase_a_seed');

-- ── Seed PROFANITY_WHITELIST: 14 common false-positive substrings ─────

INSERT INTO BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_WHITELIST
    (term, reason)
VALUES
    ('sussex',     'common false-positive substring'),
    ('scunthorpe', 'common false-positive substring'),
    ('hellas',     'common false-positive substring'),
    ('assam',      'common false-positive substring'),
    ('assembly',   'common false-positive substring'),
    ('assets',     'common false-positive substring'),
    ('asset',      'common false-positive substring'),
    ('classic',    'common false-positive substring'),
    ('glasses',    'common false-positive substring'),
    ('class',      'common false-positive substring'),
    ('cumulus',    'common false-positive substring'),
    ('passage',    'common false-positive substring'),
    ('assign',     'common false-positive substring'),
    ('assist',     'common false-positive substring');

-- ════════════════════════════════════════════════════════════════════
-- VALIDATION QUERIES — run manually after deployment
-- ════════════════════════════════════════════════════════════════════
/*
-- Row counts
SELECT COUNT(*) AS term_count
FROM BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_TERMS;
-- Expected: 37

SELECT COUNT(*) AS whitelist_count
FROM BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_WHITELIST;
-- Expected: 14

-- Severity breakdown
SELECT severity, COUNT(*) AS n
FROM BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_TERMS
GROUP BY severity
ORDER BY severity;
-- Expected:
--   mild    7
--   sexual  6
--   slur    5
--   strong  19
*/

-- ── PHASE B: EXPANSION ────────────────────────────────────────────────
-- Adds 62 new terms across mild/strong/sexual/slur to bring total to 99.
-- MERGE makes this file re-runnable without violating the PK on term.
-- allow_separators = TRUE iff length(term) >= 4 AND severity in
-- (strong, sexual, slur). Leave FALSE on mild and on short 3-letter stems.

MERGE INTO BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_TERMS t
USING (
    SELECT column1 AS term,
           column2 AS severity,
           column3 AS allow_separators,
           column4 AS added_by
    FROM VALUES
        -- plurals of existing terms (10)
        ('asses',     'mild',   FALSE, 'phase_b_expansion'),
        ('bitches',   'strong', TRUE,  'phase_b_expansion'),
        ('fuckers',   'strong', TRUE,  'phase_b_expansion'),
        ('shits',     'strong', TRUE,  'phase_b_expansion'),
        ('dicks',     'strong', TRUE,  'phase_b_expansion'),
        ('pricks',    'strong', TRUE,  'phase_b_expansion'),
        ('sluts',     'sexual', TRUE,  'phase_b_expansion'),
        ('whores',    'sexual', TRUE,  'phase_b_expansion'),
        ('assholes',  'strong', TRUE,  'phase_b_expansion'),
        ('bastards',  'strong', TRUE,  'phase_b_expansion'),
        -- suffixed forms (11)
        ('fucked',    'strong', TRUE,  'phase_b_expansion'),
        ('fucks',     'strong', TRUE,  'phase_b_expansion'),
        ('fuckin',    'strong', TRUE,  'phase_b_expansion'),
        ('fuckn',     'strong', TRUE,  'phase_b_expansion'),
        ('shitting',  'strong', TRUE,  'phase_b_expansion'),
        ('shitted',   'strong', TRUE,  'phase_b_expansion'),
        ('bitching',  'strong', TRUE,  'phase_b_expansion'),
        ('bitched',   'strong', TRUE,  'phase_b_expansion'),
        ('pissing',   'mild',   FALSE, 'phase_b_expansion'),
        ('pissed',    'mild',   FALSE, 'phase_b_expansion'),
        ('dicking',   'strong', TRUE,  'phase_b_expansion'),
        -- obfuscated / abbreviated variants (10)
        ('effin',     'strong', TRUE,  'phase_b_expansion'),
        ('effing',    'strong', TRUE,  'phase_b_expansion'),
        ('mf',        'strong', FALSE, 'phase_b_expansion'),
        ('mofo',      'strong', TRUE,  'phase_b_expansion'),
        ('mfer',      'strong', TRUE,  'phase_b_expansion'),
        ('pos',       'strong', FALSE, 'phase_b_expansion'),
        ('stfu',      'strong', TRUE,  'phase_b_expansion'),
        ('gtfo',      'strong', TRUE,  'phase_b_expansion'),
        ('wtf',       'strong', FALSE, 'phase_b_expansion'),
        ('af',        'mild',   FALSE, 'phase_b_expansion'),
        -- additional strong/sexual (11)
        ('cum',       'sexual', FALSE, 'phase_b_expansion'),
        ('jizz',      'sexual', TRUE,  'phase_b_expansion'),
        ('blowjob',   'sexual', TRUE,  'phase_b_expansion'),
        ('handjob',   'sexual', TRUE,  'phase_b_expansion'),
        ('dildo',     'sexual', TRUE,  'phase_b_expansion'),
        ('boobs',     'sexual', TRUE,  'phase_b_expansion'),
        ('tits',      'sexual', TRUE,  'phase_b_expansion'),
        ('boner',     'sexual', TRUE,  'phase_b_expansion'),
        ('nsfw',      'sexual', TRUE,  'phase_b_expansion'),
        ('porn',      'sexual', TRUE,  'phase_b_expansion'),
        ('porno',     'sexual', TRUE,  'phase_b_expansion'),
        -- additional slurs (6)
        ('chink',     'slur',   TRUE,  'phase_b_expansion'),
        ('gook',      'slur',   TRUE,  'phase_b_expansion'),
        ('spic',      'slur',   TRUE,  'phase_b_expansion'),
        ('kike',      'slur',   TRUE,  'phase_b_expansion'),
        ('tranny',    'slur',   TRUE,  'phase_b_expansion'),
        ('retard',    'slur',   TRUE,  'phase_b_expansion'),
        -- additional strong variants (14)
        ('cocksucker',    'strong', TRUE,  'phase_b_expansion'),
        ('dickless',      'strong', TRUE,  'phase_b_expansion'),
        ('arsehole',      'strong', TRUE,  'phase_b_expansion'),
        ('arse',          'mild',   FALSE, 'phase_b_expansion'),
        ('bullshitting',  'strong', TRUE,  'phase_b_expansion'),
        ('bullshitted',   'strong', TRUE,  'phase_b_expansion'),
        ('motherfucking', 'strong', TRUE,  'phase_b_expansion'),
        ('motherfuckers', 'strong', TRUE,  'phase_b_expansion'),
        ('shitty',        'strong', TRUE,  'phase_b_expansion'),
        ('shitfaced',     'strong', TRUE,  'phase_b_expansion'),
        ('twats',         'sexual', TRUE,  'phase_b_expansion'),
        ('wank',          'mild',   FALSE, 'phase_b_expansion'),
        ('wanking',       'mild',   FALSE, 'phase_b_expansion'),
        ('turd',          'mild',   FALSE, 'phase_b_expansion')
) s
ON t.term = s.term
WHEN NOT MATCHED THEN
    INSERT (term, severity, allow_separators, added_by)
    VALUES (s.term, s.severity, s.allow_separators, s.added_by);

-- ════════════════════════════════════════════════════════════════════
-- PHASE B VALIDATION QUERIES — run manually after deployment
-- ════════════════════════════════════════════════════════════════════
/*
-- Severity breakdown (Phase B target: >= 95 total rows; we land at 99)
SELECT severity, COUNT(*) AS n
FROM BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_TERMS
GROUP BY severity
ORDER BY severity;

-- Severity + allow_separators cross-tab — strong/sexual/slur rows with
-- allow_separators = TRUE must be > 0; if all TRUE counts are 0, Phase B
-- was miscoded.
SELECT severity, allow_separators, COUNT(*) AS n
FROM BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_TERMS
GROUP BY severity, allow_separators
ORDER BY severity, allow_separators;

-- Phase B rows only (expected: mild 8, strong 35, sexual 13, slur 6; sum 62)
SELECT severity, COUNT(*) AS n
FROM BLUESKYDATAENGINEERINGPROJECT.ENHANCED.PROFANITY_TERMS
WHERE added_by = 'phase_b_expansion'
GROUP BY severity
ORDER BY severity;
*/

-- Reminder: suspend warehouse after running validation queries.
-- ALTER WAREHOUSE COMPUTE_WH SUSPEND;
