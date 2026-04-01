"""Hydration work selection over SQLite captured-post state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from bluesky_pipeline.state.sqlite_store import SQLiteStore
from bluesky_pipeline.utils.time_utils import utc_now, utc_now_iso


@dataclass(slots=True, frozen=True)
class HydrationClaim:
    """Claimed hydration work item returned by selector."""

    uri: str
    capture_run_id: str
    cid_at_capture: str | None
    captured_at: str
    attempt_count: int


class HydrationSelector:
    """Coordinator for mature-row count/release/claim operations."""

    def __init__(
        self,
        store: SQLiteStore,
        *,
        maturity_hours: int,
        claim_ttl_seconds: int,
    ) -> None:
        if maturity_hours < 0:
            raise ValueError("maturity_hours must be >= 0")
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be > 0")
        self.store = store
        self.maturity_hours = maturity_hours
        self.claim_ttl_seconds = claim_ttl_seconds

    def count_pending_mature_posts(self, *, now: datetime | None = None) -> int:
        """Count mature rows in `pending`/`retryable` state."""

        return self.store.count_pending_mature_posts(self._maturity_cutoff_iso(now=now))

    def release_expired_claims(self, *, now_iso: str | None = None) -> int:
        """Release expired claims back to `pending`."""

        return self.store.release_expired_claims(now_iso or utc_now_iso())

    def claim_mature_posts(
        self,
        worker_id: str,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> Sequence[HydrationClaim]:
        """Claim mature posts for hydration processing."""

        claimed_rows = self.store.claim_mature_posts(
            worker_id=worker_id,
            limit=limit,
            maturity_cutoff_iso=self._maturity_cutoff_iso(now=now),
            claim_ttl_seconds=self.claim_ttl_seconds,
        )

        claims: list[HydrationClaim] = []
        for row in claimed_rows:
            claims.append(
                HydrationClaim(
                    uri=row["uri"],
                    capture_run_id=row["capture_run_id"],
                    cid_at_capture=row["cid_at_capture"],
                    captured_at=row["captured_at"],
                    attempt_count=int(row["hydration_attempt_count"]),
                )
            )
        return claims

    def _maturity_cutoff_iso(self, *, now: datetime | None = None) -> str:
        effective_now = now or utc_now()
        if effective_now.tzinfo is None:
            effective_now = effective_now.replace(tzinfo=timezone.utc)
        cutoff = effective_now.astimezone(timezone.utc) - timedelta(hours=self.maturity_hours)
        return cutoff.isoformat()
