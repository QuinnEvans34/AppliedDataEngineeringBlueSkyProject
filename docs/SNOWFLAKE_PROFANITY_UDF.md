# SNOWFLAKE_PROFANITY_UDF.md
## Spec: Profanity Redaction — Snowflake JavaScript UDF

---

### What This Is
A Snowflake JavaScript UDF that scans post text, replaces profanity
words with `[Profanity]`, and returns both the cleaned text and a
boolean flag indicating whether any redaction occurred.

This replaces the Python approach entirely. All cleaning happens
inside Snowflake, keeping the full moderation layer in one place.

---

### Why JavaScript UDF and Not Pure SQL
Pure SQL using nested REGEXP_REPLACE would require one call per
word in the profanity list. With 50+ words that becomes:

```sql
REGEXP_REPLACE(
  REGEXP_REPLACE(
    REGEXP_REPLACE(post_text, '\\bword1\\b', '[Profanity]', 1, 0, 'i'),
  '\\bword2\\b', '[Profanity]', 1, 0, 'i'),
'\\bword3\\b', '[Profanity]', 1, 0, 'i')
-- ... 47 more levels deep
```

This is unreadable, unmaintainable, and slow. A JavaScript UDF
loops through the list in a single function call and is both
cleaner and faster.

JavaScript UDFs are a standard Snowflake feature. They count as
Snowflake data engineering work.

---

### Credit Cost
Creating a UDF: $0
Calling a UDF in a VIEW definition: costs compute only when the
view is queried, same as any other view column.
At X-SMALL warehouse, querying 1M rows through this UDF costs
approximately $0.01–0.05 total. Negligible.

---

### UDF Specification

#### Function Name
`BLUESKYDATAENGINEERINGPROJECT.PUBLIC.clean_profanity`

#### Input
| Parameter | Type |
|---|---|
| post_text | STRING |

#### Output
OBJECT with two keys:
| Key | Type | Description |
|---|---|---|
| post_text_clean | STRING | Text with profanity replaced |
| was_profanity_redacted | BOOLEAN | TRUE if any word was replaced |

#### Behavior Rules
- Case insensitive matching — "Hell", "HELL", "hell" all match
- Whole word matching only — uses `\b` word boundaries
- URLs are preserved — words inside URLs are not redacted
- NULL input returns NULL post_text_clean and FALSE for flag
- Empty string returns empty string and FALSE
- Each matched word is replaced with exactly `[Profanity]`
  as a single token regardless of the original word length

---

### Full UDF Code

```sql
CREATE OR REPLACE FUNCTION clean_profanity(post_text STRING)
RETURNS OBJECT
LANGUAGE JAVASCRIPT
AS $$
    // Return safe defaults for null/empty input
    if (!POST_TEXT || POST_TEXT.trim() === "") {
        return { post_text_clean: POST_TEXT, was_profanity_redacted: false };
    }

    // ── Profanity word list ───────────────────────────────────────────
    // Add or remove words from this list as needed.
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
```

---

### File Location
`sql/00_setup/03_udfs.sql`

If `03_udfs.sql` does not exist, create it. All UDFs for the
project live in this file following the existing `00_setup/`
convention.

---

### How to Call the UDF in STG_ENHANCED_POSTS

In `sql/02_staging/04_stg_enhanced_posts.sql`, add these two
columns to the SELECT. They must come AFTER post_text is
extracted from the VARIANT so the UDF has something to work on:

```sql
-- Post text (already exists in the view)
r.record:text::STRING                                    AS post_text,

-- Profanity cleaning (new — calls UDF on post_text)
clean_profanity(r.record:text::STRING):post_text_clean::STRING
                                                         AS post_text_clean,
clean_profanity(r.record:text::STRING):was_profanity_redacted::BOOLEAN
                                                         AS was_profanity_redacted,
```

Important: Call `clean_profanity` directly on
`r.record:text::STRING` rather than referencing the `post_text`
alias. Snowflake does not allow referencing a column alias in the
same SELECT level, so the UDF input must use the raw expression.

---

### Downstream Impact on CURATED_POSTS_LABELED

After adding `post_text_clean` to `STG_ENHANCED_POSTS`, update
`sql/03_curated/01_curated_posts_labeled.sql` to use
`post_text_clean` instead of `post_text` in the WHERE clause
that filters empty posts:

```sql
-- Before
WHERE COALESCE(ep.post_text, '') != ''

-- After
WHERE COALESCE(ep.post_text_clean, '') != ''
```

Also pass through `was_profanity_redacted` in the SELECT so it
is available in all downstream curated views and in CURATED_ML_READY.

---

### Validation Queries

**After creating the UDF — test it directly:**
```sql
-- Test 1: Clean text
SELECT clean_profanity('This is a normal post')
    :post_text_clean::STRING AS cleaned,
    clean_profanity('This is a normal post')
    :was_profanity_redacted::BOOLEAN AS redacted;
-- Expected: 'This is a normal post', FALSE

-- Test 2: Profanity present
SELECT clean_profanity('This is bullshit honestly')
    :post_text_clean::STRING AS cleaned,
    clean_profanity('This is bullshit honestly')
    :was_profanity_redacted::BOOLEAN AS redacted;
-- Expected: 'This is [Profanity] honestly', TRUE

-- Test 3: URL preserved
SELECT clean_profanity('Check out https://example.com/classic-assets today')
    :post_text_clean::STRING AS cleaned;
-- Expected: URL intact, no [Profanity] in result

-- Test 4: NULL input
SELECT clean_profanity(NULL)
    :post_text_clean::STRING AS cleaned,
    clean_profanity(NULL)
    :was_profanity_redacted::BOOLEAN AS redacted;
-- Expected: NULL, FALSE

-- Test 5: Case insensitive
SELECT clean_profanity('What the HELL is going on')
    :post_text_clean::STRING AS cleaned;
-- Expected: 'What the [Profanity] is going on'
```

**After updating STG_ENHANCED_POSTS:**
```sql
SELECT
    post_text,
    post_text_clean,
    was_profanity_redacted
FROM STG_ENHANCED_POSTS
WHERE was_profanity_redacted = TRUE
LIMIT 20;
```

**Redaction rate check:**
```sql
SELECT
    was_profanity_redacted,
    COUNT(*) AS post_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
FROM STG_ENHANCED_POSTS
GROUP BY was_profanity_redacted;
```
A realistic redaction rate on social media data is 2–8%.
Higher than 15% suggests the word list is too aggressive.
Lower than 0.5% is plausible but worth spot-checking.

---

### Deployment Order
This UDF must be deployed BEFORE re-running
`04_stg_enhanced_posts.sql` since the view depends on it.

```
1. sql/00_setup/03_udfs.sql          ← create UDF first
2. sql/02_staging/04_stg_enhanced_posts.sql   ← update view
3. sql/03_curated/01_curated_posts_labeled.sql ← update WHERE clause
```

---

### What NOT to Change
- Do not modify any other staging or curated views
- Do not change the profanity list without updating this doc
- Do not use REGEXP_REPLACE chains as an alternative
- Do not add language detection
- Do not remove posts for profanity — redact words only
- COPY INTO statements remain commented out

---

### Adding Custom Words Later
To add words to the list after deployment, edit the
`PROFANITY_LIST` array in `03_udfs.sql` and re-run
`CREATE OR REPLACE FUNCTION`. The view automatically picks
up the change on next query — no other files need updating.