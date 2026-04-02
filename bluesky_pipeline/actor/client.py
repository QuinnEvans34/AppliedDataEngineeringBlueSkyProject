"""Actor profile API client for `app.bsky.actor.getProfiles`.

Responsibilities:
- enforce max-actor request chunk size (<= 25)
- execute HTTP requests against the public AppView endpoint
- apply retry/backoff on transient failures
- return structured per-request actor profile results
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

GET_PROFILES_MAX_ACTORS = 25


class ActorClientError(RuntimeError):
    """Base actor enrichment client error."""


class ActorRequestError(ActorClientError):
    """Actor lookup request failure with retryability metadata."""

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
class ActorBatchResult:
    """Actor profile result for one `getProfiles` request batch."""

    requested_dids: tuple[str, ...]
    profiles: tuple[dict[str, Any], ...]
    missing_dids: tuple[str, ...]


class ActorClient:
    """Bluesky AppView actor/profile enrichment client."""

    def __init__(
        self,
        api_base_url: str,
        get_profiles_path: str,
        *,
        max_actors_per_request: int = GET_PROFILES_MAX_ACTORS,
        request_timeout_seconds: float = 15.0,
        max_attempts: int = 5,
        backoff_base_delay_seconds: float = 1.0,
        backoff_max_delay_seconds: float = 30.0,
        jitter_ratio: float = 0.1,
    ) -> None:
        if max_actors_per_request <= 0:
            raise ValueError("max_actors_per_request must be > 0")
        if max_actors_per_request > GET_PROFILES_MAX_ACTORS:
            raise ValueError(f"max_actors_per_request cannot exceed {GET_PROFILES_MAX_ACTORS}")
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
        self.get_profiles_path = get_profiles_path
        self.max_actors_per_request = max_actors_per_request
        self.request_timeout_seconds = request_timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_base_delay_seconds = backoff_base_delay_seconds
        self.backoff_max_delay_seconds = backoff_max_delay_seconds
        self.jitter_ratio = jitter_ratio
        self.ssl_context = _build_ssl_context()

    def chunk_dids(self, dids: Sequence[str]) -> Iterable[list[str]]:
        """Yield DID chunks that satisfy `getProfiles` request limits."""

        unique_dids = _normalize_unique_dids(dids)
        for index in range(0, len(unique_dids), self.max_actors_per_request):
            yield unique_dids[index : index + self.max_actors_per_request]

    def get_profiles(self, dids: Sequence[str]) -> ActorBatchResult:
        """Request actor profiles for one DID chunk."""

        requested_dids = _normalize_unique_dids(dids)
        if not requested_dids:
            return ActorBatchResult(requested_dids=(), profiles=(), missing_dids=())
        if len(requested_dids) > self.max_actors_per_request:
            raise ValueError(
                f"Request contains {len(requested_dids)} DIDs, exceeds max "
                f"{self.max_actors_per_request}"
            )

        response_payload = self._request_with_retry(requested_dids)
        raw_profiles = response_payload.get("profiles", [])
        if not isinstance(raw_profiles, list):
            raise ActorRequestError(
                "Actor payload missing list field 'profiles'",
                retryable=False,
            )

        requested_set = set(requested_dids)
        returned_profiles: list[dict[str, Any]] = []
        returned_seen: set[str] = set()

        for raw_profile in raw_profiles:
            if not isinstance(raw_profile, dict):
                continue
            did = raw_profile.get("did")
            if not isinstance(did, str):
                continue
            if did not in requested_set or did in returned_seen:
                continue
            returned_profiles.append(raw_profile)
            returned_seen.add(did)

        missing_dids = [did for did in requested_dids if did not in returned_seen]
        return ActorBatchResult(
            requested_dids=tuple(requested_dids),
            profiles=tuple(returned_profiles),
            missing_dids=tuple(missing_dids),
        )

    def _request_with_retry(self, requested_dids: Sequence[str]) -> dict[str, Any]:
        """Call `getProfiles` with bounded retry/backoff behavior."""

        last_error: ActorRequestError | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._request_once(requested_dids)
            except ActorRequestError as error:
                last_error = error
                should_retry = error.retryable and attempt < self.max_attempts
                if not should_retry:
                    raise
                time.sleep(self._backoff_seconds(attempt))

        if last_error is None:
            raise ActorClientError("Actor request failed without exception detail")
        raise last_error

    def _request_once(self, requested_dids: Sequence[str]) -> dict[str, Any]:
        endpoint = f"{self.api_base_url}{self.get_profiles_path}"
        query = urlencode([("actors", did) for did in requested_dids])
        url = f"{endpoint}?{query}"

        request = Request(
            url=url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "bluesky-pipeline-actor-enrichment/phase5",
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
            raise ActorRequestError(
                f"Actor request failed with HTTP {exc.code}",
                retryable=retryable,
                status_code=exc.code,
            ) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise ActorRequestError(
                f"Actor request transport failure: {exc}",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise ActorRequestError(
                f"Actor request unexpected failure: {exc}",
                retryable=False,
            ) from exc

        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ActorRequestError(
                "Actor response was not valid UTF-8 JSON",
                retryable=True,
            ) from exc

        if not isinstance(payload, dict):
            raise ActorRequestError(
                "Actor response payload was not an object",
                retryable=False,
            )

        return payload

    def _backoff_seconds(self, attempt: int) -> float:
        raw_delay = self.backoff_base_delay_seconds * (2 ** max(0, attempt - 1))
        bounded_delay = min(raw_delay, self.backoff_max_delay_seconds)
        jitter_span = bounded_delay * self.jitter_ratio
        jitter = random.uniform(-jitter_span, jitter_span) if jitter_span > 0 else 0.0
        return max(0.0, bounded_delay + jitter)


def _normalize_unique_dids(dids: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for did in dids:
        if not isinstance(did, str):
            continue
        if not did or did in seen:
            continue
        normalized.append(did)
        seen.add(did)
    return normalized


def _build_ssl_context() -> ssl.SSLContext:
    """Build SSL context with certifi CA bundle when available."""

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

