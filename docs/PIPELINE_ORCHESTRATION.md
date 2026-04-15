# PIPELINE_ORCHESTRATION.md
## Spec: End-to-End Pipeline Orchestration Script

---

### Overview
A single shell script that runs the entire pipeline from
API capture through Snowflake task completion. This is the
one command that drives the full 1M post run.

```
run_pipeline.sh
      │
      ├── 1. Validate environment
      ├── 2. Run firehose capture (target: 1M posts)
      ├── 3. Write capture_completed_at timestamp
      ├── 4. Wait 24h for post engagement to mature
      ├── 5. Run hydration
      ├── 6. Run actor enrichment
      ├── 7. Run trend matching + write-back
      ├── 8. Load all data files to Snowflake RAW stages
      ├── 9. Resume Snowflake tasks
      └── 10. Monitor task completion + suspend tasks
```

---

### Script Location
```
run_pipeline.sh
```
Lives in project root. Always run from project root.

---

### Environment Validation (Step 1)
Before doing anything, validate:

```bash
# Must be run from project root
if [ ! -f "bluesky_pipeline/config.py" ]; then
    echo "ERROR: Must be run from project root"
    exit 1
fi

# Virtual environment must be active
if [ -z "$VIRTUAL_ENV" ]; then
    echo "ERROR: Virtual environment not active"
    echo "Run: source .venv/bin/activate"
    exit 1
fi

# Snowflake credentials must be available
if [ -z "$SNOWFLAKE_ACCOUNT" ] || [ -z "$SNOWFLAKE_USER" ]; then
    echo "ERROR: Snowflake credentials not set"
    echo "Check your .env file or environment variables"
    exit 1
fi

# Minimum disk space check (20GB)
AVAILABLE=$(df -BG . | tail -1 | awk '{print $4}' | tr -d 'G')
if [ "$AVAILABLE" -lt 20 ]; then
    echo "ERROR: Less than 20GB free disk space"
    exit 1
fi
```

---

### Resume Safety (Re-run Protection)
The script must be safe to re-run if interrupted.
Use state files in data/state/ to track progress:

```
data/state/capture_completed_at.txt     — written after capture
data/state/hydration_completed_at.txt   — written after hydration
data/state/actor_completed_at.txt       — written after actor enrich
data/state/trend_completed_at.txt       — written after trend matching
data/state/snowflake_loaded_at.txt      — written after stage upload
data/state/tasks_completed_at.txt       — written after task completion
```

Before each step, check if the corresponding state file exists.
If it does, skip that step and continue from the next one.

Example:
```bash
if [ -f "data/state/capture_completed_at.txt" ]; then
    echo "Capture already complete, skipping..."
else
    echo "Starting firehose capture..."
    python -m bluesky_pipeline.main_firehose
    date -u +"%Y-%m-%dT%H:%M:%SZ" > data/state/capture_completed_at.txt
fi
```

---

### 24-Hour Maturity Wait (Step 4)
After capture completes, enforce the 24-hour wait before
hydration. Post engagement needs time to accumulate.

```bash
CAPTURE_TIME=$(cat data/state/capture_completed_at.txt)
CAPTURE_EPOCH=$(date -d "$CAPTURE_TIME" +%s 2>/dev/null || \
                date -j -f "%Y-%m-%dT%H:%M:%SZ" "$CAPTURE_TIME" +%s)
NOW_EPOCH=$(date +%s)
ELAPSED=$(( (NOW_EPOCH - CAPTURE_EPOCH) / 3600 ))
REQUIRED=24

if [ "$ELAPSED" -lt "$REQUIRED" ]; then
    REMAINING=$(( REQUIRED - ELAPSED ))
    echo "Waiting for post maturity... ${REMAINING}h remaining"
    echo "Rerun this script in ${REMAINING} hours to continue"
    exit 0
fi
```

When the script is re-run after the wait period, it detects
that capture is done, the wait has elapsed, and proceeds
directly to hydration.

---

### Snowflake Stage Upload (Step 8)
After all Python pipeline steps complete, load output files
to RAW stages using the existing Python loader:

```bash
echo "Loading raw posts to Snowflake..."
python -m snowflake_loader.main \
    --dataset-family raw_posts \
    --source-dir data/raw_posts

echo "Loading hydrated posts to Snowflake..."
python -m snowflake_loader.main \
    --dataset-family hydrated_posts \
    --source-dir data/hydrated_posts

echo "Loading hydration misses to Snowflake..."
python -m snowflake_loader.main \
    --dataset-family hydration_misses \
    --source-dir data/hydration_misses

echo "Loading actor profiles to Snowflake..."
python -m snowflake_loader.main \
    --dataset-family actor_profiles \
    --source-dir data/actor_profiles

echo "Loading trend matches to Snowflake..."
python -m snowflake_loader.main \
    --dataset-family trend_matches \
    --source-dir data/trend_matches

echo "Loading Twitter trends to Snowflake..."
python -m snowflake_loader.main \
    --dataset-family twitter_trends \
    --source-dir data/samples
```

