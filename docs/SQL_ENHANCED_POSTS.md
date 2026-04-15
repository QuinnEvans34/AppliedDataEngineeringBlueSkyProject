# SQL_ENHANCED_POSTS.md
## Spec: STG_ENHANCED_POSTS — Enhanced Layer View

---

### What This Is
A new Snowflake view in the ENHANCED (staging) layer that extends
the existing STG_RAW_POSTS and STG_HYDRATED_POSTS views with:
- Extracted post text from the raw_record VARIANT
- Text-derived feature columns
- Moderation flags from the hydrated labels VARIANT
- Timestamp casting fixes

---

### Source Objects (already exist — do not modify)
- `BLUESKYDATAENGINEERINGPROJECT.PUBLIC.STG_RAW_POSTS`
- `BLUESKYDATAENGINEERINGPROJECT.PUBLIC.STG_HYDRATED_POSTS`

---

### Output Object
- Name: `BLUESKYDATAENGINEERINGPROJECT.PUBLIC.STG_ENHANCED_POSTS`
- Type: VIEW (not table, not materialized view)
- File: `sql/02_staging/04_stg_enhanced_posts.sql`

---

### Columns to Add

#### Text Extraction
These come from the `record` VARIANT column in STG_RAW_POSTS:

| Column | Type | Source | Notes |
|---|---|---|---|
| post_text | STRING | record:text::STRING | Core post body |
| post_length | NUMBER | LENGTH(post_text) | Char count |
| post_word_count | NUMBER | ARRAY_SIZE(SPLIT(TRIM(post_text), ' ')) | Word count |

#### Text Feature Columns
Derived from post_text using REGEXP_COUNT:

| Column | Type | Pattern |
|---|---|---|
| hashtag_count | NUMBER | '#[A-Za-z0-9_]+' |
| mention_count | NUMBER | '@[A-Za-z0-9._]+' |
| url_count | NUMBER | 'https?://' |
| exclamation_count | NUMBER | '!' |
| question_count | NUMBER | '\\?' |

#### Timestamp Fixes
STG_RAW_POSTS casts record_created_at and event_time as STRING.
Fix them here:

| Column | Type | Cast |
|---|---|---|
| post_created_at_ts | TIMESTAMP_NTZ | TRY_CAST(record_created_at AS TIMESTAMP_NTZ) |
| post_hour_utc | NUMBER | EXTRACT(HOUR FROM post_created_at_ts) |
| post_day_of_week | NUMBER | DAYOFWEEK(post_created_at_ts) |

Use TRY_CAST, not CAST — raw data may have malformed timestamps
and we must not let them crash the view.

#### Moderation Flags
These come from the `labels` VARIANT column in STG_HYDRATED_POSTS.
The labels field is an array of objects. Use ARRAY_CONTAINS to check
for specific label values.

| Column | Type | Logic |
|---|---|---|
| has_any_label | BOOLEAN | ARRAY_SIZE(labels) > 0 |
| is_adult_content | BOOLEAN | Check labels for: 'porn', 'sexual', 'nudity', 'graphic-media' |
| has_moderation_flag | BOOLEAN | Any label present regardless of type |
| moderation_label_count | NUMBER | ARRAY_SIZE(labels) |

For ARRAY_CONTAINS on Snowflake VARIANT arrays:
```sql
ARRAY_CONTAINS('porn'::VARIANT, h.labels) AS is_porn_flagged
```

Build is_adult_content as OR across all adult label values.

---

### Join Strategy
This view LEFT JOINs STG_RAW_POSTS (r) to STG_HYDRATED_POSTS (h)
on r.uri = h.uri. All columns from both views pass through.
Moderation columns default to FALSE / 0 when hydration data is
absent (use COALESCE).

---

### What NOT to Include
- Do not add engagement metrics here (those come from CURATED layer)
- Do not add actor/account columns (those come from CURATED layer)
- Do not add trend match columns (those come from a later CURATED view)
- Do not modify STG_RAW_POSTS or STG_HYDRATED_POSTS

---

### Validation Query (run after creation — LIMIT always)
```sql
SELECT
    uri,
    post_text,
    post_length,
    hashtag_count,
    mention_count,
    url_count,
    post_hour_utc,
    is_adult_content,
    has_any_label
FROM STG_ENHANCED_POSTS
WHERE post_text IS NOT NULL
LIMIT 100;
```

---

### File Naming
- SQL file: `sql/02_staging/04_stg_enhanced_posts.sql`
- Follows existing convention: `NN_object_name.sql`
- Next available number in 02_staging/ is 04