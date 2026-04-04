# 34 Large-Scale Run Runbook (Delayed Hydration)

Date: 2026-04-04  
Purpose: launch-ready sequence for the next real large run without premature hydration.

## 1) Bootstrap

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

```bash
RUN_TAG="million_$(date +%Y%m%d_%H%M%S)"
BASE="data/output/${RUN_TAG}"
DB="${BASE}/state/run.db"
export BASE DB
mkdir -p "$BASE"/{raw_posts,hydrated_posts,hydration_misses,actor_profiles,logs,state,exports}
```

## 2) Capture (~1M)

```bash
python3 -m bluesky_pipeline.main_firehose \
  --db-path "$DB" \
  --log-path "$BASE/logs/firehose_full.log" \
  --raw-output-dir "$BASE/raw_posts" \
  --target-count 1000000
```

Resolve capture run ID:

```bash
CAPTURE_RUN_ID=$(python3 - <<'PY'
import os, sqlite3
conn = sqlite3.connect(os.environ["DB"])
row = conn.execute("SELECT capture_run_id FROM capture_runs ORDER BY started_at DESC LIMIT 1").fetchone()
conn.close()
if row is None:
    raise SystemExit("No capture run found")
print(row[0])
PY
)
export CAPTURE_RUN_ID
echo "CAPTURE_RUN_ID=$CAPTURE_RUN_ID"
```

Post-capture checks:

```bash
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/raw_posts"
python3 scripts/ops/stage_drain.py check-hydration \
  --db-path "$DB" \
  --capture-run-id "$CAPTURE_RUN_ID" \
  --maturity-hours 24 || true
```

## 3) Delay Window (Do Not Hydrate Early)

- Wait at least 24 hours after capture completion before production hydration.
- Do not use `--maturity-hours 0` for this run.

Optional timestamp check:

```bash
python3 - <<'PY'
import os, sqlite3
conn = sqlite3.connect(os.environ["DB"])
row = conn.execute("SELECT capture_run_id,status,started_at,completed_at,written_post_count FROM capture_runs ORDER BY started_at DESC LIMIT 1").fetchone()
conn.close()
print(row)
PY
```

## 4) Hydrate After Delay

```bash
python3 scripts/ops/stage_drain.py drain-hydration \
  --db-path "$DB" \
  --capture-run-id "$CAPTURE_RUN_ID" \
  --log-path "$BASE/logs/hydrate_full.log" \
  --hydrated-output-dir "$BASE/hydrated_posts" \
  --miss-output-dir "$BASE/hydration_misses" \
  --maturity-hours 24 \
  --sleep-seconds 300
```

Hydration completion gate:

```bash
python3 scripts/ops/stage_drain.py check-hydration \
  --db-path "$DB" \
  --capture-run-id "$CAPTURE_RUN_ID" \
  --maturity-hours 24

python3 -m bluesky_pipeline.main_inspect files --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/hydration_misses"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydration_misses"
```

## 5) Actor Enrichment (After Hydration)

```bash
python3 scripts/ops/stage_drain.py drain-actor \
  --db-path "$DB" \
  --log-path "$BASE/logs/actor_full.log" \
  --actor-output-dir "$BASE/actor_profiles" \
  --sleep-seconds 300
```

Actor completion gate:

```bash
python3 scripts/ops/stage_drain.py check-actor --db-path "$DB"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/actor_profiles"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/actor_profiles"
```

## 6) Downstream Phase Timing (23-27)

Only run downstream local phases after:
- capture complete,
- hydration complete,
- actor complete,
- artifact validation passes.

Set source root to this run before opening phase notebooks:

```bash
export BLUESKY_SOURCE_ROOT="$BASE"
echo "$BLUESKY_SOURCE_ROOT"
```

Then execute notebooks in order:
- `notebooks/23_local_bluesky_text_preparation.ipynb`
- `notebooks/24_local_topic_extraction_candidate_generation.ipynb`
- `notebooks/25_local_post_to_trend_matching.ipynb`
- `notebooks/26_local_feature_engineering.ipynb`
- `notebooks/27_local_baseline_ml_modeling.ipynb`

## 7) Guardrails

- Never hydrate immediately after capture for production labeling.
- Always pass explicit `--capture-run-id` for hydration drains/checks.
- Keep one DB per run root; avoid mixing unrelated runs in one state DB.
- Multi-pass re-hydration of already hydrated posts is not first-class yet; treat as a later enhancement.
