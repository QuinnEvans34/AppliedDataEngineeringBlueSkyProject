# Phase 7: Frozen Feature Contract and Weekend Runbook

## Purpose
This document freezes:
- the feature/label/join contract for the first usable ML dataset package
- the operational runbook for the first real weekend collection run

This phase is documentation-first. It does not redesign firehose, hydration, actor enrichment, or canonical output formats.

## Scope Freeze
### In scope
- final data contract (datasets, joins, required fields, labels, leakage rules)
- final weekend run sequence and validation checklist
- minimal docs/support updates needed to run safely this weekend

### Out of scope
- Snowflake SQL implementation
- model training code
- news/topic enrichment implementation
- architecture redesign of existing jobs

## Frozen Dataset Package
Canonical outputs remain local rotated `.jsonl.gz` files.

### Dataset A: Raw Posts
- producer: `python3 -m bluesky_pipeline.main_firehose`
- location: `data/output/<run_tag>/raw_posts/<capture_run_id>/raw_posts_*.jsonl.gz`
- purpose: publish-time post features

### Dataset B: Hydrated Posts
- producer: `python3 -m bluesky_pipeline.main_hydrate`
- location: `data/output/<run_tag>/hydrated_posts/<hydrate_run_id>/hydrated_posts_*.jsonl.gz`
- purpose: delayed engagement outcomes (labels) + hydrated author fields

### Dataset C: Actor Profiles
- producer: `python3 -m bluesky_pipeline.main_actor_enrich`
- location: `data/output/<run_tag>/actor_profiles/<actor_run_id>/actor_profiles_*.jsonl.gz`
- purpose: author-level enrichment features

### Dataset D: Misses (audit)
- producer: hydration job miss output
- location: `data/output/<run_tag>/hydration_misses/<hydrate_run_id>/hydration_misses_*.jsonl.gz`
- purpose: unresolved lookup audit/debug only (not main modeling table)

## Frozen Join Contract
### Raw -> Hydrated
- primary key: `uri`
- secondary validation key: `cid`

### Hydrated -> Actor
- primary key: `author_did = did`

### Identity rule
- DID is the stable actor key
- handle is not a primary join key

## Frozen Label Contract
### Core engagement fields (from hydrated)
- `like_count`
- `reply_count`
- `repost_count`
- `quote_count`

### Primary regression label
```text
engagement_total = like_count + reply_count + repost_count + quote_count
```

### Recommended transformed label
```text
engagement_log = log1p(engagement_total)
```

### Optional classification label
- bucketed classes (for example `low/medium/high`) can be defined after observing first-run distribution
- thresholds are intentionally deferred until real data distribution is known

### Label timing rule
- label maturity is defined against `captured_at`
- do not schedule label windows off `record_created_at`

## Leakage Rules (Frozen)
### Allowed feature sources
- raw publish-time fields and derived publish-time features
- actor profile snapshot features (with caveat below)

### Disallowed predictors for the main model
- `like_count`, `reply_count`, `repost_count`, `quote_count`
- `engagement_total` and derived label variables
- any post-hoc ranking directly derived from delayed outcomes

### Actor snapshot caveat
Actor fields are fetched later than publish time. They are acceptable for this first dataset package if documented as enrichment-time snapshots, not guaranteed publish-time snapshots.

## Frozen Required Fields
These are the minimum fields that must survive into final local outputs.

### Required raw fields
- `capture_run_id`
- `seq`
- `repo_did`
- `event_time`
- `operation`
- `collection`
- `rkey`
- `uri`
- `cid`
- `record_created_at`
- `has_reply`
- `has_embed`
- `captured_at`
- `record`

### Required hydrated fields
- `hydrate_run_id`
- `capture_run_id`
- `uri`
- `cid`
- `indexed_at`
- `author_did`
- `author_handle`
- `author_display_name`
- `reply_count`
- `repost_count`
- `like_count`
- `quote_count`
- `labels`
- `hydrated_at`
- `record`

### Required actor fields
- `actor_run_id`
- `did`
- `handle`
- `display_name`
- `description`
- `followers_count`
- `follows_count`
- `posts_count`
- `indexed_at`
- `created_at`
- `labels`
- `associated`
- `enriched_at`
- `profile`

### Required miss fields
- `hydrate_run_id`
- `capture_run_id`
- `uri`
- `cid_at_capture`
- `captured_at`
- `status`
- `reason`
- `checked_at`
- `attempt_count`

## Weekend Runbook
This runbook is the frozen operational sequence for the first real dataset collection run.

Operator note:
- Use [08_pre_run_checklist_and_command_sheet.md](./08_pre_run_checklist_and_command_sheet.md) as the copy/paste execution sheet during the live weekend run.

### 1. Preflight (Friday)
Use an isolated run root so this weekend run is self-contained.

