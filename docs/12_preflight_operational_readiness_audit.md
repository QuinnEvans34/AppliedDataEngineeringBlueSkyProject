# Preflight Operational Readiness Audit (1M Run)

Date: 2026-04-02  
Repo: `AppliedDataEngineeringBlueSkyProject`

## Scope and Evidence
This is an audit-only pass grounded in current code and docs. No architecture redesign was done.

Primary files audited:
- `bluesky_pipeline/main_firehose.py`
- `bluesky_pipeline/main_hydrate.py`
- `bluesky_pipeline/main_actor_enrich.py`
- `bluesky_pipeline/state/sqlite_store.py`
- `bluesky_pipeline/hydrate/selector.py`
- `bluesky_pipeline/actor/selector.py`
- `bluesky_pipeline/firehose/{client,decoder,extractor,normalizer}.py`
- `bluesky_pipeline/{config.py,batching/writer.py,logging_config.py}`
- `docs/07/08/09/10` runbook docs

Validation run executed during audit:
- `python3 --version` -> `Python 3.14.3`
- `python3 -m unittest discover -s tests -v` -> `52 tests`, all passing
- import check -> `websockets`, `certifi`, `atproto_firehose`, `atproto_core` import successfully in this environment

## 1) Operational Readiness Verdict
**Verdict: GO WITH FIXES**

Why not plain GO:
- Hydration/actor stop conditions are not self-sufficient for “fully complete, nothing stranded” without external completion checks.
- Hydration/actor work selection is not hard-scoped by capture run in SQL; shared DB reuse can mix runs.
- Dependency declaration/setup for a second laptop is incomplete (no `requirements*.txt`/`pyproject.toml` in repo root).

## 2) Firehose Path Audit (Most Critical)

### What is good
- Firehose run lifecycle is tracked (`create_capture_run`, progress updates, terminal status updates).
- URI dedupe is enforced at DB layer (`captured_posts.uri` PK + `ON CONFLICT(uri) DO NOTHING`).
- Writer rotates by row/time, writes to temp files, then atomically renames on finalize.
- Reconnect backoff exists in websocket client.

### What needs attention before 1M
- **Live decode dependencies are not enforced by packaging or startup hard-fail.**
  - Firehose client explicitly requires `websockets`.
  - Decoder/extractor rely on `atproto_firehose` and `atproto_core` for real binary frames/CAR parsing.
  - If `atproto_*` modules are missing, decode/extract may silently produce no rows instead of a clear startup failure.
- **No dependency manifest in repo root.**
  - There is no `requirements.txt`/`pyproject.toml`, so second-laptop setup is fragile.
- **Raw-file lineage link is not populated.**
  - `insert_captured_post(..., capture_file_id=None)` means per-row FK linkage to `batch_files` is not currently used.
- **Crash consistency gap exists between DB insert and file durability.**
  - Post state is committed in SQLite before row durability is guaranteed in a finalized gzip file. Hard crash can leave state/file mismatch.
- **No log rotation.**
  - `logging.FileHandler` grows unbounded.
- **No dedicated firehose tests.**
  - Hydrate/actor/inspect are tested; firehose path is least proven by automated tests.

## 3) Hydration Completion Logic Audit

### Direct answer: does it process until hydration is complete?
**Not by itself, for the strict completion condition you requested.**

What code does now:
- Claims mature rows in `pending/retryable`, processes them, and exits in one-shot mode when no rows are claimable.
- Supports `--continue-polling`, but in that mode it sleeps on idle and does not self-terminate.
- One-shot mode can also exit early on retryable-only cycles (intentional hot-retry guard).

What is missing for strict completion:
- No built-in terminal check of “capture run finished + all rows matured + zero remaining eligible + zero in-flight claimed”.
- No built-in check for non-expired claimed rows held by another worker when deciding completion.
- Claim query is not filtered by `capture_run_id`; rows from other capture runs in same DB can be claimed.

### Batch/request limit behavior
- Request chunking is correct and bounded (`<=25` URIs/request).
- Outer loop keeps claiming additional DB batches, so chunk limits do not inherently strand rows.
- Rows can still remain in `retryable` by design and require later reruns.

