# PROMPT_PROFANITY_EXPANSION.md
## Claude-Extension Prompt — Expand `CLEAN_PROFANITY` so ENHANCED stays clean

Paste the **Prompt** section into the Claude extension. The rest is
context for humans.

---

### Why This Refactor

Today `BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY` is a
JavaScript UDF with a hardcoded 37-word list. It catches the obvious
cases but misses real patterns that show up in Bluesky firehose data:

- **Character separators** — `f.u.c.k`, `f u c k`, `f-u-c-k`, `f*ck`
  all slip through because `\b word \b` only matches the literal word.
- **Leetspeak / obfuscation** — `sh1t`, `fuk`, `a$$`, `b!tch`.
- **Repetition** — `fuuuuck`, `shiiiit`.
- **Plurals and suffixes we don't list** — `asses`, `bitches`,
  `fuckers` (we list `fucker` but not the plural; `fucking` is
  listed but `fucked` is not).
- **Compound slurs** — the current list catches single-word slurs
  but not phrase-level slurs.
- **Whitelist gap** — place names and technical terms that
  contain profanity substrings already get false-positive saved by
  the URL masking, but only for URLs. "Scunthorpe problem" cases
  (`classic` → `[Profanity]ic` is guarded by `\b`, but things like
  `Sussex`, `Hellas`, `asset`, `assembly` are at risk if we loosen
  the word boundary in future iterations).

We also have no mechanism to:
- Tier severity (slur vs. mild profanity vs. sexual) — we treat
  everything identically and drop it all as `[Profanity]`.
- Add words without a code change — the list is literal JavaScript
  source, so a curator editing "we also need to redact X" has to
  edit, review, and redeploy the UDF.
- Unit-test the function — there are validation queries in
  comments, but no automated check.

This prompt fixes all of the above.

---

### Target Design

Three changes, in order of impact:

1. **Move the list to a config table** — `ENHANCED.PROFANITY_TERMS`
   (term STRING, severity STRING, allow_separators BOOLEAN,
   added_at TIMESTAMP_TZ). The UDF reads from it once per call via a
   stored-procedure wrapper, **or** we stay with the JavaScript UDF
   but compile its list from the table via a deploy-time script
   (recommended — Snowflake JS UDFs can't query tables at runtime).
2. **Teach the matcher to handle obfuscation** — separator-tolerant
   regex, repeat-character normalization, common leetspeak
   substitutions. Apply only to terms tagged `allow_separators = TRUE`
   to avoid false positives on short/common English stems.
3. **Add a severity tier output** — return
   `OBJECT(post_text_clean STRING, was_profanity_redacted BOOLEAN,
   redaction_count NUMBER, severity_max STRING)`. Downstream decides
   whether to drop the row or just surface the flag.

Also add:
- A whitelist table `ENHANCED.PROFANITY_WHITELIST` (term STRING) of
  substrings we never want to match (place names, technical terms).
  The UDF scans the whitelist first and masks those occurrences the
  same way URLs are masked today.
- A real unit-test SQL file at `sql/99_validation/01_profanity_unit_tests.sql`
  that `ASSERT`s expected outputs on a fixed battery of inputs.

---

### Proposed Schema

```sql
CREATE OR REPLACE TABLE ENHANCED.PROFANITY_TERMS (
    term              STRING NOT NULL,
    severity          STRING NOT NULL,  -- 'mild', 'strong', 'slur', 'sexual'
    allow_separators  BOOLEAN NOT NULL DEFAULT FALSE,
    added_at          TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP,
    added_by          STRING,
    notes             STRING,
    PRIMARY KEY (term)
);

CREATE OR REPLACE TABLE ENHANCED.PROFANITY_WHITELIST (
    term        STRING NOT NULL,
    reason      STRING,
    added_at    TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (term)
);
```

The UDF signature becomes:

```sql
CLEAN_PROFANITY(post_text STRING) RETURNS OBJECT
-- keys: post_text_clean, was_profanity_redacted,
--       redaction_count, severity_max
```

`severity_max` is the highest-severity tier hit
(ordered: `mild` < `strong` < `sexual` < `slur`), or `NULL` when
nothing was redacted. Downstream the assembler task can use it to
decide between a hard drop (slurs) and a soft flag (mild).

---

### Prompt (paste into Claude extension)

> You are expanding the Bluesky profanity redaction UDF. The current
> UDF lives in `sql/00_setup/03_udfs.sql` and the spec that originally
> defined it is `docs/SNOWFLAKE_PROFANITY_UDF.md`. The SQL folder map
> is `docs/SQL_FOLDER_OUTLINE.md`. Read all three before making
> changes.
>
> **Goal.** Replace the hardcoded 37-word list with a
> config-table-driven expansion, add obfuscation-tolerant matching,
> add severity tiers, and ship an automated unit-test battery.
> Downstream callers (today: `ENHANCED.TASK_ENRICH_POSTS`, and after
> the enrichment split refactor: `ENHANCED.TASK_TEXT_FEATURES`) must
> continue to work without code changes — the UDF's input signature
> stays the same, and the output OBJECT only adds keys.
>
> **Work to do, in order:**
>
> 1. **Create the config tables.** Add a new file
>    `sql/00_setup/04_profanity_config.sql` that creates:
>    - `ENHANCED.PROFANITY_TERMS` (term, severity, allow_separators,
>      added_at, added_by, notes). Seed it with the existing 37-word
>      list mapped to reasonable severity tiers (see
>      `docs/PROMPT_PROFANITY_EXPANSION.md` for the expected tier
>      scheme — strong/sexual/slur; mild is for `damn`, `hell`,
>      `crap`, `jerk`, `piss`).
>    - `ENHANCED.PROFANITY_WHITELIST` (term, reason, added_at). Seed
>      with `sussex, scunthorpe, hellas, assam, assembly, assets,
>      asset, classic, glasses, class, cumulus, passage, assign,
>      assist` (add any you know are common false positives in
>      English social media text).
>    - Expand `PROFANITY_TERMS` by at least **~60 additional terms**
>      covering: plurals of existing terms (`asses`, `bitches`,
>      `fuckers`, `shits`, `dicks`, `pricks`), suffixed forms
>      (`fucked`, `fucks`, `shitting`, `shitted`, `bitching`), common
>      variants (`fuckin`, `fuckn`, `effin`, `mf`, `mofo`, `pos`,
>      `stfu`, `gtfo`), additional slurs that are semantically
>      comparable to the existing list, and sexual-explicit terms
>      that actually appear in moderation labels (`cum`, `jizz`,
>      `blowjob`, `handjob`, `dildo`, `boobs`, `tits`). Use
>      judgement; err toward including rather than excluding when
>      the term is genuinely profane. Tag `allow_separators = TRUE`
>      on strong/sexual/slur terms of length ≥ 4; leave it FALSE on
>      short mild terms (`ass`, `hell`, `crap`) to avoid false
>      positives.
>
> 2. **Rewrite the UDF.** Edit `sql/00_setup/03_udfs.sql` so the
>    JavaScript UDF:
>    - Receives the term list + whitelist as a compile-time-baked
>      constant — because Snowflake JavaScript UDFs cannot query
>      tables at runtime, the deploy script will substitute the
>      list at deploy time. Use a Jinja-style `{{PROFANITY_TERMS_JSON}}`
>      and `{{PROFANITY_WHITELIST_JSON}}` placeholder inside the
>      UDF source and write a small Python helper at
>      `scripts/render_profanity_udf.py` that reads from the config
>      tables (via `snowflake-connector-python`) and emits the final
>      rendered SQL to `sql/00_setup/_generated/03_udfs.rendered.sql`.
>      The unrendered template stays checked in; the rendered file
>      is `.gitignore`d.
>    - Masks whitelist occurrences **first**, then URLs, then scans
>      profanity terms.
>    - For each term with `allow_separators = TRUE`, compile a
>      regex that tolerates a single non-alphanumeric character
>      between each letter (e.g., `fuck` → `f[^A-Za-z0-9]?u[^A-Za-z0-9]?c[^A-Za-z0-9]?k`)
>      and collapses repeated characters in the input before matching
>      (`fuuuuck` → `fuck` via a pre-pass
>      `s.replace(/(.)\1{2,}/g, '$1$1')`).
>    - Applies common leetspeak substitutions before matching:
>      `0→o`, `1→i`, `3→e`, `4→a`, `5→s`, `7→t`, `@→a`, `$→s`. Do
>      this on a *copy* of the string used for detection, but perform
>      the redaction on the original. When a match is found on the
>      normalized copy, compute its offset+length and redact the same
>      span in the original. This preserves the user's text except
>      for the redacted span.
>    - Tracks the highest-severity hit. Severity ranking:
>      `mild=1, strong=2, sexual=3, slur=4`. Return the string name
>      of the max, or `null` when nothing redacted.
>    - Returns `{ post_text_clean, was_profanity_redacted,
>      redaction_count, severity_max }`.
>    - Preserves the existing behavior for NULL / empty string
>      inputs.
>
> 3. **Write the deploy helper.** Create
>    `scripts/render_profanity_udf.py` (≤120 lines). It:
>    - Connects to Snowflake using `snowflake-connector-python`,
>      reading credentials from env vars
>      `SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
>      SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE`.
>    - Queries `ENHANCED.PROFANITY_TERMS` and
>      `ENHANCED.PROFANITY_WHITELIST`.
>    - Reads the template at `sql/00_setup/03_udfs.sql`, substitutes
>      the JSON placeholders, and writes the rendered SQL to
>      `sql/00_setup/_generated/03_udfs.rendered.sql`.
>    - Prints the final term count and severity breakdown to
>      stdout so the operator can eyeball it before running the
>      rendered file.
>    - Has a `--dry-run` flag that only prints the rendered SQL.
>    - Does not connect to Snowflake if `--terms-json PATH` is
>      provided instead — that mode reads terms from a local JSON
>      file so CI can test without Snowflake credentials.
>
> 4. **Write the unit-test harness.** Create
>    `sql/99_validation/01_profanity_unit_tests.sql` containing 20+
>    `ASSERT` queries of the form:
>    ```sql
>    SELECT CASE WHEN
>      ENHANCED.CLEAN_PROFANITY('...'):post_text_clean::STRING = '...'
>    THEN 'PASS' ELSE 'FAIL' END AS result;
>    ```
>    Cover: clean text, each severity tier, separator-tolerant
>    matching (`f.u.c.k`, `f u c k`), leetspeak (`sh1t`, `a$$`),
>    repetition (`fuuuuck`), whitelist protection (`Sussex` must not
>    redact), URL preservation, NULL input, empty string, mixed case,
>    multiple profanities in one post (check `redaction_count`), and
>    `severity_max` ordering (a slur overrides a mild in the same
>    post).
>
> 5. **Update callers** — none of the SQL callers need to change
>    because the new OBJECT keys are additive. But **do** update
>    `ENHANCED.POSTS_ENRICHED` (and its population task) to add
>    `severity_max STRING` and `redaction_count NUMBER` columns so
>    we can inspect the behavior. These columns flow into
>    `CURATED.ML_READY` **only** as `severity_max` (categorical
>    feature). `redaction_count` stays in `POSTS_ENRICHED` for
>    debugging but is not exported to the ML table.
>
> 6. **Update docs.**
>    - Edit `docs/SNOWFLAKE_PROFANITY_UDF.md` to document the new
>      config-table approach, the expanded output shape, and the
>      deploy-via-render-script flow. Mark the old hardcoded-list
>      section as "historical" rather than deleting it.
>    - Edit `docs/SQL_FOLDER_OUTLINE.md` — the `00_setup/` section
>      (new `04_profanity_config.sql` file), and the "Pain Points"
>      section (profanity hardcoding moves from "open" to "tracked
>      in this refactor").
>
> **Constraints:**
> - Do not change the UDF name or input signature — every call site
>   uses `BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY(post_text)`.
> - Do not introduce a runtime Snowflake query inside the UDF.
>   JavaScript UDFs are compute-scoped and cannot query; the list
>   is injected at deploy time.
> - The slur tier is treated no differently from the others at the
>   UDF layer (all are redacted the same way). Severity tiers are a
>   classification output, not a branch in the redaction logic.
> - When a detected profanity span straddles a whitelist span
>   (rare, e.g., `asset` inside `asshole assets`), the whitelist
>   wins — we'd rather under-redact than corrupt the text.
> - Leetspeak substitution is applied for detection only. The
>   redacted output preserves the user's exact spelling in every
>   non-redacted span.
>
> **What to return:**
> - The new `04_profanity_config.sql`, the rewritten `03_udfs.sql`
>   template, and the renderer script.
> - The unit-test SQL file.
> - Updated docs (`SNOWFLAKE_PROFANITY_UDF.md`, `SQL_FOLDER_OUTLINE.md`).
> - A deploy-order note at the bottom of your final message
>   (config tables → seed rows → render script → execute rendered
>   UDF SQL → run unit-test SQL → redeploy any dependent tasks).
>
> Ask before you start if any of the following is unclear: whether
> the repo already has a Python Snowflake connector available (check
> `requirements.txt`), which slurs you should omit from the seeded
> list on ethical grounds (we err toward full coverage — redacting
> is protective, not endorsing), or what the right behavior is when
> the rendered file is out of date relative to the config tables
> (answer: warn; deployment is manual).

---

### Acceptance Checklist

- [ ] `SELECT COUNT(*) FROM ENHANCED.PROFANITY_TERMS` returns at
      least 95 rows (37 original + ≥60 new).
- [ ] `SELECT severity, COUNT(*) FROM ENHANCED.PROFANITY_TERMS
      GROUP BY severity` shows non-zero counts in every tier.
- [ ] All 20+ unit tests in
      `sql/99_validation/01_profanity_unit_tests.sql` return `PASS`.
- [ ] On the existing `POSTS_ENRICHED` data,
      `was_profanity_redacted = TRUE` rate is between 2% and 12%
      (realistic social media rate). If higher, review the leetspeak
      rules for over-matching; if lower, the separator-tolerant
      matching probably isn't firing.
- [ ] `Sussex`, `assets`, `classic`, `assembly`, `passage` in text
      do not trigger redaction.
- [ ] `f*ck`, `sh1t`, `a$$`, `fuuuuck`, `f.u.c.k` all trigger
      redaction with severity_max in (`strong`, `sexual`, `slur`).
- [ ] `ENHANCED.POSTS_ENRICHED` picks up the new `severity_max`
      and `redaction_count` columns on the next enrichment run.

---

### Out of Scope (Track Separately)

- Language detection / multi-language profanity. The Bluesky
  firehose is majority-English; non-English coverage is a follow-on.
- Classifier-based profanity detection (a real ML model). The UDF
  approach is deliberately simple and auditable; ML is a later
  conversation.
- Exposing the profanity config tables via a UI. For now
  `INSERT INTO ENHANCED.PROFANITY_TERMS VALUES (...)` is the editing
  interface.
