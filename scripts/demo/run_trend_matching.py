"""
Bluesky Pipeline — Run NLP Trend Matching on Demo Posts + Load to Snowflake

Reads the 25 demo posts captured by demo_load.py, runs the full 3-stage
NLP matching pipeline (exact → TF-IDF fuzzy → FAISS semantic) against
Twitter trends, and loads the match results into RAW.LANDING_TREND_MATCHES
via Snowpipe.

PRE-RUN CHECKLIST:
  [ ] Virtual environment activated
  [ ] demo_load.py has been run (25 posts in data/demo/raw_posts/)
  [ ] Twitter trends parquet exists at local/reference_snapshots/twitter_trending/
  [ ] Snowflake credentials in environment or .env
  [ ] RAW.BLUESKY_TREND_MATCHES_STAGE exists
  [ ] RAW.BLUESKY_TREND_MATCHES_PIPE exists
  [ ] RAW.LANDING_TREND_MATCHES table exists
  Run: python scripts/demo/run_trend_matching.py
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is importable so `from src.nlp...` works
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POST_FILE = Path("data/demo/raw_posts/demo_raw_posts.jsonl.gz")
TRENDS_FILE = Path(
    "local/reference_snapshots/twitter_trending/twitter_trending_normalized.parquet"
)

STAGE = "RAW.BLUESKY_TREND_MATCHES_STAGE"
PIPE = "RAW.BLUESKY_TREND_MATCHES_PIPE"
LANDING_TABLE = "RAW.LANDING_TREND_MATCHES"
SOURCE_RUN_TAG = "demo_run"

SNOWFLAKE_ENV_VARS = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_env() -> dict[str, str]:
    """Check that all required Snowflake env vars are set."""
    creds: dict[str, str] = {}
    missing: list[str] = []
    for var in SNOWFLAKE_ENV_VARS:
        val = os.environ.get(var)
        if not val:
            missing.append(var)
        else:
            creds[var] = val
    if missing:
        print(f"\n  ❌ Missing environment variables: {', '.join(missing)}")
        print("  Set them in your shell or .env file before running.")
        sys.exit(1)
    return creds


# ---------------------------------------------------------------------------
# Step 1: Load Demo Posts
# ---------------------------------------------------------------------------


def _load_demo_posts() -> list[dict]:
    """Load the 25 demo posts from gzipped JSONL."""
    print(f"Loading demo posts from {POST_FILE}")

    if not POST_FILE.exists():
        print(f"\n  ❌ Post file not found: {POST_FILE}")
        print("  Run demo_load.py first to capture posts.")
        sys.exit(1)

    posts: list[dict] = []
    with gzip.open(POST_FILE, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                posts.append(json.loads(line))

    print(f"Loaded {len(posts)} demo posts")
    return posts


# ---------------------------------------------------------------------------
# Step 2: Load Twitter Trends
# ---------------------------------------------------------------------------


def _load_trends() -> pd.DataFrame:
    """Load Twitter trends from normalized parquet."""
    print("Loading Twitter trends from parquet...")

    if not TRENDS_FILE.exists():
        print(f"\n  ❌ Trends file not found: {TRENDS_FILE}")
        print("  Ensure twitter_trending_normalized.parquet is present.")
        sys.exit(1)

    trends_df = pd.read_parquet(TRENDS_FILE)
    print(f"Loaded {len(trends_df):,} trends")
    return trends_df


# ---------------------------------------------------------------------------
# Step 3: Run NLP Pipeline
# ---------------------------------------------------------------------------


def _run_nlp_pipeline(
    posts: list[dict],
    trends_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Run the full normalization → candidate generation → trend matching pipeline."""

    from src.nlp.post_normalization import prepare_bluesky_posts
    from src.nlp.topic_candidate_generation import generate_topic_candidates_dataframe
    from src.nlp.post_trend_matching import match_post_candidates_to_trends

    # Text normalization: prepare posts into a clean DataFrame
    print("Running text normalization...")
    prepared_df = prepare_bluesky_posts(
        raw_rows=posts,
        hydrated_rows=[],
        source_run_tag=SOURCE_RUN_TAG,
    )
    print(f"  {len(prepared_df)} prepared post rows")

    # Topic candidate generation: extract candidate phrases from each post
    print("Generating topic candidates...")
    candidates_df = generate_topic_candidates_dataframe(prepared_df)
    print(f"  {len(candidates_df)} candidate phrases extracted")

    # Trend matching — this is the expensive step
    # Builds TF-IDF index + FAISS index over all trends (takes ~2-5 min first run)
    print("Building TF-IDF index over trends... (this takes ~1 min)")
    print("Building FAISS index over trends... (this takes ~2-5 min)")
    print("Running 3-stage trend matching...")

    full_matches_df, best_matches_df, summary = match_post_candidates_to_trends(
        candidates_df=candidates_df,
        trends_df=trends_df,
    )

    matched_count = int(best_matches_df["is_matched"].sum())
    unmatched_count = len(best_matches_df) - matched_count
    print(
        f"Matching complete: {matched_count} matched, "
        f"{unmatched_count} unmatched out of {len(best_matches_df)} posts"
    )

    return full_matches_df, best_matches_df, summary


