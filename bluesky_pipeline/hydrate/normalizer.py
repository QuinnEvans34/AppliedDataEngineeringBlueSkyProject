"""Hydrated view normalization scaffolding.

Intended responsibility:
- convert hydrated post views into Dataset B rows
- generate Dataset C miss/error rows when hydration returns no post
"""

from __future__ import annotations

from typing import Any


def normalize_hydrated_post(
    hydrate_run_id: str,
    capture_run_id: str,
    post_view: dict[str, Any],
    hydrated_at: str,
) -> dict[str, Any]:
    """Convert a hydrated post view into Dataset B row shape."""

    author = post_view.get("author") or {}
    return {
        "hydrate_run_id": hydrate_run_id,
        "capture_run_id": capture_run_id,
        "uri": post_view.get("uri"),
        "cid": post_view.get("cid"),
        "indexed_at": post_view.get("indexedAt"),
        "author_did": author.get("did"),
        "author_handle": author.get("handle"),
        "author_display_name": author.get("displayName"),
        "reply_count": post_view.get("replyCount"),
        "repost_count": post_view.get("repostCount"),
        "like_count": post_view.get("likeCount"),
        "quote_count": post_view.get("quoteCount"),
        "labels": post_view.get("labels"),
        "hydrated_at": hydrated_at,
        "record": post_view.get("record"),
    }


def normalize_hydration_miss(
    hydrate_run_id: str,
    capture_run_id: str,
    uri: str,
    reason: str,
    hydrated_at: str,
) -> dict[str, Any]:
    """Create a Dataset C miss row for unresolved hydration targets."""

    return {
        "hydrate_run_id": hydrate_run_id,
        "capture_run_id": capture_run_id,
        "uri": uri,
        "reason": reason,
        "hydrated_at": hydrated_at,
    }
