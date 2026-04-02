from __future__ import annotations

import unittest

from bluesky_pipeline.actor.normalizer import normalize_actor_profile


class ActorNormalizerTests(unittest.TestCase):
    def test_normalize_actor_profile(self) -> None:
        row = normalize_actor_profile(
            actor_run_id="act_test",
            enriched_at="2026-04-01T18:00:00+00:00",
            profile_view={
                "did": "did:plc:test",
                "handle": "tester.bsky.social",
                "displayName": "Tester",
                "description": "hello",
                "followersCount": "7",
                "followsCount": 2,
                "postsCount": 11,
                "indexedAt": "2026-03-31T00:00:00Z",
                "createdAt": "2023-01-01T00:00:00Z",
                "labels": [],
                "associated": {"chat": {"allowIncoming": "following"}},
            },
        )

        self.assertEqual(row["actor_run_id"], "act_test")
        self.assertEqual(row["did"], "did:plc:test")
        self.assertEqual(row["followers_count"], 7)
        self.assertEqual(row["follows_count"], 2)
        self.assertEqual(row["posts_count"], 11)
        self.assertEqual(row["handle"], "tester.bsky.social")
        self.assertEqual(row["associated"]["chat"]["allowIncoming"], "following")
        self.assertEqual(row["profile"]["did"], "did:plc:test")


if __name__ == "__main__":
    unittest.main()

