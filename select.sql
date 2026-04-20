USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

-- paste the full contents of sql/00_setup/_generated/03_udfs.rendered.sql here


SELECT ENHANCED.CLEAN_PROFANITY('This is bullshit honestly'):post_text_clean::STRING AS cleaned,
       ENHANCED.CLEAN_PROFANITY('This is bullshit honestly'):severity_max::STRING     AS sev;
-- Expected: cleaned = 'This is [Profanity] honestly', sev = 'strong'

SELECT ENHANCED.CLEAN_PROFANITY('Sussex is lovely'):post_text_clean::STRING AS cleaned;
-- Expected: 'Sussex is lovely' (whitelist protects it)


EXECUTE TASK ENHANCED.TASK_FLATTEN_LABELS;