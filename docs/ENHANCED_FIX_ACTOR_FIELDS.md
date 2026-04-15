# ENHANCED_FIX_ACTOR_FIELDS.md
## Fix: Actor Profile Field Names in demo_load.py

---

### The Problem
The Snowflake task reads actor profile data using camelCase
field names from raw_payload VARIANT:

```sql
raw_payload:did::STRING
raw_payload:followersCount::NUMBER
raw_payload:followsCount::NUMBER
raw_payload:postsCount::NUMBER
raw_payload:createdAt::STRING
```

The demo script writes actor profiles using snake_case field names:

```python
"followers_count": _to_int_or_none(pv.get("followersCount")),
"follows_count": _to_int_or_none(pv.get("followsCount")),
"posts_count": _to_int_or_none(pv.get("postsCount")),
"created_at": pv.get("createdAt"),
```

Because the JSONL row is loaded as VARIANT in Snowflake, the keys
are stored exactly as written. This means raw_payload:followersCount
returns NULL for every demo-loaded row. All actor features in the
ENHANCED layer will be NULL silently.

---

### The Fix — Exact Location
File: scripts/demo/demo_load.py
Function: _fetch_actor_profiles()
Lines: The row dict construction inside the for loop over profiles_data

Change these keys in the row dict from snake_case to camelCase
to match what the Snowflake task expects:

```python
# BEFORE (wrong — snake_case)
row = {
    "actor_run_id": actor_run_id,
    "did": pv.get("did"),
    "handle": pv.get("handle"),
    "display_name": pv.get("displayName"),
    "description": pv.get("description"),
    "followers_count": _to_int_or_none(pv.get("followersCount")),
    "follows_count": _to_int_or_none(pv.get("followsCount")),
    "posts_count": _to_int_or_none(pv.get("postsCount")),
    "indexed_at": pv.get("indexedAt"),
    "created_at": pv.get("createdAt"),
    "labels": labels if isinstance(labels, list) else [],
    "associated": dict(associated) if isinstance(associated, Mapping) else None,
    "enriched_at": enriched_at,
    "profile": dict(pv),
}

# AFTER (correct — camelCase matches Snowflake task)
row = {
    "actor_run_id": actor_run_id,
    "did": pv.get("did"),
    "handle": pv.get("handle"),
    "displayName": pv.get("displayName"),
    "description": pv.get("description"),
    "followersCount": _to_int_or_none(pv.get("followersCount")),
    "followsCount": _to_int_or_none(pv.get("followsCount")),
    "postsCount": _to_int_or_none(pv.get("postsCount")),
    "indexedAt": pv.get("indexedAt"),
    "createdAt": pv.get("createdAt"),
    "labels": labels if isinstance(labels, list) else [],
    "associated": dict(associated) if isinstance(associated, Mapping) else None,
    "enriched_at": enriched_at,
    "profile": dict(pv),
}
```

---

### What NOT to Change
- Do not change any other part of the file
- Do not change the firehose capture logic
- Do not change the Snowflake loading logic
- Do not change the PUT statements
- Do not change _write_jsonl_gz
- Only change the key names in the actor row dict

---

### Validation
After making this fix, run the demo script and then verify
in Snowflake that actor fields are populated:

```sql
SELECT
    raw_payload:did::STRING AS did,
    raw_payload:followersCount::NUMBER AS followers_count,
    raw_payload:followsCount::NUMBER AS follows_count,
    raw_payload:postsCount::NUMBER AS posts_count,
    raw_payload:createdAt::STRING AS created_at
FROM RAW.LANDING_ACTOR_PROFILES
WHERE source_run_tag = 'demo_run'
LIMIT 10;
```

Expected: All columns should have non-NULL values.
If followers_count is NULL the fix was not applied correctly.