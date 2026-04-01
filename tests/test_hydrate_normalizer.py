from __future__ import annotations

import unittest

from bluesky_pipeline.hydrate.normalizer import normalize_hydrated_post, normalize_hydration_miss


class HydrateNormalizerTests(unittest.TestCase):
    def test_normalize_hydrated_post(self) -> None:
        row = normalize_hydrated_post(
            hydrate_run_id="hyd_test",
            capture_run_id="cap_test",
            hydrated_at="2026-04-01T18:00:00+00:00",
            post_view={
                "uri": "at://did:plc:test/app.bsky.feed.post/123",
                "cid": "bafy123",
                "indexedAt": "2026-03-31T00:00:00Z",
                "author": {
                    "did": "did:plc:test",
                    "handle": "tester.bsky.social",
                    "displayName": "Tester",
                },
                "replyCount": "7",
                "repostCount": 2,
                "likeCount": 11,
                "quoteCount": 1,
                "labels": [],
                "record": {"$type": "app.bsky.feed.post", "text": "hello"},
            },
        )

        self.assertEqual(row["hydrate_run_id"], "hyd_test")
        self.assertEqual(row["capture_run_id"], "cap_test")
        self.assertEqual(row["uri"], "at://did:plc:test/app.bsky.feed.post/123")
        self.assertEqual(row["reply_count"], 7)
        self.assertEqual(row["author_handle"], "tester.bsky.social")
        self.assertEqual(row["record"]["text"], "hello")

    def test_normalize_hydration_miss(self) -> None:
        row = normalize_hydration_miss(
            hydrate_run_id="hyd_test",
            capture_run_id="cap_test",
            uri="at://did:plc:test/app.bsky.feed.post/999",
            cid_at_capture="bafy999",
            captured_at="2026-03-30T00:00:00+00:00",
            attempt_count=3,
            reason="not_returned_by_getPosts",
            checked_at="2026-04-01T18:01:00+00:00",
        )

        self.assertEqual(row["status"], "missing")
        self.assertEqual(row["attempt_count"], 3)
        self.assertEqual(row["reason"], "not_returned_by_getPosts")
        self.assertEqual(row["cid_at_capture"], "bafy999")


if __name__ == "__main__":
    unittest.main()
