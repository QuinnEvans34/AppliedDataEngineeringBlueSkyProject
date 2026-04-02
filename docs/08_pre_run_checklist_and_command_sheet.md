# Phase 8: Pre-Run Checklist and Command Sheet

## Purpose
This is the final operator-focused command sheet for the first real dataset run.

Use this document:
- before the run (preflight)
- during the run (step-by-step execution)
- after the run (QA and acceptance checks)

Launch-readiness note:
- For the current critical readiness workflow (fresh run-specific DB + repeated one-shot drains), use [`13_launch_readiness_runbook.md`](./13_launch_readiness_runbook.md) as the primary execution guide.

This phase does not add architecture or major functionality. It freezes execution clarity.

## Scope
### In scope
- final pre-run checklist
- final smoke-test sequence
- final full-run command sequence
- final post-run QA command sheet
- practical failure/recovery guidance

### Out of scope
- Snowflake SQL
- model training code
- news enrichment
- architecture redesign of firehose/hydration/actor pipelines

## Operator Quick Start
### 1) Set run directory (required)
```bash
RUN_TAG="weekend_$(date +%Y%m%d)"
BASE="data/output/${RUN_TAG}"
mkdir -p "$BASE"/{state,logs,raw_posts,hydrated_posts,hydration_misses,actor_profiles,exports}
```

### 2) Confirm CLIs are callable
```bash
python3 -m bluesky_pipeline.main_firehose --help >/dev/null
python3 -m bluesky_pipeline.main_hydrate --help >/dev/null
python3 -m bluesky_pipeline.main_actor_enrich --help >/dev/null
python3 -m bluesky_pipeline.main_inspect --help >/dev/null
```

### 3) Run smoke tests (Friday)
```bash
python3 -m bluesky_pipeline.main_firehose \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/firehose_smoke.log" \
  --raw-output-dir "$BASE/raw_posts" \
  --target-count 25 \
  --max-rows-per-file 100 \
  --max-seconds-per-file 120

python3 -m bluesky_pipeline.main_hydrate \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/hydrate_smoke.log" \
  --hydrated-output-dir "$BASE/hydrated_posts" \
  --miss-output-dir "$BASE/hydration_misses" \
  --maturity-hours 0 \
  --claim-batch-size 25 \
  --request-batch-size 25

python3 -m bluesky_pipeline.main_actor_enrich \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/actor_smoke.log" \
  --actor-output-dir "$BASE/actor_profiles" \
  --claim-batch-size 25 \
  --request-batch-size 25
```

### 4) Smoke validation gate (must pass)
```bash
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/actor_profiles"
```

If any command fails, fix before full run.
Smoke hydration uses `--maturity-hours 0` intentionally. Do not reuse that value in production runs.

## Pre-Run Checklist (Friday)
Check all boxes before starting full capture.

### Environment
- [ ] Correct Python environment is active
- [ ] Required dependencies are installed
- [ ] Machine has enough free disk space
- [ ] Machine can remain online for long-running capture

### Paths and isolation
- [ ] `BASE` points to a new dated folder under `data/output/`
- [ ] DB path will be `"$BASE/state/weekend.db"`
- [ ] Logs path uses `"$BASE/logs"`
- [ ] Outputs stay under `raw_posts/`, `hydrated_posts/`, `hydration_misses/`, `actor_profiles/`
- [ ] No mixing with older test/dry-run folders

### Pipeline readiness
- [ ] Firehose smoke command succeeded
- [ ] Hydration smoke command succeeded
- [ ] Actor smoke command succeeded
- [ ] Inspection validation passed for smoke outputs

## Full Weekend Command Sheet
### Saturday: Full firehose capture
```bash
python3 -m bluesky_pipeline.main_firehose \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/firehose_full.log" \
  --raw-output-dir "$BASE/raw_posts" \
  --target-count 1000000
```

### Saturday post-capture checks
```bash
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect profile --input "$BASE/raw_posts" --top-k 20 > "$BASE/exports/profile_raw.json"
python3 -m bluesky_pipeline.main_inspect show --input "$BASE/raw_posts" --limit 5 --pretty
```

### Sunday: Full hydration (after maturity window)
```bash
python3 -m bluesky_pipeline.main_hydrate \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/hydrate_full.log" \
  --hydrated-output-dir "$BASE/hydrated_posts" \
  --miss-output-dir "$BASE/hydration_misses" \
  --maturity-hours 24
```

### Sunday post-hydration checks
```bash
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect profile --input "$BASE/hydrated_posts" --top-k 20 > "$BASE/exports/profile_hydrated.json"
python3 -m bluesky_pipeline.main_inspect show --input "$BASE/hydrated_posts" --limit 5 --pretty

python3 -m bluesky_pipeline.main_inspect files --input "$BASE/hydration_misses"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydration_misses"
```

### Sunday: Full actor enrichment (after hydration)
```bash
python3 -m bluesky_pipeline.main_actor_enrich \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/actor_full.log" \
  --actor-output-dir "$BASE/actor_profiles"
```

### Sunday post-actor checks
```bash
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/actor_profiles"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/actor_profiles"
python3 -m bluesky_pipeline.main_inspect profile --input "$BASE/actor_profiles" --top-k 20 > "$BASE/exports/profile_actor.json"
python3 -m bluesky_pipeline.main_inspect show --input "$BASE/actor_profiles" --limit 5 --pretty
```

## Final QA/Export Command Block
Run once after all three full jobs complete.

```bash
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/actor_profiles"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/hydration_misses"

python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/actor_profiles"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydration_misses"

python3 -m bluesky_pipeline.main_inspect export --input "$BASE/raw_posts" --output "$BASE/exports/raw_sample.json" --limit 100
python3 -m bluesky_pipeline.main_inspect export --input "$BASE/hydrated_posts" --output "$BASE/exports/hydrated_sample.json" --limit 100
python3 -m bluesky_pipeline.main_inspect export --input "$BASE/actor_profiles" --output "$BASE/exports/actor_sample.json" --limit 100
```

## Manual Spot-Check Targets
### Raw rows
- `uri`, `cid`, `record_created_at`, `captured_at`
- `has_reply`, `has_embed`
- plausible `record` payload

### Hydrated rows
- `uri`, `author_did`
- `like_count`, `reply_count`, `repost_count`, `quote_count`
- plausible zero/non-zero engagement mix

### Actor rows
- `did`, `handle`
- `followers_count`, `follows_count`, `posts_count`
- `enriched_at`, `profile`

## Practical Failure Handling
### If firehose fails
- inspect `"$BASE/logs/firehose_full.log"`
- keep run folder; do not delete immediately
- decide whether to resume with same DB or restart in a new `BASE`

### If hydration fails
- inspect `"$BASE/logs/hydrate_full.log"`
- inspect misses output
- rerun hydration on same DB/path only after confirming retry behavior is expected

### If actor enrichment fails
- inspect `"$BASE/logs/actor_full.log"`
- verify actor state progression in DB/logs
- rerun on same DB/path only if state handling is healthy

### If validation fails
- inspect offending rows first
- do not stage broken data
- fix issue and rerun affected step

## Success Criteria
Weekend run is successful when:
- raw, hydrated, and actor datasets exist and validate
- sample joins (`uri`, `author_did=did`) are plausible
- profile outputs look operationally sane
- sample exports confirm data realism

## Deferred (Intentionally)
- Snowflake SQL/load implementation
- model training and tuning
- news/topic enrichment
- production serving work

## Phase 8 Completion
This checklist and command sheet is the final operator artifact for first real execution.

With Phase 8 complete, the planning/buildout sequence is complete and the project moves to run execution and defect-fix loops.
