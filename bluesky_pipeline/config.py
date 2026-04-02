"""Configuration models and default loading for the Bluesky pipeline.

This module centralizes runtime configuration for paths, batching, retries,
and job-specific settings. In this scaffold phase we expose strongly-typed
config objects with sensible defaults and leave environment/file loading for
future phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class PathsConfig:
    """Filesystem locations used by the pipeline."""

    data_dir: Path = Path("data")
    raw_posts_dir: Path = Path("data/raw_posts")
    hydrated_posts_dir: Path = Path("data/hydrated_posts")
    hydration_misses_dir: Path = Path("data/hydration_misses")
    actor_profiles_dir: Path = Path("data/actor_profiles")
    logs_dir: Path = Path("data/logs")
    state_dir: Path = Path("data/state")
    sqlite_db_path: Path = Path("data/state/pipeline_state.db")


@dataclass(slots=True)
class BatchingConfig:
    """Batch writer controls for row/time flushing and file rolling."""

    flush_row_count: int = 10_000
    flush_interval_seconds: int = 60


@dataclass(slots=True)
class RetryConfig:
    """Retry and backoff settings for transient failures."""

    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_ratio: float = 0.1


@dataclass(slots=True)
class FirehoseConfig:
    """Settings for the firehose capture worker."""

    subscribe_repos_url: str = (
        "wss://bsky.network/xrpc/com.atproto.sync.subscribeRepos"
    )
    target_capture_count: int = 1_000_000
    recv_timeout_seconds: float = 30.0
    reconnect_base_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 30.0
    progress_log_interval_seconds: float = 15.0
    progress_db_sync_interval_seconds: float = 5.0


@dataclass(slots=True)
class HydrateConfig:
    """Settings for the hydration worker."""

    api_base_url: str = "https://public.api.bsky.app"
    get_posts_path: str = "/xrpc/app.bsky.feed.getPosts"
    claim_batch_size: int = 200
    claim_ttl_seconds: int = 300
    request_batch_size: int = 25
    request_timeout_seconds: float = 15.0
    maturity_hours: int = 24
    poll_interval_seconds: int = 30
    progress_log_interval_seconds: float = 15.0
    max_unresolved_attempts: int = 3
    continue_polling_when_idle: bool = False


@dataclass(slots=True)
class ActorConfig:
    """Settings for the actor/profile enrichment worker."""

    api_base_url: str = "https://public.api.bsky.app"
    get_profiles_path: str = "/xrpc/app.bsky.actor.getProfiles"
    claim_batch_size: int = 200
    claim_ttl_seconds: int = 300
    request_batch_size: int = 25
    request_timeout_seconds: float = 15.0
    poll_interval_seconds: int = 30
    progress_log_interval_seconds: float = 15.0
    max_unresolved_attempts: int = 3
    continue_polling_when_idle: bool = False


@dataclass(slots=True)
class AppConfig:
    """Top-level application config grouped by concern."""

    paths: PathsConfig = field(default_factory=PathsConfig)
    batching: BatchingConfig = field(default_factory=BatchingConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    firehose: FirehoseConfig = field(default_factory=FirehoseConfig)
    hydrate: HydrateConfig = field(default_factory=HydrateConfig)
    actor: ActorConfig = field(default_factory=ActorConfig)


def load_config() -> AppConfig:
    """Return default typed configuration.

    Future phases may extend this function to merge environment variables or
    external files, but current behavior is intentionally static and explicit.
    """

    return AppConfig()
