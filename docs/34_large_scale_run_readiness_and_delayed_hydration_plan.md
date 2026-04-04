# 34 — Large-Scale Run Readiness and Delayed Hydration Plan

## Objective
Verify that the existing Bluesky pipeline is operationally ready for a future large-scale run targeting roughly 1M posts, with the correct sequencing for delayed hydration so downstream engagement labels are meaningful.

This phase is about readiness, configuration, and run design.
It is not the actual collection run.

## Why this phase exists
The recent audit established that:

- the current hydration code appears technically correct
- the current engagement labels are weak because hydration happened too soon after capture
- the pipeline architecture is largely in place
- the next major risk is not implementation correctness, but operational sequencing

Before running a large capture, we need to make sure the pipeline is truly ready to:
1. collect at scale
2. persist the right identifiers and state
3. hydrate later on a meaningful delay window
4. optionally support multiple hydration passes
5. produce outputs that can be reused cleanly downstream

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT run the 1M collection in this phase
- Do NOT rerun the Bluesky firehose in this phase
- Do NOT rerun hydration in this phase
- Do NOT create fresh collection output in this phase
- Do NOT redesign the full NLP / matching / ML pipeline in this phase
- Keep the work local, configuration-focused, and readiness-focused
- Prefer minimal, targeted readiness changes over broad refactors
- Do NOT commit

## Required context to read first
Before doing anything, read:

- `docs/31_bluesky_artifact_discovery_audit.md`
- `docs/32_bluesky_source_root_repoint_and_full_rerun_findings.md`
- `docs/33_hydration_correctness_and_label_quality_audit_findings.md`

Also inspect the actual code/modules/scripts involved in:
- firehose capture
- state tracking
- hydration input selection
- hydration execution
- hydration misses / retry handling
- actor enrichment if it depends on hydrated/raw state
- any runbook or config currently used for operational runs

## Goal of this phase
Answer these questions clearly:

1. Is the pipeline operationally ready to capture ~1M posts?
2. Is the current sequencing sufficient to avoid the premature-hydration problem?
3. What exact run procedure should be followed for the next real run?
4. What small readiness fixes or config changes are still needed before launch?
5. What should be validated immediately before pressing go?

## Deliverables
Create:

- `docs/34_large_scale_run_readiness_and_delayed_hydration_plan_findings.md`

Optional if useful:
- `docs/34_large_scale_run_runbook.md`
- `local/derived/audit/large_scale_run_readiness_summary.json`

If a small readiness-only config/helper change is necessary, make it.
But do not add speculative new pipeline features.

## Required audit / readiness behavior

### 1. Capture-path readiness audit
Inspect the current collection pipeline and document:
- where capture starts
- where raw outputs are written
- how run roots are created
- how state/progress is tracked
- whether the pipeline is resumable
- whether file rollover / chunking is already supported
- whether anything obvious would block a ~1M-post run

The goal is to determine whether the capture system itself is operationally usable at larger scale.

### 2. Identifier/state preservation audit
Verify that the run preserves the identifiers needed later for delayed hydration and downstream joins, such as:
- post URI / post ID
- actor DID / handle if applicable
- timestamps
- any keys needed for hydration and later joins

Be explicit about whether those identifiers are already captured correctly.

### 3. Hydration sequencing readiness audit
Inspect the current hydration workflow and determine:
- whether hydration can be run cleanly against an earlier captured post corpus
- whether hydration can be delayed without code changes
- whether hydration selection depends on raw/state in a clean way
- whether repeated hydration passes are already possible or would need a small adjustment
- whether misses and retries can support a delayed workflow

This is the key operational section.

### 4. Recommend the next-run sequencing
Write a concrete recommended sequencing plan for the next large run.

At minimum specify:
- capture first
- wait/delay before hydration
- hydrate after delay
- whether additional later hydrate passes are recommended
- when actor enrichment should run relative to hydration
- when downstream phases 23–27 should run

Do not guess arbitrary numbers without evidence.
If the exact delay window cannot be proven from current local evidence, recommend a practical conservative operational approach and label it as a recommendation.

### 5. Readiness gaps
Identify any remaining concrete gaps that would stop or materially weaken the next run, such as:
- missing config knobs
- hardcoded paths
- fragile assumptions
- lack of a clear runbook
- inability to point hydration at a prior run root cleanly
- insufficient logging or completion checks
- missing environment/config validation

Only include real gaps found from inspection.

### 6. Minimal readiness fixes only
If you find a small, concrete readiness problem that should be fixed before the run, fix it now if it is low-risk and directly related to launch readiness.

Examples of acceptable changes:
- adding a missing config/env parameter
- clarifying or centralizing a run-root path setting
- adding a dry-run/config validation check
- tightening a runbook or readiness helper

Do NOT:
- redesign the collection architecture
- add major new features
- change downstream NLP/matching/modeling logic
- build speculative automation that you do not need for the upcoming run

### 7. Pre-run checklist
Provide a blunt pre-run checklist covering:
- required config/env values
- output path expectations
- available disk/path assumptions
- what command(s) to run
- what not to run too early
- what to validate after capture and before hydration
- what to validate after hydration and before downstream phases

### 8. Recommendation section
End with a clear recommendation choosing one of:
- ready to run as-is
- ready to run after minor fixes
- not ready; specific blocking fixes still needed

This must be evidence-based.

## Findings markdown requirements
Write:

- `docs/34_large_scale_run_readiness_and_delayed_hydration_plan_findings.md`

It should include:

1. Executive summary
2. Capture-path readiness
3. Identifier/state preservation
4. Hydration sequencing readiness
5. Recommended next-run sequencing
6. Remaining gaps / fixes
7. Pre-run checklist
8. Final readiness verdict

If a separate runbook is helpful, create:
- `docs/34_large_scale_run_runbook.md`

## Optional JSON summary
If created, write:
- `local/derived/audit/large_scale_run_readiness_summary.json`

This should contain compact structured summaries of:
- readiness status
- key confirmed capabilities
- gaps
- recommended sequencing
- final verdict

## Non-goals
This phase should NOT:
- run the collection
- run hydration
- rerun downstream phases
- touch Snowflake
- redesign the engagement-label logic beyond sequencing recommendations
- build presentation artifacts yet

## Definition of done
This phase is done when:
1. there is a grounded answer on whether the pipeline is ready for a ~1M-post run
2. the delayed-hydration sequencing is explicitly defined
3. any small readiness blockers are identified or fixed
4. there is a clear pre-run checklist
5. the team knows whether it can safely launch the run tomorrow or the next day