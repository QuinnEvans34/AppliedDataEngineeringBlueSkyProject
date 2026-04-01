"""Firehose job entrypoint scaffold.

This module wires config, logging, and SQLite schema bootstrap for the
firehose pipeline process. Full frame processing and write orchestration are
intentionally deferred to later implementation phases.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bluesky_pipeline.config import load_config
from bluesky_pipeline.logging_config import configure_logging
from bluesky_pipeline.state.sqlite_store import SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for the firehose entrypoint."""

    parser = argparse.ArgumentParser(description="Bluesky firehose capture job")
    parser.add_argument("--db-path", type=Path, default=Path("data/state/pipeline_state.db"))
    parser.add_argument("--log-path", type=Path, default=Path("data/logs/firehose.log"))
    return parser


def main(argv: list[str] | None = None) -> int:
    """Initialize firehose runtime scaffolding and exit.

    This placeholder performs schema bootstrap and logs intended responsibilities.
    It does not yet connect to the firehose or write capture rows.
    """

    args = build_parser().parse_args(argv)
    config = load_config()
    logger = configure_logging("firehose", args.log_path)

    logger.info("Starting firehose scaffold")
    logger.info("Target unique posts: %d", config.firehose.target_capture_count)

    with SQLiteStore(args.db_path) as store:
        store.ensure_schema()
        logger.info("SQLite schema ensured at %s", args.db_path)

    logger.info("Firehose scaffold complete. Processing loop is TODO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