### Safe run mode to use
- Use **one-shot mode** (default; do **not** set `--continue-polling`) in repeated invocations.
- Drive completion via external completion checker (see command section below).

## 4) Actor Enrichment Completion Logic Audit

### Direct answer: does it process until actor enrichment is complete?
**Not by itself, for strict completion.**

What code does now:
- Re-seeds actor DIDs each cycle.
- Claims `pending/retryable` actor rows and processes in request chunks (`<=25`).
- Exits one-shot on no claimable rows, or on retryable-only cycle guard.
- `--continue-polling` mode idles forever unless externally stopped.

What is missing:
- No built-in terminal check for zero in-flight `claimed` rows before run completion.
- No built-in upstream gate that hydration stage is fully complete.
- No run-scope filter; actor seeding pulls from all `captured_posts` in DB.

### Batch/request limit behavior
- Chunking logic is correct (`<=25` DIDs/request).
- Outer loop keeps claiming until no claimable rows; chunk size alone does not strand rows.

### Safe run mode to use
- Use repeated **one-shot** actor runs (default mode) with external completion checks.

## 5) Run Scoping and DB Isolation Audit

### Explicit answers
- Capture run scoping: firehose writes `capture_run_id` per row, but dedupe key is global URI across the whole DB.
- Hydrate run scoping: hydrate run records a `capture_run_id`, but claim SQL is not filtered by it.
- Actor enrichment scoping: seeding/claiming is global to `actor_profiles_state` and source tables in DB.
- Safe to reuse one DB for large run: **Not recommended** due cross-run claim/seed risk.
- Fresh run-specific DB required/recommended: **Strongly recommended for safety (treat as required operationally for 1M).**

## 6) Second-Laptop Readiness Audit

### Gaps found
- No dependency lock/manifest file in repo root.
- Firehose live decode requires more than what runbook currently emphasizes:
  - `websockets`
  - `atproto` (provides `atproto_firehose` and `atproto_core`)
  - `certifi`
- Running `--help` does not validate live decode dependencies.

### Environment/path assumptions
- Commands assume execution from repo root (`python3 -m bluesky_pipeline...`).
- Docs assume bash-like shell syntax (`$(date ...)`, brace expansion), not Windows cmd/PowerShell.
- Relative defaults exist, but runbook should pass explicit `BASE` paths (already done in recent docs).

## 7) Scheduling/Orchestration Reality Audit

### Explicit answers
- “Automatic hydration after 24 hours” already implemented? **No.**
- What exists: maturity cutoff logic and polling capability.
- What does not exist: built-in staged scheduler/orchestrator with completion-aware stop conditions.

### Simplest grounded orchestration for this repo
- Use **external scheduled staged orchestration** that runs hydration/actor in repeated one-shot invocations with DB completion checks.
- Avoid long-lived `--continue-polling` workers for completion-driven automation because they do not self-complete.

## 8) 1M Practical Risk List (Code-Grounded)

- Disk usage risk: large raw/hydrated/actor gzip outputs + SQLite growth; capacity planning is mandatory.
- Runtime uncertainty: no 1M benchmark in repo; firehose has limited live proof and no dedicated tests.
- Network interruption risk: reconnect/backoff exists, but prolonged instability will increase total duration.
- Sleep/power risk: laptop sleep interrupts long jobs; hard interruptions increase retry/recovery complexity.
- SQLite durability/perf risk: per-row commits on capture can be slow; no WAL/busy-timeout tuning in store setup.
- Output folder growth: many files/large trees under one run root; no automatic cleanup.
- Log growth: no rotation in logger setup.
- Rerun/recovery risk: one-shot retryable guard intentionally leaves retryables for later runs; operator must rerun.

## 9) Exact Commands for a Safe Operator Run

Use fresh run-scoped paths and DB:

```bash
RUN_TAG="million_$(date +%Y%m%d_%H%M%S)"
BASE="data/output/${RUN_TAG}"
DB="${BASE}/state/run.db"
export DB
mkdir -p "$BASE"/{state,logs,raw_posts,hydrated_posts,hydration_misses,actor_profiles,exports}
```

