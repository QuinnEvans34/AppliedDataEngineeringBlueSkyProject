"""Firehose frame decoding utilities.

Decoder responsibilities:
- convert raw websocket frames into structured events
- parse AT Protocol subscribeRepos message frames when available
- expose a stable decoded-event contract for extraction
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


class FirehoseDecodeError(ValueError):
    """Raised when a frame cannot be decoded into a supported event."""


@dataclass(slots=True)
class DecodedEvent:
    """Structured firehose event passed from decoder to extractor."""

    event_type: str
    seq: int | None
    event_time: str | None
    payload: Any


def decode_frame(raw_frame: bytes | str | Mapping[str, Any] | Any) -> DecodedEvent | None:
    """Decode raw frame data into `DecodedEvent`.

    Returns `None` for unsupported frame types that should be skipped.
    Raises `FirehoseDecodeError` for malformed data.
    """

    message_frame = _coerce_message_frame(raw_frame)
    if message_frame is not None:
        return _decode_message_frame(message_frame)

    payload_map = _coerce_mapping(raw_frame)
    if payload_map is None:
        return None

    return _decode_mapping_event(payload_map)


def _coerce_message_frame(raw_frame: Any) -> Any | None:
    """Return atproto firehose MessageFrame instance when available."""

    try:
        from atproto_firehose.client import _get_message_frame_from_bytes_or_raise
        from atproto_firehose.models import MessageFrame
    except ModuleNotFoundError:
        return None

    if isinstance(raw_frame, MessageFrame):
        return raw_frame

    if isinstance(raw_frame, bytes):
        try:
            return _get_message_frame_from_bytes_or_raise(raw_frame)
        except Exception:
            # Not a binary subscribeRepos frame; decoder may still handle JSON.
            return None

    return None


def _decode_message_frame(message_frame: Any) -> DecodedEvent:
    """Decode an atproto MessageFrame into a stable DecodedEvent."""

    try:
        from atproto_firehose import parse_subscribe_repos_message
    except ModuleNotFoundError as exc:
        raise FirehoseDecodeError(
            "atproto firehose parser is unavailable; install `atproto` package."
        ) from exc

    try:
        parsed = parse_subscribe_repos_message(message_frame)
    except Exception as exc:
        raise FirehoseDecodeError(f"Failed to parse subscribeRepos message: {exc}") from exc

    event_type = _normalize_event_type(message_frame.type)
    seq = getattr(parsed, "seq", None)
    event_time = getattr(parsed, "time", None)
    return DecodedEvent(event_type=event_type, seq=seq, event_time=event_time, payload=parsed)


def _coerce_mapping(raw_frame: Any) -> Mapping[str, Any] | None:
    """Convert raw frame into mapping for mock/testing decode path."""

    if isinstance(raw_frame, Mapping):
        return raw_frame

    if isinstance(raw_frame, str):
        try:
            decoded = json.loads(raw_frame)
        except json.JSONDecodeError as exc:
            raise FirehoseDecodeError(f"Invalid JSON text frame: {exc.msg}") from exc
        if isinstance(decoded, Mapping):
            return decoded
        raise FirehoseDecodeError("JSON text frame is not an object")

    if isinstance(raw_frame, bytes):
        try:
            decoded = json.loads(raw_frame.decode("utf-8"))
        except UnicodeDecodeError:
            return None
        except json.JSONDecodeError as exc:
            raise FirehoseDecodeError(f"Invalid JSON binary frame: {exc.msg}") from exc

        if isinstance(decoded, Mapping):
            return decoded
        raise FirehoseDecodeError("JSON binary frame is not an object")

    return None


def _decode_mapping_event(payload: Mapping[str, Any]) -> DecodedEvent:
    """Decode mapping payload (used for mocked runs)."""

    raw_type = payload.get("t") or payload.get("type") or payload.get("event_type")
    event_type = _normalize_event_type(raw_type)

    seq = payload.get("seq")
    if seq is not None:
        try:
            seq = int(seq)
        except (TypeError, ValueError):
            seq = None

    event_time = payload.get("time")
    if event_time is not None and not isinstance(event_time, str):
        event_time = str(event_time)

    return DecodedEvent(
        event_type=event_type,
        seq=seq,
        event_time=event_time,
        payload=payload,
    )


def _normalize_event_type(raw_type: Any) -> str:
    """Normalize source event type labels to a compact set."""

    if raw_type is None:
        return "unknown"

    event_type = str(raw_type).strip().lower()

    if event_type in {"#commit", "commit", "com.atproto.sync.subscriberepos#commit"}:
        return "commit"
    if event_type in {"#info", "info", "com.atproto.sync.subscriberepos#info"}:
        return "info"
    if event_type in {"#identity", "identity", "com.atproto.sync.subscriberepos#identity"}:
        return "identity"
    if event_type in {"#account", "account", "com.atproto.sync.subscriberepos#account"}:
        return "account"
    if event_type in {"#sync", "sync", "com.atproto.sync.subscriberepos#sync"}:
        return "sync"

    return event_type
