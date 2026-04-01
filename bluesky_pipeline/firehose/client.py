"""Firehose transport client scaffolding.

Intended responsibility:
- manage websocket connection lifecycle
- stream raw frames
- handle reconnect policy
"""

from __future__ import annotations

from typing import Iterator, Optional


class FirehoseClient:
    """Placeholder client for AT Protocol firehose frame streaming."""

    def __init__(self, subscribe_url: str) -> None:
        self.subscribe_url = subscribe_url
        self._connected = False

    def connect(self) -> None:
        """Open connection to the firehose endpoint (TODO)."""

        self._connected = True

    def disconnect(self) -> None:
        """Close connection and release client resources (TODO)."""

        self._connected = False

    def iter_frames(self) -> Iterator[bytes]:
        """Yield raw websocket frames.

        Returns an empty iterator during scaffolding until transport logic is
        implemented.
        """

        return iter(())

    @property
    def connected(self) -> bool:
        """Expose connection status for orchestration logic."""

        return self._connected
