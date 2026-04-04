# Week 2 Phase 4 — Validation, Manifest Integration, Tests, and Demo Runbook

## Credit minimization requirement
Use the least amount of Snowflake credits possible.
- Validation should rely on the smallest deterministic fixture loads.
- Do not run large-scale ingestion for this phase.
- Reuse the 25-row fixture flow.
- Only add the minimum tests and operational documentation needed to prove Week 2 is complete.

## Objective
Finish Week 2 by making the Snowpipe path testable, auditable, and easy to demo.

This phase must implement:
1. validation for Snowpipe-based fixture loads
2. manifest recording compatibility in Snowpipe mode
3. tests for Snowpipe mode and dual-mode safety
4. a concise Week 2 runbook / demo checklist

## Current repo facts to align with
The audit found:
- manifest logging already exists for COPY mode
- parity checks already exist
- no Snowpipe manifest integration currently exists
- no Snowpipe tests currently exist
- Week 2 requires live proof that recent rows landed in RAW without manual UI loading

## Validation requirements
Snowpipe mode should be validated with deterministic 25-row fixture runs.

Validation should prove:
- files are staged to the expected prefix
- the correct pipe is refreshed/submitted
- rows land in the correct landing table
- row counts are correct
- manifest entries are recorded
- reruns are idempotent or clearly controlled
- COPY fallback still works

## Test requirements
Add only the minimum useful tests.

At minimum, cover:
- snowpipe mode CLI wiring
- correct pipe resolution by dataset family
- completion gate default vs skip behavior
- manifest handling in Snowpipe mode
- fallback COPY mode not broken

If true end-to-end Snowflake integration tests are not practical locally, add targeted unit/integration tests around loader decision logic and helper functions.
Do not overbuild a heavy test harness.

## Runbook requirements
Add a concise Week 2 runbook that shows:
1. required setup
2. command order
3. fixture generation
4. Snowpipe load execution
5. validation queries/checks
6. what to show the instructor
7. how to keep credits low

The runbook should be clear enough that the demo can be repeated without guesswork.

## Constraints
- least Snowflake credits possible
- do not overbuild
- keep documentation concise and operational
- preserve dual mode
- keep Week 2 assignment scope only

## Deliverables
1. Snowpipe validation support
2. manifest-compatible Snowpipe row tracking where feasible
3. minimal tests
4. Week 2 runbook / demo checklist
5. summary of remaining known limitations