# ---------------------------------------------------------------------------
# Step 4 + 5: Load Match Results to Snowflake
# ---------------------------------------------------------------------------


def _load_to_snowflake(summary: dict) -> None:
    """PUT written match files to Snowflake stage and refresh pipe."""

    try:
        import snowflake.connector
    except ModuleNotFoundError:
        print("\n  ❌ Missing dependency: snowflake-connector-python")
        print("  Install with: pip install snowflake-connector-python")
        sys.exit(1)

    written_files = summary.get("trend_match_files_written", [])
    run_id = summary.get("trend_match_run_id", "unknown")

    if not written_files:
        print("No match files were written — nothing to load.")
        return

    file_paths = [Path(p) for p in written_files]

    print("Writing match results...")
    print(f"Written {len(file_paths)} file(s) for run {run_id}")

    print("Loading to Snowflake...")
    creds = _validate_env()

    try:
        conn = snowflake.connector.connect(
            account=creds["SNOWFLAKE_ACCOUNT"],
            user=creds["SNOWFLAKE_USER"],
            password=creds["SNOWFLAKE_PASSWORD"],
            role=creds["SNOWFLAKE_ROLE"],
            warehouse=creds["SNOWFLAKE_WAREHOUSE"],
            database=creds["SNOWFLAKE_DATABASE"],
            schema=creds["SNOWFLAKE_SCHEMA"],
            autocommit=True,
        )
    except Exception as e:
        print(f"\n  ❌ Snowflake connection failed: {e}")
        print("  Check your credentials and network.")
        sys.exit(1)

    cur = conn.cursor()

    try:
        for file_path in file_paths:
            stage_path = (
                f"@{STAGE}/{SOURCE_RUN_TAG}/trend_matches/{run_id}/"
            )
            cur.execute(
                f"PUT 'file://{file_path.resolve()}' {stage_path} "
                f"AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
            )
            print(f"PUT {file_path.name} → {stage_path}")

        cur.execute(f"ALTER PIPE {PIPE} REFRESH")
        print("Pipe refreshed — trend matches will load in ~60 seconds")

        print("Waiting 60 seconds for Snowpipe to ingest...")
        time.sleep(60)

        cur.execute(f"SELECT COUNT(*) FROM {LANDING_TABLE}")
        count = cur.fetchone()[0]
        print(f"{LANDING_TABLE}: {count} rows")

    except Exception as e:
        print(f"\n  ❌ Snowflake load failed: {e}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 60)
    print("  BLUESKY PIPELINE — NLP TREND MATCHING")
    print("=" * 60)

    # Step 1: Load demo posts
    posts = _load_demo_posts()

    # Step 2: Load Twitter trends
    trends_df = _load_trends()

    # Step 3: Run NLP pipeline (normalization → candidates → matching)
    # The matching function internally writes results via TrendMatchWriter
    full_matches_df, best_matches_df, summary = _run_nlp_pipeline(posts, trends_df)

    # Steps 4+5: Load written match files to Snowflake
    _load_to_snowflake(summary)

    print("\nDone.")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
