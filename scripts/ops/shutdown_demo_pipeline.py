#!/usr/bin/env python3
"""Safely shut down the Snowflake demo pipeline in one command.

Default behavior is non-destructive:
- Connect with repo-standard SNOWFLAKE_* environment variables.
- Verify ENHANCED tasks exist.
- Suspend ENHANCED task chain.

Optional behavior:
- Show task states before/after suspension.
- Run full deep cleanup via sql/99_cleanup/02_truncate_raw_data.sql.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import snowflake.connector


REPO_ROOT = Path(__file__).resolve().parents[2]
RESET_SQL_FILE = "sql/99_cleanup/02_truncate_raw_data.sql"

REQUIRED_ENV = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
)

TARGET_TASKS = (
    "ENHANCED.TASK_ENRICH_POSTS",
    "ENHANCED.TASK_BUILD_ML_READY",
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


def _set_session_context(conn: snowflake.connector.SnowflakeConnection, creds: dict[str, str]) -> None:
    _exec(conn, f"USE ROLE {_quote_identifier(creds['SNOWFLAKE_ROLE'])}", action="Set role context")
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


def _split_task_name(task_fqn: str) -> tuple[str, str]:
    schema, task_name = task_fqn.split(".", 1)
    return schema, task_name


def _fetch_task_state(
    conn: snowflake.connector.SnowflakeConnection,
    *,
    task_fqn: str,
) -> str | None:
    schema, task_name = _split_task_name(task_fqn)
    with conn.cursor() as cur:
        cur.execute(f"SHOW TASKS LIKE '{task_name}' IN SCHEMA {schema}")
        rows = cur.fetchall()
        if not rows:
            return None
        columns = [desc[0].lower() for desc in cur.description]
        state_index = columns.index("state")
        return str(rows[0][state_index])


def _require_tasks_exist(conn: snowflake.connector.SnowflakeConnection) -> None:
    missing: list[str] = []
    for task in TARGET_TASKS:
        if _fetch_task_state(conn, task_fqn=task) is None:
            missing.append(task)
    if missing:
        raise RuntimeError(
            "Required task(s) not found: "
            + ", ".join(missing)
            + ". Deploy tasks with sql/05_tasks/00_tasks.sql first."
        )


def _print_task_states(conn: snowflake.connector.SnowflakeConnection, *, header: str) -> None:
    print(header)
    for task in TARGET_TASKS:
        state = _fetch_task_state(conn, task_fqn=task)
        if state is None:
            raise RuntimeError(f"Task missing while reading state: {task}")
        print(f"  - {task}: {state}")


def _suspend_tasks(conn: snowflake.connector.SnowflakeConnection) -> list[str]:
    suspended: list[str] = []
    for task in TARGET_TASKS:
        _exec(conn, f"ALTER TASK {task} SUSPEND", action="Suspend task")
        suspended.append(task)
    return suspended


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely shut down Snowflake demo pipeline tasks")
    parser.add_argument(
        "--show-task-state",
        action="store_true",
        help="Print task state before and after suspension.",
    )
    parser.add_argument(
        "--deep-cleanup",
        action="store_true",
        help="Run sql/99_cleanup/02_truncate_raw_data.sql after tasks are suspended (destructive).",
    )
    parser.add_argument(
        "--confirm-deep-cleanup",
        action="store_true",
        help="Required confirmation flag when using --deep-cleanup.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.deep_cleanup and not args.confirm_deep_cleanup:
        print(
            "ERROR: --deep-cleanup requires --confirm-deep-cleanup because it truncates data "
            "and removes stage files.",
            file=sys.stderr,
        )
        return 1

    print("=" * 72)
    print("Shutdown Demo Pipeline (Snowflake)")
    print("=" * 72)
    print(f"  Repo root: {REPO_ROOT}")
    print(f"  Show task state: {args.show_task_state}")
    print(f"  Deep cleanup requested: {args.deep_cleanup}")

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

    suspended_tasks: list[str] = []
    cleanup_applied = False

    try:
        print("\n[1/4] Applying explicit Snowflake session context...")
        _set_session_context(conn, creds)
        _print_context(conn)

        print("\n[2/4] Validating target tasks exist...")
        _require_tasks_exist(conn)
        print("  All target tasks exist.")

        if args.show_task_state:
            _print_task_states(conn, header="\n[3/4] Task states before suspension:")
        else:
            print("\n[3/4] Suspending target tasks...")

        suspended_tasks = _suspend_tasks(conn)
        print("  Suspended tasks:")
        for task in suspended_tasks:
            print(f"  - {task}")

        if args.show_task_state:
            _print_task_states(conn, header="\n[4/4] Task states after suspension:")
        else:
            print("\n[4/4] Task suspension complete.")

        if args.deep_cleanup:
            print("\nDeep cleanup enabled: applying reset SQL...")
            _exec_sql_file(conn, RESET_SQL_FILE)
            cleanup_applied = True

        print("\nShutdown complete.")
        print("-" * 72)
        print("Summary")
        print("- Tasks suspended:")
        for task in suspended_tasks:
            print(f"  - {task}")
        print(f"- Deep cleanup applied: {'yes' if cleanup_applied else 'no'}")
        if cleanup_applied:
            print(f"- Cleanup SQL applied: {RESET_SQL_FILE}")
            print("- Reload required before next demo run:")
            print("  - RAW.LANDING_RAW_POSTS")
            print("  - RAW.LANDING_ACTOR_PROFILES")
            print("  - RAW.LANDING_HYDRATED_POSTS (if used)")
            print("  - RAW.LANDING_TWITTER_TRENDS")
            print("  - RAW.LANDING_TREND_MATCHES")
        else:
            print("- Data was not deleted (non-destructive shutdown).")

        return 0
    except Exception as exc:
        print(f"ERROR: Shutdown failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
