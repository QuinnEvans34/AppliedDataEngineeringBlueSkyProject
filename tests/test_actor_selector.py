from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bluesky_pipeline.actor.selector import ActorSelector
from bluesky_pipeline.state.sqlite_store import SQLiteStore
from bluesky_pipeline.utils.time_utils import utc_now_iso


class ActorSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "state.db"
        self.store = SQLiteStore(self.db_path)
        self.store.connect()
        self.store.ensure_schema()
        self.capture_run_id = self.store.create_capture_run(
            target_post_count=10,
            capture_run_id="cap_test_selector",
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def _insert_post(self, uri: str, did: str, status: str) -> None:
        self.store.insert_captured_post(
            uri=uri,
            capture_run_id=self.capture_run_id,
            repo_did=did,
            rkey=uri.rsplit("/", 1)[-1],
            cid_at_capture="bafycap",
            seq=1,
            record_created_at=utc_now_iso(),
            captured_at=utc_now_iso(),
            capture_file_id=None,
        )
        conn = self.store.connect()
        conn.execute(
            "UPDATE captured_posts SET hydration_status = ? WHERE uri = ?",
            (status, uri),
        )
        conn.commit()

    def test_seeding_hydrated_then_captured(self) -> None:
        hydrated_did = "did:plc:hydrated"
        captured_only_did = "did:plc:captured"
        self._insert_post("at://did:plc:hydrated/app.bsky.feed.post/1", hydrated_did, "hydrated")
        self._insert_post("at://did:plc:captured/app.bsky.feed.post/2", captured_only_did, "pending")

        selector = ActorSelector(self.store, claim_ttl_seconds=300)

        seed_result = selector.seed_actor_dids()

        self.assertEqual(seed_result.inserted_from_hydrated, 1)
        self.assertEqual(seed_result.inserted_from_captured, 1)
        self.assertEqual(seed_result.inserted_total, 2)
        self.assertEqual(selector.count_pending_actor_dids(), 2)

    def test_claiming_and_release_expired_claims(self) -> None:
        hydrated_did = "did:plc:hydrated"
        self._insert_post("at://did:plc:hydrated/app.bsky.feed.post/1", hydrated_did, "hydrated")

        selector = ActorSelector(self.store, claim_ttl_seconds=300)
        selector.seed_actor_dids()

        claims = selector.claim_actor_dids(worker_id="worker-a", limit=10)
        self.assertEqual([claim.did for claim in claims], [hydrated_did])
        self.assertEqual(claims[0].attempt_count, 1)

        released = selector.release_expired_claims(now_iso="2099-01-01T00:00:00+00:00")
        row = self.store.get_actor_state(hydrated_did)
        self.assertEqual(released, 1)
        self.assertEqual(row["enrichment_status"], "pending")
        self.assertIsNone(row["claimed_by_worker"])


if __name__ == "__main__":
    unittest.main()

