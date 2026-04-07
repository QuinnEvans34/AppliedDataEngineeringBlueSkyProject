#!/usr/bin/env bash
# run_1m_pipeline.sh — Run the full 1M-post Bluesky capture pipeline.
#
# Stages:  firehose capture → 24-hour maturity wait → hydration → actor enrichment
#
# Safe to re-run: skips completed stages based on sentinel files.

set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────
STAMP_FILE="data/state/capture_completed_at.txt"
HYDRATE_DONE_FILE="data/state/hydration_completed_at.txt"
MATURITY_SECONDS=$((24 * 3600))

# ── Helpers ──────────────────────────────────────────────────────────────────
ts()      { date "+%Y-%m-%d %H:%M:%S"; }
status()  { printf "\n[%s] ===== %s =====\n\n" "$(ts)" "$1"; }
die()     { printf "[%s] ERROR: %s\n" "$(ts)" "$1" >&2; exit 1; }

# ── Validate project root ────────────────────────────────────────────────────
if [[ ! -f "bluesky_pipeline/config.py" ]]; then
    die "Must be run from the project root (bluesky_pipeline/config.py not found)."
fi

# ── Activate virtual environment ─────────────────────────────────────────────
if [[ ! -f ".venv/bin/activate" ]]; then
    die ".venv/bin/activate not found. Create the virtualenv first."
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# ── Set up logging ───────────────────────────────────────────────────────────
mkdir -p logs data/state
LOG_FILE="logs/run_1m_$(date +%Y%m%d_%H%M%S).log"

# Tee all stdout+stderr to the log file AND the terminal.
exec > >(tee -a "$LOG_FILE") 2>&1

status "Pipeline run started — logging to $LOG_FILE"

# ── Stage 1: Firehose capture ────────────────────────────────────────────────
if [[ -f "$STAMP_FILE" ]]; then
    status "Firehose capture already completed ($(cat "$STAMP_FILE")). Skipping."
else
    status "Stage 1/3: Starting firehose capture (target: 1,000,000 posts)"

    python -m bluesky_pipeline.main_firehose
    firehose_rc=$?

    if [[ $firehose_rc -ne 0 ]]; then
        die "Firehose capture failed (exit code $firehose_rc). Fix and re-run."
    fi

    date -u "+%Y-%m-%dT%H:%M:%SZ" > "$STAMP_FILE"
    status "Stage 1/3: Firehose capture completed at $(cat "$STAMP_FILE")"
fi

# ── Stage 2: Maturity wait gate ──────────────────────────────────────────────
capture_ts=$(cat "$STAMP_FILE")

# Parse the UTC timestamp to epoch seconds (portable across GNU and BSD date).
if date --version >/dev/null 2>&1; then
    # GNU date
    capture_epoch=$(date -d "$capture_ts" +%s)
else
    # BSD/macOS date
    capture_epoch=$(date -jf "%Y-%m-%dT%H:%M:%SZ" "$capture_ts" +%s)
fi

now_epoch=$(date +%s)
elapsed=$((now_epoch - capture_epoch))
remaining=$((MATURITY_SECONDS - elapsed))

if [[ $remaining -gt 0 ]]; then
    remaining_hours=$(awk "BEGIN {printf \"%.1f\", $remaining / 3600}")
    ready_at=$(date -u -d "@$((capture_epoch + MATURITY_SECONDS))" "+%Y-%m-%d %H:%M UTC" 2>/dev/null \
            || date -u -r "$((capture_epoch + MATURITY_SECONDS))" "+%Y-%m-%d %H:%M UTC")
    status "WAITING: 24-hour maturity window not yet elapsed"
    echo "  Capture completed at : $capture_ts"
    echo "  Earliest hydration at: $ready_at"
    echo "  Time remaining       : ${remaining_hours} hours"
    echo ""
    echo "Re-run this script after the maturity window has passed."
    exit 0
fi

status "Maturity window satisfied (${elapsed}s since capture). Proceeding."

# ── Stage 3: Hydration ───────────────────────────────────────────────────────
if [[ -f "$HYDRATE_DONE_FILE" ]]; then
    status "Hydration already completed ($(cat "$HYDRATE_DONE_FILE")). Skipping."
else
    status "Stage 2/3: Starting hydration (default maturity-hours)"

    python -m bluesky_pipeline.main_hydrate
    hydrate_rc=$?

    if [[ $hydrate_rc -ne 0 ]]; then
        die "Hydration failed (exit code $hydrate_rc). Fix and re-run."
    fi

    date -u "+%Y-%m-%dT%H:%M:%SZ" > "$HYDRATE_DONE_FILE"
    status "Stage 2/3: Hydration completed at $(cat "$HYDRATE_DONE_FILE")"
fi

# ── Stage 4: Actor enrichment ────────────────────────────────────────────────
status "Stage 3/3: Starting actor enrichment"

python -m bluesky_pipeline.main_actor_enrich
actor_rc=$?

if [[ $actor_rc -ne 0 ]]; then
    die "Actor enrichment failed (exit code $actor_rc). Fix and re-run."
fi

status "Stage 3/3: Actor enrichment completed"

# ── Done ─────────────────────────────────────────────────────────────────────
status "Pipeline finished successfully. Log: $LOG_FILE"
