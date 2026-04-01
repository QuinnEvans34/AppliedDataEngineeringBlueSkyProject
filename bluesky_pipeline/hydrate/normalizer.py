"""Hydrated view and miss-row normalization for output datasets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def normalize_hydrated_post(
    hydrate_run_id: str,
    capture_run_id: str,
    post_view: dict[str, Any],
    hydrated_at: str,
) -> dict[str, Any]:
    """Convert a hydrated post view into Dataset B row shape."""

    author_value = post_view.get("author")
    author = author_value if isinstance(author_value, Mapping) else {}
    record_value = post_view.get("record")
    labels = post_view.get("labels")
    if not isinstance(labels, list):
        labels = []

    return {
        "hydrate_run_id": hydrate_run_id,
        "capture_run_id": capture_run_id,
        "uri": post_view.get("uri"),
        "cid": post_view.get("cid"),
        "indexed_at": post_view.get("indexedAt"),
        "author_did": author.get("did"),
        "author_handle": author.get("handle"),
        "author_display_name": author.get("displayName"),
        "reply_count": _to_int_or_none(post_view.get("replyCount")),
        "repost_count": _to_int_or_none(post_view.get("repostCount")),
        "like_count": _to_int_or_none(post_view.get("likeCount")),
        "quote_count": _to_int_or_none(post_view.get("quoteCount")),
        "labels": labels,
        "hydrated_at": hydrated_at,
        "record": dict(record_value) if isinstance(record_value, Mapping) else None,
    }


def normalize_hydration_miss(
    hydrate_run_id: str,
    capture_run_id: str,
    uri: str,
    *,
    cid_at_capture: str | None,
    captured_at: str,
    attempt_count: int,
    reason: str,
    checked_at: str,
) -> dict[str, Any]:
    """Create a Dataset C miss row for unresolved hydration targets."""

    return {
        "hydrate_run_id": hydrate_run_id,
        "capture_run_id": capture_run_id,
        "uri": uri,
        "cid_at_capture": cid_at_capture,
        "captured_at": captured_at,
        "status": "missing",
        "reason": reason,
        "checked_at": checked_at,
        "attempt_count": attempt_count,
    }


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
