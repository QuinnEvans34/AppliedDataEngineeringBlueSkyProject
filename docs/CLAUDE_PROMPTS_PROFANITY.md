# CLAUDE_PROMPTS_PROFANITY.md
## Phased Prompts — Expand `CLEAN_PROFANITY`

Work through the phases in order. One phase per Claude session.
Review the diff and run the verification after each phase before
moving on.

The full design lives in `docs/PROMPT_PROFANITY_EXPANSION.md`;
these phase prompts tell Claude to read it.

---

## Phase A — Create the config + whitelist tables, seed with existing terms

**Scope:** only the two new tables and their seed rows. Do not
touch the UDF yet. Goal is to land the tables, get them reviewable
in Snowflake, and move on.

```
>>> PROMPT START >>>
Read these three files before making any changes:
  - docs/SQL_FOLDER_OUTLINE.md
  - docs/PROMPT_PROFANITY_EXPANSION.md
  - sql/00_setup/04_udfs_template.sql  (the current UDF, to extract the
    existing 37-word list)

Do ONLY Phase A of the profanity refactor:

1. Create a new file `sql/00_setup/03_profanity_config.sql` that:
   - Uses BLUESKYDATAENGINEERINGPROJECT and the ENHANCED schema.
   - Creates ENHANCED.PROFANITY_TERMS(term, severity, allow_separators,
     added_at, added_by, notes) with a PRIMARY KEY on term. See the
     "Proposed Schema" section of PROMPT_PROFANITY_EXPANSION.md for
     the exact column types.
   - Creates ENHANCED.PROFANITY_WHITELIST(term, reason, added_at)
     with a PRIMARY KEY on term.
   - Seeds PROFANITY_TERMS with EXACTLY the 37 existing terms from
     sql/00_setup/04_udfs_template.sql, mapped to severity per this scheme:
       mild:   ass, crap, damn, hell, jerk, piss, bollocks
       strong: asshole, bastard, bitch, bullshit, dick, dickhead,
               douche, douchebag, fuck, fucker, fucking, goddamn,
               horseshit, jackass, motherfucker, prick, shit,
               shithead, wanker
       sexual: cock, cunt, pussy, slut, twat, whore
       slur:   dyke, fag, faggot, nigga, nigger
     For every term, set allow_separators = FALSE (we enable
     tolerance in Phase C) and added_by = 'phase_a_seed'.
   - Seeds PROFANITY_WHITELIST with: sussex, scunthorpe, hellas,
     assam, assembly, assets, asset, classic, glasses, class,
     cumulus, passage, assign, assist. Reason column: 'common
     false-positive substring'.
   - Ends with a commented validation query block showing the
     expected counts (37 term rows, 14 whitelist rows) and a
     severity-breakdown query.

2. Update docs/SQL_FOLDER_OUTLINE.md — in the 00_setup/ table, add
   a row for 04_profanity_config.sql describing what it creates.

Do NOT change sql/00_setup/04_udfs_template.sql yet. Do NOT change any task
files. Do NOT update the PAIN POINTS section of the outline yet —
this is only Phase A.

Stop and report when done. Tell me: (a) the exact counts you seeded,
(b) any terms from the existing list you were unsure about assigning
a severity to, (c) confirmation the UDF was not touched.
<<< PROMPT END <<<
```

**Verify in Snowflake after Phase A:**

```sql
USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

SELECT COUNT(*) AS term_count FROM PROFANITY_TERMS;            -- expect 37
SELECT severity, COUNT(*) FROM PROFANITY_TERMS GROUP BY severity;
SELECT COUNT(*) AS whitelist_count FROM PROFANITY_WHITELIST;   -- expect 14
```

Commit before moving on.

---

## Phase B — Expand the word list and add the full severity tier set

**Scope:** purely data edits — insert more rows into
`PROFANITY_TERMS`. No code changes.

