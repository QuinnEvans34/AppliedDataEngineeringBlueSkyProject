"""Firehose commit extraction scaffolding.

Intended responsibility:
- inspect commit operations
- filter for app.bsky.feed.post create actions
- extract decoded post records from CAR blocks
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(slots=True)
class ExtractedPostEvent:
    """Normalized intermediate record extracted from a commit op."""

    seq: int
    repo_did: str
    collection: str
    rkey: str
    uri: str
    cid: str | None
    record: Mapping[str, Any]


def extract_post_creates(commit_payload: Mapping[str, Any]) -> Iterable[ExtractedPostEvent]:
    """Extract post-create events from a decoded commit payload (TODO)."""

    _ = commit_payload
    return ()
