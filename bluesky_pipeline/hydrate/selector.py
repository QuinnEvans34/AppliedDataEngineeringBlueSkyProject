"""Hydration work selection scaffolding.

Intended responsibility:
- query mature pending/retryable captured posts
- atomically claim rows for a worker
- release expired claims and return selected URIs
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True)
class HydrationClaim:
    """Claimed hydration work item returned by selector."""

    uri: str
    capture_run_id: str


class HydrationSelector:
    """Placeholder coordinator for selecting and claiming hydration work."""

    def claim_mature_posts(self, worker_id: str, limit: int) -> Sequence[HydrationClaim]:
        """Claim mature posts for hydration processing (TODO)."""

        _ = (worker_id, limit)
        return ()
