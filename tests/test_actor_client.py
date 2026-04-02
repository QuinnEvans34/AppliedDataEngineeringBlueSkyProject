from __future__ import annotations

import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from bluesky_pipeline.actor.client import (
    ActorBatchResult,
    ActorClient,
    ActorRequestError,
)


class _SequencedClient(ActorClient):
    def __init__(self, outcomes):
        super().__init__(
            api_base_url="https://public.api.bsky.app",
            get_profiles_path="/xrpc/app.bsky.actor.getProfiles",
            max_attempts=3,
            jitter_ratio=0.0,
        )
        self._outcomes = list(outcomes)
        self.calls = 0

    def _request_once(self, requested_dids):
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


class ActorClientTests(unittest.TestCase):
    def test_chunking_enforces_max_25(self) -> None:
        client = ActorClient(
            api_base_url="https://public.api.bsky.app",
            get_profiles_path="/xrpc/app.bsky.actor.getProfiles",
            max_actors_per_request=25,
        )
        dids = [f"did:plc:test{i:03d}" for i in range(26)]

        chunks = list(client.chunk_dids(dids))

        self.assertEqual([len(c) for c in chunks], [25, 1])

    def test_get_profiles_filters_and_marks_missing(self) -> None:
        request_dids = ["did:plc:one", "did:plc:two"]
        payload = {
            "profiles": [
                {"did": request_dids[0], "handle": "one.bsky.social"},
                {"did": request_dids[0], "handle": "duplicate.bsky.social"},
                {"did": "did:plc:other", "handle": "other.bsky.social"},
            ]
        }
        client = _SequencedClient([payload])

        result = client.get_profiles(request_dids)

        self.assertEqual(result.requested_dids, tuple(request_dids))
        self.assertEqual([profile["did"] for profile in result.profiles], [request_dids[0]])
        self.assertEqual(result.missing_dids, (request_dids[1],))

    @mock.patch("bluesky_pipeline.actor.client.time.sleep")
    def test_retryable_error_is_retried(self, sleep_mock) -> None:
        retryable_error = ActorRequestError("temporary", retryable=True)
        client = _SequencedClient([retryable_error, {"profiles": []}])

        result = client.get_profiles(["did:plc:one"])

        self.assertIsInstance(result, ActorBatchResult)
        self.assertEqual(client.calls, 2)
        sleep_mock.assert_called_once()

    @mock.patch("bluesky_pipeline.actor.client.time.sleep")
    def test_non_retryable_error_is_not_retried(self, sleep_mock) -> None:
        non_retryable_error = ActorRequestError("bad request", retryable=False)
        client = _SequencedClient([non_retryable_error])

        with self.assertRaises(ActorRequestError):
            client.get_profiles(["did:plc:one"])

        self.assertEqual(client.calls, 1)
        sleep_mock.assert_not_called()

    @mock.patch("bluesky_pipeline.actor.client.urlopen")
    def test_http_429_is_retryable(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = HTTPError(
            url="https://example.test",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )
        client = ActorClient(
            api_base_url="https://public.api.bsky.app",
            get_profiles_path="/xrpc/app.bsky.actor.getProfiles",
            max_attempts=1,
        )

        with self.assertRaises(ActorRequestError) as ctx:
            client._request_once(["did:plc:one"])

        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(ctx.exception.status_code, 429)

    @mock.patch("bluesky_pipeline.actor.client.urlopen")
    def test_http_500_is_retryable(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = HTTPError(
            url="https://example.test",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=None,
        )
        client = ActorClient(
            api_base_url="https://public.api.bsky.app",
            get_profiles_path="/xrpc/app.bsky.actor.getProfiles",
            max_attempts=1,
        )

        with self.assertRaises(ActorRequestError) as ctx:
            client._request_once(["did:plc:one"])

        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(ctx.exception.status_code, 500)

    @mock.patch("bluesky_pipeline.actor.client.urlopen")
    def test_http_400_is_non_retryable(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = HTTPError(
            url="https://example.test",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=None,
        )
        client = ActorClient(
            api_base_url="https://public.api.bsky.app",
            get_profiles_path="/xrpc/app.bsky.actor.getProfiles",
            max_attempts=1,
        )

        with self.assertRaises(ActorRequestError) as ctx:
            client._request_once(["did:plc:one"])

        self.assertFalse(ctx.exception.retryable)
        self.assertEqual(ctx.exception.status_code, 400)

    @mock.patch("bluesky_pipeline.actor.client.urlopen")
    def test_timeout_transport_error_is_retryable(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = URLError("timed out")
        client = ActorClient(
            api_base_url="https://public.api.bsky.app",
            get_profiles_path="/xrpc/app.bsky.actor.getProfiles",
            max_attempts=1,
        )

        with self.assertRaises(ActorRequestError) as ctx:
            client._request_once(["did:plc:one"])

        self.assertTrue(ctx.exception.retryable)

    @mock.patch("bluesky_pipeline.actor.client.urlopen")
    def test_invalid_json_is_retryable(self, urlopen_mock) -> None:
        urlopen_mock.return_value = _FakeResponse(b"not-json")
        client = ActorClient(
            api_base_url="https://public.api.bsky.app",
            get_profiles_path="/xrpc/app.bsky.actor.getProfiles",
            max_attempts=1,
        )

        with self.assertRaises(ActorRequestError) as ctx:
            client._request_once(["did:plc:one"])

        self.assertTrue(ctx.exception.retryable)


if __name__ == "__main__":
    unittest.main()

