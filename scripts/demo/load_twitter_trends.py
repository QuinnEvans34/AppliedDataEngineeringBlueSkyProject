"""
load_twitter_trends.py
Converts the local Twitter trends Parquet snapshot to gzip JSONL
and loads it into RAW.LANDING_TWITTER_TRENDS via Snowpipe.

Usage:
    python scripts/demo/load_twitter_trends.py
"""

from __future__ import annotations

import gzip
import json
import math
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from src.nlp.trend_normalization import normalize_trend_name

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PARQUET_FILENAME = "twitter_trending_normalized.parquet"

SEARCH_DIRS = [
    Path("local/reference_snapshots/twitter_trending"),
    Path("data/samples"),
    Path("data"),
]

OUTPUT_DIR = Path("data/twitter_trends/full")
OUTPUT_FILENAME = "twitter_trends_000001.jsonl.gz"

STAGE = "@RAW.BLUESKY_TWITTER_TRENDS_STAGE"
STAGE_PATH = f"{STAGE}/full/twitter_trends/load"
PIPE = "RAW.BLUESKY_TWITTER_TRENDS_PIPE"
LANDING_TABLE = "RAW.LANDING_TWITTER_TRENDS"

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


def _find_parquet() -> Path:
    """Search common locations for the normalized Parquet file."""
    for directory in SEARCH_DIRS:
        candidate = directory / PARQUET_FILENAME
        if candidate.exists():
            return candidate

    print(f"\n  ❌ Could not find {PARQUET_FILENAME}")
    print("  Searched in:")
    for d in SEARCH_DIRS:
        print(f"    - {d}/")
    print("\n  Please place the file in one of the above directories.")
    sys.exit(1)


def _write_jsonl_gz(path: Path, rows: list[dict]) -> int:
    """Write rows as gzipped JSONL. Returns row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False))
            fh.write("\n")
    return len(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 60)
    print("  TWITTER TRENDS — PARQUET → SNOWPIPE LOADER")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Find the Parquet file
    # ------------------------------------------------------------------
    parquet_path = _find_parquet()
    print(f"\n[1/6] Found Parquet file: {parquet_path}")

    # ------------------------------------------------------------------
    # Step 2: Read with pandas
    # ------------------------------------------------------------------
    try:
        import pandas as pd
    except ModuleNotFoundError:
        print("\n  ❌ Missing dependency: pandas")
        print("  Install with: pip install pandas pyarrow")
        sys.exit(1)

    df = pd.read_parquet(parquet_path)
    print(f"[2/6] Loaded {len(df):,} rows from Parquet")
    print(f"      Columns: {list(df.columns)}")

    # ------------------------------------------------------------------
    # Step 3: Transform to output schema
    # ------------------------------------------------------------------
    print("[3/6] Transforming to output JSONL schema...")

    rows: list[dict] = []
    for _, record in df.iterrows():
        name_raw = str(record["name"]) if record["name"] is not None else ""
        normalized_name = normalize_trend_name(name_raw)
        trend_name = normalized_name["trend_name_clean_no_hash"]
        trend_key_no_hash = normalized_name["normalized_key_no_hash"] or trend_name
        counts = record["counts"]

        if counts is not None and not (isinstance(counts, float) and math.isnan(counts)):
            tweet_volume = int(counts)
        else:
            tweet_volume = 0

        rows.append({
            "trend_name": trend_name,
            "trend_name_raw": name_raw,
            "trend_key_no_hash": trend_key_no_hash,
            "trend_date": str(record["date"]),
            "tweet_volume": tweet_volume,
            "num_hours": int(record["num_hours"]),
            "rank": None,
        })

    print(f"      ✅ Transformed {len(rows):,} rows")

    # ------------------------------------------------------------------
    # Step 4: Write gzip JSONL
    # ------------------------------------------------------------------
    output_path = OUTPUT_DIR / OUTPUT_FILENAME
    written = _write_jsonl_gz(output_path, rows)
    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"[4/6] Wrote {written:,} rows to {output_path} ({file_size_mb:.1f} MB)")

    # ------------------------------------------------------------------
    # Step 5: Connect to Snowflake and load
    # ------------------------------------------------------------------
    try:
        import snowflake.connector
    except ModuleNotFoundError:
        print("\n  ❌ Missing dependency: snowflake-connector-python")
        print("  Install with: pip install snowflake-connector-python")
        sys.exit(1)

    creds = _validate_env()

    print("[5/6] Loading to Snowflake...")

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
        # Remove any existing files from the stage path
        print("      Removing existing files from stage...", end="", flush=True)
        cur.execute(f"REMOVE {STAGE_PATH}/")
        print(" ✅")

        # PUT the file to the stage
        abs_path = output_path.resolve()
        print("      Uploading to stage...", end="", flush=True)
        cur.execute(
            f"PUT 'file://{abs_path}' {STAGE_PATH} "
            f"AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
        )
        print(" ✅")

        # Refresh the pipe
        print(f"      Refreshing pipe {PIPE}...", end="", flush=True)
        cur.execute(f"ALTER PIPE {PIPE} REFRESH")
        print(" ✅")

    except Exception as e:
        print(f"\n  ❌ Snowflake load failed: {e}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

    # ------------------------------------------------------------------
    # Step 6: Wait and confirm
    # ------------------------------------------------------------------
    print("\n[6/6] Waiting 60 seconds for Snowpipe to ingest...")
    time.sleep(60)

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
        cur = conn.cursor()

        # Row count
        cur.execute(f"SELECT COUNT(*) FROM {LANDING_TABLE}")
        row_count = cur.fetchone()[0]

        print(f"\n      Row count in {LANDING_TABLE}: {row_count:,}")
        print(f"      Expected: ~101,731")

        # Sample 3 rows
        cur.execute(
            f"SELECT "
            f"  raw_payload:trend_name::STRING AS trend_name, "
            f"  raw_payload:trend_name_raw::STRING AS trend_name_raw, "
            f"  raw_payload:trend_date::DATE AS trend_date, "
            f"  raw_payload:tweet_volume::NUMBER AS tweet_volume, "
            f"  raw_payload:num_hours::NUMBER AS num_hours "
            f"FROM {LANDING_TABLE} "
            f"LIMIT 3"
        )
        sample_rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]

        print("\n      Sample rows:")
        print(f"      {col_names}")
        for row in sample_rows:
            print(f"      {list(row)}")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"\n  ❌ Verification query failed: {e}")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  TWITTER TRENDS LOAD COMPLETE")
    print("=" * 60)
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
