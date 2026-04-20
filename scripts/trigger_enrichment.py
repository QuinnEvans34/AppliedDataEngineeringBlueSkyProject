"""DEPRECATED: left in place for manual backfill runs.

Normal operation uses the triggered root task in
ENHANCED.TASK_FLATTEN_LABELS (stream-gated via
`WHEN SYSTEM$STREAM_HAS_DATA('RAW.STRM_LANDING_TREND_MATCHES')`). Python
does NOT need to call this during live ingestion — Snowflake fires the
task automatically whenever the Snowpipe-fed landing table produces
stream rows.

Run this standalone only when you need to kick the chain manually
against data that has already landed (e.g. re-processing after a task
suspend, or debugging):

    python scripts/trigger_enrichment.py
"""
from __future__ import annotations

import argparse
import os
import sys

REQUIRED_ENV = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
)

ROOT_TASK = "BLUESKYDATAENGINEERINGPROJECT.ENHANCED.TASK_FLATTEN_LABELS"


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()

    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        import snowflake.connector
    except ModuleNotFoundError:
        print("snowflake-connector-python is not installed", file=sys.stderr)
        return 1

    try:
        conn = snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
            database=os.environ["SNOWFLAKE_DATABASE"],
            autocommit=True,
        )
    except Exception as exc:
        print(f"Snowflake connect failed: {exc}", file=sys.stderr)
        return 1

    try:
        cur = conn.cursor()
        cur.execute(f"EXECUTE TASK {ROOT_TASK}")
        print(f"Triggered {ROOT_TASK} (query id {cur.sfqid})")
        cur.close()
    except Exception as exc:
        print(f"EXECUTE TASK failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
