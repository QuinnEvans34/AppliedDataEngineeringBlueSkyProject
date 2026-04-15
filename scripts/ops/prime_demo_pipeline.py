#!/usr/bin/env python3
"""Prime Snowflake objects for the demo pipeline in one command."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import snowflake.connector


REPO_ROOT = Path(__file__).resolve().parents[2]

SQL_BOOTSTRAP_SEQUENCE = [
    "sql/00_setup/00_bootstrap_database_schema.sql",
    "sql/00_setup/00_file_formats.sql",
    "sql/00_setup/01_internal_stages.sql",
    "sql/01_landing/00_landing_raw_posts.sql",
    "sql/01_landing/01_landing_hydrated_posts.sql",
    "sql/01_landing/02_landing_hydration_misses.sql",
    "sql/01_landing/03_landing_actor_profiles.sql",
    "sql/01_landing/04_landing_twitter_trends.sql",
    "sql/01_landing/05_landing_trend_matches.sql",
    "sql/00_setup/02_pipes.sql",
    "sql/02_streams/00_streams.sql",
    "sql/03_enhanced/00_posts_enriched_table.sql",
    "sql/04_curated/00_ml_ready_table.sql",
    "sql/00_setup/03_udfs.sql",
]

TASK_SQL_FILE = "sql/05_tasks/00_tasks.sql"
RESET_SQL_FILE = "sql/99_cleanup/02_truncate_raw_data.sql"

TASKS_RESUME_ORDER = (
    "ENHANCED.TASK_BUILD_ML_READY",
    "ENHANCED.TASK_ENRICH_POSTS",
)
TASKS_SUSPEND_ORDER = (
    "ENHANCED.TASK_BUILD_ML_READY",
    "ENHANCED.TASK_ENRICH_POSTS",
)
TASKS_SUMMARY_ORDER = (
    "ENHANCED.TASK_ENRICH_POSTS",
    "ENHANCED.TASK_BUILD_ML_READY",
)

PIPES = (
    "RAW.BLUESKY_RAW_POSTS_PIPE",
    "RAW.BLUESKY_HYDRATED_POSTS_PIPE",
    "RAW.BLUESKY_HYDRATION_MISSES_PIPE",
    "RAW.BLUESKY_ACTOR_PROFILES_PIPE",
    "RAW.BLUESKY_TWITTER_TRENDS_PIPE",
    "RAW.BLUESKY_TREND_MATCHES_PIPE",
)

REQUIRED_ENV = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
)

DATASETS_TO_LOAD = (
    "RAW.LANDING_RAW_POSTS",
    "RAW.LANDING_ACTOR_PROFILES",
    "RAW.LANDING_HYDRATED_POSTS",
    "RAW.LANDING_TWITTER_TRENDS",
    "RAW.LANDING_TREND_MATCHES",
)


def _require_env() -> dict[str, str]:
    load_dotenv(REPO_ROOT / ".env")
    values: dict[str, str] = {}
    missing: list[str] = []
    for key in REQUIRED_ENV:
        val = os.getenv(key, "").strip()
        if not val:
            missing.append(key)
        else:
            values[key] = val
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    return values


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _connect(creds: dict[str, str]) -> snowflake.connector.SnowflakeConnection:
    return snowflake.connector.connect(
        account=creds["SNOWFLAKE_ACCOUNT"],
        user=creds["SNOWFLAKE_USER"],
        password=creds["SNOWFLAKE_PASSWORD"],
        role=creds["SNOWFLAKE_ROLE"],
        warehouse=creds["SNOWFLAKE_WAREHOUSE"],
        database=creds["SNOWFLAKE_DATABASE"],
        schema=creds["SNOWFLAKE_SCHEMA"],
        autocommit=True,
    )


def _exec(conn: snowflake.connector.SnowflakeConnection, sql: str, *, action: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"{action} failed for SQL [{sql}]: {exc}") from exc


def _exec_sql_file(conn: snowflake.connector.SnowflakeConnection, relative_path: str) -> None:
    file_path = REPO_ROOT / relative_path
    if not file_path.exists():
        raise FileNotFoundError(f"SQL file not found: {file_path}")

    sql_text = file_path.read_text(encoding="utf-8")
    try:
        count = 0
        for _ in conn.execute_stream(io.StringIO(sql_text), remove_comments=True):
            count += 1
        print(f"  Applied {relative_path} ({count} statements)")
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"SQL apply failed for file [{relative_path}]: {exc}") from exc


def _set_task_state(conn: snowflake.connector.SnowflakeConnection, *, suspended: bool) -> None:
    action = "SUSPEND" if suspended else "RESUME"
    tasks = TASKS_SUSPEND_ORDER if suspended else TASKS_RESUME_ORDER
    for task in tasks:
        _exec(conn, f"ALTER TASK IF EXISTS {task} {action}", action=f"Task {action.lower()}")
    state = "suspended" if suspended else "resumed"
    print(f"  Tasks {state}: {', '.join(tasks)}")


def _set_pipe_state(conn: snowflake.connector.SnowflakeConnection, *, paused: bool) -> None:
    target = "TRUE" if paused else "FALSE"
    for pipe in PIPES:
        _exec(
            conn,
            f"ALTER PIPE IF EXISTS {pipe} SET PIPE_EXECUTION_PAUSED = {target}",
            action="Pipe pause alignment",
        )
    state = "paused" if paused else "unpaused"
    print(f"  Pipes {state}: {', '.join(PIPES)}")


def _set_session_context(conn: snowflake.connector.SnowflakeConnection, creds: dict[str, str]) -> None:
    _exec(
        conn,
        f"USE ROLE {_quote_identifier(creds['SNOWFLAKE_ROLE'])}",
        action="Set role context",
    )
    _exec(
        conn,
        f"USE WAREHOUSE {_quote_identifier(creds['SNOWFLAKE_WAREHOUSE'])}",
        action="Set warehouse context",
    )
    _exec(
        conn,
        f"USE DATABASE {_quote_identifier(creds['SNOWFLAKE_DATABASE'])}",
        action="Set database context",
    )
    _exec(
        conn,
        f"USE SCHEMA {_quote_identifier(creds['SNOWFLAKE_SCHEMA'])}",
        action="Set schema context",
    )


def _print_context(conn: snowflake.connector.SnowflakeConnection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
        db, schema, role, wh = cur.fetchone()
    print(f"  Context: database={db}, schema={schema}, role={role}, warehouse={wh}")


def _get_pipe_status(conn: snowflake.connector.SnowflakeConnection, pipe: str) -> str:
    with conn.cursor() as cur:
        cur.execute(f"SELECT SYSTEM$PIPE_STATUS('{pipe}')")
        row = cur.fetchone()
        if not row:
            return "UNKNOWN"
        payload = str(row[0] or "")
    try:
        parsed = json.loads(payload)
        execution_state = parsed.get("executionState", "UNKNOWN")
        pending_count = parsed.get("pendingFileCount", "n/a")
        return f"executionState={execution_state}, pendingFileCount={pending_count}"
    except json.JSONDecodeError:
        return payload


def _validate_and_refresh_pipes(conn: snowflake.connector.SnowflakeConnection, *, skip_refresh: bool) -> None:
    print("  Pipe status check:")
    for pipe in PIPES:
        status = _get_pipe_status(conn, pipe)
        print(f"    {pipe}: {status}")
        if not skip_refresh:
            _exec(conn, f"ALTER PIPE IF EXISTS {pipe} REFRESH", action="Pipe refresh")
    if skip_refresh:
        print("  Pipe refresh skipped by flag.")
    else:
        print("  Pipe refresh issued for all RAW pipes.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prime Snowflake demo pipeline objects")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Run full truncate/reset script after suspending tasks.",
    )
    parser.add_argument(
        "--leave-tasks-suspended",
        action="store_true",
        help="Do not resume tasks at the end.",
    )
    parser.add_argument(
        "--leave-pipes-paused",
        action="store_true",
        help="Leave Snowpipes paused at the end (skip default unpause + validation refresh flow).",
    )
    parser.add_argument(
        "--skip-pipe-refresh",
        action="store_true",
        help="Validate pipe status but skip ALTER PIPE ... REFRESH calls.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    print("=" * 72)
    print("Prime Demo Pipeline (Snowflake)")
    print("=" * 72)
    print(f"  Repo root: {REPO_ROOT}")
    print(f"  Reset requested: {args.reset}")
    print(f"  Leave tasks suspended: {args.leave_tasks_suspended}")
    print(f"  Leave pipes paused: {args.leave_pipes_paused}")
    print(f"  Skip pipe refresh: {args.skip_pipe_refresh}")

    try:
        creds = _require_env()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        conn = _connect(creds)
    except Exception as exc:
        print(f"ERROR: Snowflake connection failed: {exc}", file=sys.stderr)
        return 1

    applied_sql_files: list[str] = []
    tasks_resumed: list[str] = []

    try:
        print("\n[1/7] Applying explicit Snowflake session context...")
        _set_session_context(conn, creds)
        _print_context(conn)

        print("\n[2/7] Applying base SQL objects in order...")
        for path in SQL_BOOTSTRAP_SEQUENCE:
            _exec_sql_file(conn, path)
            applied_sql_files.append(path)

        if args.reset:
            print("\n[3/7] Reset requested: suspending tasks before destructive reset...")
            _set_task_state(conn, suspended=True)
            _exec_sql_file(conn, RESET_SQL_FILE)
            applied_sql_files.append(RESET_SQL_FILE)
        else:
            print("\n[3/7] Reset not requested; skipping truncate/reset.")

        print("\n[4/7] Applying repaired ENHANCED/CURATED task definitions...")
        _exec_sql_file(conn, TASK_SQL_FILE)
        applied_sql_files.append(TASK_SQL_FILE)

        print("\n[5/7] Aligning pipe execution state...")
        if args.leave_pipes_paused:
            _set_pipe_state(conn, paused=True)
        else:
            _set_pipe_state(conn, paused=False)

        print("\n[6/7] Validating and refreshing pipes...")
        if args.leave_pipes_paused:
            print("  Pipes intentionally left paused; skipping status/refresh checks.")
        else:
            _validate_and_refresh_pipes(conn, skip_refresh=args.skip_pipe_refresh)

        print("\n[7/7] Final task state...")
        if args.leave_tasks_suspended:
            _set_task_state(conn, suspended=True)
        else:
            _set_task_state(conn, suspended=False)
            tasks_resumed.extend(TASKS_SUMMARY_ORDER)

        print("\nPrime complete.")
        print("-" * 72)
        print("Summary")
        print("- SQL files applied (in order):")
        for path in applied_sql_files:
            print(f"  - {path}")

        if tasks_resumed:
            print("- Tasks resumed:")
            for task in tasks_resumed:
                print(f"  - {task}")
        else:
            print("- Tasks resumed: none (left suspended by flag)")

        print("- Datasets still needing load:")
        for dataset in DATASETS_TO_LOAD:
            print(f"  - {dataset}")

        return 0
    except Exception as exc:
        print(f"ERROR: Prime failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
