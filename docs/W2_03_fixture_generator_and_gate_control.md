# Week 2 Phase 3 — Deterministic 25-Row Fixtures and Optional Completion Gate Bypass

## Credit minimization requirement
Use the least amount of Snowflake credits possible.
- We are explicitly using deterministic 25-row fixture files for Week 2 testing.
- Do not use fresh live collection for the Week 2 demo path.
- Do not create more than the minimum fixture volume required.
- Generate exactly the required row counts.

## Objective
Add a fixture-generation path and gate control so Week 2 can be demonstrated cheaply, repeatably, and without dependence on live ingestion timing.

This phase must implement:
1. deterministic fixture generation
2. exactly 25 rows per dataset family
3. support for all 4 landing families:
   - raw posts
   - hydrated posts
   - actor profiles
   - hydration misses
4. loader flag to skip strict completion gating for fixture/demo runs

## Current repo facts to align with
The audit found:
- current local artifacts already include:
  - raw posts: 25
  - hydrated posts: 25
  - actor profiles: 21
  - hydration misses: 1
- current local artifacts are not enough to support 25-row fixture demos across all 4 families
- no explicit `--skip-completion-gate` exists yet

## Required fixture behavior
The fixture generator should:
- build realistic `.jsonl.gz` files
- produce exactly 25 rows for each of the 4 families
- prefer deriving from known-good local artifacts where possible
- keep output deterministic and repeatable
- avoid introducing fake payload structures that break loader assumptions

If duplication is necessary to reach 25 rows for thin families like actor profiles or hydration misses, do it in a controlled and explicit way.
The output must remain structurally valid for the RAW landing load path.

## Gate behavior requirements
Strict hydrate/actor completion gating should remain the default for normal runs.
But Week 2 fixture demos need an explicit bypass.

Add a flag:
- `--skip-completion-gate`

Behavior:
- default: gate enforced
- flag present: gate bypassed for fixture/demo flow

Do not disable the gate globally.

## Constraints
- do not replace real run behavior
- do not weaken production/default flow
- do not overbuild a fixture framework
- least Snowflake credits possible

## Deliverables
1. fixture generator for all 4 families
2. exact 25-row output support
3. `--skip-completion-gate` loader flag
4. minimal docs/comments explaining intended Week 2 use