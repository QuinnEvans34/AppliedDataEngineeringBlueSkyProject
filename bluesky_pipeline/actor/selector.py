"""Actor enrichment work selection over SQLite actor state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from bluesky_pipeline.state.sqlite_store import SQLiteStore
from bluesky_pipeline.utils.time_utils import utc_now_iso


@dataclass(slots=True, frozen=True)
class ActorEnrichmentClaim:
    """Claimed actor enrichment work item returned by selector."""

    did: str
    attempt_count: int


@dataclass(slots=True, frozen=True)
class ActorSeedResult:
    """Counts returned when seeding actor DIDs from captured pipeline state."""

    inserted_from_hydrated: int
    inserted_from_captured: int

    @property
    def inserted_total(self) -> int:
        return self.inserted_from_hydrated + self.inserted_from_captured


class ActorSelector:
    """Coordinator for actor DID seeding, count, release, and claim operations."""

    def __init__(self, store: SQLiteStore, *, claim_ttl_seconds: int) -> None:
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be > 0")
        self.store = store
        self.claim_ttl_seconds = claim_ttl_seconds

    def seed_actor_dids(self, *, seeded_at_iso: str | None = None) -> ActorSeedResult:
        """Seed unique DIDs from hydrated-first then captured fallback sources."""

        inserted_hydrated, inserted_captured = self.store.seed_actor_dids_from_hydrated_then_captured(
            seeded_at_iso=seeded_at_iso
        )
        return ActorSeedResult(
            inserted_from_hydrated=inserted_hydrated,
            inserted_from_captured=inserted_captured,
        )

    def count_pending_actor_dids(self) -> int:
        """Count actor rows in `pending`/`retryable` state."""

        return self.store.count_pending_actor_dids()

    def release_expired_claims(self, *, now_iso: str | None = None) -> int:
        """Release expired actor claims back to `pending`."""

        return self.store.release_expired_actor_claims(now_iso or utc_now_iso())

    def claim_actor_dids(self, worker_id: str, limit: int) -> Sequence[ActorEnrichmentClaim]:
        """Claim actor rows for enrichment processing."""

        claimed_rows = self.store.claim_actor_dids(
            worker_id=worker_id,
            limit=limit,
            claim_ttl_seconds=self.claim_ttl_seconds,
        )
        claims: list[ActorEnrichmentClaim] = []
        for row in claimed_rows:
            claims.append(
                ActorEnrichmentClaim(
                    did=row["did"],
                    attempt_count=int(row["enrichment_attempt_count"]),
                )
            )
        return claims

