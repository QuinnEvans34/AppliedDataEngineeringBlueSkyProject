"""Firehose transport client.

This client owns connection lifecycle and frame streaming concerns:
- connect to `com.atproto.sync.subscribeRepos`
- yield raw websocket frames
- reconnect with bounded exponential backoff
- support deterministic mock-frame replay for local validation
"""

from __future__ import annotations

import json
import random
import ssl
import time
from pathlib import Path
from typing import Iterator


class FirehoseClientError(RuntimeError):
    """Base error raised by the firehose client."""


class FirehoseDependencyError(FirehoseClientError):
    """Raised when required websocket dependencies are unavailable."""


class FirehoseClient:
    """Stream raw firehose frames from websocket or local mock source."""

    def __init__(
        self,
        subscribe_url: str,
        *,
        reconnect_base_delay_seconds: float = 1.0,
        reconnect_max_delay_seconds: float = 30.0,
        recv_timeout_seconds: float = 30.0,
        mock_frames_path: Path | str | None = None,
    ) -> None:
        self.subscribe_url = subscribe_url
        self.reconnect_base_delay_seconds = reconnect_base_delay_seconds
        self.reconnect_max_delay_seconds = reconnect_max_delay_seconds
        self.recv_timeout_seconds = recv_timeout_seconds
        self.mock_frames_path = Path(mock_frames_path) if mock_frames_path else None

        self._connected = False
        self._stopped = False
        self._ws = None

    @property
    def connected(self) -> bool:
        """Expose connection status for orchestration metrics."""

        return self._connected

    def stop(self) -> None:
        """Request streaming loop shutdown and close active socket if present."""

        self._stopped = True
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                # Best-effort shutdown.
                pass
            finally:
                self._ws = None
                self._connected = False

    def iter_frames(self) -> Iterator[bytes | str | dict]:
        """Yield raw firehose frames.

        In live mode, frames are websocket messages from the relay. In mock
        mode, frames are newline-delimited JSON values from a local file.
        """

        self._stopped = False

        if self.mock_frames_path is not None:
            yield from self._iter_mock_frames()
            return

        yield from self._iter_live_frames()

    def _iter_mock_frames(self) -> Iterator[dict]:
        """Replay newline-delimited JSON mock frames for local testing."""

        if self.mock_frames_path is None:
            return
        if not self.mock_frames_path.exists():
            raise FileNotFoundError(f"Mock frames file not found: {self.mock_frames_path}")

        with self.mock_frames_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if self._stopped:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise FirehoseClientError(
                        f"Invalid JSON in mock frame file at line {line_no}: {exc.msg}"
                    ) from exc
                yield payload

    def _iter_live_frames(self) -> Iterator[bytes | str]:
        """Consume websocket frames with reconnect/backoff behavior."""

        try:
            from websockets.sync.client import connect
        except ModuleNotFoundError as exc:
            raise FirehoseDependencyError(
                "Live firehose streaming requires the `websockets` package. "
                "Install it with `python3 -m pip install websockets`."
            ) from exc

        reconnect_attempt = 0
        ssl_context = _build_ssl_context()

        while not self._stopped:
            try:
                with connect(
                    self.subscribe_url,
                    ping_interval=None,
                    close_timeout=0.1,
                    max_size=16 * 1024 * 1024,
                    ssl=ssl_context,
                ) as websocket:
                    self._ws = websocket
                    self._connected = True
                    reconnect_attempt = 0

                    while not self._stopped:
                        frame = websocket.recv(timeout=self.recv_timeout_seconds)
                        if frame is None:
                            raise FirehoseClientError("Websocket returned no frame")
                        yield frame
            except Exception as exc:
                self._connected = False
                self._ws = None

                if self._stopped:
                    break

                reconnect_attempt += 1
                delay = self._compute_reconnect_delay(reconnect_attempt)
                time.sleep(delay)
                continue
            finally:
                self._connected = False
                self._ws = None

    def _compute_reconnect_delay(self, attempt: int) -> float:
        """Compute bounded exponential backoff with a small jitter."""

        exponent = max(0, attempt - 1)
        base_delay = self.reconnect_base_delay_seconds * (2**exponent)
        bounded = min(base_delay, self.reconnect_max_delay_seconds)

        # Keep jitter small to avoid sharp synchronization during restarts.
        jitter_range = min(1.0, bounded * 0.1)
        jitter = random.uniform(-jitter_range, jitter_range)
        return max(0.0, bounded + jitter)


def _build_ssl_context() -> ssl.SSLContext:
    """Build SSL context with certifi CA bundle when available."""

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()
