# SQL_FIX_LABEL_FLATTEN.md
## Fix: labels VARIANT Structure in STG_ENHANCED_POSTS

---

### What Is Broken and Why

The current `STG_ENHANCED_POSTS` view uses this pattern to detect
adult content:

```sql
ARRAY_CONTAINS('porn'::VARIANT, h.labels) AS is_adult_content
```

This assumes the labels field is an array of bare strings:
```json
["porn", "nudity"]
```

But the Bluesky AT Protocol stores labels as an array of objects:
```json
[
  {"val": "porn", "src": "did:plc:abc123", "cts": "2024-01-01T00:00:00Z"},
  {"val": "nudity", "src": "did:plc:abc123", "cts": "2024-01-01T00:00:00Z"}
]
```

ARRAY_CONTAINS against a bare string literal will never match an
object. The result: is_adult_content is always FALSE regardless of
what labels are present. Adult content passes through the curated
layer completely unfiltered.

---

### The Fix

Replace every ARRAY_CONTAINS label check with a FLATTEN-based
EXISTS subquery that navigates into the object structure:

```sql
-- WRONG (current)
ARRAY_CONTAINS('porn'::VARIANT, h.labels)

-- CORRECT (replacement)
EXISTS (
    SELECT 1
    FROM TABLE(FLATTEN(input => h.labels)) f
    WHERE f.value:val::STRING IN ('porn', 'sexual', 'nudity', 'graphic-media')
)
```

This uses Snowflake's LATERAL FLATTEN to expand the labels array
into individual rows, then checks the val key of each object.

---

### All Columns That Need This Fix

In `sql/02_staging/04_stg_enhanced_posts.sql`, update these columns:

| Column | Current Logic | Fixed Logic |
|---|---|---|
| has_any_label | ARRAY_SIZE(h.labels) > 0 | ARRAY_SIZE(h.labels) > 0 — THIS ONE IS FINE, keep as is |
| is_adult_content | ARRAY_CONTAINS across label strings | FLATTEN EXISTS check for val IN ('porn','sexual','nudity','graphic-media') |
| has_moderation_flag | ARRAY_SIZE(h.labels) > 0 | Same fix as has_any_label — ARRAY_SIZE is fine, no change needed |
| moderation_label_count | ARRAY_SIZE(h.labels) | Fine — ARRAY_SIZE works on arrays of objects |

Only `is_adult_content` needs the rewrite. The other three columns
use ARRAY_SIZE which works correctly regardless of whether the array
contains strings or objects.

---

### Also Fix: Actor Labels in STG_ENHANCED_ACTORS

The same issue exists in `sql/02_staging/05_stg_enhanced_actors.sql`:

```sql
-- Current (broken)
ARRAY_SIZE(labels) > 0 AS has_actor_label
```

ARRAY_SIZE works fine — this one is actually correct. No change needed.

However, if any future logic checks for specific label values on
actor profiles (e.g., checking if an actor is flagged as a bot by
Bluesky's own moderation), it must use the same FLATTEN pattern.
Add a comment to the file noting this for future reference.

---

### Null Safety

The labels column may be NULL for posts that have no labels at all
(most posts). FLATTEN on a NULL input will error. Wrap with a
COALESCE or add a NULL guard:

```sql
EXISTS (
    SELECT 1
    FROM TABLE(FLATTEN(input => COALESCE(h.labels, ARRAY_CONSTRUCT()))) f
    WHERE f.value:val::STRING IN ('porn', 'sexual', 'nudity', 'graphic-media')
)
```

`ARRAY_CONSTRUCT()` returns an empty array, so FLATTEN produces
zero rows and EXISTS returns FALSE — correct behavior for unlabeled
posts.

---

### What NOT to Change
- Do not change the view name or any other column
- Do not change the join logic
- Do not change anything in the curated layer — this fix in the
  enhanced layer propagates automatically to all downstream views
- Do not change has_any_label, has_moderation_flag, or 
  moderation_label_count — they are correct as is

---

### Validation Query (run after fix — always LIMIT)
```sql
-- Check that is_adult_content is not always FALSE
-- If it returns zero rows after loading real data, labels are
-- likely structured differently than expected
SELECT
    has_any_label,
    is_adult_content,
    has_moderation_flag,
    moderation_label_count,
    COUNT(*) AS post_count
FROM STG_ENHANCED_POSTS
WHERE has_any_label = TRUE
GROUP BY 1, 2, 3, 4
ORDER BY post_count DESC
LIMIT 50;
```

If has_any_label = TRUE but is_adult_content is always FALSE after
this fix, it means the posts have labels but none of them are in
the adult content list — which is plausible and not necessarily wrong.

---

### File to Modify
`sql/02_staging/04_stg_enhanced_posts.sql`

This is a CREATE OR REPLACE VIEW — replacing the file and
re-running it in Snowflake is safe and costs zero credits.