Second-laptop dependency bootstrap (explicit):

```bash
python3 -m pip install --upgrade pip
python3 -m pip install websockets atproto certifi
python3 - <<'PY'
for m in ("websockets", "certifi", "atproto_firehose", "atproto_core"):
    __import__(m)
print("live_dependencies_ok")
PY
```

### 9.1 Start 1M firehose capture

```bash
python3 -m bluesky_pipeline.main_firehose \
  --db-path "$DB" \
  --log-path "$BASE/logs/firehose_full.log" \
  --raw-output-dir "$BASE/raw_posts" \
  --target-count 1000000
```

Get run ID (for explicit hydrate scoping metadata):

```bash
CAPTURE_RUN_ID=$(python3 - <<'PY'
import os, sqlite3
db = os.environ["DB"]
conn = sqlite3.connect(db)
row = conn.execute("SELECT capture_run_id FROM capture_runs ORDER BY started_at DESC LIMIT 1").fetchone()
conn.close()
if not row:
    raise SystemExit("No capture run found")
print(row[0])
PY
)
export CAPTURE_RUN_ID
```

### 9.2 Hydration in safe completion mode (repeated one-shot)

```bash
while true; do
  python3 -m bluesky_pipeline.main_hydrate \
    --db-path "$DB" \
    --log-path "$BASE/logs/hydrate_full.log" \
    --capture-run-id "$CAPTURE_RUN_ID" \
    --hydrated-output-dir "$BASE/hydrated_posts" \
    --miss-output-dir "$BASE/hydration_misses" \
    --maturity-hours 24

  python3 - <<'PY'
import os, sqlite3, sys
from datetime import datetime, timezone, timedelta

def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

db = os.environ["DB"]
run_id = os.environ["CAPTURE_RUN_ID"]
maturity_hours = 24
now = datetime.now(timezone.utc)
cutoff = (now - timedelta(hours=maturity_hours)).isoformat()

conn = sqlite3.connect(db)
row = conn.execute(
    "SELECT status FROM capture_runs WHERE capture_run_id = ?",
    (run_id,),
).fetchone()
if row is None:
    conn.close()
    print("HYDRATION_COMPLETE=0 missing_capture_run")
    sys.exit(1)

capture_completed = (row[0] == "completed")
max_cap = conn.execute(
    "SELECT MAX(captured_at) FROM captured_posts WHERE capture_run_id = ?",
    (run_id,),
).fetchone()[0]
all_rows_mature = bool(max_cap) and (parse_iso(max_cap) <= now - timedelta(hours=maturity_hours))

mature_pending_retryable = conn.execute(
    """
    SELECT COUNT(*) FROM captured_posts
    WHERE capture_run_id = ?
      AND hydration_status IN ('pending','retryable')
      AND captured_at <= ?
    """,
    (run_id, cutoff),
).fetchone()[0]

inflight_claimed = conn.execute(
    """
    SELECT COUNT(*) FROM captured_posts
    WHERE capture_run_id = ?
      AND hydration_status = 'claimed'
    """,
    (run_id,),
).fetchone()[0]
conn.close()

ok = capture_completed and all_rows_mature and mature_pending_retryable == 0 and inflight_claimed == 0
print(f"HYDRATION_COMPLETE={int(ok)} capture_completed={capture_completed} all_rows_mature={all_rows_mature} mature_pending_retryable={mature_pending_retryable} inflight_claimed={inflight_claimed}")
sys.exit(0 if ok else 1)
PY

  if [ $? -eq 0 ]; then
    break
  fi

  sleep 300
 done
```

### 9.3 Actor enrichment in safe completion mode (repeated one-shot)

