from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bluesky_pipeline.hydrate.selector import HydrationSelector
from bluesky_pipeline.state.sqlite_store import SQLiteStore
from bluesky_pipeline.utils.time_utils import utc_now_iso


class HydrateSelectorTests(unittest.TestCase):
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

    def _insert_post(self, uri: str, captured_at: str) -> None:
        self.store.insert_captured_post(
            uri=uri,
            capture_run_id=self.capture_run_id,
            repo_did="did:plc:test",
            rkey=uri.rsplit("/", 1)[-1],
            cid_at_capture="bafycap",
            seq=1,
            record_created_at=captured_at,
            captured_at=captured_at,
            capture_file_id=None,
        )

    def test_maturity_cutoff_and_claiming(self) -> None:
        mature_uri = "at://did:plc:test/app.bsky.feed.post/mature"
        recent_uri = "at://did:plc:test/app.bsky.feed.post/recent"

        self._insert_post(mature_uri, "2026-03-20T00:00:00+00:00")
        self._insert_post(recent_uri, utc_now_iso())

        selector = HydrationSelector(
            self.store,
            maturity_hours=24,
            claim_ttl_seconds=300,
        )

        mature_count = selector.count_pending_mature_posts(now=None)
        claims = selector.claim_mature_posts(worker_id="worker-a", limit=10)

        self.assertEqual(mature_count, 1)
        self.assertEqual([claim.uri for claim in claims], [mature_uri])
        self.assertEqual(claims[0].attempt_count, 1)

    def test_release_expired_claims(self) -> None:
        mature_uri = "at://did:plc:test/app.bsky.feed.post/mature"
        self._insert_post(mature_uri, "2026-03-20T00:00:00+00:00")

        selector = HydrationSelector(
            self.store,
            maturity_hours=24,
            claim_ttl_seconds=300,
        )

        claims = selector.claim_mature_posts(worker_id="worker-a", limit=10)
        self.assertEqual(len(claims), 1)

        released = selector.release_expired_claims(now_iso="2099-01-01T00:00:00+00:00")
        row = self.store.get_captured_post(mature_uri)

        self.assertEqual(released, 1)
        self.assertEqual(row["hydration_status"], "pending")
        self.assertIsNone(row["claimed_by_worker"])


if __name__ == "__main__":
    unittest.main()
