"""Firehose frame decoding scaffolding.

Intended responsibility:
- parse raw frame bytes
- identify commit vs non-commit events
- return structured event payloads for extraction
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(slots=True)
class DecodedEvent:
    """Minimal structured event shape produced by the decoder."""

    event_type: str
    payload: Mapping[str, Any]


def decode_frame(raw_frame: bytes) -> Optional[DecodedEvent]:
    """Decode a raw frame into a structured event.

    Returns `None` for unsupported or undecodable frames in this scaffold.
    """

    _ = raw_frame
    return None