```bash
while true; do
  python3 -m bluesky_pipeline.main_actor_enrich \
    --db-path "$DB" \
    --log-path "$BASE/logs/actor_full.log" \
    --actor-output-dir "$BASE/actor_profiles"

  python3 - <<'PY'
import os, sqlite3, sys

db = os.environ["DB"]
conn = sqlite3.connect(db)
pending_retryable = conn.execute(
    "SELECT COUNT(*) FROM actor_profiles_state WHERE enrichment_status IN ('pending','retryable')"
).fetchone()[0]
inflight_claimed = conn.execute(
    "SELECT COUNT(*) FROM actor_profiles_state WHERE enrichment_status = 'claimed'"
).fetchone()[0]
conn.close()

ok = (pending_retryable == 0 and inflight_claimed == 0)
print(f"ACTOR_COMPLETE={int(ok)} pending_retryable={pending_retryable} inflight_claimed={inflight_claimed}")
sys.exit(0 if ok else 1)
PY

  if [ $? -eq 0 ]; then
    break
  fi

  sleep 300
done
```

## 10) Safest Bounded Preflight Before 1M

Recommended smallest realistic preflight:
- Target count: **20,000 posts**
- Why: exercises multi-file raw rotation (`10,000` default rows/file), many hydrate/actor API request batches, and retry/claim lifecycle at non-trivial scale.

Preflight command sequence:

```bash
RUN_TAG="preflight_$(date +%Y%m%d_%H%M%S)"
BASE="data/output/${RUN_TAG}"
DB="${BASE}/state/preflight.db"
export DB
mkdir -p "$BASE"/{state,logs,raw_posts,hydrated_posts,hydration_misses,actor_profiles,exports}

python3 -m bluesky_pipeline.main_firehose \
  --db-path "$DB" \
  --log-path "$BASE/logs/firehose_preflight.log" \
  --raw-output-dir "$BASE/raw_posts" \
  --target-count 20000
```

Then run the same hydration/actor loop pattern above, but for preflight set `--maturity-hours 0` in hydration to validate pipeline mechanics quickly.

Required preflight acceptance checks before 1M:
- Firehose completes with target reached and no fatal errors in log.
- `main_inspect validate` passes on raw/hydrated/actor outputs.
- Hydration completion checker reaches `HYDRATION_COMPLETE=1`.
- Actor completion checker reaches `ACTOR_COMPLETE=1`.
- No stranded claims remain (`claimed` counts are zero in both tables).

Validation commands:

```bash
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect validate --input "$BASE/actor_profiles"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/raw_posts"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/hydrated_posts"
python3 -m bluesky_pipeline.main_inspect files --input "$BASE/actor_profiles"
```

## 11) Fixes by Severity

### Critical fixes before 1M run
1. Enforce fresh run-specific DB per run root (`data/output/<run_tag>/state/*.db`).  
   Why blocking: current hydrate/actor selectors are not run-scoped in SQL; shared DB can mix old/new work and invalidate run boundaries.
2. Add external completion-aware orchestration for hydration and actor (repeated one-shot + DB checks from section 9).  
   Why blocking: one-shot mode can end with retryables left, and built-in completion does not verify zero in-flight claims.
3. Add explicit second-laptop dependency bootstrap/verification for live firehose decode (`websockets`, `atproto`, `certifi`).  
   Why blocking: without these, live capture may fail or make no progress.

### Strongly recommended fixes
1. Add a real dependency manifest (`requirements.txt` or `pyproject.toml`) and pin tested versions.
2. Add startup hard-fail check in firehose live mode for required decode modules (`atproto_firehose`, `atproto_core`) instead of silent no-op behavior risk.
3. Add firehose-focused tests (at least decode/extract + bounded loop integration with mock/live-like frames).
4. Add log rotation (RotatingFileHandler) for long runs.
5. Consider SQLite runtime tuning (`journal_mode=WAL`, `busy_timeout`) and document concurrency assumptions.

### Nice-to-have improvements
1. Add a small “state status” CLI command to print pending/retryable/claimed counts directly.
2. Add per-stage health summaries (rows/sec, API error-rate snapshots) at fixed intervals.
3. Populate `capture_file_id` linkage when feasible for stronger row->file lineage.

## Final Notes / Uncertainty
- No large-scale (1M) performance benchmark is present in repo artifacts; runtime/disk estimates remain approximate.
- Snowflake load stage is not implemented in this repo; this audit covers capture/hydrate/actor readiness and operator safety up to local dataset generation.
