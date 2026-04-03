SELECT METADATA$FILENAME, $1
FROM @PUBLIC.RAWACCOUNTSTAGE
(FILE_FORMAT => 'PUBLIC.MY_JSONL_FORMAT');

SELECT METADATA$FILENAME, $1
FROM @PUBLIC.RAWINTERACTIONSTAGE
(FILE_FORMAT => 'PUBLIC.MY_JSONL_FORMAT');

SELECT METADATA$FILENAME, $1
FROM @PUBLIC.RAWPOSTSTAGE
(FILE_FORMAT => 'PUBLIC.MY_JSONL_FORMAT');

SELECT
    $1:uri::string                AS uri,
    $1:repo_did::string           AS repo_did,
    $1:record.text::string        AS post_text,
    $1
FROM @PUBLIC.RAWACCOUNTSTAGE
(
    FILE_FORMAT => 'PUBLIC.MY_JSONL_FORMAT',
    PATTERN => '.*raw_posts_.*\.jsonl\.gz'
)
LIMIT 10;


SELECT
    COUNT(*) AS total_post_rows,
    COUNT(DISTINCT $1:uri::string) AS distinct_post_uris,
    COUNT(DISTINCT $1:repo_did::string) AS distinct_authors
FROM @PUBLIC.RAWACCOUNTSTAGE
(
    FILE_FORMAT => 'PUBLIC.MY_JSONL_FORMAT',
    PATTERN => '.*raw_posts_.*\.jsonl\.gz'
);


LIST @PUBLIC.STAGES;