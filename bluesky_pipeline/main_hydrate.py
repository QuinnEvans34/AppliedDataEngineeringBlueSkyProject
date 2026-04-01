"""Hydration job entrypoint scaffold.

This module wires config, logging, and SQLite schema bootstrap for the
hydration pipeline process. Polling, claiming, API calls, and write logic are
left as explicit TODOs for later phases.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bluesky_pipeline.config import load_config
from bluesky_pipeline.logging_config import configure_logging
from bluesky_pipeline.state.sqlite_store import SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for the hydrator entrypoint."""

    parser = argparse.ArgumentParser(description="Bluesky hydration job")
    parser.add_argument("--db-path", type=Path, default=Path("data/state/pipeline_state.db"))
    parser.add_argument("--log-path", type=Path, default=Path("data/logs/hydrate.log"))
    return parser


def main(argv: list[str] | None = None) -> int:
    """Initialize hydration runtime scaffolding and exit.

    This placeholder performs schema bootstrap and logs intended responsibilities.
    It does not yet execute maturity selection or `getPosts` hydration.
    """

    args = build_parser().parse_args(argv)
    config = load_config()
    logger = configure_logging("hydrate", args.log_path)

    logger.info("Starting hydration scaffold")
    logger.info("Maturity threshold (hours): %d", config.hydrate.maturity_hours)

    with SQLiteStore(args.db_path) as store:
        store.ensure_schema()
        logger.info("SQLite schema ensured at %s", args.db_path)

    logger.info("Hydration scaffold complete. Polling worker loop is TODO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
