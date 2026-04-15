"""
resume_tasks.py
Resumes the ENHANCED Snowflake task chain,
monitors completion, then confirms both tasks suspended.
"""

import os
import sys
import time

import snowflake.connector


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERROR: Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def _get_task_state(cursor, task_name: str, schema: str) -> str:
    """Return the state string for a Snowflake task via SHOW TASKS."""
    cursor.execute(f"SHOW TASKS LIKE '{task_name}' IN SCHEMA {schema}")
    rows = cursor.fetchall()
    if not rows:
        print(f"ERROR: Task {schema}.{task_name} not found", file=sys.stderr)
        sys.exit(1)
    # SHOW TASKS returns columns; 'state' is typically at index position
    # Use description to find the column index for 'state'
    col_names = [desc[0].lower() for desc in cursor.description]
    state_idx = col_names.index("state")
    return rows[0][state_idx]


def resume_and_monitor():
    conn = snowflake.connector.connect(
        account=_require_env("SNOWFLAKE_ACCOUNT"),
        user=_require_env("SNOWFLAKE_USER"),
        password=_require_env("SNOWFLAKE_PASSWORD"),
        role=_require_env("SNOWFLAKE_ROLE"),
        warehouse=_require_env("SNOWFLAKE_WAREHOUSE"),
        database=_require_env("SNOWFLAKE_DATABASE"),
    )

    try:
        cursor = conn.cursor()

        # Resume in dependency order: child before parent
        print("Resuming ENHANCED.TASK_BUILD_ML_READY...")
        cursor.execute("ALTER TASK ENHANCED.TASK_BUILD_ML_READY RESUME")

        print("Resuming ENHANCED.TASK_ENRICH_POSTS...")
        cursor.execute("ALTER TASK ENHANCED.TASK_ENRICH_POSTS RESUME")

        print("Tasks resumed. Monitoring completion...")
        print("")

        poll_interval = 60
        while True:
            enhanced_state = _get_task_state(cursor, "TASK_ENRICH_POSTS", "ENHANCED")
            curated_state = _get_task_state(cursor, "TASK_BUILD_ML_READY", "ENHANCED")

            if enhanced_state == "suspended" and curated_state == "suspended":
                print("All tasks completed and suspended.")
                break

            print(
                f"Tasks still running "
                f"(ENHANCED.TASK_ENRICH_POSTS={enhanced_state}, "
                f"ENHANCED.TASK_BUILD_ML_READY={curated_state})"
                f"... checking again in {poll_interval}s"
            )
            time.sleep(poll_interval)

        # Validate row counts
        print("")
        cursor.execute("SELECT COUNT(*) FROM ENHANCED.POSTS_ENRICHED")
        enhanced_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM CURATED.ML_READY")
        curated_count = cursor.fetchone()[0]

        print(f"ENHANCED.POSTS_ENRICHED: {enhanced_count:,} rows")
        print(f"CURATED.ML_READY:       {curated_count:,} rows")

    finally:
        conn.close()


if __name__ == "__main__":
    resume_and_monitor()