```bash
RUN_TAG="weekend_$(date +%Y%m%d)"
BASE="data/output/${RUN_TAG}"
mkdir -p "$BASE"/{state,logs,raw_posts,hydrated_posts,hydration_misses,actor_profiles,exports}
```

Optional dependency sanity checks:

```bash
python3 -c "import websockets, certifi; print('deps_ok')"
python3 -m bluesky_pipeline.main_firehose --help >/dev/null
python3 -m bluesky_pipeline.main_hydrate --help >/dev/null
python3 -m bluesky_pipeline.main_actor_enrich --help >/dev/null
python3 -m bluesky_pipeline.main_inspect --help >/dev/null
```

### 2. Smoke test (Friday, bounded)
#### Firehose smoke
```bash
python3 -m bluesky_pipeline.main_firehose \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/firehose_smoke.log" \
  --raw-output-dir "$BASE/raw_posts" \
  --target-count 25 \
  --max-rows-per-file 100 \
  --max-seconds-per-file 120
```

#### Hydration smoke (maturity override only for smoke)
Use `--maturity-hours 0` only for smoke validation. This is immediate/test-style hydration.

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

#### Actor enrichment smoke
```bash
python3 -m bluesky_pipeline.main_actor_enrich \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/actor_smoke.log" \
  --actor-output-dir "$BASE/actor_profiles" \
  --claim-batch-size 25 \
  --request-batch-size 25
```

#### Smoke validation via inspection CLI
```bash
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/actor_profiles"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect profile --input "$BASE/raw_posts" --top-k 10
```

Do not start the full run until smoke commands succeed.

### 3. Full capture run (Saturday)
```bash
python3 -m bluesky_pipeline.main_firehose \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/firehose_full.log" \
  --raw-output-dir "$BASE/raw_posts" \
  --target-count 1000000
```

### 4. Full hydration run (Sunday, after maturity window)
Production hydration should use a 24-hour maturity window. Keep this explicit in the full run command.

```bash
python3 -m bluesky_pipeline.main_hydrate \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/hydrate_full.log" \
  --hydrated-output-dir "$BASE/hydrated_posts" \
  --miss-output-dir "$BASE/hydration_misses" \
  --maturity-hours 24
```

### 5. Full actor enrichment run (after hydration)
```bash
python3 -m bluesky_pipeline.main_actor_enrich \
  --db-path "$BASE/state/weekend.db" \
  --log-path "$BASE/logs/actor_full.log" \
  --actor-output-dir "$BASE/actor_profiles"
```

### 6. End-of-run validation and exports
```bash
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/actor_profiles"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/hydration_misses"

python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/actor_profiles"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydration_misses"

python3 -m bluesky_pipeline.main_inspect profile --input "$BASE/raw_posts" --top-k 20 > "$BASE/exports/profile_raw.json"
python3 -m bluesky_pipeline.main_inspect profile --input "$BASE/hydrated_posts" --top-k 20 > "$BASE/exports/profile_hydrated.json"
python3 -m bluesky_pipeline.main_inspect profile --input "$BASE/actor_profiles" --top-k 20 > "$BASE/exports/profile_actor.json"

python3 -m bluesky_pipeline.main_inspect export --input "$BASE/raw_posts" --output "$BASE/exports/raw_sample.json" --limit 50
python3 -m bluesky_pipeline.main_inspect export --input "$BASE/hydrated_posts" --output "$BASE/exports/hydrated_sample.json" --limit 50
python3 -m bluesky_pipeline.main_inspect export --input "$BASE/actor_profiles" --output "$BASE/exports/actor_sample.json" --limit 50
```

## Post-Run QA Checklist
### Raw QA
- file counts and row counts are plausible
- required fields validate cleanly
- `has_reply` / `has_embed` distributions are plausible

### Hydrated QA
- row count is plausible relative to mature captured rows
- engagement fields are present and include zero/non-zero mix
- unresolved rows appear in misses when expected

### Actor QA
- one row per DID (no obvious duplication)
- follower/following/post counts populated where available
- row count is plausible relative to unique hydrated authors

### Cross-dataset QA
- sample `raw.uri -> hydrated.uri` joins succeed
- sample `hydrated.author_did -> actor.did` joins succeed

## Acceptance Criteria (Weekend Dataset Usable)
The first dataset package is usable when:
- raw, hydrated, and actor datasets are present and readable
- required-field validation passes for all produced datasets
- sample joins succeed on both join boundaries
- inspection exports confirm rows look real and structurally valid

## Intentionally Deferred
- Snowflake SQL implementation and orchestration
- model training / feature selection / tuning
- final split strategy for training/validation/test
- news/topic enrichment and semantic similarity features
- production inference service work

This deferred scope must not block the first weekend dataset collection.
