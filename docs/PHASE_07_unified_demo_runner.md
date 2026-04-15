# Phase 07 — Unified Demo Orchestration + Match-Driven Enhanced Trigger

## Goal
Create a single demo orchestration entrypoint that runs the full upstream demo flow in the correct order, then adjust the enhanced-layer trigger so enrichment happens only after trend-match data is present.

## Why this phase exists
The current demo flow is split across:
- `scripts/demo/demo_load.py`
- `scripts/demo/run_trend_matching.py`

That creates two problems:

1. **Operational split**
   - The operator has to run multiple scripts in the right order.
   - Relative-path assumptions make this more fragile than necessary.

2. **Wrong enhanced-layer trigger timing**
   - `ENHANCED.TASK_ENRICH_POSTS` currently reacts too early.
   - It starts when raw-post data lands, before actor/profile and trend-match data are fully ready.
   - That causes null enrichment fields in `ENHANCED.POSTS_ENRICHED`.

The fix is to:
- create one orchestration script that runs the upstream demo sequence in one place
- move enhanced triggering to the **trend-match readiness point**, not raw-post arrival

## Deliverables

### Deliverable 1 — New unified demo runner
Create a new script:

- `scripts/demo/run_full_demo_pipeline.py`

This script should become the canonical way to run the demo pipeline.

### Deliverable 2 — Trigger fix in SQL
Patch the enhanced task trigger so it keys off **trend-match data readiness** rather than raw-post arrival.

If the simplest clean version is:
- add/use a stream on `RAW.LANDING_TREND_MATCHES`
- trigger `ENHANCED.TASK_ENRICH_POSTS` from that stream
- keep `ENHANCED.TASK_BUILD_ML_READY` chained after enhanced

then do that.

If the existing task architecture makes explicit task execution cleaner for the unified demo runner, document that clearly and choose the smallest clean implementation.

## Required behavior for `run_full_demo_pipeline.py`

### 1. Run from repo root
The script must be safe to run from the repo root and should explicitly document that expectation.

### 2. Reuse existing scripts/modules
Do **not** rewrite all logic from scratch if the existing scripts already contain the correct implementations.

Prefer one of these patterns:
- import and call functions from `demo_load.py` and `run_trend_matching.py`
- or refactor those scripts minimally so their core logic is reusable from the new runner

Do not duplicate large blocks of logic unless unavoidable.

### 3. Correct execution order
The unified script must orchestrate this order:

1. load/capture demo posts
2. fetch/load actor profiles
3. upload raw posts + actor profiles
4. refresh/unpause relevant pipes if needed
5. run trend matching using the newly created demo posts file
6. upload trend matches
7. only then allow enhanced-layer processing
8. then curated can follow from the task chain or explicit execution

### 4. Prefer deterministic orchestration
The script should:
- log each stage clearly
- fail fast on critical errors
- make it obvious where the pipeline failed
- print a concise end summary

### 5. Handle enhanced execution cleanly
Pick the smallest clean approach:

#### Preferred if easy and safe
- trigger enhanced from trend-match stream readiness in SQL

#### Acceptable if operationally cleaner
- have the unified script explicitly execute:
  - `ENHANCED.TASK_ENRICH_POSTS`
  - then `ENHANCED.TASK_BUILD_ML_READY`
after upstream uploads complete

If choosing explicit execution in the unified script, explain why that is preferable for the demo flow.

### 6. Keep existing loaders compatible
Do not break:
- `scripts/demo/demo_load.py`
- `scripts/demo/run_trend_matching.py`

It is fine to refactor them for reuse, but they should still be runnable individually unless there is a strong reason not to.

## Required SQL changes

### A. Enhanced trigger source
Audit `sql/05_tasks/00_tasks.sql` and patch the enhanced task so it no longer keys off raw-post arrival alone.

Preferred target:
- trend-match readiness

Likely required supporting change:
- ensure there is a stream on `RAW.LANDING_TREND_MATCHES`
- ensure the task `WHEN` / trigger logic points to the correct stream or readiness condition

### B. Preserve deterministic joins
Do not undo the enhanced-layer refactor.
The enhanced task must still:
- dedupe source tables
- keep one row per `uri` in `merge_source`
- join actor/profile and trend data through canonical aliases

### C. Preserve curated chaining
`ENHANCED.TASK_BUILD_ML_READY` should still run after enhanced, either:
- by `AFTER ENHANCED.TASK_ENRICH_POSTS`
- or by explicit execution from the unified runner if that is the chosen demo orchestration pattern

## Acceptance criteria

This phase is complete only when:

1. there is one canonical demo runner script
2. the runner executes posts + actors + trend matching in one place
3. enhanced does not fire prematurely on raw-post arrival
4. enhanced runs only after required upstream enrichment inputs are ready
5. actor counts and trend metadata can populate in enhanced rows when source data exists
6. curated still runs correctly after enhanced
7. the flow is simple for the operator:
   - prime
   - run one demo script
   - validate

## Validation requirements
After implementation, provide validation steps for:

### 1. Unified runner success
- command to run it from repo root
- expected local outputs
- expected stage uploads
- expected landing row-count changes

### 2. Trigger timing
Prove enhanced does **not** populate too early from raw-post data alone.

### 3. Enhanced correctness
Provide SQL checks showing:
- actor/profile counts are populating
- trend metadata is populating
- `ENHANCED.POSTS_ENRICHED` remains unique on `uri`

### 4. Curated correctness
Provide SQL checks showing:
- curated task runs after enhanced
- `CURATED.ML_READY` has rows and expected distributions

## Constraints
- Keep the implementation narrow and practical
- Do not do unrelated cleanup
- Do not redesign the whole architecture
- Prefer the smallest clean orchestration fix that makes the demo reliable
- Be explicit about whether the final design is:
  - stream-triggered on trend matches
  - script-driven explicit task execution
  - or a hybrid

## Required final output from implementation
Codex should return:

1. **Problem summary**
2. **Files changed**
3. **New unified demo runner script**
4. **Any refactors to existing demo scripts**
5. **SQL trigger patch**
6. **Final run instructions**
7. **Validation queries**
8. **Any remaining risks / assumptions**
