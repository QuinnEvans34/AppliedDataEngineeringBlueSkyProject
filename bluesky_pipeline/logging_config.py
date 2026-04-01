"""Logging setup helpers for pipeline entrypoints.

The current implementation provides a practical baseline: console + file
handlers with a uniform formatter. Future phases can add structured logging,
metrics exporters, and log rotation policies.
"""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(job_name: str, log_path: Path, level: int = logging.INFO) -> logging.Logger:
    """Configure and return a logger for a pipeline job."""

    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(job_name)
    logger.setLevel(level)
    logger.propagate = False

    # Avoid duplicate handlers when entrypoints are re-run in the same process.
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger
