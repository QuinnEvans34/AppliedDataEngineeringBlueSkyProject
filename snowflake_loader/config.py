"""Configuration loading for Snowflake loader entrypoint."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from snowflake_loader.manifest import DATASET_FAMILIES


@dataclass(frozen=True, slots=True)
class SnowflakeAuthConfig:
    account: str | None
    user: str | None
    password: str | None
    role: str | None
    warehouse: str | None
    database: str | None
    schema: str | None


@dataclass(frozen=True, slots=True)
class SnowflakeObjectConfig:
    file_format_name: str = "BLUESKY_JSONL_GZ"
    manifest_table_name: str = "LOADER_FILE_MANIFEST"
    stage_names: dict[str, str] = field(
        default_factory=lambda: {
            "raw_posts": "BLUESKY_RAW_POSTS_STAGE",
            "hydrated_posts": "BLUESKY_HYDRATED_POSTS_STAGE",
            "hydration_misses": "BLUESKY_HYDRATION_MISSES_STAGE",
            "actor_profiles": "BLUESKY_ACTOR_PROFILES_STAGE",
        }
    )
    pipe_names: dict[str, str] = field(
        default_factory=lambda: {
            "raw_posts": "BLUESKY_RAW_POSTS_PIPE",
            "hydrated_posts": "BLUESKY_HYDRATED_POSTS_PIPE",
            "hydration_misses": "BLUESKY_HYDRATION_MISSES_PIPE",
            "actor_profiles": "BLUESKY_ACTOR_PROFILES_PIPE",
        }
    )
    landing_table_names: dict[str, str] = field(
        default_factory=lambda: {
            "raw_posts": "LANDING_RAW_POSTS",
            "hydrated_posts": "LANDING_HYDRATED_POSTS",
            "hydration_misses": "LANDING_HYDRATION_MISSES",
            "actor_profiles": "LANDING_ACTOR_PROFILES",
        }
    )


@dataclass(frozen=True, slots=True)
class LoaderConfig:
    run_root: Path
    run_tag: str
    state_db_path: Path | None
    dry_run: bool
    maturity_hours: int
    strict_completion_gate: bool
    load_invocation_id: str
    auth: SnowflakeAuthConfig
    objects: SnowflakeObjectConfig

    def validate_family_mappings(self) -> None:
        for family in DATASET_FAMILIES:
            if family not in self.objects.stage_names:
                raise ValueError(f"Missing stage name mapping for dataset family: {family}")
            if family not in self.objects.pipe_names:
                raise ValueError(f"Missing pipe name mapping for dataset family: {family}")
            if family not in self.objects.landing_table_names:
                raise ValueError(f"Missing landing table mapping for dataset family: {family}")


def build_loader_config(
    *,
    run_root: Path,
    state_db_path: Path | None,
    dry_run: bool,
    maturity_hours: int,
) -> LoaderConfig:
    """Build loader config from CLI flags + Snowflake env vars."""

    if maturity_hours < 0:
        raise ValueError("maturity_hours must be >= 0")

    auth = SnowflakeAuthConfig(
        account=_getenv("SNOWFLAKE_ACCOUNT"),
        user=_getenv("SNOWFLAKE_USER"),
        password=_getenv("SNOWFLAKE_PASSWORD"),
        role=_getenv("SNOWFLAKE_ROLE"),
        warehouse=_getenv("SNOWFLAKE_WAREHOUSE"),
        database=_getenv("SNOWFLAKE_DATABASE"),
        schema=_getenv("SNOWFLAKE_SCHEMA"),
    )

    config = LoaderConfig(
        run_root=run_root.resolve(),
        run_tag=run_root.name,
        state_db_path=state_db_path.resolve() if state_db_path else None,
        dry_run=dry_run,
        maturity_hours=maturity_hours,
        strict_completion_gate=True,
        load_invocation_id=f"load_{uuid.uuid4().hex}",
        auth=auth,
        objects=SnowflakeObjectConfig(),
    )
    config.validate_family_mappings()
    return config


def ensure_required_snowflake_env(config: LoaderConfig) -> None:
    """Require Snowflake connection env vars when not in dry-run mode."""

    if config.dry_run:
        return

    required = {
        "SNOWFLAKE_ACCOUNT": config.auth.account,
        "SNOWFLAKE_USER": config.auth.user,
        "SNOWFLAKE_PASSWORD": config.auth.password,
        "SNOWFLAKE_ROLE": config.auth.role,
        "SNOWFLAKE_WAREHOUSE": config.auth.warehouse,
        "SNOWFLAKE_DATABASE": config.auth.database,
        "SNOWFLAKE_SCHEMA": config.auth.schema,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Missing required Snowflake environment variables: {joined}")


def _getenv(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None
