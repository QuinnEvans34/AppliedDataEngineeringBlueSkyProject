# 32 — Bluesky Source Root Repoint and Full Rerun

## Objective
Repoint the downstream local Bluesky pipeline phases to the real larger Bluesky corpus and rerun the downstream phases on that corpus without changing the overall pipeline design.

This phase is about fixing source-path selection, not redesigning the NLP/ML pipeline.

## Why this phase exists
The checkpoint and artifact-discovery audits established that:

- the real larger Bluesky corpus exists
- it lives in a sibling workspace folder:
  - `../snowflake_package - Copy`
- downstream phases 23–27 were defaulting to repo-local `data/`
- repo-local `data/` only contained a tiny diagnostic subset (`25` raw / `25` hydrated / `21` actor)

So the downstream pipeline is structurally implemented, but it has been reading the wrong Bluesky source root.

The immediate goal is to:
1. make the Bluesky source root configurable
2. point it to the real larger corpus
3. rerun downstream phases on the larger corpus
4. regenerate downstream artifacts so we can evaluate real NLP/matching/model performance

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the Bluesky firehose
- Do NOT rerun hydration
- Do NOT rerun actor/profile enrichment
- Do NOT create new collection runs
- Do NOT modify the upstream corpus files in place
- Do NOT hardcode a brittle one-off path as the only supported option
- Keep the solution local, configurable, and reproducible
- Preserve current repo-local `data/` behavior as a fallback/default where reasonable

## Confirmed source facts
The artifact-discovery audit found the real larger Bluesky corpus in:

- `../snowflake_package - Copy`

With approximately:
- `raw_posts`: `19,994` rows
- `hydrated_posts`: `19,731` rows
- `actor_profiles`: `13,850` rows

The current downstream source-discovery logic was effectively constrained to repo-local `data/`, which is why phases 23–27 used the tiny diagnostic subset instead.

## Required context to read first
Before changing anything, read:

- `docs/29_checkpoint_status_audit_findings.md`
- `docs/30_data_location_and_coverage_audit.md`
- `docs/31_bluesky_artifact_discovery_audit.md`

Also inspect the actual code and notebooks for phases:
- 23 local Bluesky text preparation
- 24 local topic extraction / candidate generation
- 25 local post-to-trend matching
- 26 local feature engineering
- 27 local baseline ML modeling

Specifically identify where the Bluesky source root is assumed, defaulted, or hardcoded.

## Objective of the code change
Make the Bluesky source root configurable for the downstream phases so they can operate on either:
- the default repo-local diagnostic source, or
- the larger sibling-run-root source

Preferred target source for this rerun:
- `../snowflake_package - Copy`

## Deliverables
Update the relevant downstream code/notebooks/config so that phases 23–27 can use a configurable Bluesky source root.

Then rerun/regenerate the downstream artifacts using the real larger corpus.

At minimum produce/update:

### Code / config / notebooks
Update the relevant files that currently assume `data/` as the only source root.

This may include:
- `src/...` files involved in source discovery / loading
- notebook path/config setup
- helper/config files if needed

If a single shared config/helper is the cleanest path, prefer that over repeated path literals.

### Regenerated downstream artifacts
Regenerate outputs for:
- Phase 23 prepared Bluesky posts
- Phase 24 topic candidates
- Phase 25 matching outputs
- Phase 26 feature dataset
- Phase 27 baseline modeling artifacts

Using the larger Bluesky source root.

### Findings report
Create:

- `docs/32_bluesky_source_root_repoint_and_full_rerun_findings.md`

Optional if useful:
- `local/derived/audit/full_rerun_summary.json`

## Required implementation behavior

### 1. Make Bluesky source root configurable
Implement a clear, simple configuration mechanism.

Acceptable options:
- environment variable
- function parameter with default
- centralized config constant/module
- small CLI argument where the scripts already support it

Preferred behavior:
- default remains compatible with current repo-local behavior
- override can point to `../snowflake_package - Copy`

Do not scatter multiple inconsistent path overrides across files.

### 2. Use the configurable source in downstream phases
Ensure the configurable source root is actually used by phases 23–27 wherever they load Bluesky upstream data.

Do not patch only notebook display code while leaving the real loaders unchanged.

### 3. Preserve downstream pipeline structure
Do not redesign the matching or modeling stack in this phase.
This phase is about feeding the existing pipeline the correct input corpus.

Only make the smallest necessary changes to:
- source discovery
- path resolution
- artifact regeneration

### 4. Rerun downstream phases on the larger corpus
Using the larger source root, rerun/regenerate:
- prepared posts
- topic candidates
- match outputs
- feature outputs
- baseline modeling outputs

Use the existing pipeline design unless a small compatibility fix is strictly required.

### 5. Report coverage changes
In the findings report, compare old vs new at a high level:
- prepared post count
- candidate count
- matched post/candidate counts
- feature row count
- label distribution
- baseline metrics if successfully regenerated

Do not over-interpret results yet.
Just report the outcome of using the correct corpus.

### 6. Be explicit about any partial failures
If one downstream phase succeeds and a later one fails, report that clearly.
Do not hide breakages behind partial success.

### 7. Keep the implementation clean
Preferred design:
- one shared way to resolve Bluesky source root
- readable fallback logic
- explicit reporting of the source path actually used

Avoid:
- burying the sibling path in multiple notebooks
- introducing repo-specific hacks that are hard to maintain
- changing unrelated logic

## Findings markdown requirements
Write:

- `docs/32_bluesky_source_root_repoint_and_full_rerun_findings.md`

It should include:

1. What source-path assumption was wrong
2. What code/config was changed
3. What actual Bluesky source root was used for the rerun
4. Which downstream phases were rerun successfully
5. Old vs new row-count comparison
6. Old vs new matching / feature / modeling coverage summary
7. Any failures or limitations encountered
8. Recommended next move after the full-corpus rerun

## Suggested implementation direction
A clean solution would likely:
- centralize Bluesky source-root resolution in one helper/config location
- default to repo-local `data/`
- allow override to `../snowflake_package - Copy`
- make notebooks and code use the same resolved source

But use the simplest clean design that matches the current repo structure.

## Non-goals
This phase should NOT:
- touch Snowflake
- rerun upstream collection/enrichment jobs
- redesign topic extraction
- redesign matching logic
- add new feature types
- do model refinement beyond rerunning baseline artifacts on the correct corpus
- build presentation slides yet

## Definition of done
This phase is done when:
1. the downstream pipeline no longer depends on repo-local `data/` as the only Bluesky source root
2. phases 23–27 can use `../snowflake_package - Copy`
3. downstream artifacts have been regenerated from the larger corpus
4. the findings report shows how coverage changed after using the correct source
5. the team can evaluate real NLP/matching/model quality on the larger dataset