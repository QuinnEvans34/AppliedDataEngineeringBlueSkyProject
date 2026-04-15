# SQL_ENHANCED_ACTORS.md
## Spec: STG_ENHANCED_ACTORS — Enhanced Layer View

---

### What This Is
A new Snowflake view in the ENHANCED layer that extends
STG_ACTOR_PROFILES with bot detection heuristics, follower
tier bucketing, and account age signals.

---

### Source Object (already exists — do not modify)
- `BLUESKYDATAENGINEERINGPROJECT.PUBLIC.STG_ACTOR_PROFILES`

---

### Output Object
- Name: `BLUESKYDATAENGINEERINGPROJECT.PUBLIC.STG_ENHANCED_ACTORS`
- Type: VIEW
- File: `sql/02_staging/05_stg_enhanced_actors.sql`

---

### Columns to Add

#### Account Age
| Column | Type | Logic |
|---|---|---|
| account_age_days | NUMBER | DATEDIFF('day', TRY_CAST(created_at AS TIMESTAMP_NTZ), CURRENT_TIMESTAMP()) |

Use TRY_CAST — created_at may be malformed in some records.

#### Follower / Follow Ratios
| Column | Type | Logic |
|---|---|---|
| follow_follower_ratio | FLOAT | follows_count / NULLIF(followers_count, 0) |
| posts_per_day | FLOAT | posts_count / NULLIF(account_age_days, 0) |

Always use NULLIF to avoid division by zero.

#### Follower Tier
Bucket accounts into tiers for use as a categorical feature:

```sql
CASE
    WHEN followers_count >= 10000 THEN 'HIGH'
    WHEN followers_count >= 1000  THEN 'MID'
    WHEN followers_count >= 100   THEN 'LOW'
    ELSE 'MICRO'
END AS follower_tier
```

#### Bot Detection Heuristics
Flag accounts that match bot-like patterns. Each flag is independent
— an account can trip multiple flags.

| Column | Type | Condition |
|---|---|---|
| is_high_follow_ratio | BOOLEAN | follow_follower_ratio > 20 |
| is_low_follower_high_post | BOOLEAN | followers_count < 10 AND posts_count > 500 |
| is_new_high_volume | BOOLEAN | account_age_days < 30 AND posts_per_day > 50 |
| has_actor_label | BOOLEAN | ARRAY_SIZE(labels) > 0 |

Composite bot suspect flag:
```sql
(is_high_follow_ratio
 OR is_low_follower_high_post
 OR is_new_high_volume
 OR has_actor_label) AS is_bot_suspect
```

This is a heuristic — it will have false positives. That is
acceptable. The goal is to exclude obvious bots from the
presentation layer, not to build a perfect classifier.

#### Spam Suspect
```sql
(is_bot_suspect AND posts_per_day > 100) AS is_spam_suspect
```

---

### What NOT to Include
- Do not add post-level columns here (wrong grain — this is actor level)
- Do not modify STG_ACTOR_PROFILES
- Do not add engagement metrics (not available at actor level)

---

### Validation Query
```sql
SELECT
    did,
    handle,
    followers_count,
    follows_count,
    account_age_days,
    follow_follower_ratio,
    follower_tier,
    is_bot_suspect,
    is_spam_suspect
FROM STG_ENHANCED_ACTORS
WHERE is_bot_suspect = TRUE
LIMIT 100;
```

---

### File Naming
- SQL file: `sql/02_staging/05_stg_enhanced_actors.sql`