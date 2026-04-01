"""Hydration API client for Bluesky `app.bsky.feed.getPosts`.

Responsibilities:
- enforce max-URI request chunk size (<= 25)
- execute HTTP requests against the public AppView endpoint
- apply retry/backoff on transient failures
- return structured per-request hydration results
"""

from __future__ import annotations

import json
import random
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GET_POSTS_MAX_URIS = 25


class HydrateClientError(RuntimeError):
    """Base hydration client error."""


class HydrateRequestError(HydrateClientError):
    """Hydration request failure with retryability metadata."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass(slots=True, frozen=True)
class HydrateBatchResult:
    """Hydration result for one `getPosts` request batch."""

    requested_uris: tuple[str, ...]
    posts: tuple[dict[str, Any], ...]
    missing_uris: tuple[str, ...]


class HydrateClient:
    """Bluesky AppView hydration client."""

    def __init__(
        self,
        api_base_url: str,
        get_posts_path: str,
        *,
        max_uris_per_request: int = GET_POSTS_MAX_URIS,
        request_timeout_seconds: float = 15.0,
        max_attempts: int = 5,
        backoff_base_delay_seconds: float = 1.0,
        backoff_max_delay_seconds: float = 30.0,
        jitter_ratio: float = 0.1,
    ) -> None:
        if max_uris_per_request <= 0:
            raise ValueError("max_uris_per_request must be > 0")
        if max_uris_per_request > GET_POSTS_MAX_URIS:
            raise ValueError(f"max_uris_per_request cannot exceed {GET_POSTS_MAX_URIS}")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be > 0")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be > 0")
        if backoff_base_delay_seconds <= 0:
            raise ValueError("backoff_base_delay_seconds must be > 0")
        if backoff_max_delay_seconds <= 0:
            raise ValueError("backoff_max_delay_seconds must be > 0")
        if jitter_ratio < 0:
            raise ValueError("jitter_ratio must be >= 0")

        self.api_base_url = api_base_url.rstrip("/")
        self.get_posts_path = get_posts_path
        self.max_uris_per_request = max_uris_per_request
        self.request_timeout_seconds = request_timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_base_delay_seconds = backoff_base_delay_seconds
        self.backoff_max_delay_seconds = backoff_max_delay_seconds
        self.jitter_ratio = jitter_ratio
        self.ssl_context = _build_ssl_context()

    def chunk_uris(self, uris: Sequence[str]) -> Iterable[list[str]]:
        """Yield URI chunks that satisfy `getPosts` request limits."""

        unique_uris = _normalize_unique_uris(uris)
        for index in range(0, len(unique_uris), self.max_uris_per_request):
            yield unique_uris[index : index + self.max_uris_per_request]

    def get_posts(self, uris: Sequence[str]) -> HydrateBatchResult:
        """Request hydrated post views for one URI chunk."""

        requested_uris = _normalize_unique_uris(uris)
        if not requested_uris:
            return HydrateBatchResult(requested_uris=(), posts=(), missing_uris=())
        if len(requested_uris) > self.max_uris_per_request:
            raise ValueError(
                f"Request contains {len(requested_uris)} URIs, exceeds max "
                f"{self.max_uris_per_request}"
            )

        response_payload = self._request_with_retry(requested_uris)
        raw_posts = response_payload.get("posts", [])
        if not isinstance(raw_posts, list):
            raise HydrateRequestError(
                "Hydration payload missing list field 'posts'",
                retryable=False,
            )

        requested_set = set(requested_uris)
        returned_posts: list[dict[str, Any]] = []
        returned_seen: set[str] = set()

        for raw_post in raw_posts:
            if not isinstance(raw_post, dict):
                continue
            uri = raw_post.get("uri")
            if not isinstance(uri, str):
                continue
            if uri not in requested_set or uri in returned_seen:
                continue
            returned_posts.append(raw_post)
            returned_seen.add(uri)

        missing_uris = [uri for uri in requested_uris if uri not in returned_seen]
        return HydrateBatchResult(
            requested_uris=tuple(requested_uris),
            posts=tuple(returned_posts),
            missing_uris=tuple(missing_uris),
        )

    def _request_with_retry(self, requested_uris: Sequence[str]) -> dict[str, Any]:
        """Call `getPosts` with bounded retry/backoff behavior."""

        last_error: HydrateRequestError | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._request_once(requested_uris)
            except HydrateRequestError as error:
                last_error = error
                should_retry = error.retryable and attempt < self.max_attempts
                if not should_retry:
                    raise
                time.sleep(self._backoff_seconds(attempt))

        if last_error is None:
            raise HydrateClientError("Hydration request failed without exception detail")
        raise last_error

    def _request_once(self, requested_uris: Sequence[str]) -> dict[str, Any]:
        endpoint = f"{self.api_base_url}{self.get_posts_path}"
        query = urlencode([("uris", uri) for uri in requested_uris])
        url = f"{endpoint}?{query}"

        request = Request(
            url=url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "bluesky-pipeline-hydrator/phase4",
            },
        )

        try:
            with urlopen(
                request,
                timeout=self.request_timeout_seconds,
                context=self.ssl_context,
            ) as response:
                body_bytes = response.read()
        except HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            raise HydrateRequestError(
                f"Hydration request failed with HTTP {exc.code}",
                retryable=retryable,
                status_code=exc.code,
            ) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise HydrateRequestError(
                f"Hydration request transport failure: {exc}",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise HydrateRequestError(
                f"Hydration request unexpected failure: {exc}",
                retryable=False,
            ) from exc

        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HydrateRequestError(
                "Hydration response was not valid UTF-8 JSON",
                retryable=True,
            ) from exc

        if not isinstance(payload, dict):
            raise HydrateRequestError(
                "Hydration response payload was not an object",
                retryable=False,
            )

        return payload

    def _backoff_seconds(self, attempt: int) -> float:
        raw_delay = self.backoff_base_delay_seconds * (2 ** max(0, attempt - 1))
        bounded_delay = min(raw_delay, self.backoff_max_delay_seconds)
        jitter_span = bounded_delay * self.jitter_ratio
        jitter = random.uniform(-jitter_span, jitter_span) if jitter_span > 0 else 0.0
        return max(0.0, bounded_delay + jitter)


def _normalize_unique_uris(uris: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for uri in uris:
        if not isinstance(uri, str):
            continue
        if not uri or uri in seen:
            continue
        normalized.append(uri)
        seen.add(uri)
    return normalized


def _build_ssl_context() -> ssl.SSLContext:
    """Build SSL context with certifi CA bundle when available."""

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()