```
>>> PROMPT START >>>
Phase A of the profanity refactor is complete —
ENHANCED.PROFANITY_TERMS exists with 37 seed rows. Read:
  - docs/PROMPT_PROFANITY_EXPANSION.md (especially the "Work to do"
    step 1 guidance on ~60 additional terms)

Do ONLY Phase B:

1. Append an INSERT block to sql/00_setup/03_profanity_config.sql
   that adds at least 60 additional terms to PROFANITY_TERMS,
   covering:
     - Plurals of existing terms: asses, bitches, fuckers, shits,
       dicks, pricks, sluts, whores, assholes, bastards
     - Suffixed forms: fucked, fucks, fuckin, fuckn, shitting,
       shitted, bitching, bitched, pissing, pissed, dicking
     - Common obfuscated / abbreviated variants: effin, effing,
       mf, mofo, mfer, pos, stfu, gtfo, wtf, af (as a suffix
       intensifier)
     - Additional strong/sexual terms that show up in real
       social-media moderation: cum, jizz, blowjob, handjob,
       dildo, boobs, tits, boner, nsfw, porn, porno
     - Any additional slurs semantically comparable to the
       existing slur tier — use judgement; err toward full
       coverage because we are redacting, not endorsing.
   For every new row set allow_separators = TRUE on terms of
   length >= 4 in strong/sexual/slur tiers. Leave FALSE on mild
   and on short 3-letter stems.
   Set added_by = 'phase_b_expansion'.

2. Use ON CONFLICT DO NOTHING (Snowflake pattern: MERGE or a
   WHERE NOT EXISTS subquery) so re-running the file is safe.

3. Do NOT update or rewrite the UDF. Do NOT add new columns to
   the tables. Do NOT touch any other SQL files.

4. At the bottom of the file, add a commented validation query:
     SELECT severity, COUNT(*) FROM ENHANCED.PROFANITY_TERMS
     GROUP BY severity ORDER BY severity;
   and note the expected row-count bound (>= 95 total).

Stop and report when done. Tell me: (a) total rows after your
insert, (b) any term you chose to omit and why, (c) any term you
were unsure belonged in the list.
<<< PROMPT END <<<
```

**Verify in Snowflake after Phase B:**

```sql
SELECT COUNT(*) FROM ENHANCED.PROFANITY_TERMS;  -- expect >= 95
SELECT severity, allow_separators, COUNT(*)
FROM ENHANCED.PROFANITY_TERMS
GROUP BY severity, allow_separators
ORDER BY severity, allow_separators;
```

Eyeball the output — if strong/sexual/slur have zero rows with
`allow_separators = TRUE`, Phase B was miscoded.

---

## Phase C — Rewrite the UDF template + build the deploy renderer

**Scope:** the UDF, the renderer script, and the unit-test harness.
This is the biggest phase. Commit in two sub-commits if you want:
one for the template, one for the renderer.

