from __future__ import annotations

import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from bluesky_pipeline.hydrate.client import (
    HydrateBatchResult,
    HydrateClient,
    HydrateRequestError,
)


class _SequencedClient(HydrateClient):
    def __init__(self, outcomes):
        super().__init__(
            api_base_url="https://public.api.bsky.app",
            get_posts_path="/xrpc/app.bsky.feed.getPosts",
            max_attempts=3,
            jitter_ratio=0.0,
        )
        self._outcomes = list(outcomes)
        self.calls = 0

    def _request_once(self, requested_uris):
        self.calls += 1
        if not self._outcomes:
            raise AssertionError("No outcome configured")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


class HydrateClientTests(unittest.TestCase):
    def test_chunking_enforces_max_25(self) -> None:
        client = HydrateClient(
            api_base_url="https://public.api.bsky.app",
            get_posts_path="/xrpc/app.bsky.feed.getPosts",
            max_uris_per_request=25,
        )
        uris = [f"at://did:plc:test/app.bsky.feed.post/{i:03d}" for i in range(26)]

        chunks = list(client.chunk_uris(uris))

        self.assertEqual([len(c) for c in chunks], [25, 1])

    def test_get_posts_filters_and_marks_missing(self) -> None:
        request_uris = [
            "at://did:plc:one/app.bsky.feed.post/1",
            "at://did:plc:two/app.bsky.feed.post/2",
        ]
        payload = {
            "posts": [
                {"uri": request_uris[0], "cid": "cid1"},
                {"uri": request_uris[0], "cid": "duplicate"},
                {"uri": "at://did:plc:other/app.bsky.feed.post/x", "cid": "other"},
            ]
        }
        client = _SequencedClient([payload])

        result = client.get_posts(request_uris)

        self.assertEqual(result.requested_uris, tuple(request_uris))
        self.assertEqual([post["uri"] for post in result.posts], [request_uris[0]])
        self.assertEqual(result.missing_uris, (request_uris[1],))

    @mock.patch("bluesky_pipeline.hydrate.client.time.sleep")
    def test_retryable_error_is_retried(self, sleep_mock) -> None:
        retryable_error = HydrateRequestError("temporary", retryable=True)
        client = _SequencedClient([retryable_error, {"posts": []}])

        result = client.get_posts(["at://did:plc:one/app.bsky.feed.post/1"])

        self.assertIsInstance(result, HydrateBatchResult)
        self.assertEqual(client.calls, 2)
        sleep_mock.assert_called_once()

    @mock.patch("bluesky_pipeline.hydrate.client.time.sleep")
    def test_non_retryable_error_is_not_retried(self, sleep_mock) -> None:
        non_retryable_error = HydrateRequestError("bad request", retryable=False)
        client = _SequencedClient([non_retryable_error])

        with self.assertRaises(HydrateRequestError):
            client.get_posts(["at://did:plc:one/app.bsky.feed.post/1"])

        self.assertEqual(client.calls, 1)
        sleep_mock.assert_not_called()

    @mock.patch("bluesky_pipeline.hydrate.client.urlopen")
    def test_http_429_is_retryable(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = HTTPError(
            url="https://example.test",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )
        client = HydrateClient(
            api_base_url="https://public.api.bsky.app",
            get_posts_path="/xrpc/app.bsky.feed.getPosts",
            max_attempts=1,
        )

        with self.assertRaises(HydrateRequestError) as ctx:
            client._request_once(["at://did:plc:one/app.bsky.feed.post/1"])

        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(ctx.exception.status_code, 429)

    @mock.patch("bluesky_pipeline.hydrate.client.urlopen")
    def test_http_500_is_retryable(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = HTTPError(
            url="https://example.test",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=None,
        )
        client = HydrateClient(
            api_base_url="https://public.api.bsky.app",
            get_posts_path="/xrpc/app.bsky.feed.getPosts",
            max_attempts=1,
        )

        with self.assertRaises(HydrateRequestError) as ctx:
            client._request_once(["at://did:plc:one/app.bsky.feed.post/1"])

        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(ctx.exception.status_code, 500)

    @mock.patch("bluesky_pipeline.hydrate.client.urlopen")
    def test_http_400_is_non_retryable(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = HTTPError(
            url="https://example.test",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=None,
        )
        client = HydrateClient(
            api_base_url="https://public.api.bsky.app",
            get_posts_path="/xrpc/app.bsky.feed.getPosts",
            max_attempts=1,
        )

        with self.assertRaises(HydrateRequestError) as ctx:
            client._request_once(["at://did:plc:one/app.bsky.feed.post/1"])

        self.assertFalse(ctx.exception.retryable)
        self.assertEqual(ctx.exception.status_code, 400)

    @mock.patch("bluesky_pipeline.hydrate.client.urlopen")
    def test_timeout_transport_error_is_retryable(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = URLError("timed out")
        client = HydrateClient(
            api_base_url="https://public.api.bsky.app",
            get_posts_path="/xrpc/app.bsky.feed.getPosts",
            max_attempts=1,
        )

        with self.assertRaises(HydrateRequestError) as ctx:
            client._request_once(["at://did:plc:one/app.bsky.feed.post/1"])

        self.assertTrue(ctx.exception.retryable)

    @mock.patch("bluesky_pipeline.hydrate.client.urlopen")
    def test_invalid_json_is_retryable(self, urlopen_mock) -> None:
        urlopen_mock.return_value = _FakeResponse(b"not-json")
        client = HydrateClient(
            api_base_url="https://public.api.bsky.app",
            get_posts_path="/xrpc/app.bsky.feed.getPosts",
            max_attempts=1,
        )

        with self.assertRaises(HydrateRequestError) as ctx:
            client._request_once(["at://did:plc:one/app.bsky.feed.post/1"])

        self.assertTrue(ctx.exception.retryable)


if __name__ == "__main__":
    unittest.main()
