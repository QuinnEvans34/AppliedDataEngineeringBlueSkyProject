"""Shared path-resolution helpers for local source datasets."""

from __future__ import annotations

import os
from pathlib import Path

BLUESKY_SOURCE_ROOT_ENV = "BLUESKY_SOURCE_ROOT"
DEFAULT_BLUESKY_SOURCE_ROOT = "data"


def resolve_bluesky_source_root(base_dir: Path | str | None = None) -> Path:
    """
    Resolve Bluesky source root with deterministic precedence:
    1) explicit function argument
    2) BLUESKY_SOURCE_ROOT environment variable
    3) repo-local default "data"
    """

    if base_dir is not None:
        return Path(base_dir)

    env_value = os.getenv(BLUESKY_SOURCE_ROOT_ENV, "").strip()
    if env_value:
        return Path(env_value)

    return Path(DEFAULT_BLUESKY_SOURCE_ROOT)


__all__ = [
    "BLUESKY_SOURCE_ROOT_ENV",
    "DEFAULT_BLUESKY_SOURCE_ROOT",
    "resolve_bluesky_source_root",
]

