#!/usr/bin/env python3
"""Run-stage completion checks and one-shot drain loops for hydrate/actor jobs."""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True, slots=True)
class HydrationCheckResult:
    capture_run_id: str
    capture_run_status: str | None
    capture_completed: bool
    total_rows: int
    all_rows_mature: bool
    mature_pending_retryable: int
    claimed_in_flight: int
    maturity_hours: int
    cutoff_utc_iso: str
    is_complete: bool


@dataclass(frozen=True, slots=True)
class ActorCheckResult:
    actor_rows_total: int
    pending_retryable: int
    claimed_in_flight: int
    is_complete: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hydration/actor stage drain utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_hydration = subparsers.add_parser(
        "check-hydration",
        help="Check whether hydration is fully complete for a capture run",
    )
    check_hydration.add_argument("--db-path", type=Path, required=True)
    check_hydration.add_argument("--capture-run-id", type=str, required=True)
    check_hydration.add_argument("--maturity-hours", type=int, default=24)

    drain_hydration = subparsers.add_parser(
        "drain-hydration",
        help="Run one-shot hydration repeatedly until completion check passes",
    )
    drain_hydration.add_argument("--db-path", type=Path, required=True)
    drain_hydration.add_argument("--capture-run-id", type=str, required=True)
    drain_hydration.add_argument("--log-path", type=Path, required=True)
    drain_hydration.add_argument("--hydrated-output-dir", type=Path, required=True)
    drain_hydration.add_argument("--miss-output-dir", type=Path, required=True)
    drain_hydration.add_argument("--maturity-hours", type=int, default=24)
    drain_hydration.add_argument("--sleep-seconds", type=float, default=300.0)
    drain_hydration.add_argument("--max-cycles", type=int, default=0)
    drain_hydration.add_argument("--claim-batch-size", type=int, default=None)
    drain_hydration.add_argument("--request-batch-size", type=int, default=None)
    drain_hydration.add_argument("--claim-ttl-seconds", type=int, default=None)
    drain_hydration.add_argument("--request-timeout-seconds", type=float, default=None)
    drain_hydration.add_argument("--max-unresolved-attempts", type=int, default=None)

    check_actor = subparsers.add_parser(
        "check-actor",
        help="Check whether actor enrichment is fully complete",
    )
    check_actor.add_argument("--db-path", type=Path, required=True)

    drain_actor = subparsers.add_parser(
        "drain-actor",
        help="Run one-shot actor enrichment repeatedly until completion check passes",
    )
    drain_actor.add_argument("--db-path", type=Path, required=True)
    drain_actor.add_argument("--log-path", type=Path, required=True)
    drain_actor.add_argument("--actor-output-dir", type=Path, required=True)
    drain_actor.add_argument("--sleep-seconds", type=float, default=300.0)
    drain_actor.add_argument("--max-cycles", type=int, default=0)
    drain_actor.add_argument("--claim-batch-size", type=int, default=None)
    drain_actor.add_argument("--request-batch-size", type=int, default=None)
    drain_actor.add_argument("--claim-ttl-seconds", type=int, default=None)
    drain_actor.add_argument("--request-timeout-seconds", type=float, default=None)
    drain_actor.add_argument("--max-unresolved-attempts", type=int, default=None)

    return parser


def _parse_iso8601(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def check_hydration_completion(
    *,
    db_path: Path,
    capture_run_id: str,
    maturity_hours: int,
) -> HydrationCheckResult:
    if maturity_hours < 0:
        raise ValueError("maturity_hours must be >= 0")

    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc - timedelta(hours=maturity_hours)
    cutoff_utc_iso = cutoff_utc.isoformat()

    conn = sqlite3.connect(db_path)
    try:
        run_row = conn.execute(
            """
            SELECT status
            FROM capture_runs
            WHERE capture_run_id = ?
            """,
            (capture_run_id,),
        ).fetchone()
        capture_run_status = str(run_row[0]) if run_row is not None else None
        capture_completed = capture_run_status == "completed"

        total_rows = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM captured_posts
                WHERE capture_run_id = ?
                """,
                (capture_run_id,),
            ).fetchone()[0]
        )

        max_captured_at = conn.execute(
            """
            SELECT MAX(captured_at)
            FROM captured_posts
            WHERE capture_run_id = ?
            """,
            (capture_run_id,),
        ).fetchone()[0]

        if max_captured_at is None:
            all_rows_mature = True
        else:
            all_rows_mature = _parse_iso8601(str(max_captured_at)) <= cutoff_utc

        mature_pending_retryable = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM captured_posts
                WHERE capture_run_id = ?
                  AND hydration_status IN ('pending', 'retryable')
                  AND captured_at <= ?
                """,
                (capture_run_id, cutoff_utc_iso),
            ).fetchone()[0]
        )

        claimed_in_flight = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM captured_posts
                WHERE capture_run_id = ?
                  AND hydration_status = 'claimed'
                """,
                (capture_run_id,),
            ).fetchone()[0]
        )
    finally:
        conn.close()

    is_complete = (
        capture_completed
        and all_rows_mature
        and mature_pending_retryable == 0
        and claimed_in_flight == 0
    )

    return HydrationCheckResult(
        capture_run_id=capture_run_id,
        capture_run_status=capture_run_status,
        capture_completed=capture_completed,
        total_rows=total_rows,
        all_rows_mature=all_rows_mature,
        mature_pending_retryable=mature_pending_retryable,
        claimed_in_flight=claimed_in_flight,
        maturity_hours=maturity_hours,
        cutoff_utc_iso=cutoff_utc_iso,
        is_complete=is_complete,
    )


def check_actor_completion(*, db_path: Path) -> ActorCheckResult:
    conn = sqlite3.connect(db_path)
    try:
        actor_rows_total = int(
            conn.execute(
                "SELECT COUNT(*) FROM actor_profiles_state"
            ).fetchone()[0]
        )
        pending_retryable = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM actor_profiles_state
                WHERE enrichment_status IN ('pending', 'retryable')
                """
            ).fetchone()[0]
        )
        claimed_in_flight = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM actor_profiles_state
                WHERE enrichment_status = 'claimed'
                """
            ).fetchone()[0]
        )
    finally:
        conn.close()

    return ActorCheckResult(
        actor_rows_total=actor_rows_total,
        pending_retryable=pending_retryable,
        claimed_in_flight=claimed_in_flight,
        is_complete=(pending_retryable == 0 and claimed_in_flight == 0),
    )


def _run_subprocess(command: Sequence[str]) -> int:
    return subprocess.run(command).returncode


def _build_hydrate_command(args: argparse.Namespace) -> list[str]:
    command: list[str] = [
        sys.executable,
        "-m",
        "bluesky_pipeline.main_hydrate",
        "--db-path",
        str(args.db_path),
        "--capture-run-id",
        str(args.capture_run_id),
        "--log-path",
        str(args.log_path),
        "--hydrated-output-dir",
        str(args.hydrated_output_dir),
        "--miss-output-dir",
        str(args.miss_output_dir),
        "--maturity-hours",
        str(args.maturity_hours),
    ]
    optional_args: tuple[tuple[str, int | float | None], ...] = (
        ("--claim-batch-size", args.claim_batch_size),
        ("--request-batch-size", args.request_batch_size),
        ("--claim-ttl-seconds", args.claim_ttl_seconds),
        ("--request-timeout-seconds", args.request_timeout_seconds),
        ("--max-unresolved-attempts", args.max_unresolved_attempts),
    )
    for flag, value in optional_args:
        if value is None:
            continue
        command.extend([flag, str(value)])
    return command


def _build_actor_command(args: argparse.Namespace) -> list[str]:
    command: list[str] = [
        sys.executable,
        "-m",
        "bluesky_pipeline.main_actor_enrich",
        "--db-path",
        str(args.db_path),
        "--log-path",
        str(args.log_path),
        "--actor-output-dir",
        str(args.actor_output_dir),
    ]
    optional_args: tuple[tuple[str, int | float | None], ...] = (
        ("--claim-batch-size", args.claim_batch_size),
        ("--request-batch-size", args.request_batch_size),
        ("--claim-ttl-seconds", args.claim_ttl_seconds),
        ("--request-timeout-seconds", args.request_timeout_seconds),
        ("--max-unresolved-attempts", args.max_unresolved_attempts),
    )
    for flag, value in optional_args:
        if value is None:
            continue
        command.extend([flag, str(value)])
    return command


def _print_hydration_status(result: HydrationCheckResult) -> None:
    print(
        "HYDRATION_COMPLETE="
        f"{int(result.is_complete)} "
        f"capture_run_id={result.capture_run_id} "
        f"capture_run_status={result.capture_run_status} "
        f"capture_completed={int(result.capture_completed)} "
        f"total_rows={result.total_rows} "
        f"all_rows_mature={int(result.all_rows_mature)} "
        f"mature_pending_retryable={result.mature_pending_retryable} "
        f"claimed_in_flight={result.claimed_in_flight} "
        f"maturity_hours={result.maturity_hours} "
        f"cutoff_utc={result.cutoff_utc_iso}"
    )


def _print_actor_status(result: ActorCheckResult) -> None:
    print(
        "ACTOR_COMPLETE="
        f"{int(result.is_complete)} "
        f"actor_rows_total={result.actor_rows_total} "
        f"pending_retryable={result.pending_retryable} "
        f"claimed_in_flight={result.claimed_in_flight}"
    )


def _sleep_with_message(seconds: float) -> None:
    if seconds <= 0:
        return
    print(f"Sleeping {seconds:.2f}s before next cycle...")
    time.sleep(seconds)


def _run_check_hydration(args: argparse.Namespace) -> int:
    result = check_hydration_completion(
        db_path=args.db_path,
        capture_run_id=args.capture_run_id,
        maturity_hours=args.maturity_hours,
    )
    _print_hydration_status(result)
    return 0 if result.is_complete else 1


def _run_drain_hydration(args: argparse.Namespace) -> int:
    if args.sleep_seconds < 0:
        raise ValueError("sleep-seconds must be >= 0")
    if args.max_cycles < 0:
        raise ValueError("max-cycles must be >= 0")

    cycle = 0
    while True:
        cycle += 1
        print(f"Starting hydration cycle={cycle}")
        command = _build_hydrate_command(args)
        exit_code = _run_subprocess(command)
        if exit_code != 0:
            print(f"Hydration cycle failed with exit_code={exit_code}")
            return exit_code

        result = check_hydration_completion(
            db_path=args.db_path,
            capture_run_id=args.capture_run_id,
            maturity_hours=args.maturity_hours,
        )
        _print_hydration_status(result)
        if result.is_complete:
            return 0

        if args.max_cycles > 0 and cycle >= args.max_cycles:
            print("Hydration drain reached max-cycles before completion.")
            return 1

        _sleep_with_message(args.sleep_seconds)


def _run_check_actor(args: argparse.Namespace) -> int:
    result = check_actor_completion(db_path=args.db_path)
    _print_actor_status(result)
    return 0 if result.is_complete else 1


def _run_drain_actor(args: argparse.Namespace) -> int:
    if args.sleep_seconds < 0:
        raise ValueError("sleep-seconds must be >= 0")
    if args.max_cycles < 0:
        raise ValueError("max-cycles must be >= 0")

    cycle = 0
    while True:
        cycle += 1
        print(f"Starting actor cycle={cycle}")
        command = _build_actor_command(args)
        exit_code = _run_subprocess(command)
        if exit_code != 0:
            print(f"Actor cycle failed with exit_code={exit_code}")
            return exit_code

        result = check_actor_completion(db_path=args.db_path)
        _print_actor_status(result)
        if result.is_complete:
            return 0

        if args.max_cycles > 0 and cycle >= args.max_cycles:
            print("Actor drain reached max-cycles before completion.")
            return 1

        _sleep_with_message(args.sleep_seconds)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "check-hydration":
        return _run_check_hydration(args)
    if args.command == "drain-hydration":
        return _run_drain_hydration(args)
    if args.command == "check-actor":
        return _run_check_actor(args)
    if args.command == "drain-actor":
        return _run_drain_actor(args)

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
