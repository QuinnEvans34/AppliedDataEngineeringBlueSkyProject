"""Hydration API client scaffolding.

Intended responsibility:
- call app.bsky.feed.getPosts
- batch URI requests
- apply retry/backoff for transient failures
"""

from __future__ import annotations

from typing import Any, Sequence


class HydrateClient:
    """Placeholder client for Bluesky post hydration requests."""

    def __init__(self, api_base_url: str, get_posts_path: str) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.get_posts_path = get_posts_path

    def get_posts(self, uris: Sequence[str]) -> list[dict[str, Any]]:
        """Request hydrated post views for URIs (TODO)."""

        _ = uris
        return []
