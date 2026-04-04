# Week 2 Phase 2 — Snowpipe Loader Mode for Internal Stages

## Credit minimization requirement
Use the least amount of Snowflake credits possible.
- Reuse current loader flow wherever possible.
- Do not remove or rewrite the existing COPY-based implementation.
- Add the smallest clean Snowpipe path needed for Week 2.
- Do not perform large loads.
- Assume tests will use deterministic 25-row files.

## Objective
Add Snowpipe execution support to the existing loader while preserving COPY fallback.

This phase must implement:
1. Snowpipe submission flow for internal stages
2. pipe refresh / load trigger logic
3. polling/load-status logic
4. dual loader mode support:
   - snowpipe
   - copy

This phase must NOT implement fixtures yet.
This phase must NOT change downstream modeling logic.

## Current repo facts to align with
The audit found:
- stage upload already exists
- direct COPY INTO already exists
- main loader orchestration already exists
- manifest logging already exists
- parity checks already exist
- no Snowpipe submit/status code exists yet

## Required design
We are keeping dual mode:
- `snowpipe`
- `copy`

Expected CLI behavior:
- loader should accept a load mode flag
- Week 2 should default to `snowpipe`
- COPY mode must remain operational as fallback

## Snowpipe behavior requirements
For internal stages, the Snowpipe mode should follow this sequence:
1. discover files
2. upload files to internal stage
3. trigger the correct pipe for the correct prefix/path
4. poll load status/history until files are loaded or failed
5. record manifest info
6. run existing parity checks

## Implementation requirements
Add a Snowpipe helper module for:
- refreshing / submitting files to the correct pipe
- polling Snowflake load status
- retrieving per-file loaded row counts if possible
- surfacing clear success/failure output

Prefer a focused helper module instead of scattering Snowpipe logic across many files.

## Manifest requirements
Snowpipe mode must still support manifest recording.
Do not abandon the manifest path just because COPY is no longer doing the load.
If per-file row counts can be recovered cleanly from Snowflake history, use that.
If not, document the limitation clearly.

## Required flags / CLI updates
Update the main loader entrypoint so it supports:
- `--load-mode {snowpipe,copy}`

Default:
- `snowpipe`

Do not remove the existing COPY path.

## Constraints
- preserve current COPY behavior
- do not over-refactor
- do not implement fixture generation here
- do not add unrelated features
- least Snowflake credits possible

## Deliverables
1. Snowpipe helper module
2. loader CLI support for dual mode
3. Snowpipe execution wiring in the main load flow
4. manifest-compatible Snowpipe integration
5. concise summary of design decisions