# SQL_FIX_TREND_MATCH.md
## Fix: Trend Name Length Guard in CURATED_POSTS_WITH_TRENDS

---

### What Is Broken and Why

The current trend join in `CURATED_POSTS_WITH_TRENDS` uses
CONTAINS for substring matching:

```sql
LEFT JOIN STG_TWITTER_TRENDS t
    ON DATE(p.post_created_at_ts) = t.trend_date
    AND (
        CONTAINS(LOWER(p.post_text), t.trend_name_clean)
        OR CONTAINS(LOWER(p.post_text), REPLACE(t.trend_name_clean, ' ', ''))
    )
```

The problem: short trend names produce massive false positives.

Examples of what goes wrong:
- Trend "AI" matches any post containing "said", "mail", "rain",
  "train", "afraid" — every post about anything
- Trend "UK" matches "look", "book", "duke", "truck"
- Trend "Go" matches every post with "good", "google", "going"

This means has_trend_match will be TRUE for a huge percentage
of posts that have nothing to do with the trend. The feature
becomes noise instead of signal, which explains why trend
features contributed near zero to model importance previously.

---

### Fix 1: Minimum Trend Name Length Guard

Add a length filter to the JOIN condition so very short trend
names are excluded from matching entirely:

```sql
LEFT JOIN STG_TWITTER_TRENDS t
    ON DATE(p.post_created_at_ts) = t.trend_date
    AND LENGTH(t.trend_name_clean) >= 4
    AND (
        CONTAINS(LOWER(p.post_text), t.trend_name_clean)
        OR CONTAINS(LOWER(p.post_text), REPLACE(t.trend_name_clean, ' ', ''))
    )
```

Why 4? Trends shorter than 4 characters are almost always
abbreviations or acronyms that appear as substrings in unrelated
words. 4 characters still allows "nfl", "nba", "gpt" style
trends if they are written as hashtags (#nfl matches cleanly).

---

### Fix 2: Word Boundary Improvement (Optional but Recommended)

Pure CONTAINS has no concept of word boundaries. A better
approach for the no-spaces variant is to check against the
post text with spaces preserved around the match using a
REGEXP_LIKE pattern:

```sql
OR REGEXP_LIKE(LOWER(p.post_text),
    CONCAT('(^|[^a-z0-9])',
           REPLACE(t.trend_name_clean, ' ', ''),
           '([^a-z0-9]|$)'))
```

This ensures "ai" only matches when surrounded by non-alphanumeric
characters (spaces, punctuation, start/end of string) rather than
as a substring of a word.

This is more expensive than CONTAINS — only add it if the simple
length guard alone does not reduce false positives enough after
validation.

Start with Fix 1 only. Validate. Add Fix 2 only if needed.

---

### Fix 3: Strengthen the QUALIFY Logic

The current QUALIFY keeps the highest tweet_volume match per post:

```sql
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY p.uri
    ORDER BY t.tweet_volume DESC NULLS LAST
) = 1
```

This is correct. No change needed here — just confirm it is
present in the file exactly as written.

---

### What NOT to Change
- Do not change the date join condition
- Do not change the QUALIFY logic
- Do not change any columns in the SELECT
- Do not change CURATED_POSTS_LABELED — only this file

---

### Validation Query (run after fix — always LIMIT)

```sql
-- Check match rate before and after fix
-- Run this, note the numbers, apply fix, run again
SELECT
    has_trend_match,
    COUNT(*) AS post_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total,
    AVG(engagement_total) AS avg_engagement
FROM CURATED_POSTS_WITH_TRENDS
GROUP BY has_trend_match;
```

Before the fix: has_trend_match = TRUE should be suspiciously high
(potentially 60-80% of posts).

After the fix: has_trend_match = TRUE should drop significantly.
A realistic match rate for Bluesky posts against Twitter trends
is probably 5-25%. If it is still above 50% after the fix,
the REGEXP approach from Fix 2 should be applied.

Also run this to check which trends are matching most — if you
see very generic words at the top, the length guard needs raising:

```sql
SELECT
    matched_trend_name,
    COUNT(*) AS matched_posts,
    AVG(engagement_total) AS avg_engagement
FROM CURATED_POSTS_WITH_TRENDS
WHERE has_trend_match = TRUE
GROUP BY matched_trend_name
ORDER BY matched_posts DESC
LIMIT 30;
```

---

### File to Modify
`sql/03_curated/02_curated_posts_with_trends.sql`

This is a CREATE OR REPLACE VIEW. Re-running it costs zero credits.
All downstream views (CURATED_ML_READY) will automatically reflect
the fix on next query — no need to touch them.