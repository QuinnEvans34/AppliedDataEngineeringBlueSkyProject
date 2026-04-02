"""Actor profile normalization for output dataset."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def normalize_actor_profile(
    actor_run_id: str,
    profile_view: dict[str, Any],
    enriched_at: str,
) -> dict[str, Any]:
    """Convert an actor profile view into Dataset D row shape."""

    labels = profile_view.get("labels")
    associated = profile_view.get("associated")

    return {
        "actor_run_id": actor_run_id,
        "did": profile_view.get("did"),
        "handle": profile_view.get("handle"),
        "display_name": profile_view.get("displayName"),
        "description": profile_view.get("description"),
        "followers_count": _to_int_or_none(profile_view.get("followersCount")),
        "follows_count": _to_int_or_none(profile_view.get("followsCount")),
        "posts_count": _to_int_or_none(profile_view.get("postsCount")),
        "indexed_at": profile_view.get("indexedAt"),
        "created_at": profile_view.get("createdAt"),
        "labels": labels if isinstance(labels, list) else [],
        "associated": dict(associated) if isinstance(associated, Mapping) else None,
        "enriched_at": enriched_at,
        "profile": dict(profile_view),
    }


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