```
>>> PROMPT START >>>
Phases A and B of the profanity refactor are complete.
ENHANCED.PROFANITY_TERMS has ~95+ terms across mild/strong/sexual/
slur. ENHANCED.PROFANITY_WHITELIST has the false-positive set.
Read:
  - docs/PROMPT_PROFANITY_EXPANSION.md (especially Work-to-do
    steps 2, 3, 4 — UDF rewrite, render script, unit tests)
  - docs/SNOWFLAKE_PROFANITY_UDF.md (the original spec)
  - sql/00_setup/04_udfs_template.sql (current UDF source)

Do ONLY Phase C:

1. Rewrite sql/00_setup/04_udfs_template.sql as a TEMPLATE. The JavaScript
   UDF source uses two Jinja-style placeholders:
     {{PROFANITY_TERMS_JSON}}  -> renders as a JS array of
        { term, severity, allow_separators } objects
     {{PROFANITY_WHITELIST_JSON}} -> renders as a JS array of strings
   The file as checked in should contain the placeholders unchanged.
   Running the file directly in Snowflake should fail with a clear
   error like "template not rendered — run scripts/render_profanity_udf.py"
   (e.g., wrap the template body in a SQL comment plus a
   `SELECT 1/0` guard, whatever is clearest — document the choice).

2. The rewritten UDF logic must:
   - Keep the input signature: CLEAN_PROFANITY(post_text STRING)
     RETURNS OBJECT.
   - Return keys: post_text_clean, was_profanity_redacted,
     redaction_count, severity_max.
   - Mask whitelist occurrences FIRST, then URLs, then scan terms.
   - For each term with allow_separators = TRUE: build a regex
     that tolerates one non-alphanumeric between each letter AND
     collapse 3+ repeated characters in the input first.
   - Apply leetspeak substitutions (0->o, 1->i, 3->e, 4->a,
     5->s, 7->t, @->a, $->s) on a DETECTION COPY. Redaction
     happens at the matched offsets on the ORIGINAL string so
     users' spelling is preserved in non-redacted spans.
   - severity_max = highest-ranked severity hit, null if nothing
     redacted. Rank: mild=1, strong=2, sexual=3, slur=4.
   - redaction_count = total redaction spans applied.
   - Preserve NULL/empty-string behavior from the original UDF.

3. Create scripts/render_profanity_udf.py (<= 150 lines). It:
   - Uses argparse.
   - Has a --terms-json PATH mode (reads a local JSON file) AND
     a Snowflake-query mode (reads from PROFANITY_TERMS and
     PROFANITY_WHITELIST). Prefer the local-file mode for CI.
   - Reads env vars SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER,
     SNOWFLAKE_PASSWORD, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE
     only in the Snowflake-query mode.
   - Reads the template at sql/00_setup/04_udfs_template.sql, substitutes
     the placeholders, writes the rendered SQL to
     sql/00_setup/_generated/03_udfs.rendered.sql.
   - Adds sql/00_setup/_generated/ to .gitignore if not present.
   - Prints term count, whitelist count, and severity breakdown
     to stdout.
   - Has a --dry-run flag that prints the rendered SQL instead of
     writing.

4. Create sql/99_validation/01_profanity_unit_tests.sql with
   20+ assertion queries of the form:
     SELECT CASE WHEN
       ENHANCED.CLEAN_PROFANITY('input'):post_text_clean::STRING
         = 'expected'
     THEN 'PASS' ELSE 'FAIL' END AS result,
     'test_name' AS test;
   Cover everything listed in PROMPT_PROFANITY_EXPANSION.md
   acceptance checklist, including: Sussex unchanged, f*ck /
   sh1t / a$$ / fuuuuck / f.u.c.k all redacted, URL preserved,
   NULL safe, empty-string safe, mixed case, multiple profanity
   counts correctly, severity_max ordering when a slur and mild
   both appear in the same input.

5. Update docs/SNOWFLAKE_PROFANITY_UDF.md — mark the old
   "Hardcoded list" section as HISTORICAL (don't delete it), add
   a new section explaining the template + renderer + unit-test
   workflow.

Do NOT alter ENHANCED.POSTS_ENRICHED or the tasks yet — that's
Phase D.

Stop and report when done. Tell me: (a) the exact template
placeholder syntax you used, (b) which mode of the renderer is
the default (local JSON vs Snowflake), (c) how many unit tests
you wrote and which acceptance-checklist items each covers.
<<< PROMPT END <<<
```

**Verify after Phase C:**

1. Run the renderer:
   ```
   python scripts/render_profanity_udf.py \
     --terms-json <your-terms-export>.json
   ```
   Check `sql/00_setup/_generated/03_udfs.rendered.sql` was written.
2. Run the rendered file in Snowflake to redeploy the UDF.
3. Run `sql/99_validation/01_profanity_unit_tests.sql` and confirm
   every row returns `PASS`.
4. Spot-check with SQL:
   ```sql
   SELECT ENHANCED.CLEAN_PROFANITY('What the f*ck, Sussex is nice')
     :post_text_clean::STRING AS cleaned,
     ENHANCED.CLEAN_PROFANITY('What the f*ck, Sussex is nice')
     :severity_max::STRING AS sev,
     ENHANCED.CLEAN_PROFANITY('What the f*ck, Sussex is nice')
     :redaction_count::NUMBER AS n;
   ```
   Expected: `"What the [Profanity], Sussex is nice"`, `strong`, `1`.

