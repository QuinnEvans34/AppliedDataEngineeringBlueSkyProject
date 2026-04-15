#!/usr/bin/env bash
set -euo pipefail

# ── Setup ─────────────────────────────────────────────────
LOG_DIR="logs"
STATE_DIR="data/state"
mkdir -p "$LOG_DIR" "$STATE_DIR"

LOG_FILE="$LOG_DIR/pipeline_$(date +%Y%m%dT%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "========================================"
echo "  Bluesky Pipeline — Full Run"
echo "========================================"
echo "Pipeline started at $(date -u)"
echo "Log file: $LOG_FILE"
echo ""

# ── Step 1: Validate environment ──────────────────────────
echo "── Step 1: Validate environment ──"

if [ ! -f "bluesky_pipeline/config.py" ]; then
    echo "ERROR: Must be run from project root"
    exit 1
fi

if [ -z "${VIRTUAL_ENV:-}" ]; then
    echo "ERROR: Virtual environment not active"
    echo "Run: source .venv/bin/activate"
    exit 1
fi

if [ -z "${SNOWFLAKE_ACCOUNT:-}" ] || [ -z "${SNOWFLAKE_USER:-}" ]; then
    echo "ERROR: Snowflake credentials not set"
    echo "Check your .env file or environment variables"
    exit 1
fi

# Disk space check — 20GB minimum (cross-platform)
if [ "$(uname)" = "Darwin" ]; then
    AVAILABLE=$(df -Pg . | tail -1 | awk '{print $4}')
else
    AVAILABLE=$(df -BG . | tail -1 | awk '{print $4}' | tr -d 'G')
fi
if [ "$AVAILABLE" -lt 20 ]; then
    echo "ERROR: Less than 20GB free disk space (${AVAILABLE}GB available)"
    exit 1
fi

echo "Environment OK"
echo ""

# ── Step 2: Firehose capture ─────────────────────────────
echo "── Step 2: Firehose capture ──"

if [ -f "$STATE_DIR/capture_completed_at.txt" ]; then
    echo "Capture already complete, skipping..."
else
    echo "Starting firehose capture (target: 1M posts)..."
    python -m bluesky_pipeline.main_firehose
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$STATE_DIR/capture_completed_at.txt"
    echo "Capture complete."
fi
echo ""

# ── Step 3-4: 24-hour maturity wait ─────────────────────
echo "── Step 3-4: 24-hour maturity wait ──"

CAPTURE_TS=$(cat "$STATE_DIR/capture_completed_at.txt")
# Use Python for cross-platform date math (macOS date lacks -d flag)
MATURITY_CHECK=$(python3 -c "
from datetime import datetime, timezone
ts = '${CAPTURE_TS}'.replace('Z', '+00:00')
capture = datetime.fromisoformat(ts)
elapsed = (datetime.now(timezone.utc) - capture).total_seconds() / 3600
if elapsed < 24:
    remaining = int(24 - elapsed) + 1
    print(f'WAIT:{remaining}')
else:
    print('READY')
")

if [[ "$MATURITY_CHECK" == WAIT:* ]]; then
    REMAINING=${MATURITY_CHECK#WAIT:}
    echo "Waiting for post maturity... ${REMAINING}h remaining"
    echo "Rerun this script in ${REMAINING} hours to continue"
    exit 0
fi

echo "Maturity wait elapsed. Proceeding."
echo ""

# ── Step 5: Hydration ────────────────────────────────────
echo "── Step 5: Hydration ──"

if [ -f "$STATE_DIR/hydration_completed_at.txt" ]; then
    echo "Hydration already complete, skipping..."
else
    echo "Starting hydration..."
    python -m bluesky_pipeline.main_hydrate
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$STATE_DIR/hydration_completed_at.txt"
    echo "Hydration complete."
fi
echo ""

# ── Step 6: Actor enrichment ─────────────────────────────
echo "── Step 6: Actor enrichment ──"

if [ -f "$STATE_DIR/actor_completed_at.txt" ]; then
    echo "Actor enrichment already complete, skipping..."
else
    echo "Starting actor enrichment..."
    python -m bluesky_pipeline.main_actor_enrich
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$STATE_DIR/actor_completed_at.txt"
    echo "Actor enrichment complete."
fi
echo ""

# ── Step 7: Trend matching + write-back ──────────────────
echo "── Step 7: Trend matching + write-back ──"

if [ -f "$STATE_DIR/trend_completed_at.txt" ]; then
    echo "Trend matching already complete, skipping..."
else
    echo "Starting trend matching..."
    python3 -c "
import pandas as pd
from src.nlp.post_trend_matching import MatchConfig, match_post_candidates_to_trends

candidates_df = pd.read_parquet('local/derived/bluesky/bluesky_topic_candidates.parquet')
trends_df = pd.read_parquet('local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet')

cfg = MatchConfig(
    date_window_days=3,
    fuzzy_min_score=0.88,
    semantic_min_score=0.60,
    max_stage_pool=5000,
    semantic_pool_top_k=250,
)

full_df, best_df, summary = match_post_candidates_to_trends(candidates_df, trends_df, cfg)
matched = summary.get('matched_count', 0)
total = summary.get('total_candidates', 0)
print(f'Trend matching complete: {matched}/{total} posts matched')
if summary.get('trend_match_files_written'):
    for f in summary['trend_match_files_written']:
        print(f'  Written: {f}')
"
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$STATE_DIR/trend_completed_at.txt"
    echo "Trend matching complete."
fi
echo ""

# ── Step 8: Load to Snowflake stages ─────────────────────
echo "── Step 8: Load to Snowflake stages ──"

if [ -f "$STATE_DIR/snowflake_loaded_at.txt" ]; then
    echo "Snowflake load already complete, skipping..."
else
    echo "Loading all dataset families to Snowflake stages..."
    python -m snowflake_loader.main_load_run \
        --run-root data \
        --skip-completion-gate
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$STATE_DIR/snowflake_loaded_at.txt"
    echo "Snowflake stage load complete."
fi
echo ""

# ── Step 9: Resume Snowflake tasks ───────────────────────
echo "── Step 9: Resume Snowflake tasks ──"

if [ -f "$STATE_DIR/tasks_completed_at.txt" ]; then
    echo "Tasks already completed, skipping..."
else
    echo "Resuming Snowflake processing tasks..."
    python scripts/ops/resume_tasks.py
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$STATE_DIR/tasks_completed_at.txt"
    echo "Snowflake tasks complete."
fi
echo ""

# ── Step 10: Final summary ───────────────────────────────
echo "========================================"
echo "  Pipeline complete at $(date -u)"
echo "  Log saved to: $LOG_FILE"
echo "========================================"
