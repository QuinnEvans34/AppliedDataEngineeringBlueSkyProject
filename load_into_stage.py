#!/usr/bin/env python3
"""Upload local .jsonl.gz test files into Snowflake internal stages.

What it does:
1. Connects to Snowflake using env vars.
2. PUTs your local .jsonl.gz files into the matching internal stages.
3. Lists each stage after upload.
4. Optionally runs ALTER PIPE ... REFRESH if you pass pipe names.

Required env vars:
- SNOWFLAKE_ACCOUNT
- SNOWFLAKE_USER
- SNOWFLAKE_WAREHOUSE

One of:
- SNOWFLAKE_PASSWORD
- SNOWFLAKE_AUTHENTICATOR=externalbrowser

Optional env vars:
- SNOWFLAKE_ROLE
- SNOWFLAKE_DATABASE   (defaults to BLUESKYDATAENGINEERINGPROJECT)
- SNOWFLAKE_SCHEMA     (defaults to PUBLIC)
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import snowflake.connector
    from snowflake.connector.errors import Error as SnowflakeError
except Exception:  # pragma: no cover - import handling for dry-run usability
    snowflake = None  # type: ignore[assignment]
    SnowflakeError = Exception  # type: ignore[assignment,misc]


DEFAULT_DATABASE = os.getenv("SNOWFLAKE_DATABASE", "BLUESKYDATAENGINEERINGPROJECT")
DEFAULT_SCHEMA = os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")

DEFAULT_PIPE_NAMES = {
    "raw_posts": "BLUESKY_RAW_POSTS_PIPE",
    "hydrated_posts": "BLUESKY_HYDRATED_POSTS_PIPE",
    "hydration_misses": "BLUESKY_HYDRATION_MISSES_PIPE",
    "actor_profiles": "BLUESKY_ACTOR_PROFILES_PIPE",
}


@dataclass
class UploadTarget:
    family: str
    local_file: Path
    stage: str
    pipe: str | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload local .jsonl.gz files into Snowflake internal stages."
    )

    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"Snowflake database name (default: {DEFAULT_DATABASE})",
    )
    parser.add_argument(
        "--schema",
        default=DEFAULT_SCHEMA,
        help=f"Snowflake schema name (default: {DEFAULT_SCHEMA})",
    )
    parser.add_argument(
        "--run-id",
        default="top25_manual",
        help="Run identifier used in stage destination prefix (default: top25_manual).",
    )

    parser.add_argument(
        "--raw-posts-file",
        type=Path,
        default=Path(
            "/Users/quintonevans/Desktop/Neumont/DataEngineeringProjectClass/"
            "AppliedDataEngineeringBlueSkyProject/data/test_data/raw_posts/"
            "raw_posts_top25.jsonl.gz"
        ),
    )
    parser.add_argument(
        "--hydrated-posts-file",
        type=Path,
        default=Path(
            "/Users/quintonevans/Desktop/Neumont/DataEngineeringProjectClass/"
            "AppliedDataEngineeringBlueSkyProject/data/test_data/raw_interactions/"
            "hydrated_posts_top25.jsonl.gz"
        ),
    )
    parser.add_argument(
        "--actor-profiles-file",
        type=Path,
        default=Path(
            "/Users/quintonevans/Desktop/Neumont/DataEngineeringProjectClass/"
            "AppliedDataEngineeringBlueSkyProject/data/test_data/raw_profiles/"
            "actor_profiles_top25.jsonl.gz"
        ),
    )
    parser.add_argument(
        "--hydration-misses-file",
        type=Path,
        default=None,
        help=(
            "Optional local hydration_misses .jsonl.gz file. "
            "If omitted, hydration_misses upload/refresh is skipped."
        ),
    )

    parser.add_argument(
        "--raw-posts-stage",
        default="BLUESKY_RAW_POSTS_STAGE",
    )
    parser.add_argument(
        "--hydrated-posts-stage",
        default="BLUESKY_HYDRATED_POSTS_STAGE",
    )
    parser.add_argument(
        "--actor-profiles-stage",
        default="BLUESKY_ACTOR_PROFILES_STAGE",
    )
    parser.add_argument(
        "--hydration-misses-stage",
        default="BLUESKY_HYDRATION_MISSES_STAGE",
    )

    parser.add_argument(
        "--raw-posts-pipe",
        default=os.getenv("RAW_POSTS_PIPE") or DEFAULT_PIPE_NAMES["raw_posts"],
        help="Optional pipe name for raw posts. Example: BLUESKY_RAW_POSTS_PIPE",
    )
    parser.add_argument(
        "--hydrated-posts-pipe",
        default=os.getenv("HYDRATED_POSTS_PIPE") or DEFAULT_PIPE_NAMES["hydrated_posts"],
        help="Optional pipe name for hydrated posts.",
    )
    parser.add_argument(
        "--actor-profiles-pipe",
        default=os.getenv("ACTOR_PROFILES_PIPE") or DEFAULT_PIPE_NAMES["actor_profiles"],
        help="Optional pipe name for actor profiles.",
    )
    parser.add_argument(
        "--hydration-misses-pipe",
        default=os.getenv("HYDRATION_MISSES_PIPE") or DEFAULT_PIPE_NAMES["hydration_misses"],
        help="Optional pipe name for hydration misses.",
    )

    parser.add_argument(
        "--refresh-pipes",
        action="store_true",
        help="After PUT, run ALTER PIPE ... REFRESH for any provided pipes.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite files already in the stage.",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=4,
        help="PUT parallel thread count (default: 4).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without executing them.",
    )

    return parser


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def build_connection_kwargs(database: str, schema: str) -> dict:
    missing_required = [
        name
        for name in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")
        if not os.getenv(name)
    ]
    if missing_required:
        joined = ", ".join(missing_required)
        raise RuntimeError(f"Missing required environment variables: {joined}")

    kwargs = {
        "account": required_env("SNOWFLAKE_ACCOUNT"),
        "user": required_env("SNOWFLAKE_USER"),
        "warehouse": required_env("SNOWFLAKE_WAREHOUSE"),
        "database": database,
        "schema": schema,
    }

    role = os.getenv("SNOWFLAKE_ROLE")
    if role:
        kwargs["role"] = role

    authenticator = os.getenv("SNOWFLAKE_AUTHENTICATOR")
    password = os.getenv("SNOWFLAKE_PASSWORD")

    if authenticator:
        kwargs["authenticator"] = authenticator

    if password:
        kwargs["password"] = password

    if not authenticator and not password:
        raise RuntimeError(
            "Set either SNOWFLAKE_PASSWORD or SNOWFLAKE_AUTHENTICATOR=externalbrowser"
        )

    return kwargs


def sql_quote_string(value: str) -> str:
    return value.replace("'", "''")


def qualify_name(database: str, schema: str, object_name: str) -> str:
    if "." in object_name:
        return object_name
    return f"{database}.{schema}.{object_name}"


def execute_and_print(cursor, sql: str):
    print(f"\nSQL> {sql}")
    cursor.execute(sql)
    try:
        rows = cursor.fetchall()
    except Exception:
        rows = []

    if rows:
        for row in rows:
            print(row)


def _execute_and_collect(cursor, sql: str) -> list[tuple]:
    print(f"\nSQL> {sql}")
    cursor.execute(sql)
    try:
        return list(cursor.fetchall())
    except Exception:
        return []


def build_stage_prefix(*, family: str, run_id: str) -> str:
    return f"{family}/{run_id}"


def put_file(
    *,
    cursor,
    database: str,
    schema: str,
    target: UploadTarget,
    overwrite: bool,
    parallel: int,
    run_id: str,
):
    file_path = target.local_file.resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"[{target.family}] local file not found: {file_path}")
    if not file_path.is_file():
        raise FileNotFoundError(f"[{target.family}] path is not a file: {file_path}")

    stage_name = qualify_name(database, schema, target.stage)
    stage_prefix = build_stage_prefix(family=target.family, run_id=run_id)
    stage_destination = f"@{stage_name}/{stage_prefix}"
    file_uri = f"file://{file_path.as_posix()}"
    overwrite_sql = "TRUE" if overwrite else "FALSE"

    sql = (
        f"PUT '{sql_quote_string(file_uri)}' "
        f"{stage_destination} "
        f"AUTO_COMPRESS=FALSE "
        f"OVERWRITE={overwrite_sql} "
        f"PARALLEL={parallel}"
    )
    put_rows = _execute_and_collect(cursor, sql)
    if put_rows:
        print(f"PUT result rows: {len(put_rows)}")
        for row in put_rows[:5]:
            print(row)
    expected_stage_object = f"{stage_prefix}/{file_path.name}"
    return file_path.name, stage_prefix, expected_stage_object


def list_stage_for_uploaded_file(
    *,
    cursor,
    database: str,
    schema: str,
    stage: str,
    uploaded_filename: str,
    stage_prefix: str,
    expected_stage_object: str,
):
    stage_name = qualify_name(database, schema, stage)
    sql = f"LIST @{stage_name}/{stage_prefix}"
    rows = _execute_and_collect(cursor, sql)
    if not rows:
        raise RuntimeError(
            f"Uploaded file verification failed: no objects found under @{stage_name}/{stage_prefix}"
        )
    matched_rows = [row for row in rows if expected_stage_object in str(row[0])]
    if not matched_rows:
        raise RuntimeError(
            "Uploaded file verification failed: "
            f"{uploaded_filename} not found under @{stage_name}/{stage_prefix}"
        )
    print(f"Stage verification: found {len(rows)} matching object(s) in {stage_name}")
    print(f"Expected staged object suffix: {expected_stage_object}")
    for row in matched_rows[:5]:
        print(row)



def refresh_pipe(
    *,
    cursor,
    database: str,
    schema: str,
    pipe_name: str,
    refresh_prefix: str | None = None,
):
    qualified_pipe = qualify_name(database, schema, pipe_name)
    if refresh_prefix:
        sql = f"ALTER PIPE {qualified_pipe} REFRESH PREFIX='{sql_quote_string(refresh_prefix)}'"
    else:
        sql = f"ALTER PIPE {qualified_pipe} REFRESH"
    execute_and_print(cursor, sql)

    status_sql = f"SELECT SYSTEM$PIPE_STATUS('{sql_quote_string(qualified_pipe)}')"
    execute_and_print(cursor, status_sql)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    targets: list[UploadTarget] = [
        UploadTarget(
            family="raw_posts",
            local_file=args.raw_posts_file,
            stage=args.raw_posts_stage,
            pipe=args.raw_posts_pipe,
        ),
        UploadTarget(
            family="hydrated_posts",
            local_file=args.hydrated_posts_file,
            stage=args.hydrated_posts_stage,
            pipe=args.hydrated_posts_pipe,
        ),
        UploadTarget(
            family="actor_profiles",
            local_file=args.actor_profiles_file,
            stage=args.actor_profiles_stage,
            pipe=args.actor_profiles_pipe,
        ),
    ]

    if args.hydration_misses_file:
        targets.append(
            UploadTarget(
                family="hydration_misses",
                local_file=args.hydration_misses_file,
                stage=args.hydration_misses_stage,
                pipe=args.hydration_misses_pipe,
            )
        )

    print("Upload plan:")
    for target in targets:
        stage_prefix = build_stage_prefix(family=target.family, run_id=args.run_id)
        print(f"- {target.family}: {target.local_file}")
        print(f"  stage: {args.database}.{args.schema}.{target.stage}")
        print(f"  destination_prefix: {stage_prefix}")
        print(f"  staged_object_path: {stage_prefix}/{Path(target.local_file).name}")
        if args.refresh_pipes:
            print(f"  pipe: {target.pipe or '[not provided]'}")
    if not args.hydration_misses_file:
        print("- hydration_misses: skipped (no --hydration-misses-file provided)")

    if args.dry_run:
        print("\nDry run only. No Snowflake commands executed.")
        return 0

    if snowflake is None:
        print(
            "Dependency error: snowflake-connector-python is not installed. "
            "Install requirements before running uploads.",
            file=sys.stderr,
        )
        return 1

    if args.refresh_pipes:
        missing_pipe_targets = [t.family for t in targets if not t.pipe]
        if missing_pipe_targets:
            joined = ", ".join(missing_pipe_targets)
            print(
                f"Pipe configuration error: --refresh-pipes requested but pipe name missing for: {joined}",
                file=sys.stderr,
            )
            return 1

    try:
        conn_kwargs = build_connection_kwargs(args.database, args.schema)
    except Exception as exc:
        print(f"Connection config error: {exc}", file=sys.stderr)
        return 1

    conn = None
    upload_failures = 0
    refresh_failures = 0
    successful_uploads: list[UploadTarget] = []
    try:
        conn = snowflake.connector.connect(**conn_kwargs)  # type: ignore[union-attr]
        cursor = conn.cursor()

        execute_and_print(cursor, f"USE DATABASE {args.database}")
        execute_and_print(cursor, f"USE SCHEMA {args.schema}")

        for target in targets:
            print(f"\n=== Uploading {target.family} ===")
            try:
                uploaded_filename = put_file(
                    cursor=cursor,
                    database=args.database,
                    schema=args.schema,
                    target=target,
                    overwrite=args.overwrite,
                    parallel=args.parallel,
                    run_id=args.run_id,
                )
                file_name, stage_prefix, expected_stage_object = uploaded_filename
                list_stage_for_uploaded_file(
                    cursor=cursor,
                    database=args.database,
                    schema=args.schema,
                    stage=target.stage,
                    uploaded_filename=file_name,
                    stage_prefix=stage_prefix,
                    expected_stage_object=expected_stage_object,
                )
                successful_uploads.append(target)
            except FileNotFoundError as exc:
                upload_failures += 1
                print(f"Upload error: {exc}", file=sys.stderr)
            except SnowflakeError as exc:
                upload_failures += 1
                message = str(exc)
                lowered = message.lower()
                if "does not exist" in lowered and "stage" in lowered:
                    print(
                        f"Upload error [{target.family}]: stage not found ({target.stage}). Details: {exc}",
                        file=sys.stderr,
                    )
                elif "authentication" in lowered or "incorrect username or password" in lowered:
                    print(f"Upload error [{target.family}]: auth/connect failure. Details: {exc}", file=sys.stderr)
                else:
                    print(f"Upload error [{target.family}]: Snowflake failure. Details: {exc}", file=sys.stderr)
            except Exception as exc:
                upload_failures += 1
                print(f"Upload error [{target.family}]: {exc}", file=sys.stderr)

        if args.refresh_pipes:
            print("\nRefreshing pipes for successfully uploaded families...")
            for target in successful_uploads:
                assert target.pipe is not None
                print(f"\n=== Refreshing pipe for {target.family}: {target.pipe} ===")
                try:
                    refresh_prefix = build_stage_prefix(family=target.family, run_id=args.run_id)
                    refresh_pipe(
                        cursor=cursor,
                        database=args.database,
                        schema=args.schema,
                        pipe_name=target.pipe,
                        refresh_prefix=refresh_prefix,
                    )
                    print(f"Pipe refresh ran with prefix: {refresh_prefix}")
                except SnowflakeError as exc:
                    refresh_failures += 1
                    message = str(exc)
                    lowered = message.lower()
                    if "does not exist" in lowered and "pipe" in lowered:
                        print(
                            f"Pipe refresh error [{target.family}]: pipe not found ({target.pipe}). Details: {exc}",
                            file=sys.stderr,
                        )
                    else:
                        print(
                            f"Pipe refresh error [{target.family}]: Snowflake failure. Details: {exc}",
                            file=sys.stderr,
                        )
                except Exception as exc:
                    refresh_failures += 1
                    print(f"Pipe refresh error [{target.family}]: {exc}", file=sys.stderr)

        print("\nSummary:")
        print(f"- targets requested: {len(targets)}")
        print(f"- uploads succeeded: {len(successful_uploads)}")
        print(f"- upload failures: {upload_failures}")
        if args.refresh_pipes:
            print(f"- refresh attempts: {len(successful_uploads)}")
            print(f"- refresh failures: {refresh_failures}")

        if upload_failures or refresh_failures:
            print("Result: FAILED", file=sys.stderr)
            return 1
        print("Result: SUCCESS")
        return 0

    except SnowflakeError as exc:
        message = str(exc)
        lowered = message.lower()
        if "authentication" in lowered or "incorrect username or password" in lowered:
            print(f"\nFailed: auth/connect failure. Details: {exc}", file=sys.stderr)
        else:
            print(f"\nFailed: Snowflake error. Details: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nFailed: {exc}", file=sys.stderr)
        return 1

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
