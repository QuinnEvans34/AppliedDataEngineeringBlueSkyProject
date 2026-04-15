# SQL_CURATED_LAYERS.md
## Spec: CURATED_POSTS_LABELED + CURATED_POSTS_WITH_TRENDS + CURATED_ML_READY

---

### Overview
Three sequential CURATED layer views that build on each other.
Each depends on the previous one. Build and validate in order.

```
CURATED_POSTS_CORE          (already exists — do not modify)
        ↓
CURATED_POSTS_LABELED       (engagement labels + moderation filter)
        ↓
CURATED_POSTS_WITH_TRENDS   (trend join)
        ↓
CURATED_ML_READY            (final feature vector + train/test split)
```

---

## View 1: CURATED_POSTS_LABELED

### What This Is
Extends CURATED_POSTS_CORE with:
- Moderation filtering (excludes bots and adult content)
- Actor-level features from STG_ENHANCED_ACTORS
- Post-level features from STG_ENHANCED_POSTS
- Engagement labeling via NTILE

### Output Object
- Name: `BLUESKYDATAENGINEERINGPROJECT.PUBLIC.CURATED_POSTS_LABELED`
- Type: VIEW
- File: `sql/03_curated/01_curated_posts_labeled.sql`

### Source Objects
- `CURATED_POSTS_CORE` (existing)
- `STG_ENHANCED_POSTS` (new — built in prompt 1)
- `STG_ENHANCED_ACTORS` (new — built in prompt 2)

### Columns

Pull all columns from CURATED_POSTS_CORE, then add:

#### From STG_ENHANCED_POSTS (join on uri)
```
post_text, post_length, post_word_count,
hashtag_count, mention_count, url_count,
exclamation_count, question_count,
post_created_at_ts, post_hour_utc, post_day_of_week,
is_adult_content, has_any_label, moderation_label_count
```

#### From STG_ENHANCED_ACTORS (join on join_actor_did = did)
```
account_age_days, follow_follower_ratio, posts_per_day,
follower_tier, is_bot_suspect, is_spam_suspect
```

#### Engagement Label
```sql
NTILE(3) OVER (ORDER BY engagement_total ASC) AS engagement_tercile,
CASE NTILE(3) OVER (ORDER BY engagement_total ASC)
    WHEN 1 THEN 'LOW'
    WHEN 2 THEN 'MEDIUM'
    WHEN 3 THEN 'HIGH'
END AS engagement_label
```

#### Moderation Filter
This view should EXCLUDE posts that are clearly unsafe.
Add a WHERE clause:

```sql
WHERE COALESCE(ep.is_adult_content, FALSE) = FALSE
  AND COALESCE(ea.is_bot_suspect, FALSE) = FALSE
  AND COALESCE(ep.post_text, '') != ''
```

This keeps the RAW and ENHANCED layers untouched (full data)
while the CURATED layer is presentation-safe.

### Validation Query
```sql
SELECT
    engagement_label,
    COUNT(*) AS post_count,
    AVG(engagement_total) AS avg_engagement,
    AVG(post_length) AS avg_length
FROM CURATED_POSTS_LABELED
GROUP BY engagement_label
ORDER BY engagement_label;
```

The three buckets should be roughly equal in count (that is
the point of NTILE). If they are extremely unequal, the
engagement_total distribution is still degenerate.

---

## View 2: CURATED_POSTS_WITH_TRENDS

### What This Is
Adds Twitter trend match signals to CURATED_POSTS_LABELED.
This is the date-aligned join between posts and trends.

### Output Object
- Name: `BLUESKYDATAENGINEERINGPROJECT.PUBLIC.CURATED_POSTS_WITH_TRENDS`
- Type: VIEW
- File: `sql/03_curated/02_curated_posts_with_trends.sql`

### Source Objects
- `CURATED_POSTS_LABELED`
- `STG_TWITTER_TRENDS`

