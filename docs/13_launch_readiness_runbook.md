# Launch Readiness Runbook (Preflight 20k -> Real 1M)

Date: 2026-04-02

This is the canonical launch sheet for the critical readiness fixes:
- explicit dependency install contract (`requirements.txt`)
- live firehose dependency fail-fast
- repeated one-shot hydration/actor drain via `scripts/ops/stage_drain.py`

Use a fresh run root and a fresh run-specific DB for each staged run.

## 1) Second-Laptop Setup

From repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

Dependency sanity check:

```bash
python3 - <<'PY'
import importlib.util
for module in ("websockets", "atproto_firehose", "atproto_core", "certifi"):
    if importlib.util.find_spec(module) is None:
        raise SystemExit(f"missing:{module}")
print("live_dependencies_ok")
PY
```

CLI sanity check:

```bash
python3 -m bluesky_pipeline.main_firehose --help >/dev/null
python3 -m bluesky_pipeline.main_hydrate --help >/dev/null
python3 -m bluesky_pipeline.main_actor_enrich --help >/dev/null
python3 scripts/ops/stage_drain.py --help >/dev/null
```

## 2) Run Root Bootstrap

Use this for both preflight and 1M runs:

```bash
RUN_TAG="preflight_$(date +%Y%m%d_%H%M%S)"
BASE="data/output/${RUN_TAG}"
DB="${BASE}/state/run.db"
export DB
mkdir -p "$BASE"/{raw_posts,hydrated_posts,hydration_misses,actor_profiles,logs,state,exports}
```

Layout standard:
- `data/output/<run_tag>/raw_posts`
- `data/output/<run_tag>/hydrated_posts`
- `data/output/<run_tag>/hydration_misses`
- `data/output/<run_tag>/actor_profiles`
- `data/output/<run_tag>/logs`
- `data/output/<run_tag>/state`

## 3) Preflight (20,000 Posts)

### 3.1 Capture

```bash
python3 -m bluesky_pipeline.main_firehose \
  --db-path "$DB" \
  --log-path "$BASE/logs/firehose_preflight.log" \
  --raw-output-dir "$BASE/raw_posts" \
  --target-count 20000
```

Resolve capture run ID:

```bash
CAPTURE_RUN_ID=$(python3 - <<'PY'
import os, sqlite3
db = os.environ["DB"]
conn = sqlite3.connect(db)
row = conn.execute("SELECT capture_run_id FROM capture_runs ORDER BY started_at DESC LIMIT 1").fetchone()
conn.close()
if row is None:
    raise SystemExit("No capture run found")
print(row[0])
PY
)
echo "CAPTURE_RUN_ID=$CAPTURE_RUN_ID"
```

### 3.2 Hydration Drain (One-Shot Loop to Completion)

For preflight, use `--maturity-hours 0` to validate the full staged machinery quickly.

```bash
python3 scripts/ops/stage_drain.py drain-hydration \
  --db-path "$DB" \
  --capture-run-id "$CAPTURE_RUN_ID" \
  --log-path "$BASE/logs/hydrate_preflight.log" \
  --hydrated-output-dir "$BASE/hydrated_posts" \
  --miss-output-dir "$BASE/hydration_misses" \
  --maturity-hours 0 \
  --sleep-seconds 30
```

### 3.3 Actor Drain (One-Shot Loop to Completion)

```bash
python3 scripts/ops/stage_drain.py drain-actor \
  --db-path "$DB" \
  --log-path "$BASE/logs/actor_preflight.log" \
  --actor-output-dir "$BASE/actor_profiles" \
  --sleep-seconds 30
```

### 3.4 Preflight Validation Gates (Must Pass)

```bash
python3 scripts/ops/stage_drain.py check-hydration \
  --db-path "$DB" \
  --capture-run-id "$CAPTURE_RUN_ID" \
  --maturity-hours 0

python3 scripts/ops/stage_drain.py check-actor \
  --db-path "$DB"

python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/actor_profiles"

python3 -m bluesky_pipeline.main_inspect files --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/actor_profiles"
```

Promote to 1M only after all checks pass.

## 4) Real Run (1,000,000 Posts)

Create a fresh run root and DB:

```bash
RUN_TAG="million_$(date +%Y%m%d_%H%M%S)"
BASE="data/output/${RUN_TAG}"
DB="${BASE}/state/run.db"
export DB
mkdir -p "$BASE"/{raw_posts,hydrated_posts,hydration_misses,actor_profiles,logs,state,exports}
```

### 4.1 Capture 1M

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
db = os.environ["DB"]
conn = sqlite3.connect(db)
row = conn.execute("SELECT capture_run_id FROM capture_runs ORDER BY started_at DESC LIMIT 1").fetchone()
conn.close()
if row is None:
    raise SystemExit("No capture run found")
print(row[0])
PY
)
echo "CAPTURE_RUN_ID=$CAPTURE_RUN_ID"
```

### 4.2 Hydration Drain (Production Maturity)

Run after maturity window:

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

### 4.3 Actor Drain

```bash
python3 scripts/ops/stage_drain.py drain-actor \
  --db-path "$DB" \
  --log-path "$BASE/logs/actor_full.log" \
  --actor-output-dir "$BASE/actor_profiles" \
  --sleep-seconds 300
```

### 4.4 Completion Checks + Final Validation

```bash
python3 scripts/ops/stage_drain.py check-hydration \
  --db-path "$DB" \
  --capture-run-id "$CAPTURE_RUN_ID" \
  --maturity-hours 24

python3 scripts/ops/stage_drain.py check-actor \
  --db-path "$DB"

python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/actor_profiles"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydration_misses"
```

## 5) Completion Rules Used by the Helper

Hydration (`check-hydration`) returns complete only when all are true:
- `capture_run.status == completed`
- all captured rows for that run are mature at the configured maturity window
- mature `pending/retryable` hydration rows = `0`
- `claimed` hydration rows in-flight = `0`

Actor (`check-actor`) returns complete only when:
- actor `pending/retryable` rows = `0`
- actor `claimed` rows in-flight = `0`

Safety note:
- These checks are intended for fresh run-specific DB isolation (`$BASE/state/run.db`).