Commit (or two commits: template + renderer/tests separately).

---

## Phase D — Wire the new columns through `POSTS_ENRICHED` → `ML_READY`

**Scope:** expose `severity_max` and `redaction_count` downstream.
Small, focused change — but it touches the enrichment task SQL,
so if you have also done the enrichment split (the other stream),
coordinate which task file to edit.

```
>>> PROMPT START >>>
Phases A-C of the profanity refactor are complete — the UDF now
returns severity_max and redaction_count. Read:
  - docs/PROMPT_PROFANITY_EXPANSION.md (step 5: "Update callers")
  - docs/SQL_FOLDER_OUTLINE.md (to confirm current POSTS_ENRICHED
    column list)
  - sql/04_enhanced/00_posts_enriched_table.sql
  - sql/05_curated/00_ml_ready_table.sql
  - sql/06_tasks/00_tasks.sql  (unless the enrichment split has
    already happened — then read whichever file now owns the
    post_text_cleaned CTE and the final MERGE)

Do ONLY Phase D:

1. Add two columns to ENHANCED.POSTS_ENRICHED:
     severity_max       STRING
     redaction_count    NUMBER
   Use ALTER TABLE ... ADD COLUMN (non-destructive). Put the
   ALTER statements in a new file
     sql/04_enhanced/02_add_severity_columns.sql
   with a comment explaining the change and when it was added.
   Do NOT rewrite sql/04_enhanced/00_posts_enriched_table.sql —
   that's the create-table DDL and stays as the source of truth
   for fresh deployments, but we also add to it at the bottom
   the same two columns in the CREATE TABLE so future fresh
   deployments include them.

2. In the enrichment task SQL, update the post_text_cleaned CTE
   to surface ptc.cp:severity_max::STRING AS severity_max and
   ptc.cp:redaction_count::NUMBER AS redaction_count, then add
   both columns to the merge_source SELECT, the MERGE WHEN MATCHED
   UPDATE SET, and the MERGE WHEN NOT MATCHED INSERT.

3. In sql/05_curated/00_ml_ready_table.sql and the
   TASK_BUILD_ML_READY body (currently in sql/06_tasks/00_tasks.sql):
   - Add severity_max as a categorical feature column in
     CURATED.ML_READY (after the trend features).
   - DO NOT export redaction_count to ML_READY — it stays in
     POSTS_ENRICHED for debugging only.

4. Update docs/SQL_FOLDER_OUTLINE.md:
   - POSTS_ENRICHED column count (39 -> 41).
   - ML_READY column count (20 -> 21).
   - Move the "Hardcoded profanity list" pain point from "open"
     to "resolved in CLAUDE_PROMPTS_PROFANITY Phases A-D".

Do NOT touch the enrichment split work if that stream has its
own in-progress branch — if you notice a conflict, stop and ask.

Stop and report when done. Tell me: (a) the two files you edited
for the enrichment MERGE, (b) one spot-check query result
showing a recent row with a non-null severity_max.
<<< PROMPT END <<<
```

**Verify after Phase D:**

```sql
-- Confirm columns exist
DESC TABLE ENHANCED.POSTS_ENRICHED;           -- severity_max, redaction_count present
DESC TABLE CURATED.ML_READY;                  -- severity_max present, redaction_count NOT present

-- Confirm values are being populated (after next task run)
SELECT severity_max, COUNT(*) AS rows
FROM ENHANCED.POSTS_ENRICHED
GROUP BY severity_max
ORDER BY rows DESC;

-- Row-level spot check
SELECT post_text_clean, severity_max, redaction_count
FROM ENHANCED.POSTS_ENRICHED
WHERE redaction_count > 0
LIMIT 10;
```

Commit. The profanity stream is now done.