### Join Strategy
```sql
LEFT JOIN STG_TWITTER_TRENDS t
    ON DATE(p.post_created_at_ts) = t.trend_date
    AND (
        CONTAINS(LOWER(p.post_text), t.trend_name_clean)
        OR CONTAINS(LOWER(p.post_text), REPLACE(t.trend_name_clean, ' ', ''))
    )
```

This is a SQL-native exact/substring match. The semantic
matching (FAISS) happens in Python and writes results back
separately. This SQL join handles the exact match stage only.

### Columns to Add
```
matched_trend_name      STRING   — trend_name from STG_TWITTER_TRENDS (NULL if no match)
matched_trend_date      DATE     — trend_date
matched_tweet_volume    NUMBER   — tweet_volume of matched trend
matched_trend_rank      NUMBER   — rank of matched trend
has_trend_match         BOOLEAN  — matched_trend_name IS NOT NULL
```

### Note on Multiple Matches
One post could match multiple trends. Use a subquery or
QUALIFY ROW_NUMBER() to keep only the highest-volume trend
match per post (best signal):

```sql
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY p.uri
    ORDER BY t.tweet_volume DESC NULLS LAST
) = 1
```

### Validation Query
```sql
SELECT
    has_trend_match,
    COUNT(*) AS posts,
    AVG(engagement_total) AS avg_engagement
FROM CURATED_POSTS_WITH_TRENDS
GROUP BY has_trend_match;
```

---

## View 3: CURATED_ML_READY

### What This Is
The final model-ready feature view. Contains only the columns
the ML model needs, with a deterministic train/test split.
This is what Python reads for model training.

### Output Object
- Name: `BLUESKYDATAENGINEERINGPROJECT.PUBLIC.CURATED_ML_READY`
- Type: VIEW
- File: `sql/03_curated/03_curated_ml_ready.sql`

### Source Object
- `CURATED_POSTS_WITH_TRENDS`

### Columns (final feature vector)
```
uri                     -- row identifier
engagement_label        -- target variable: LOW / MEDIUM / HIGH
engagement_total        -- raw target (for regression fallback)

-- Text features
post_length
post_word_count
hashtag_count
mention_count
url_count
exclamation_count
question_count

-- Temporal features
post_hour_utc
post_day_of_week

-- Actor features
followers_count         -- from CURATED_POSTS_CORE
follower_tier
account_age_days
follow_follower_ratio
posts_per_day

-- Trend features
has_trend_match
matched_tweet_volume    -- 0 if no match (COALESCE)
matched_trend_rank      -- 999 if no match (COALESCE to high number)

-- Split
split_bucket            -- TRAIN / TEST
```

### Train/Test Split
```sql
CASE
    WHEN ABS(MOD(HASH(uri), 100)) < 80 THEN 'TRAIN'
    ELSE 'TEST'
END AS split_bucket
```

This is deterministic — the same uri always gets the same bucket.
Reproducible across runs without needing a random seed.

### What to Exclude
Do not include:
- Raw text (post_text) — too large, handled in Python NLP
- VARIANT columns — not readable by sklearn
- Run IDs and loader metadata — not features
- Timestamp columns beyond hour/day — already extracted
- Author handles and display names — PII, not features

### Validation Query
```sql
SELECT
    split_bucket,
    engagement_label,
    COUNT(*) AS rows
FROM CURATED_ML_READY
GROUP BY split_bucket, engagement_label
ORDER BY split_bucket, engagement_label;
```

An 80/20 TRAIN/TEST split with roughly equal LOW/MEDIUM/HIGH
within each split confirms the view is working correctly.

---

### File Naming Summary
| File | Object |
|---|---|
| sql/03_curated/01_curated_posts_labeled.sql | CURATED_POSTS_LABELED |
| sql/03_curated/02_curated_posts_with_trends.sql | CURATED_POSTS_WITH_TRENDS |
| sql/03_curated/03_curated_ml_ready.sql | CURATED_ML_READY |