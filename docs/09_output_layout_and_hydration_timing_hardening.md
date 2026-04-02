# Phase 9: Output Layout Cleanup and Hydration Timing Hardening

## Purpose
This phase standardizes run outputs under one root and makes hydration timing behavior explicit and safer for production runs.

This is a cleanup/hardening phase only.

## Final Standard Output Layout
All weekend-run artifacts should live under:

```text
data/output/<run_tag>/
  raw_posts/
  hydrated_posts/
  actor_profiles/
  hydration_misses/
  exports/
  logs/
  state/
```

Notes:
- `raw_posts/`, `hydrated_posts/`, and `actor_profiles/` are the three main datasets.
- `hydration_misses/` is audit/debug output.
- `exports/` is inspection output.
- `logs/` and `state/` isolate operational files per run.

## Command Root (Frozen)
Use this start block for all weekend runs:

```bash
RUN_TAG="weekend_$(date +%Y%m%d)"
BASE="data/output/${RUN_TAG}"
mkdir -p "$BASE"/{state,logs,raw_posts,hydrated_posts,hydration_misses,actor_profiles,exports}
```

## Hydration Timing Hardening

### Production-safe default
Hydration default maturity remains `24` hours in config (`HydrateConfig.maturity_hours = 24`).

### Startup visibility
`main_hydrate.py` now logs at startup:
- effective maturity window
- current UTC timestamp used for evaluation
- eligibility cutoff timestamp
- run mode classification (`immediate/test-style`, `low-maturity override`, or `production-style`)

### Warning behavior
Hydration now emits a visible warning when:
- `--maturity-hours 0` (immediate/test-style)
- `--maturity-hours` is below `24` (low-maturity override)

This does not block execution, but makes accidental early hydration obvious.

## Smoke vs Production Commands

### Smoke hydration (test wiring only)
```bash
python3 -m bluesky_pipeline.main_hydrate \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/hydrate_smoke.log" \
  --hydrated-output-dir "$BASE/hydrated_posts" \
  --miss-output-dir "$BASE/hydration_misses" \
  --maturity-hours 0 \
  --claim-batch-size 25 \
  --request-batch-size 25
```

### Production hydration (real dataset run)
```bash
python3 -m bluesky_pipeline.main_hydrate \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/hydrate_full.log" \
  --hydrated-output-dir "$BASE/hydrated_posts" \
  --miss-output-dir "$BASE/hydration_misses" \
  --maturity-hours 24
```

## Validation Checklist for This Phase
- docs use `data/output/<run_tag>/...` for live run commands
- hydrate config default is clearly `24` hours
- hydrator startup logs include maturity window and cutoff
- low/zero maturity runs emit clear warnings

## Intentionally Not Changed
- firehose/hydration/actor architecture
- Snowflake logic
- model training logic
- news-enrichment logic

## Phase 9 Completion Criteria
Phase 9 is complete when:
- output layout is standardized under `data/output/<run_tag>/...`
- production hydration timing is explicit and safe
- smoke hydration is still supported but clearly marked as test behavior