---

### Task Resume (Step 9)
After all data is loaded to stages, resume the Snowflake
task chain using the Python Snowflake connector:

```bash
echo "Resuming Snowflake processing tasks..."
python scripts/ops/resume_tasks.py
```

This calls a small Python script (defined below) that
resumes tasks and monitors completion.

---

### Task Monitor Script
```
scripts/ops/resume_tasks.py
```

```python
"""
resume_tasks.py
Resumes the ENHANCED and CURATED Snowflake task chain,
monitors completion, then confirms both tasks suspended.
"""
import time
import snowflake.connector
from bluesky_pipeline.config import load_config

def resume_and_monitor():
    config = load_config()
    conn = snowflake.connector.connect(...)

    # Resume in reverse order (child before parent)
    conn.execute("ALTER TASK CURATED.TASK_BUILD_ML_READY RESUME")
    conn.execute("ALTER TASK ENHANCED.TASK_ENRICH_POSTS RESUME")
    print("Tasks resumed. Monitoring completion...")

    # Poll every 60 seconds until both tasks are suspended again
    # (tasks self-suspend after completion)
    while True:
        enhanced_status = conn.execute(
            "SHOW TASKS LIKE 'TASK_ENRICH_POSTS' IN SCHEMA ENHANCED"
        ).fetchone()
        curated_status = conn.execute(
            "SHOW TASKS LIKE 'TASK_BUILD_ML_READY' IN SCHEMA CURATED"
        ).fetchone()

        if (enhanced_status['state'] == 'suspended' and
            curated_status['state'] == 'suspended'):
            print("All tasks completed and suspended.")
            break

        print("Tasks still running... checking again in 60s")
        time.sleep(60)

    # Validate row counts
    enhanced_count = conn.execute(
        "SELECT COUNT(*) FROM ENHANCED.POSTS_ENRICHED"
    ).fetchone()[0]
    curated_count = conn.execute(
        "SELECT COUNT(*) FROM CURATED.ML_READY"
    ).fetchone()[0]

    print(f"ENHANCED.POSTS_ENRICHED: {enhanced_count:,} rows")
    print(f"CURATED.ML_READY: {curated_count:,} rows")
    conn.close()

if __name__ == "__main__":
    resume_and_monitor()
```

---

### Logging
All output must be logged:

```bash
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/pipeline_$(date +%Y%m%dT%H%M%S).log"

# Redirect all output to log file AND terminal
exec > >(tee -a "$LOG_FILE") 2>&1
echo "Pipeline started at $(date -u)"
echo "Log file: $LOG_FILE"
```

---

### Full Script Structure

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── Setup ─────────────────────────────────────────────────
LOG_FILE="logs/pipeline_$(date +%Y%m%dT%H%M%S).log"
mkdir -p logs data/state
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Step 1: Validate environment ──────────────────────────
# ... validation checks ...

# ── Step 2: Firehose capture ──────────────────────────────
# ... capture with state file check ...

# ── Step 3: Write capture timestamp ──────────────────────
# ... already in capture block ...

# ── Step 4: Wait for maturity ─────────────────────────────
# ... 24h check, exit 0 if not ready ...

# ── Step 5: Hydration ─────────────────────────────────────
# ... hydration with state file check ...

# ── Step 6: Actor enrichment ──────────────────────────────
# ... actor enrich with state file check ...

# ── Step 7: Trend matching ────────────────────────────────
# ... trend matching + write-back with state file check ...

# ── Step 8: Load to Snowflake ─────────────────────────────
# ... all 6 dataset families with state file check ...

# ── Step 9: Resume tasks ──────────────────────────────────
# ... resume_tasks.py ...

# ── Step 10: Final summary ────────────────────────────────
echo "Pipeline complete at $(date -u)"
echo "Log saved to: $LOG_FILE"
```

---

### Files to Deliver
```
run_pipeline.sh                    ← main orchestration script
scripts/ops/resume_tasks.py        ← task monitor script
```

---

### Critical Rules
- Script must be safe to re-run at any point
- Never skip the 24h maturity wait
- Never pass --maturity-hours 0 to hydration worker
- All state files written to data/state/
- All logs written to logs/ directory
- Tasks resume only AFTER all data is loaded to stages
- Script exits cleanly with clear message if wait is needed