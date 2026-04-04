# 33 — Hydration Correctness and Label Quality Audit

## Objective
Audit the Bluesky hydration pipeline and the resulting hydrated dataset to determine:

1. whether hydration is technically working correctly
2. whether the current hydrated engagement data is useful for label construction
3. whether immediate hydration timing is the main reason model quality is weak
4. what must change before a future large-scale run (for example 1M posts)

This phase is an audit phase only.

## Why this phase exists
The full downstream rerun established that the pipeline now works on the real larger Bluesky corpus.

However, current model quality is still likely limited by the engagement-label source, not by missing implementation.

The most likely cause is that hydration was run too soon after collection, which would produce many posts with:
- zero or near-zero likes
- zero or near-zero reposts
- zero or near-zero replies
- zero or near-zero quotes

If those early interactions were used to build LOW / MEDIUM / HIGH labels, then the target itself may be weak or misleading.

At the same time, we still need to verify that the hydration code is technically correct and not introducing its own problems.

This phase should separate:
- code correctness
from
- data usefulness

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the Bluesky firehose
- Do NOT rerun hydration
- Do NOT create new collection runs
- Do NOT modify upstream corpus files in place
- Do NOT redesign the modeling pipeline in this phase
- Keep the audit local, read-only, and evidence-based
- Prefer exact evidence from code and artifacts over speculation

## Required context to read first
Before auditing, read:

- `docs/29_checkpoint_status_audit_findings.md`
- `docs/30_data_location_and_coverage_audit.md`
- `docs/31_bluesky_artifact_discovery_audit.md`
- `docs/32_bluesky_source_root_repoint_and_full_rerun_findings.md`
- `docs/26_local_feature_engineering_findings.md`
- `docs/27_local_baseline_ml_modeling_findings.md`

Also inspect the actual code and artifacts involved in:
- post capture
- hydration
- hydration misses
- feature engineering
- label construction

## Scope
This audit must cover both:

### A. Hydration pipeline correctness
Inspect the code path that:
- selects posts for hydration
- calls the hydration/API endpoint(s)
- parses engagement fields
- writes hydrated outputs
- records misses
- retries/re-drains until completion
- preserves identifiers needed for later joins

### B. Hydration output / label quality
Inspect the actual hydrated dataset to determine:
- how many posts have zero engagement
- how many have near-zero engagement
- what the engagement distribution looks like
- whether the target labels are dominated by premature low-signal observations
- whether the current labels are useful enough for modeling

## Deliverables
Create:

- `docs/33_hydration_correctness_and_label_quality_audit_findings.md`

Optional if useful:
- `local/derived/audit/hydration_label_quality_summary.json`

## Required audit behavior

### 1. Hydration code-path audit
Inspect the actual hydration code and document:
- where the hydration logic lives
- what input records it expects
- what endpoint/client logic it uses
- which engagement fields it extracts
- how it identifies hydrated success vs miss
- how retries/drain loops work
- how completion is decided
- how hydrated outputs are written
- how misses are written
- what identifiers/keys are preserved for downstream joins

The goal here is to answer:
- is the hydrate code technically behaving as intended?
- are there any obvious logic flaws or fragile assumptions?

Be specific.
Name the files/modules/functions inspected.

### 2. Hydration artifact audit
Inspect the real hydrated artifacts under the large source root and summarize:
- file paths used
- total hydrated row count
- total hydration misses if available
- schema / key fields present
- engagement columns actually present
- timestamp/date fields present
- whether the data appears internally consistent for downstream joins

If helpful, inspect a small sample of rows to confirm structure.

### 3. Engagement distribution audit
Using the hydrated dataset actually used downstream, quantify at minimum:
- percent of hydrated posts with total engagement = 0
- percent with total engagement <= 1
- percent with total engagement <= 5
- distribution summaries for:
  - likes
  - reposts
  - replies
  - quotes
  - aggregate engagement if constructed
- whether the engagement signal is extremely sparse or heavily zero-inflated

Do not guess.
Compute summaries from the existing local artifacts.

### 4. Label-construction audit
Inspect the current Phase 26 label logic and document:
- how aggregate engagement is constructed
- how LOW / MEDIUM / HIGH labels are assigned
- whether quantiles or fixed rules are used
- whether the label assignment is technically correct given the data
- whether the resulting class distribution reflects premature hydration rather than real engagement separation

This should answer:
- is the label logic itself correct?
- even if correct, is the input engagement data too weak to produce meaningful labels?

### 5. Timing / staleness diagnosis
Use the available evidence to assess whether hydration timing is the likely root cause.

Check for signals such as:
- many posts with zero interactions
- very compressed engagement distributions
- timestamps indicating hydration happened close to capture time
- label buckets driven mostly by tiny early differences

Be explicit about what is confirmed vs inferred.

### 6. Downstream impact summary
Explain how hydration quality is likely affecting:
- feature engineering
- label usefulness
- class balance
- macro F1 / minority-class recall
- model interpretability

This should connect the label problem to the observed modeling weakness.

### 7. Operational readiness for future large-scale run
Evaluate whether the current hydrate pipeline is operationally suitable for a future 1M-post workflow.

Answer:
- is the hydrate code itself reusable as-is?
- what sequencing changes are needed?
- should hydration happen after a delay window?
- should there be one delayed hydrate pass or multiple passes?
- what should be validated before running at large scale?

Do not propose full implementation yet.
Just state what must change operationally.

### 8. Recommendation section
End with a blunt recommendation choosing the next move.

Possible outcomes:
- hydration code is correct, but current labels are weak due to timing -> redesign run sequencing next
- hydration code has correctness issues -> fix hydration implementation next
- both issues exist -> fix correctness first, then sequencing
- labels are usable enough -> move back to matching/features/modeling

The recommendation must be evidence-based.

## Markdown findings requirements
Write:
- `docs/33_hydration_correctness_and_label_quality_audit_findings.md`

It should include:

1. Executive summary
2. Hydration code-path audit
3. Hydration artifact/schema summary
4. Engagement distribution summary
5. Label-construction summary
6. Root-cause assessment
7. Downstream impact on modeling
8. Readiness for future 1M-post workflow
9. Recommended next move

Use concise tables and summaries where helpful.
Keep it readable.
Do not pad with generic commentary.

## Optional JSON summary
If created, write:
- `local/derived/audit/hydration_label_quality_summary.json`

This should contain compact structured summaries of:
- hydration code status
- artifact counts
- engagement sparsity metrics
- label distribution context
- root-cause assessment
- recommended next move

## Non-goals
This phase should NOT:
- rerun hydration
- touch Snowflake
- redesign matching
- redesign model architecture
- build new features
- create slides or presentation artifacts yet

## Definition of done
This phase is done when:
1. there is a grounded answer on whether hydration code is technically correct
2. there is a grounded answer on whether current hydrated labels are useful
3. the audit clearly separates code correctness from timing/data-quality problems
4. the report explains how hydration quality affects modeling outcomes
5. the team has a clear next move for either fixing hydration logic or changing future run sequencing